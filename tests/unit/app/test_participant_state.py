"""What a participant carries from one activity, and one part, to the next (W10).

`StateDocument` was frozen with no runtime user, so nothing a participant did in
one activity could reach another. These drive the whole path: a page writes a
namespace the study declared, a later activity is delivered what it wrote, and a
participant who comes back for the second part of the study finds it still there.

**Only what the second part declares is carried** (NS-08). A namespace the new
version does not ask for is not handed to it, which is a statement about scope
rather than about storage: state a later part never declared is state its
participants were never told it would read.
"""

from __future__ import annotations

from typing import Any, cast

from fastapi.testclient import TestClient
from starlette.testclient import WebSocketTestSession

from mug.app import build_study_app
from mug.client import RealtimeCommand
from mug.content import Choice, Form, Page, Study
from mug.gateway import Gateway
from mug.kernel import Digest, SchemaRef
from mug.storage import InMemoryStore, Store
from mug.visits.state import State

_A_DIGEST = Digest(algorithm="sha-256", hex="a" * 64)


def _frame(channel: str, payload: dict[str, Any], tag: str) -> dict[str, Any]:
    """Build one command frame on a channel, with a unique idempotency key."""
    command = RealtimeCommand(
        command_id=f"command_019b6000-0000-7000-8000-0000000000{tag}",
        channel_key=channel,
        intent_schema=SchemaRef(name="mug.demo.intent", version=0, digest=_A_DIGEST),
        payload_digest=_A_DIGEST,
        idempotency_key="idem_" + tag.ljust(21, "0") + "A",
        submitted_at="2026-07-27T00:00:00.000000Z",
    )
    return {
        "type": "command",
        "command": command.model_dump(mode="json", exclude_none=True),
        "payload": payload,
    }


def _advance(tag: str, answers: dict[str, Any] | None = None) -> dict[str, Any]:
    return _frame("flow.advance", {"answers": answers or {}}, tag)


def _set_state(
    namespace: str, value: dict[str, Any], revision: int, tag: str
) -> dict[str, Any]:
    return _frame(
        "state.set",
        {"namespace": namespace, "value": value, "revision": revision},
        tag,
    )


def _settled(socket: WebSocketTestSession, limit: int = 40) -> dict[str, Any]:
    """Read past the parse acknowledgement to what the command settled as.

    An accepted command settles as its durable acknowledgement; a refused one
    settles as a safe error frame that names no value the participant sent.
    """
    for _ in range(limit):
        frame = cast("dict[str, Any]", socket.receive_json())
        if frame.get("type") == "error":
            return frame
        ack = frame.get("ack")
        if isinstance(ack, dict) and cast("dict[str, Any]", ack)["ack_kind"] != (
            "parsed"
        ):
            return frame
    raise AssertionError("the command settled as nothing")


def _delivery(socket: WebSocketTestSession, limit: int = 40) -> dict[str, Any]:
    """Read frames until a delivery arrives, and return it."""
    for _ in range(limit):
        frame = cast("dict[str, Any]", socket.receive_json())
        delivery = frame.get("delivery")
        if isinstance(delivery, dict):
            return cast("dict[str, Any]", delivery)
    raise AssertionError("no delivery arrived")


def _state_documents(store: Store) -> set[tuple[str, str]]:
    """Return every (visit, namespace) a state document was written for.

    The delivery is filtered by what a part declares, so reading the delivery
    alone cannot tell whether a namespace was **carried into the visit at all**.
    That is the NS-08 rule, so it is checked where it happens: the store.
    """
    found: set[tuple[str, str]] = set()
    for _id, state in store.scan_aggregates():
        if not isinstance(state, dict):
            continue
        head = cast("dict[str, Any]", state)
        schema = head.get("schema")
        if not isinstance(schema, dict):
            continue
        if cast("dict[str, Any]", schema).get("name") == "mug.api-04.state-document":
            found.add((cast("str", head["visit_id"]), cast("str", head["namespace"])))
    return found


def _one_part(*, state: list[State]) -> Study:
    """A study of two pages, so a page can write and a later page can read."""
    return Study(
        Form("consent", Choice("agree", "Do you agree?", ["yes", "no"])),
        Page("notes", "# Make a note"),
        Page("debrief", "# Thank you"),
        state=state,
    )


_SECRET = b"one-secret-for-both-parts"
_SIGNING = b"one-signing-key-for-both-parts--"


def _app(store: Store, study: Study, *, launch: bool = False) -> Any:
    """Build one deployment over the store. Two parts share the secrets, not the study.

    The gateway secret has to be shared for the derived identifiers to agree, and
    the signing key for the return link of one part to verify in the next -- which
    is exactly what a real multi-process deployment sets (see ``build_app_from_env``).
    """
    return build_study_app(
        study=study,
        store=store,
        gateway=Gateway(secret=_SECRET),
        require_launch=launch,
        signing_key=_SIGNING,
    )


def _client(store: Store, study: Study, *, launch: bool = False) -> TestClient:
    return TestClient(_app(store, study, launch=launch))


# -- what a page writes, a later activity reads -----------------------------------


def test_a_later_activity_is_delivered_what_an_earlier_one_wrote() -> None:
    """The gap this closes: nothing a participant did could reach another activity."""
    store = InMemoryStore()
    client = _client(store, _one_part(state=[State("progress")]))
    with client, client.websocket_connect("/ws") as socket:
        assert socket.receive_json()["type"] == "handshake_ack"
        first = _delivery(socket)
        # Nothing has been written, so the namespace is delivered empty rather
        # than missing: a page's first read and its hundredth are one shape.
        assert first["state"] == {"progress": {}}

        socket.send_json(_advance("01", {"agree": "yes"}))
        assert _delivery(socket)["content"]["content_key"] == "notes"

        socket.send_json(_set_state("progress", {"seen": ["notes"]}, 0, "02"))
        assert _settled(socket)["ack"]["ack_kind"] == "accepted"

        socket.send_json(_advance("03"))
        later = _delivery(socket)

    assert later["content"]["content_key"] == "debrief"
    assert later["state"] == {"progress": {"seen": ["notes"]}}


def test_a_namespace_is_written_more_than_once() -> None:
    """A page keeps a running note, so the second write must land as well.

    Every earlier test wrote each namespace once, and once is the case that
    creates the record. Writing again is the case that updates it, and it is the
    one a study actually does.
    """
    store = InMemoryStore()
    client = _client(store, _one_part(state=[State("progress")]))
    with client, client.websocket_connect("/ws") as socket:
        assert socket.receive_json()["type"] == "handshake_ack"
        _delivery(socket)
        socket.send_json(_set_state("progress", {"step": 1}, 0, "20"))
        assert _settled(socket)["ack"]["ack_kind"] == "accepted"
        socket.send_json(_set_state("progress", {"step": 2}, 1, "21"))
        assert _settled(socket)["ack"]["ack_kind"] == "accepted"
        socket.send_json(_set_state("progress", {"step": 3}, 2, "22"))
        assert _settled(socket)["ack"]["ack_kind"] == "accepted"

        socket.send_json(_advance("23", {"agree": "yes"}))
        later = _delivery(socket)

    assert later["state"] == {"progress": {"step": 3}}


def test_a_namespace_the_study_never_declared_is_refused() -> None:
    """A page cannot open a store nobody analyses and no export knows about."""
    store = InMemoryStore()
    client = _client(store, _one_part(state=[State("progress")]))
    with client, client.websocket_connect("/ws") as socket:
        assert socket.receive_json()["type"] == "handshake_ack"
        _delivery(socket)
        socket.send_json(_set_state("smuggled", {"condition": "hard"}, 0, "04"))
        refusal = _settled(socket)

    assert refusal["type"] == "error"
    assert refusal["category"] == "validation"
    assert "smuggled" in refusal["message"]


def test_a_namespace_the_study_keeps_to_itself_is_not_the_participants_to_write() -> (
    None
):
    """R-13: a value a page could write is a value a participant could choose."""
    store = InMemoryStore()
    study = _one_part(state=[State("score", write="study")])
    client = _client(store, study)
    with client, client.websocket_connect("/ws") as socket:
        assert socket.receive_json()["type"] == "handshake_ack"
        _delivery(socket)
        socket.send_json(_set_state("score", {"points": 9000}, 0, "05"))
        refusal = _settled(socket)

    assert refusal["type"] == "error"
    assert "may not write" in refusal["message"]


def test_a_namespace_the_study_keeps_to_itself_is_not_delivered() -> None:
    """A score a participant must not see does not travel to the page showing them."""
    store = InMemoryStore()
    study = _one_part(state=[State("progress"), State("secret", read="study")])
    client = _client(store, study)
    with client, client.websocket_connect("/ws") as socket:
        assert socket.receive_json()["type"] == "handshake_ack"
        first = _delivery(socket)

    assert set(first["state"]) == {"progress"}


def test_a_write_that_lost_a_race_is_refused_rather_than_overwriting() -> None:
    """Two tabs are the ordinary case, and last-write-wins loses one of them."""
    store = InMemoryStore()
    client = _client(store, _one_part(state=[State("progress")]))
    with client, client.websocket_connect("/ws") as socket:
        assert socket.receive_json()["type"] == "handshake_ack"
        _delivery(socket)
        socket.send_json(_set_state("progress", {"tab": "one"}, 0, "06"))
        assert _settled(socket)["ack"]["ack_kind"] == "accepted"
        # The second tab still holds revision zero, so its write is stale.
        socket.send_json(_set_state("progress", {"tab": "two"}, 0, "07"))
        refusal = _settled(socket)

    assert refusal["type"] == "error"
    assert refusal["category"] == "conflict"
    # It is told the revision it lost to, so the page re-reads rather than guesses.
    assert "revision 1" in refusal["message"]


def test_a_study_that_keeps_nothing_is_delivered_nothing() -> None:
    """A study that declares no namespace reads exactly as it did before W10."""
    store = InMemoryStore()
    client = _client(store, _one_part(state=[]))
    with client, client.websocket_connect("/ws") as socket:
        assert socket.receive_json()["type"] == "handshake_ack"
        first = _delivery(socket)

    assert "state" not in first


# -- the second part of a study ---------------------------------------------------


def _part_one() -> Study:
    """Part one keeps two namespaces: one the next part wants, one it does not."""
    return Study(
        Form("consent", Choice("agree", "Do you agree?", ["yes", "no"])),
        Page("notes", "# Part one"),
        state=[State("carried"), State("dropped")],
    )


def _part_two() -> Study:
    """Part two keeps one namespace from part one and opens one of its own.

    ``fresh`` is what part one never wrote. It is declared here, so it is
    delivered -- empty -- and **no document is opened for it in the new visit**:
    carrying nothing is not the same as carrying an empty thing, and a record that
    says a namespace was carried when it held nothing is a false statement about
    what the participant brought with them.
    """
    return Study(
        Page("welcome-back", "# Part two"),
        Page("debrief", "# Thank you"),
        state=[State("carried"), State("fresh")],
    )


def _finish_part_one(client: TestClient, ticket: str) -> str:
    """Play part one to the end, writing both namespaces, and return the token."""
    with client.websocket_connect(f"/ws?ticket={ticket}") as socket:
        token = cast("str", socket.receive_json()["resume_token"])
        assert _delivery(socket)["form"]["form_key"] == "consent"

        socket.send_json(_set_state("carried", {"answer": 42}, 0, "10"))
        assert _settled(socket)["ack"]["ack_kind"] == "accepted"
        socket.send_json(_set_state("dropped", {"scratch": "working"}, 0, "11"))
        assert _settled(socket)["ack"]["ack_kind"] == "accepted"

        socket.send_json(_advance("12", {"agree": "yes"}))
        assert _delivery(socket)["content"]["content_key"] == "notes"
        socket.send_json(_advance("13"))
        assert _delivery(socket)["kind"] == "complete"
    return token


def test_the_second_part_reads_what_the_first_part_wrote() -> None:
    """The NS-08 proof: a participant comes back and finds what they built up.

    Part two is a different study version served over the same store. The return
    link brings the same enrollment into a **new** visit under that version, and
    what part one kept is carried into it.
    """
    store = InMemoryStore()
    one = _app(store, _part_one(), launch=True)
    token = _finish_part_one(TestClient(one), one.state.launch_ticket)

    two = _app(store, _part_two(), launch=True)
    with TestClient(two) as client, client.websocket_connect(
        f"/ws?resume_token={token}"
    ) as socket:
        assert socket.receive_json()["type"] == "handshake_ack"
        back = _delivery(socket)

    # A new part, opened at its own first activity rather than at the end of the
    # part they finished.
    assert back["content"]["content_key"] == "welcome-back"
    assert back["state"]["carried"] == {"answer": 42}


def test_a_namespace_the_second_part_does_not_declare_is_not_carried() -> None:
    """Scope, not storage: state a part never declared was never consented to it.

    The check is on the **store**, not on the delivery. A namespace filtered out of
    what a page is sent has still been written into the new visit, and NS-08 is
    about what the new part holds rather than about what it shows.
    """
    store = InMemoryStore()
    one = _app(store, _part_one(), launch=True)
    token = _finish_part_one(TestClient(one), one.state.launch_ticket)
    first_part = _state_documents(store)
    assert {namespace for _visit, namespace in first_part} == {"carried", "dropped"}

    two = _app(store, _part_two(), launch=True)
    with TestClient(two) as client, client.websocket_connect(
        f"/ws?resume_token={token}"
    ) as socket:
        assert socket.receive_json()["type"] == "handshake_ack"
        back = _delivery(socket)

    # Both declared namespaces are delivered; the one nobody wrote is empty.
    assert back["state"] == {"carried": {"answer": 42}, "fresh": {}}
    # But only the one that held something was written into the new visit. The
    # namespace part two dropped was not carried, and the one it opened fresh has
    # no document claiming it was.
    opened = _state_documents(store) - first_part
    assert {namespace for _visit, namespace in opened} == {"carried"}
    assert len(opened) == 1


def _left_part_one_unfinished(client: TestClient, ticket: str) -> str:
    """Start part one, write a namespace, and leave without finishing it."""
    with client.websocket_connect(f"/ws?ticket={ticket}") as socket:
        token = cast("str", socket.receive_json()["resume_token"])
        assert _delivery(socket)["form"]["form_key"] == "consent"
        socket.send_json(_set_state("carried", {"answer": 7}, 0, "30"))
        assert _settled(socket)["ack"]["ack_kind"] == "accepted"
    return token


def test_a_return_before_the_part_is_finished_is_not_moved_to_the_next_one() -> None:
    """A new version is not a new part for somebody still in the old one.

    Moving them on would abandon the part they were in and the plan committed for
    it (D05-1), so it does not happen. This deployment cannot present that part
    either -- one deployment serves one version -- so the connection is refused
    safely instead of being shown an activity from a study nobody is running.
    """
    store = InMemoryStore()
    one = _app(store, _part_one(), launch=True)
    token = _left_part_one_unfinished(TestClient(one), one.state.launch_ticket)

    two = _app(store, _part_two(), launch=True)
    with TestClient(two) as client, client.websocket_connect(
        f"/ws?resume_token={token}"
    ) as socket:
        refusal = cast("dict[str, Any]", socket.receive_json())

    assert refusal["type"] == "error"
    assert refusal["code"] == "policy.version_unavailable"
    # And nothing was opened for a second part: no new visit, no carried state.
    assert {namespace for _visit, namespace in _state_documents(store)} == {"carried"}
    assert len(_state_documents(store)) == 1


def test_the_same_deployment_still_re_presents_an_unfinished_part() -> None:
    """The refusal is about a version that moved, not about coming back at all."""
    store = InMemoryStore()
    one = _app(store, _part_one(), launch=True)
    token = _left_part_one_unfinished(TestClient(one), one.state.launch_ticket)

    same = _app(store, _part_one(), launch=True)
    with TestClient(same) as client, client.websocket_connect(
        f"/ws?resume_token={token}"
    ) as socket:
        assert socket.receive_json()["type"] == "handshake_ack"
        back = _delivery(socket)

    # Back where they were, with what they had written still theirs.
    assert back["form"]["form_key"] == "consent"
    assert back["state"]["carried"] == {"answer": 7}


def _part_three() -> Study:
    """A third part, so "the part they were last in" is a real choice."""
    return Study(
        Page("third", "# Part three"),
        state=[State("carried")],
    )


def _finish_a_middle_part(client: TestClient, token: str, tag: str) -> str:
    """Walk part two to its end, writing over what part one carried in."""
    with client.websocket_connect(f"/ws?resume_token={token}") as socket:
        back = cast("str", socket.receive_json()["resume_token"])
        assert _delivery(socket)["content"]["content_key"] == "welcome-back"
        socket.send_json(_set_state("carried", {"answer": 43}, 1, tag))
        assert _settled(socket)["ack"]["ack_kind"] == "accepted"
        socket.send_json(_advance("41"))
        assert _delivery(socket)["content"]["content_key"] == "debrief"
        socket.send_json(_advance("42"))
        assert _delivery(socket)["kind"] == "complete"
    return back


def test_a_third_part_carries_what_the_second_part_left_not_the_first() -> None:
    """The part they were last in is the one that is carried, not the first one."""
    store = InMemoryStore()
    one = _app(store, _part_one(), launch=True)
    token = _finish_part_one(TestClient(one), one.state.launch_ticket)

    two = _app(store, _part_two(), launch=True)
    token = _finish_a_middle_part(TestClient(two), token, "40")

    three = _app(store, _part_three(), launch=True)
    with TestClient(three) as client, client.websocket_connect(
        f"/ws?resume_token={token}"
    ) as socket:
        assert socket.receive_json()["type"] == "handshake_ack"
        back = _delivery(socket)

    assert back["content"]["content_key"] == "third"
    # 43 is what part two left. 42 was part one's, and reaching back past the part
    # they were last in would hand them a value they had already replaced.
    assert back["state"]["carried"] == {"answer": 43}


def test_a_return_to_the_same_part_resumes_it_rather_than_opening_another() -> None:
    """A return link is still a return link: only a new version is a new part."""
    store = InMemoryStore()
    one = _app(store, _part_one(), launch=True)
    token = _finish_part_one(TestClient(one), one.state.launch_ticket)

    same = _app(store, _part_one(), launch=True)
    with TestClient(same) as client, client.websocket_connect(
        f"/ws?resume_token={token}"
    ) as socket:
        assert socket.receive_json()["type"] == "handshake_ack"
        back = _delivery(socket)

    # The part they finished is the part they come back to, completed.
    assert back["kind"] == "complete"
