"""Run one comparison activity over the realtime socket: the annotation transport.

This is the annotation counterpart to the game stepping loop and the chat mount.
Where a game mount owns the socket to step an environment and record transitions,
this mount owns the socket to ask one question about runs the participant already
made, and to record the answer. It writes through the same command spine, so one
annotation's lineage is a canonical event stream like an episode's.

The activity runs in four recorded steps:

1. The mount resolves each authored option to the recorded thing it names. A
   comparison of runs names the study's own game activities, and the episode each
   activity captured names the trajectory artifact that holds what happened
   (``mug.game.trajectory``); a comparison of model outputs names the generations
   the study recorded before its participants arrived, and each one names the
   visible artifact that holds the text (``mug.agents.generation``). An option with
   nothing recorded behind it is not an option, and the activity records no
   annotation rather than invent one.
2. It assigns the participant a blinded, ordered set of candidates. The order is a
   permutation of a seed the assignment commits to by digest, so it is reproducible
   and carries no signal about which candidate is which.
3. It presents the options in that order. What goes to the browser is a display
   handle and what the option recorded -- how long a run went and what it earned,
   or the text a generation produced. Never the author's label, the episode, the
   generation, the artifact, or the provider that answered, because those are the
   condition the study is measuring.
4. It takes the one response and commits it against the assignment, then the flow
   advances past the activity with the streams it wrote.

The assignment is the exposure record: it states which candidates were presented
and in which order, and the response re-attests that same order beside the choice,
so what the participant saw is recorded rather than reconstructed.

Everything a participant must meet twice is derived, not minted: the assignment
identifier, each display handle, and the randomization seed all come from the flow
and the activity through the gateway's derivation. So a participant who refreshes
the page, or who returns after the connection drops, reaches the same assignment
with the same options in the same order, and a retry of their answer under the same
idempotency key replays to the first receipt instead of recording a second choice
(NS-10).
"""

from __future__ import annotations

import json
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any, cast

from fastapi import WebSocket, WebSocketDisconnect

from mug.agents.generation import RecordedGeneration
from mug.authoring import Comparison
from mug.content import FlowState, flow_of
from mug.game.capture import recorded_trajectory
from mug.game.trajectory import TrajectoryFrame, read_trajectory
from mug.gateway import Gateway
from mug.kernel import (
    ArtifactRef,
    DataHandlingRef,
    Digest,
    PrincipalRef,
    WireCommandEnvelope,
)
from mug.preferences import (
    ComparisonIds,
    CompiledComparison,
    PreferenceAssignment,
    PreferenceService,
    compile_comparison,
)
from mug.preferences.runtime import response_id_for
from mug.providers import read_generation_form
from mug.realtime import Session
from mug.runtime import CommandContext
from mug.storage import ArtifactStore, Store

_RESEARCH = DataHandlingRef(privacy_labels=["research"])
_ENVELOPE_DIGEST = Digest(algorithm="sha-256", hex="0" * 64)

# The schema name an assignment head carries. The aggregate advances assignment ->
# response, so the head says which stage this activity is at.
_ASSIGNMENT_SCHEMA = "mug.api-18.preference-assignment"

# The derivation roles. Each keeps one derived value independent of the others, so
# a display handle can never be re-derived from an assignment identifier.
_ASSIGNMENT_ROLE = "prefassign"
_QUERY_ROLE = "prefquery"
_PROTOCOL_DEFINITION_ROLE = "prefdef"
_PROTOCOL_VERSION_ROLE = "prefver"
_ORDER_SEED_ROLE = "preference-display-order"

# How many frames the mount reads before it stops waiting for an answer. A
# participant may mis-click an option that is not theirs, or their client may send
# frames of its own, so the bound is well above one answer; a connection that
# reaches it has stopped answering, and the activity stays unanswered for the next
# connection rather than being spent here.
_MAX_FRAMES_READ = 64


@dataclass(frozen=True)
class RecordedRun:
    """One run this participant made, ready to stand as a comparison candidate.

    ``candidate_key`` is the episode itself, which is what the recorded choice
    names. ``played`` is the ordinal of the run among the runs this visit recorded
    (the first, the second), and ``trajectory`` is the artifact that holds what
    happened in it.
    """

    candidate_key: str
    activity_key: str
    episode_id: str
    played: int
    trajectory: ArtifactRef


@dataclass(frozen=True)
class Option:
    """One authored option resolved to the recorded thing it stands for.

    ``option`` is the value the author wrote, which is how the compiled comparison
    finds it again. ``candidate_key`` is what the recorded choice names -- the
    episode for a run, the generation for a model output -- so the answer carries
    its own lineage. ``artifact`` is the one artifact the participant is shown from,
    and ``run`` is set only for a run, which is described from its trajectory.
    """

    option: str
    candidate_key: str
    artifact: ArtifactRef
    run: RecordedRun | None = None


@dataclass(frozen=True)
class ComparisonOutcome:
    """What one comparison activity recorded, and why it recorded nothing.

    ``streams`` names the streams the annotation committed on, for the flow to
    record. ``recorded`` is false when no annotation was made, and ``reason`` then
    says which precondition was missing, so a study is never told that a comparison
    happened when none did.

    ``finished`` is false when the participant has not answered yet and could still
    answer -- they closed the tab, or the connection dropped. The flow must then
    stay where it is: advancing would spend the activity on a participant who was
    never asked, and they would come back to the next screen with the question gone.
    """

    streams: list[str] = field(default_factory=list)
    recorded: bool = False
    reason: str | None = None
    finished: bool = True


# --- resolving the runs the participant made ---------------------------------


def recorded_runs(store: Store, flow: FlowState) -> dict[str, tuple[str, int]]:
    """Map each game activity of this visit to its episode and its ordinal.

    A flow records the stream every captured activity wrote, in the order the
    participant reached them, and an episode's stream shares its aggregate's
    identifier body. So the visit's own record is enough to find what the
    participant played, with no session memory that a refresh would lose.
    """
    found: dict[str, tuple[str, int]] = {}
    played = 0
    for stream_id in flow.captured_streams:
        episode_id = "episode_" + stream_id.split("_", 1)[1]
        state = store.load_aggregate(episode_id)
        if not isinstance(state, dict):
            continue
        activity_key = cast("dict[str, Any]", state).get("activity_key")
        if not isinstance(activity_key, str):
            continue
        played += 1
        found[activity_key] = (episode_id, played)
    return found


def resolve_options(
    store: Store,
    flow: FlowState,
    comparison: Comparison,
    generations: Mapping[str, RecordedGeneration] | None = None,
) -> list[Option] | None:
    """Resolve every authored option to the recorded thing it names.

    What an option names follows from the comparison's kind: a run names one of the
    study's game activities, and a model output names one of the generations the
    study recorded. Both end at one artifact, which is what a candidate references.

    Returns None when any option has nothing recorded behind it: a comparison of one
    thing against a gap is not the comparison the author wrote, and presenting it
    would record a choice about something that does not exist.
    """
    if comparison.of == "trajectory":
        return _resolve_runs(store, flow, comparison)
    return _resolve_generations(comparison, generations or {})


def _resolve_runs(
    store: Store, flow: FlowState, comparison: Comparison
) -> list[Option] | None:
    """Resolve each option to the run this participant made for that activity."""
    played_by_activity = recorded_runs(store, flow)
    resolved: list[Option] = []
    for run in comparison.options.values():
        if not isinstance(run, str):
            return None
        found = played_by_activity.get(run)
        if found is None:
            return None
        episode_id, played = found
        trajectory = recorded_trajectory(store, episode_id)
        if trajectory is None:
            return None
        resolved.append(
            Option(
                option=run,
                candidate_key=episode_id,
                artifact=trajectory,
                run=RecordedRun(
                    candidate_key=episode_id,
                    activity_key=run,
                    episode_id=episode_id,
                    played=played,
                    trajectory=trajectory,
                ),
            )
        )
    return resolved


def _resolve_generations(
    comparison: Comparison, generations: Mapping[str, RecordedGeneration]
) -> list[Option] | None:
    """Resolve each option to the generation the study recorded under that key.

    The option resolves to the *visible* form and to nothing else. The raw provider
    response and the private provenance are recorded beside it and are not reachable
    from here, so no path exists from a comparison screen to the provider's identity.
    """
    resolved: list[Option] = []
    for key in comparison.options.values():
        if not isinstance(key, str):
            return None
        generation = generations.get(key)
        if generation is None:
            return None
        resolved.append(
            Option(
                option=key,
                candidate_key=generation.generation_id,
                artifact=generation.visible,
            )
        )
    return resolved


async def describe(artifacts: ArtifactStore, option: Option) -> dict[str, Any]:
    """Describe one option in the terms the participant answers about.

    A run is described by how long it went and what it earned, read from its own
    recorded trajectory; a generation is described by the text it produced, read
    from its visible form. Both are the evidence itself rather than a label beside
    it, and neither says which condition the option was.
    """
    if option.run is not None:
        return {
            "played": option.run.played,
            "summary": await run_summary(artifacts, option.run),
        }
    return await _shown_form(artifacts, option.artifact)


async def _shown_form(artifacts: ArtifactStore, ref: ArtifactRef) -> dict[str, Any]:
    """Read one generation's participant-visible form, and send it as it stands.

    The mount does not filter here, and that is deliberate. What may be shown is
    decided once, where the generation is written: the visible form holds the text
    and nothing else, and it is the only one of the four classified ``public``. A
    mount that re-filtered would make that classification decorative, and would
    quietly go on working if it were ever handed the raw provider response.
    """
    body: Any = await read_generation_form(artifacts, ref)
    if not isinstance(body, dict):
        return {"text": ""}
    return cast("dict[str, Any]", body)


async def run_summary(artifacts: ArtifactStore, run: RecordedRun) -> dict[str, Any]:
    """Summarize one recorded run in terms every environment shares.

    A participant answers about runs they played, so the summary is there to help
    them tell the runs apart: how long it went and what it earned. Both are read
    from the recorded trajectory, so the summary is the evidence rather than a
    label beside it, and neither says which condition the run was.
    """
    frames = read_trajectory(await artifacts.read_artifact(run.trajectory.artifact_id))
    return {"frames": len(frames), "reward": _total_reward(frames)}


def _total_reward(frames: Sequence[TrajectoryFrame]) -> float:
    """Return what a recorded run earned, over every seat and every frame."""
    total = 0.0
    for frame in frames:
        total += sum(float(value) for value in frame.rewards.values())
    return round(total, 6)


# --- the assignment ----------------------------------------------------------


def _compile(
    gateway: Gateway,
    comparison: Comparison,
    options: Sequence[Option],
    *,
    assignment_id: str,
) -> CompiledComparison:
    """Compile the author's comparison against what this participant will be shown.

    Each candidate is named by the thing it stands for -- the episode of a run, the
    generation of a model output -- so the recorded choice says what was preferred
    and a reader needs nothing beside it. The author's label is deliberately not the
    name, because the label is the condition under test.

    Each candidate is shown behind a handle derived from the assignment and the
    option's place in it, so the same participant meets the same handles on every
    connection and no two participants meet the same ones.
    """
    artifacts = {option.option: option.artifact for option in options}
    keys = {option.option: option.candidate_key for option in options}
    positions = iter(range(len(options)))
    return compile_comparison(
        comparison,
        ids=ComparisonIds(
            protocol_version_id=gateway.derived_id(
                _PROTOCOL_VERSION_ROLE, f"comparison:{comparison.key}"
            ),
            protocol_definition_id=gateway.derived_id(
                _PROTOCOL_DEFINITION_ROLE, f"comparison:{comparison.key}"
            ),
        ),
        resolve=lambda run: artifacts[cast("str", run)],
        new_handle=lambda: gateway.derived_handle(f"{assignment_id}:{next(positions)}"),
        key_for=lambda _label, run: keys[cast("str", run)],
    )


def assignment_id_for(gateway: Gateway, flow_id: str, activity_key: str) -> str:
    """Return the one assignment identifier this flow and activity always give."""
    return gateway.derived_id(_ASSIGNMENT_ROLE, f"{flow_id}:{activity_key}")


def _existing_assignment(
    store: Store, assignment_id: str
) -> PreferenceAssignment | None:
    """Return the assignment already recorded for this activity, if there is one.

    A reconnection reads it rather than assigning a second time, so the order the
    participant is shown is the order that was recorded.
    """
    state = store.load_aggregate(assignment_id)
    if not isinstance(state, dict):
        return None
    body = cast("dict[str, Any]", state)
    if body.get("schema", {}).get("name") != _ASSIGNMENT_SCHEMA:
        return None
    return PreferenceAssignment.model_validate(body)


def _already_answered(store: Store, assignment_id: str) -> bool:
    """Report whether this assignment has already recorded its one response.

    An assignment can address one response aggregate, so the answer is whether that
    aggregate exists. The assignment's own head stays the assignment, which is what
    keeps the enrollment and the seed commitment readable after the answer.
    """
    return store.load_aggregate(response_id_for(assignment_id)) is not None


# --- the socket --------------------------------------------------------------


def _envelope(
    command_name: str, target_id: str, data: dict[str, Any], idem: str
) -> WireCommandEnvelope:
    """Build the wire envelope for one annotation command."""
    schema = {
        "name": "mug.command-envelope",
        "version": 0,
        "digest": _ENVELOPE_DIGEST.model_dump(mode="json"),
    }
    return WireCommandEnvelope.model_validate(
        {
            "schema": schema,
            "protocol_version": "0.1.0",
            "command": {"name": command_name, "version": 0},
            "request_id": "request_019b6000-0000-7000-8000-000000000001",
            "idempotency_key": idem,
            "target": {"id": target_id},
            "payload": {
                "schema": {
                    "name": "mug.edge.payload",
                    "version": 0,
                    "digest": _ENVELOPE_DIGEST.model_dump(mode="json"),
                },
                "data": data,
            },
        }
    )


def _mint(
    gateway: Gateway,
    principal: PrincipalRef,
    *,
    command: str,
    target_id: str,
    data: dict[str, Any],
    idem: str,
) -> CommandContext:
    """Mint the trusted context for one annotation command.

    The idempotency key comes from the participant's own frame when they sent one,
    and the command identity is content-addressed from that key and this payload. So
    an identical retry re-mints identical identifiers and replays, and the same key
    over a different choice is refused as a conflict (NS-10).
    """
    return gateway.mint(
        _envelope(command, target_id, data, idem),
        principal=principal,
        data_handling=_RESEARCH,
    )


def _fresh_idem(gateway: Gateway) -> str:
    """Mint one well-formed idempotency key for a participant who sent none."""
    body = gateway.new_id("request").split("_", 1)[1].replace("-", "")
    return "idem_" + body[:21] + "A"


def _client_idem(frame: Mapping[str, Any], gateway: Gateway) -> str:
    """Read the participant's idempotency key, or mint one when they sent none."""
    key = frame.get("idempotency_key")
    if isinstance(key, str) and key.startswith("idem_") and len(key) <= 32:
        return key
    return _fresh_idem(gateway)


async def _read_frame(websocket: WebSocket) -> dict[str, Any] | None:
    """Read the next frame, or None when the participant goes away.

    A frame that is not a json object is dropped rather than ending the activity: a
    malformed frame must not cost a participant their answer.
    """
    while True:
        try:
            raw = await websocket.receive_text()
        except WebSocketDisconnect:
            return None
        try:
            loaded: Any = json.loads(raw)
        except ValueError:
            continue
        if isinstance(loaded, dict):
            return cast("dict[str, Any]", loaded)


async def _present(
    websocket: WebSocket,
    comparison: Comparison,
    assignment: PreferenceAssignment,
    shown: Sequence[dict[str, Any]],
) -> None:
    """Send the question and the blinded options, in the order committed."""
    await websocket.send_json(
        {
            "type": "comparison",
            "activity_key": comparison.key,
            "ask": comparison.ask,
            "style": comparison.style,
            "assignment_id": assignment.assignment_id,
            "options": list(shown),
        }
    )


async def _refuse(websocket: WebSocket, code: str, message: str) -> None:
    """Tell the participant why their answer was not taken."""
    await websocket.send_json(
        {"type": "comparison_error", "code": code, "message": message}
    )


async def run_comparison_activity(
    websocket: WebSocket,
    session: Session,
    comparison: Comparison,
    *,
    store: Store,
    gateway: Gateway,
    now: Callable[[], str],
    generations: Mapping[str, RecordedGeneration] | None = None,
) -> ComparisonOutcome:
    """Own the socket for one comparison activity and return what it recorded.

    The mount assigns the blinded candidates once, presents them in the committed
    order, and takes the one response. It returns when the response is recorded,
    when the participant leaves, or at once when this assignment has already been
    answered -- a participant is asked once, however many times they connect.

    An outcome that is not ``finished`` means the participant has not answered and
    still could, so the caller leaves the flow where it is.
    """
    flow_id = session.state.get("flow_id")
    if not isinstance(flow_id, str):
        return ComparisonOutcome(reason="the connection has no flow")
    flow = flow_of(store.load_aggregate(flow_id))
    if flow is None:
        return ComparisonOutcome(reason="the connection has no flow")
    assignment_id = assignment_id_for(gateway, flow_id, comparison.key)
    if _already_answered(store, assignment_id):
        return ComparisonOutcome(recorded=True)

    options = resolve_options(store, flow, comparison, generations)
    if options is None:
        return ComparisonOutcome(
            reason="an option named something this study has not recorded"
        )
    compiled = _compile(gateway, comparison, options, assignment_id=assignment_id)
    service = PreferenceService(store=store)
    assignment = await _assign(
        service,
        store,
        gateway,
        session,
        comparison,
        compiled,
        assignment_id=assignment_id,
        flow_id=flow_id,
    )
    if assignment is None:
        return ComparisonOutcome(reason="the assignment did not commit")

    handles = {
        candidate.candidate_key: candidate.display_handle
        for candidate in compiled.candidates
    }
    by_handle = {handle: key for key, handle in handles.items()}
    by_key = {option.candidate_key: option for option in options}
    shown = [
        {
            "handle": handles[key],
            **await describe(cast("ArtifactStore", store), by_key[key]),
        }
        for key in assignment.candidate_display_order
    ]
    await _present(websocket, comparison, assignment, shown)
    return await _take_response(
        websocket,
        service,
        gateway,
        session,
        assignment,
        by_handle=by_handle,
        now=now,
    )


async def _assign(
    service: PreferenceService,
    store: Store,
    gateway: Gateway,
    session: Session,
    comparison: Comparison,
    compiled: CompiledComparison,
    *,
    assignment_id: str,
    flow_id: str,
) -> PreferenceAssignment | None:
    """Return this activity's assignment, creating it the first time only.

    A reconnection reads the assignment the store already holds, so the order the
    participant sees is the order that was recorded, not one recomputed beside it.
    """
    existing = _existing_assignment(store, assignment_id)
    if existing is not None:
        return existing
    context = _mint(
        gateway,
        session.principal,
        command="preference.assign",
        target_id=assignment_id,
        data={"activity_key": comparison.key, "flow_id": flow_id},
        idem=_fresh_idem(gateway),
    )
    receipt, assignment = await service.assign(
        context=context,
        protocol=compiled.protocol,
        query_id=gateway.derived_id(_QUERY_ROLE, f"{flow_id}:{comparison.key}"),
        enrollment_id=_enrollment_of(gateway, session, flow_id),
        candidate_keys=compiled.candidate_keys,
        seed=gateway.derived_seed(_ORDER_SEED_ROLE, assignment_id),
    )
    return assignment if receipt.outcome == "accepted" else None


def _enrollment_of(gateway: Gateway, session: Session, flow_id: str) -> str:
    """Return the enrollment this annotation belongs to.

    A launch-gated visit has a durable enrollment and the assignment names it. An
    ungated demo has none -- it bootstraps an anonymous subject per connection -- so
    the assignment names the visit's own derived stand-in and the record stays
    within one visit, which is all an ungated run can honestly claim.
    """
    enrollment_id = session.state.get("enrollment_id")
    if isinstance(enrollment_id, str):
        return enrollment_id
    return gateway.derived_id("enrollment", flow_id)


async def _take_response(
    websocket: WebSocket,
    service: PreferenceService,
    gateway: Gateway,
    session: Session,
    assignment: PreferenceAssignment,
    *,
    by_handle: Mapping[str, str],
    now: Callable[[], str],
) -> ComparisonOutcome:
    """Read frames until the one response is recorded, or the participant leaves.

    A handle that was not presented is refused and the participant may answer again;
    a recorded response ends the activity. A retry that the store replays is the
    same recorded response, so it ends the activity too and the flow advances once.
    """
    for _ in range(_MAX_FRAMES_READ):
        frame = await _read_frame(websocket)
        if frame is None:
            return ComparisonOutcome(
                reason="the participant left before answering", finished=False
            )
        if frame.get("type") != "comparison_response":
            continue
        choice = by_handle.get(cast("str", frame.get("choice")))
        if choice is None:
            await _refuse(
                websocket, "validation", "that option was not one of the two shown"
            )
            continue
        context = _mint(
            gateway,
            session.principal,
            command="preference.respond",
            target_id=response_id_for(assignment.assignment_id),
            data={"choice": choice},
            idem=_client_idem(frame, gateway),
        )
        receipt, _ = await service.respond(
            context=context,
            assignment_id=assignment.assignment_id,
            choice=choice,
            presented_order=assignment.candidate_display_order,
            submitted_at=now(),
        )
        if receipt.outcome == "accepted":
            await websocket.send_json(
                {"type": "comparison_ack", "receipt_id": receipt.receipt_id}
            )
            return ComparisonOutcome(streams=[context.stream_id], recorded=True)
        # The store refused a second, different answer: the first one is canonical
        # and stays. The participant is told, and the activity is over either way.
        await _refuse(websocket, "conflict", "this comparison is already answered")
        return ComparisonOutcome(recorded=True, reason="a second answer was refused")
    return ComparisonOutcome(reason="the participant sent no answer", finished=False)


__all__ = [
    "ComparisonOutcome",
    "Option",
    "RecordedRun",
    "assignment_id_for",
    "describe",
    "recorded_runs",
    "resolve_options",
    "run_comparison_activity",
    "run_summary",
]
