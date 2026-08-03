"""Browser (Pyodide) execution: ship a public bundle, capture a fenced client run.

This is the API-07 ``browser`` execution mode. The environment steps in the
participant browser through Pyodide, not the server loop, and the client is the
writer of the episode ledger. The server side is three things: it projects a
public client manifest from the study spec, split from any private server field;
it validates the client-reported episode into the same normalized transition
contract the server loop produces; and it commits that run under browser authority
with a producer generation, so a superseded client cannot write after a newer one
takes over.

The server never trusts the client for identity: the episode and interaction ids
are minted server-side and shipped in the manifest, and a reported transition that
names a different episode, a different channel, or a non-browser authority is
refused. The bundle carries no secret material and no private manifest data.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any, cast

from pydantic import ValidationError

from mug.game.capture import capture_episode
from mug.game.capture_parts import FRAMES_PER_PART, ClaimedPart
from mug.game.determinism import state_hash_source
from mug.game.keys import Bindings, chords, single_keys
from mug.game.runtime import EpisodeSummary
from mug.game.types import EpisodeBoundary, GameTransition
from mug.kernel import CommandReceipt, Digest
from mug.runtime import CommandContext, FencingClaim
from mug.storage import ArtifactStore, Store

# Where the client gets the inference runtime that scores an exported network.
# A deployment that must not reach a public network serves its own copy and names
# it here, so this is a default rather than an address the platform insists on.
ONNX_RUNTIME_URL = "https://cdn.jsdelivr.net/npm/onnxruntime-web@1.19.2/dist/ort.min.js"


@dataclass(frozen=True)
class BrowserPartner:
    """An exported network that plays a seat in the participant's own browser.

    The environment steps in Pyodide, where no ONNX runtime can be installed, so
    the network is scored by the browser's own runtime beside it -- the same model
    file the server plays, run by the JavaScript build of the same runtime. This is
    what lets one study run a human-AI task with no server in the loop at all.

    ``model`` is the **name** of a declared study asset, never a path or a URL: the
    client resolves it against the same collection the renderer resolves a sprite
    against, so a study names a network exactly as it names a picture.
    ``input_name`` and ``output_name`` are what the exported graph calls its
    observation input and its action scores.

    ``decide_every`` is the frame skip -- how many frames pass between decisions,
    with the action held between (the browser twin of ``Pace``). ``selection`` is
    how scores become an action: ``argmax`` takes the greatest, ``sample`` draws
    from the softmax at ``temperature``, seeded from the episode seed so the run
    stays reproducible. ``default_action`` is what the seat does before the first
    decision and whenever the runtime is unavailable.

    The bundle meets this with two functions: ``partner_observation()`` returns the
    numbers to score, and ``partner_acts(action)`` hands back what was chosen. A
    study that declares a partner and defines neither is refused at publication
    rather than playing a whole round against a seat that never moves.
    """

    model: str
    input_name: str = "input"
    output_name: str = "logits"
    decide_every: int = 1
    selection: str = "argmax"
    temperature: float = 1.0
    default_action: int = 0
    runtime_url: str = ONNX_RUNTIME_URL

    def __post_init__(self) -> None:
        if self.decide_every < 1:
            raise ValueError("a partner decides at least once every frame")
        if self.selection not in ("argmax", "sample"):
            raise ValueError("a partner selects by argmax or by sample")


@dataclass(frozen=True)
class BrowserGameSpec:
    """One browser-executed game channel a study supplies.

    ``source_bundle`` is the Python source the client runs in Pyodide; it defines
    the environment and its drawing, the browser twin of ``GameSpec``.
    ``requires`` are the pinned packages the client installs once. ``seed`` fixes
    the episode seed the client must use, and ``hooks`` declares the determinism
    hooks the environment supports. ``server_notes`` stands for private server
    manifest data; it never reaches the client manifest.

    ``input_mode`` says how long a press lasts, and the client must read it the
    same way the server does: a browser run is verified by re-executing it, so a
    client that counted one press where the server counted three would make an
    honest participant's run unverifiable.

    ``partner`` seats an exported network beside the participant, scored by the
    browser's own inference runtime. Its decisions are reported with the run and
    replayed when the server re-executes it, so a partner the participant played
    against is part of the record rather than something that has to be guessed at.

    ``verification`` is what this environment can support, which is a property of
    the environment and not of the platform. The default, ``deterministic``, says
    the run can be re-executed from its seed and its actions: the server checks
    every state hash and refuses a run that does not match, which is what makes a
    client-written record evidence. ``visual-fallback`` says it cannot -- and a
    study must be able to say so, because otherwise an environment that does not
    repeat refuses **every** participant's run, at the end, and records nothing.
    That is what an unseeded environment did here, and the study had no way to
    express it. A run recorded under ``visual-fallback`` carries that verdict, so a
    reader can always tell what was checked rather than assuming it was.
    """

    channel_key: str
    source_bundle: str
    requires: tuple[str, ...]
    action_bindings: Bindings
    default_action: int
    seed: int
    hooks: tuple[str, ...] = ("snapshot-restore", "state-hash")
    fps: int = 30
    max_steps: int = 200
    countdown_seconds: int = 3
    input_mode: str = "pressed_keys"
    partner: BrowserPartner | None = None
    verification: str = "deterministic"
    server_notes: str | None = field(default=None)

    def __post_init__(self) -> None:
        if self.verification not in ("deterministic", "visual-fallback"):
            raise ValueError(
                "verification is 'deterministic' or 'visual-fallback'; "
                f"{self.verification!r} is neither"
            )
        if self.partner is None:
            return
        missing = [
            name
            for name in ("partner_observation", "partner_acts")
            if f"def {name}" not in self.source_bundle
        ]
        if missing:
            raise ValueError(
                "a browser game with an exported partner must define "
                + " and ".join(missing)
                + " in its bundle"
            )


def client_manifest(
    spec: BrowserGameSpec,
    *,
    episode_id: str,
    interaction_id: str,
    seat_key: str,
) -> dict[str, Any]:
    """Project the public client manifest, split from the private server data.

    The projection is an explicit whitelist, so a new private field never leaks
    by default. The server-minted episode and interaction ids ship here, so the
    client stamps them on every transition it reports. The state-hash hook source
    ships too, so the client computes each state hash the exact way the server
    re-computes it when it verifies the run.
    """
    partner = (
        None
        if spec.partner is None
        else {
            "model": spec.partner.model,
            "input_name": spec.partner.input_name,
            "output_name": spec.partner.output_name,
            "decide_every": spec.partner.decide_every,
            "selection": spec.partner.selection,
            "temperature": spec.partner.temperature,
            "default_action": spec.partner.default_action,
            "runtime_url": spec.partner.runtime_url,
        }
    )
    return {
        "mode": "browser",
        "channel_key": spec.channel_key,
        "partner": partner,
        "episode_id": episode_id,
        "interaction_id": interaction_id,
        "seat_key": seat_key,
        "source_bundle": spec.source_bundle,
        "requires": list(spec.requires),
        "action_bindings": single_keys(spec.action_bindings),
        "action_chords": chords(spec.action_bindings),
        "default_action": spec.default_action,
        "input_mode": spec.input_mode,
        "seed": spec.seed,
        "hooks": list(spec.hooks),
        "fps": spec.fps,
        "max_steps": spec.max_steps,
        # How often the client reports what it has played. The server sets the
        # cadence because the server is what has to hold the parts: a client that
        # chose its own could report once at the end, which is the failure this
        # exists to remove.
        "frames_per_part": FRAMES_PER_PART,
        "countdown_seconds": spec.countdown_seconds,
        "state_hash_source": state_hash_source(),
    }


class ClientEpisodeError(ValueError):
    """The client-reported episode did not meet the transition contract."""


def parse_client_part(
    payload: object,
    *,
    expected_channel_key: str,
    expected_episode_id: str,
) -> ClaimedPart:
    """Validate one slice of a run as the client reported it while playing.

    A run arrives in parts now, so the frames are checked where they arrive rather
    than only at the end: a part that does not validate is refused while the
    participant is still playing and can be reported again, and nothing invalid is
    ever staged.

    ``first_frame`` counts from one and the transitions must run on from it without a
    gap. A payload naming no ``first_frame`` is a whole run reported at once, which is
    what a client that has not been updated sends, so it means frame one and the last
    part together.
    """
    if not isinstance(payload, dict):
        raise ClientEpisodeError("the episode payload is not an object")
    data = cast("dict[str, Any]", payload)
    episode = data.get("episode")
    if not isinstance(episode, dict):
        raise ClientEpisodeError("the part names no episode")
    body = cast("dict[str, Any]", episode)
    raw_transitions = body.get("transitions")
    if not isinstance(raw_transitions, list):
        raise ClientEpisodeError("the part names no transitions")

    first_frame = data.get("first_frame", 1)
    if not isinstance(first_frame, int) or isinstance(first_frame, bool):
        raise ClientEpisodeError("first_frame is not a whole number")
    if first_frame < 1:
        raise ClientEpisodeError("a run's frames are numbered from one")
    # Absent means the whole run in one report, which is the closing part by
    # definition. A client that reports parts says which one this is.
    final = bool(data.get("final", True))

    transitions: list[dict[str, Any]] = []
    for index, raw in enumerate(cast("list[Any]", raw_transitions)):
        try:
            transition = GameTransition.model_validate(raw)
        except ValidationError as error:
            raise ClientEpisodeError("a transition did not validate") from error
        if transition.authority != "browser":
            raise ClientEpisodeError("a browser transition claims browser authority")
        if transition.channel_key != expected_channel_key:
            raise ClientEpisodeError("a transition names the wrong channel")
        if transition.episode_id != expected_episode_id:
            raise ClientEpisodeError("a transition names the wrong episode")
        if transition.frame_number != first_frame + index:
            raise ClientEpisodeError("the transitions are not a contiguous run")
        transitions.append(transition.model_dump(mode="json", exclude_none=True))
    if not transitions and not final:
        raise ClientEpisodeError("a part that does not close the run carries no frames")

    boundary = body.get("boundary")
    if final:
        if not isinstance(boundary, dict):
            raise ClientEpisodeError("the closing part names no boundary")
        try:
            EpisodeBoundary.model_validate(boundary)
        except ValidationError as error:
            raise ClientEpisodeError("the boundary did not validate") from error
    elif boundary is not None:
        raise ClientEpisodeError("only the closing part carries a boundary")

    return ClaimedPart(
        first_frame=first_frame,
        transitions=transitions,
        actions=_whole_numbers(data.get("actions")),
        partner_actions=_whole_numbers(data.get("partner_actions")),
        final=final,
        boundary=cast("dict[str, Any] | None", boundary) if final else None,
    )


def _whole_numbers(value: object) -> list[int]:
    """Read one reported action sequence; a bool is not an action."""
    if not isinstance(value, list):
        return []
    return [
        one
        for one in cast("list[Any]", value)
        if isinstance(one, int) and not isinstance(one, bool)
    ]


def parse_client_episode(
    payload: object,
    *,
    expected_channel_key: str,
    expected_episode_id: str,
    seat_key: str,
) -> EpisodeSummary:
    """Validate a client-reported episode into the normalized contract.

    The payload names its transitions and its closing boundary. Each transition
    and the boundary must validate as the same records the server loop produces,
    must claim browser authority, and must name the expected episode and channel.
    A mismatch raises ``ClientEpisodeError``, so the caller answers a safe refusal
    rather than committing an untrusted or malformed run.
    """
    if not isinstance(payload, dict):
        raise ClientEpisodeError("the episode payload is not an object")
    data = cast("dict[str, Any]", payload)
    raw_transitions = data.get("transitions")
    if not isinstance(raw_transitions, list):
        raise ClientEpisodeError("the episode names no transitions")

    transitions: list[GameTransition] = []
    for index, raw in enumerate(cast("list[Any]", raw_transitions)):
        try:
            transition = GameTransition.model_validate(raw)
        except ValidationError as error:
            raise ClientEpisodeError("a transition did not validate") from error
        if transition.authority != "browser":
            raise ClientEpisodeError("a browser transition claims browser authority")
        if transition.channel_key != expected_channel_key:
            raise ClientEpisodeError("a transition names the wrong channel")
        if transition.episode_id != expected_episode_id:
            raise ClientEpisodeError("a transition names the wrong episode")
        if transition.frame_number != index + 1:
            raise ClientEpisodeError("the transitions are not a contiguous run")
        transitions.append(transition)

    try:
        boundary = EpisodeBoundary.model_validate(data.get("boundary"))
    except ValidationError as error:
        raise ClientEpisodeError("the boundary did not validate") from error
    if boundary.authority != "browser":
        raise ClientEpisodeError("the boundary claims browser authority")
    if boundary.episode_id != expected_episode_id:
        raise ClientEpisodeError("the boundary names the wrong episode")

    return EpisodeSummary(
        channel_key=expected_channel_key,
        seat_key=seat_key,
        frames=len(transitions),
        transitions=transitions,
        boundary=boundary,
        solved=boundary.kind == "terminal",
    )


async def capture_browser_episode(
    summary: EpisodeSummary,
    *,
    visit_id: str,
    context: CommandContext,
    epoch_id: str,
    generation: int,
    store: Store,
    verification: str = "visual-fallback",
    state_hash_chain_digest: Digest | None = None,
    artifacts: ArtifactStore | None = None,
    new_artifact_id: Callable[[], str] | None = None,
    new_upload_id: Callable[[], str] | None = None,
    now: Callable[[], str] | None = None,
    activity_key: str | None = None,
) -> CommandReceipt:
    """Commit a client-run episode under browser authority, fenced by generation.

    The commit carries a producer generation, so the store fences a write from a
    generation below the one installed on the episode stream. A newer client
    installs a strictly greater generation when it takes over.

    ``verification`` records how the server checked the run: ``deterministic`` when
    it re-executed the run and every state hash matched, or ``visual-fallback``
    when it could not re-execute. ``state_hash_chain_digest`` binds the verified
    trajectory when the verification is deterministic. The episode aggregate keeps
    the verdict, so the export shows whether the run was server-verified.

    The artifact store and its minters, when supplied, record the run's trajectory
    beside the ledger digests. A browser reports no values, so what is recorded is
    the server's own verified re-execution, handed in on the summary.
    """
    fenced = context.model_copy(
        update={"fencing": FencingClaim(epoch_id=epoch_id, generation=generation)}
    )
    return await capture_episode(
        summary,
        visit_id=visit_id,
        context=fenced,
        store=store,
        verification=verification,
        state_hash_chain_digest=state_hash_chain_digest,
        artifacts=artifacts,
        new_artifact_id=new_artifact_id,
        new_upload_id=new_upload_id,
        now=now,
        activity_key=activity_key,
    )


__all__ = [
    "ONNX_RUNTIME_URL",
    "BrowserGameSpec",
    "BrowserPartner",
    "ClientEpisodeError",
    "capture_browser_episode",
    "client_manifest",
    "parse_client_episode",
    "parse_client_part",
]
