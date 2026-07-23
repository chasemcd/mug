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

from dataclasses import dataclass, field
from typing import Any, cast

from pydantic import ValidationError

from mug.game.capture import capture_episode
from mug.game.determinism import state_hash_source
from mug.game.runtime import EpisodeSummary
from mug.game.types import EpisodeBoundary, GameTransition
from mug.kernel import CommandReceipt, Digest
from mug.runtime import CommandContext, FencingClaim
from mug.storage import Store


@dataclass(frozen=True)
class BrowserGameSpec:
    """One browser-executed game channel a study supplies.

    ``source_bundle`` is the Python source the client runs in Pyodide; it defines
    the environment and its drawing, the browser twin of ``GameSpec``.
    ``requires`` are the pinned packages the client installs once. ``seed`` fixes
    the episode seed the client must use, and ``hooks`` declares the determinism
    hooks the environment supports. ``server_notes`` stands for private server
    manifest data; it never reaches the client manifest.
    """

    channel_key: str
    source_bundle: str
    requires: tuple[str, ...]
    action_bindings: dict[str, int]
    default_action: int
    seed: int
    hooks: tuple[str, ...] = ("snapshot-restore", "state-hash")
    fps: int = 30
    max_steps: int = 200
    countdown_seconds: int = 3
    server_notes: str | None = field(default=None)


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
    return {
        "mode": "browser",
        "channel_key": spec.channel_key,
        "episode_id": episode_id,
        "interaction_id": interaction_id,
        "seat_key": seat_key,
        "source_bundle": spec.source_bundle,
        "requires": list(spec.requires),
        "action_bindings": dict(spec.action_bindings),
        "default_action": spec.default_action,
        "seed": spec.seed,
        "hooks": list(spec.hooks),
        "fps": spec.fps,
        "max_steps": spec.max_steps,
        "countdown_seconds": spec.countdown_seconds,
        "state_hash_source": state_hash_source(),
    }


class ClientEpisodeError(ValueError):
    """The client-reported episode did not meet the transition contract."""


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
    )


__all__ = [
    "BrowserGameSpec",
    "ClientEpisodeError",
    "capture_browser_episode",
    "client_manifest",
    "parse_client_episode",
]
