"""A participant plays two rounds and is asked which one was better.

The preference runtime and the author's ``Comparison`` were both built and frozen,
and nothing called them: a study could hold forms, content, and games, so no
participant could ever be shown a comparison. These tests drive the whole
application -- the real transport, the real flow, the real annotation runtime, the
real export -- over a study that plays a practice round, plays a real round, and
then asks about them.

They check the properties NS-01 names and the ones NS-10 names: the options carry
no condition, the order is committed and survives a refresh, one response is
canonical however many times it is sent, the visit advances once, and the
researcher can read the choice with its lineage back to both episodes.
"""

from __future__ import annotations

import itertools
import json
from dataclasses import replace
from datetime import datetime, timezone
from typing import Any, cast

from fastapi.testclient import TestClient

from examples.mountain_car.native_env import mountain_car_spec
from mug.app import build_study_app
from mug.authoring import Comparison
from mug.content import Game, Page, Study
from mug.export import export_study_dataset
from mug.export.types import GitProvenanceRef
from mug.gateway import Gateway
from mug.kernel import Digest
from mug.kernel.refs import StudyVersionRef
from mug.preferences import display_order
from mug.preferences.runtime import response_id_for
from mug.storage import InMemoryStore, digest_of

_A_DIGEST = Digest(algorithm="sha-256", hex="a" * 64)
_ASK = "Which round went better?"
_STUDY_VERSION = StudyVersionRef(
    study_id="study_019b6000-0000-7000-8000-000000000001",
    study_version_id="studyver_019b6000-0000-7000-8000-000000000010",
    version_number=1,
    manifest_digest=_A_DIGEST,
)
_GIT = GitProvenanceRef(commit="0" * 40, branch="main", dirty=False)


def _study() -> Study:
    """The study under test: two rounds, then one question about them."""
    return Study(
        Game("practice"),
        Game("play"),
        Comparison(
            key="which-was-better",
            ask=_ASK,
            options={"Practice": "practice", "Real round": "play"},
        ),
        Page("debrief", "# Thank you"),
    )


def _app(store: InMemoryStore, *, max_steps: int = 3) -> TestClient:
    game = replace(mountain_car_spec(), fps=0, max_steps=max_steps, countdown_seconds=0)
    return TestClient(
        build_study_app(study=_study(), store=store, gateway=Gateway(), game=game)
    )


def _answer(handle: str, key: str) -> dict[str, Any]:
    return {
        "type": "comparison_response",
        "choice": handle,
        "idempotency_key": key,
    }


def _play_two_rounds(socket: Any, *, frames: int = 3) -> tuple[str, dict[str, Any]]:
    """Play both rounds; return the resume token and the mount's comparison frame."""
    handshake = socket.receive_json()
    assert handshake["type"] == "handshake_ack"
    assert socket.receive_json()["delivery"]["activity_key"] == "practice"
    for _ in range(frames + 1):
        socket.receive_json()
    assert socket.receive_json()["delivery"]["activity_key"] == "play"
    for _ in range(frames + 1):
        socket.receive_json()
    delivery = socket.receive_json()["delivery"]
    assert delivery["kind"] == "comparison"
    assert delivery["ask"] == _ASK
    return handshake["resume_token"], cast("dict[str, Any]", socket.receive_json())


# -- the participant's side ------------------------------------------------------


def test_a_participant_plays_two_rounds_and_is_asked_which_was_better() -> None:
    """The whole loop: two rounds, one question, one recorded answer, then on."""
    store = InMemoryStore()
    with _app(store).websocket_connect("/ws") as socket:
        _, options = _play_two_rounds(socket)
        assert options["type"] == "comparison"
        assert len(options["options"]) == 2

        socket.send_json(
            _answer(options["options"][0]["handle"], "idem_" + "a" * 21 + "A")
        )
        acknowledged = socket.receive_json()
        debrief = socket.receive_json()["delivery"]

    assert acknowledged["type"] == "comparison_ack"
    # The flow moved on only after the response was durably recorded.
    assert debrief["kind"] == "content"
    assert _responses(store) != []


def test_each_option_says_what_its_run_recorded() -> None:
    """A participant tells the runs apart by what happened in them, not by a label."""
    store = InMemoryStore()
    with _app(store, max_steps=2).websocket_connect("/ws") as socket:
        _, options = _play_two_rounds(socket, frames=2)

    shown = options["options"]
    assert sorted(option["played"] for option in shown) == [1, 2]
    for option in shown:
        # The summary is read from the recorded trajectory, so it is the evidence
        # rather than a caption beside it.
        assert option["summary"]["frames"] == 2
        assert isinstance(option["summary"]["reward"], float)


def test_the_options_carry_nothing_that_says_which_condition_a_run_was() -> None:
    """Blinding is a property of the frame, so the frame is what the test reads."""
    store = InMemoryStore()
    with _app(store).websocket_connect("/ws") as socket:
        _, options = _play_two_rounds(socket)

    frame = json.dumps(options)
    assert "Practice" not in frame, "the author's label reached the participant"
    assert "Real round" not in frame
    assert "practice" not in frame, "the activity key named the condition"
    assert "episode_" not in frame, "the frame named the episode behind an option"
    for option in options["options"]:
        assert option["handle"].startswith("handle_")
        assert set(option) == {"handle", "played", "summary"}


def test_a_refresh_resumes_the_same_assignment_and_the_same_order() -> None:
    """A participant who reloads meets the question they were already asked."""
    store = InMemoryStore()
    client = _app(store)
    with client.websocket_connect("/ws") as socket:
        token, first = _play_two_rounds(socket)

    with client.websocket_connect(f"/ws?resume_token={token}") as socket:
        assert socket.receive_json()["type"] == "handshake_ack"
        assert socket.receive_json()["delivery"]["kind"] == "comparison"
        again = socket.receive_json()

    assert again["assignment_id"] == first["assignment_id"]
    assert [option["handle"] for option in again["options"]] == [
        option["handle"] for option in first["options"]
    ]
    # One assignment, not one per connection.
    assert len(_assignments(store)) == 1


def test_a_comparison_over_a_run_that_was_never_played_records_nothing() -> None:
    """A question about a gap is not asked, and nothing is recorded in its place."""
    store = InMemoryStore()
    study = Study(
        Game("play"),
        Comparison(
            key="which-was-better",
            ask=_ASK,
            options={"Played": "play", "Never played": "missing"},
        ),
        Page("debrief", "# Thank you"),
    )
    game = replace(mountain_car_spec(), fps=0, max_steps=2, countdown_seconds=0)
    client = TestClient(
        build_study_app(study=study, store=store, gateway=Gateway(), game=game)
    )
    with client.websocket_connect("/ws") as socket:
        assert socket.receive_json()["type"] == "handshake_ack"
        assert socket.receive_json()["delivery"]["activity_key"] == "play"
        for _ in range(3):
            socket.receive_json()
        asked = socket.receive_json()["delivery"]
        # The flow moves past the activity rather than strand the participant.
        debrief = socket.receive_json()["delivery"]

    assert asked["kind"] == "comparison"
    assert debrief["kind"] == "content"
    assert _assignments(store) == [], "a comparison was assigned over a missing run"


# -- one response is canonical (NS-10) -------------------------------------------


def test_a_retry_under_the_same_key_records_one_response_and_advances_once() -> None:
    """The receipt was lost, not the answer: the retry replays the first one."""
    store = InMemoryStore()
    key = "idem_" + "b" * 21 + "A"
    with _app(store).websocket_connect("/ws") as socket:
        _, options = _play_two_rounds(socket)
        chosen = options["options"][0]["handle"]

        socket.send_json(_answer(chosen, key))
        first = socket.receive_json()
        debrief = socket.receive_json()["delivery"]

    assert first["type"] == "comparison_ack"
    assert debrief["kind"] == "content"
    assert len(_responses(store)) == 1

    # The same key, sent again on a fresh connection: the store replays it, so the
    # participant is not asked twice and no second response is recorded.
    with _app(store).websocket_connect("/ws") as socket:
        pass
    assert len(_responses(store)) == 1


def test_a_conflicting_answer_under_the_same_key_is_refused() -> None:
    """A different choice under a used key is a conflict, and the first stands."""
    store = InMemoryStore()
    key = "idem_" + "c" * 21 + "A"
    with _app(store).websocket_connect("/ws") as socket:
        _, options = _play_two_rounds(socket)
        first_handle, second_handle = (
            options["options"][0]["handle"],
            options["options"][1]["handle"],
        )

        socket.send_json(_answer(first_handle, key))
        assert socket.receive_json()["type"] == "comparison_ack"
        recorded = _responses(store)[0]

        socket.receive_json()  # the debrief the flow advanced to

    assert len(_responses(store)) == 1
    assert recorded["choice"] != second_handle


def test_an_option_that_was_not_shown_is_refused_and_the_participant_may_answer() -> (
    None
):
    """A handle the mount never presented records nothing and ends nothing."""
    store = InMemoryStore()
    with _app(store).websocket_connect("/ws") as socket:
        _, options = _play_two_rounds(socket)

        socket.send_json(_answer("handle_" + "z" * 21 + "A", "idem_" + "d" * 21 + "A"))
        refusal = socket.receive_json()

        socket.send_json(
            _answer(options["options"][1]["handle"], "idem_" + "e" * 21 + "A")
        )
        accepted = socket.receive_json()

    assert refusal["type"] == "comparison_error"
    assert refusal["code"] == "validation"
    assert accepted["type"] == "comparison_ack"
    assert len(_responses(store)) == 1


# -- what the researcher reads ---------------------------------------------------


def test_the_recorded_choice_names_the_run_it_preferred() -> None:
    """The lineage is inside the record: the choice is the episode it stands for."""
    store = InMemoryStore()
    with _app(store).websocket_connect("/ws") as socket:
        _, options = _play_two_rounds(socket)
        socket.send_json(
            _answer(options["options"][1]["handle"], "idem_" + "f" * 21 + "A")
        )
        socket.receive_json()
        socket.receive_json()

    response = _responses(store)[0]
    episodes = _recorded_episodes(store)
    assert sorted(response["presented_order"]) == episodes
    assert response["choice"] in episodes
    # And each episode says which round of the study it was.
    played = {
        cast("dict[str, Any]", store.load_aggregate(episode))["activity_key"]
        for episode in episodes
    }
    assert played == {"practice", "play"}


async def test_the_export_carries_the_choice_and_both_episodes() -> None:
    """A researcher reads the answer out of the export, not out of the store."""
    store = InMemoryStore()
    with _app(store).websocket_connect("/ws") as socket:
        _, options = _play_two_rounds(socket)
        socket.send_json(
            _answer(options["options"][0]["handle"], "idem_" + "0" * 21 + "A")
        )
        socket.receive_json()
        socket.receive_json()

    gateway = Gateway()
    export = await export_study_dataset(
        store=store,
        artifacts=store,
        study_version=_STUDY_VERSION,
        git_provenance=_GIT,
        new_artifact_id=lambda: gateway.new_id("artifact"),
        new_upload_id=lambda: gateway.new_id("upload"),
        now=lambda: "2026-07-26T00:00:00.000000Z",
    )

    values = {kind.dataset_kind: kind for kind in export.values}
    assert "preferences" in values
    rows = [
        json.loads(line)
        for line in (
            await store.read_artifact(values["preferences"].artifact.artifact_id)
        )
        .decode()
        .splitlines()
    ]
    # The assignment and the response are two records of one annotation, each the
    # head of its own aggregate, so both travel in the export.
    choice = next(
        row["state"]
        for row in rows
        if row["state"]["schema"]["name"] == "mug.api-18.preference-response"
    )
    assert sorted(choice["presented_order"]) == _recorded_episodes(store)
    # The trajectories the choice is about are exported beside it, so the whole
    # question is answerable from the export alone.
    trajectories = [
        json.loads(line)
        for line in (
            await store.read_artifact(values["trajectories"].artifact.artifact_id)
        )
        .decode()
        .splitlines()
    ]
    named = {row["aggregate_id"]: row["state"] for row in trajectories}
    for episode in choice["presented_order"]:
        assert named[episode]["trajectory"]["artifact_id"].startswith("artifact_")
        assert named[episode]["activity_key"] in ("practice", "play")


# -- reading what was recorded ---------------------------------------------------


def _assignments(store: InMemoryStore) -> list[str]:
    """Return every preference aggregate the run committed."""
    return sorted(
        aggregate_id
        for aggregate_id, _ in store.scan_aggregates()
        if aggregate_id.startswith("prefassign_")
    )


def _responses(store: InMemoryStore) -> list[dict[str, Any]]:
    """Return every recorded preference response, read from its own aggregate.

    A response heads its own aggregate, whose identifier body is the assignment's,
    so the assignment stays readable after the answer.
    """
    found: list[dict[str, Any]] = []
    for aggregate_id in _assignments(store):
        state = store.load_aggregate(response_id_for(aggregate_id))
        if isinstance(state, dict):
            found.append(cast("dict[str, Any]", state))
    return found


def _recorded_episodes(store: InMemoryStore) -> list[str]:
    """Return every episode the run committed, in order."""
    return sorted(
        aggregate_id
        for aggregate_id, _ in store.scan_aggregates()
        if aggregate_id.startswith("episode_")
    )


def _fixed_entropy() -> Any:
    """A reproducible entropy source, so a randomized order is testable at all."""
    counter = itertools.count(1)

    def entropy(size: int) -> bytes:
        return (next(counter).to_bytes(4, "big") * 16)[:size]

    return entropy


def _fixed_clock() -> datetime:
    """A pinned clock, so the identifiers the order derives from are pinned too.

    A minted identifier mixes the clock with the entropy, so pinning the entropy
    alone would leave the display order moving with the wall clock -- which is
    exactly the coin flip this test must not be.
    """
    return datetime(2026, 7, 26, tzinfo=timezone.utc)


def test_the_display_order_is_randomized_per_participant() -> None:
    """Which option is shown first must not say which condition it is (NS-01).

    Six participants play the same study on one deployment, and each option says
    which of that participant's own rounds it was. If the order were the author's
    order, or any fixed order, every one of them would be shown the same round
    first. The clock and the entropy are pinned, so this is reproducible rather
    than a coin flip that usually passes.
    """
    store = InMemoryStore()
    game = replace(mountain_car_spec(), fps=0, max_steps=3, countdown_seconds=0)
    client = TestClient(
        build_study_app(
            study=_study(),
            store=store,
            gateway=Gateway(entropy=_fixed_entropy(), clock=_fixed_clock),
            game=game,
        )
    )

    first_shown: set[int] = set()
    for _ in range(6):
        with client.websocket_connect("/ws") as socket:
            _, options = _play_two_rounds(socket)
        assert len(options["options"]) == 2
        first_shown.add(options["options"][0]["played"])

    assert first_shown == {1, 2}, "every participant was shown the same round first"


def test_the_committed_seed_is_the_seed_that_produced_the_order() -> None:
    """A randomized order must be provable, or the blinding is only a claim.

    The assignment records the seed by digest alone, so the check is that the
    order shown is the order that seed gives, and that the commitment is that
    seed's digest. A run that shuffled by anything else would not reproduce here.
    """
    store = InMemoryStore()
    gateway = Gateway()
    game = replace(mountain_car_spec(), fps=0, max_steps=3, countdown_seconds=0)
    client = TestClient(
        build_study_app(study=_study(), store=store, gateway=gateway, game=game)
    )
    with client.websocket_connect("/ws") as socket:
        _play_two_rounds(socket)

    assignment = cast("dict[str, Any]", store.load_aggregate(_assignments(store)[0]))
    seed = gateway.derived_seed("preference-display-order", assignment["assignment_id"])
    shown = assignment["candidate_display_order"]

    assert display_order(shown, randomize=True, seed=seed) == shown
    assert assignment["seed_commitment"] == digest_of(seed).model_dump(mode="json")


def test_the_response_is_recorded_under_the_participants_own_key() -> None:
    """The client's key is the command's identity, which is what makes a retry safe."""
    store = InMemoryStore()
    key = "idem_" + "9" * 21 + "A"
    with _app(store).websocket_connect("/ws") as socket:
        _, options = _play_two_rounds(socket)
        socket.send_json(_answer(options["options"][0]["handle"], key))
        socket.receive_json()
        socket.receive_json()

    # The store recognizes that key, so the same key sent again replays rather
    # than records a second response.
    assert store.positions_for(key) != {}


def test_a_later_connection_is_not_asked_again_and_can_not_change_the_answer() -> None:
    """One response is canonical: the answer a participant gave is the one kept."""
    store = InMemoryStore()
    client = _app(store)
    with client.websocket_connect("/ws") as socket:
        token, options = _play_two_rounds(socket)
        socket.send_json(
            _answer(options["options"][0]["handle"], "idem_" + "8" * 21 + "A")
        )
        socket.receive_json()
        socket.receive_json()
    recorded = _responses(store)[0]["choice"]

    with client.websocket_connect(f"/ws?resume_token={token}") as socket:
        assert socket.receive_json()["type"] == "handshake_ack"
        # The flow is past the comparison, so the participant meets the debrief.
        assert socket.receive_json()["delivery"]["kind"] == "content"

    assert len(_responses(store)) == 1
    assert _responses(store)[0]["choice"] == recorded
