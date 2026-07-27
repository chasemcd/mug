"""Several people and an AI in one environment (W8, the north-star story).

Until now no mounted mode could do it. The mesh seated people only, the
server-authoritative loop named one person by field, and the agent loop allowed at
most one. So the story the platform exists for -- two participants, a partner model
that plays and chats, a coach that only talks -- could not be run.

These drive it through the running application. The study writes **one list** of
who is in the environment, the mount reads the transport it needs from that list,
and two connections rendezvous into one interaction over one stepped environment.
One run is captured and both visits record it.

The seat somebody plays is the seat the interaction cast them into, which is what
makes a reconnection sit back down rather than start again.
"""

from __future__ import annotations

import asyncio
from collections.abc import Mapping
from typing import Any, ClassVar, cast

import pytest
from fastapi.testclient import TestClient
from starlette.testclient import WebSocketTestSession

from mug.agents import AgentGameSpec, AgentIds, HumanSeatSpec
from mug.app import build_study_app
from mug.authoring import Chat, Fallback, History, LLMAgent, Provider, Thoughts
from mug.content import Game, Page, Study
from mug.content.seats import Bot, Human, Model, MultiSeatGame, seat_game
from mug.game.multiseat import MultiStepResult
from mug.gateway import Gateway
from mug.participant import (
    _Gone,  # pyright: ignore[reportPrivateUsage]
    _Table,  # pyright: ignore[reportPrivateUsage]
    _watched,  # pyright: ignore[reportPrivateUsage]
)
from mug.participant_chat import ChatSeatSpec, ChatSpec
from mug.providers import ModelCall, ModelCompletion, Usage
from mug.storage import InMemoryStore, Store

_AGENTS = ("chef-0", "chef-1", "chef-2")
_UUID = "019b6000-0000-7000-8000-{:012x}"
_EPISODE_LEN = 8


class _Kitchen:
    """A three-seat environment that ends after a fixed number of steps.

    Every seat's observation carries what every seat last did, so a test can read
    off the recorded run whether a seat was really being stepped.
    """

    ACTIONS: ClassVar[list[str]] = ["STAY", "LEFT", "RIGHT"]

    def __init__(self, length: int = _EPISODE_LEN) -> None:
        self._t = 0
        self._length = length
        self._last: dict[str, int] = dict.fromkeys(_AGENTS, 0)

    def reset(self) -> MultiStepResult:
        self._t = 0
        self._last = dict.fromkeys(_AGENTS, 0)
        return MultiStepResult(
            observations={agent: [0.0, 0.0, 0.0] for agent in _AGENTS},
            rewards=dict.fromkeys(_AGENTS, 0.0),
            terminated=False,
            truncated=False,
        )

    def step(self, actions: Mapping[str, int]) -> MultiStepResult:
        self._t += 1
        for agent in _AGENTS:
            self._last[agent] = int(actions.get(agent, 0))
        seen = [float(self._last[agent]) for agent in _AGENTS]
        done = self._t >= self._length
        return MultiStepResult(
            observations={agent: list(seen) for agent in _AGENTS},
            rewards=dict.fromkeys(_AGENTS, 1.0 if done else 0.0),
            terminated=done,
            truncated=False,
        )

    def legal_actions(self, agent_id: str) -> list[str]:
        return list(self.ACTIONS)

    def text_view(self, agent_id: str) -> str:
        return f"t={self._t}; you are {agent_id}"


class _Partner(LLMAgent):
    """The model that plays a seat and comments on the same reply (W7)."""

    provider = Provider.OSS
    model = "fake-local"
    decides_every = 1
    on_timeout = Fallback.REPEAT_LAST

    def get_prompt(
        self,
        env: object,
        agent_id: str,
        history: History,
        chat: Chat,
        thoughts: Thoughts,
    ) -> str:
        heard = "; ".join(message.text for message in chat.last(5))
        return f"{env.text_view(agent_id)}\nheard: {heard}"  # type: ignore[attr-defined]

    def say(self, reply: str, env: Any, agent_id: str) -> str | None:
        for line in str(reply).splitlines():
            if line.startswith("Say: "):
                return line.removeprefix("Say: ").strip()
        return None


class _Adapter:
    """A keyless adapter that answers on a script and records every prompt."""

    def __init__(self, *, say: str = "I have the onions") -> None:
        self._say = say
        self.prompts: list[str] = []

    async def __call__(self, call: ModelCall) -> ModelCompletion:
        payload: Any = call.payload
        self.prompts.append(payload["messages"][0]["content"])
        # It speaks once, so a test can count the messages rather than race a loop.
        said = f"\nSay: {self._say}" if len(self.prompts) == 1 else ""
        return _completion(f"Action: RIGHT{said}")


def _completion(text: str) -> ModelCompletion:
    """Return one completed model reply carrying the given text."""
    return ModelCompletion(
        outcome="completed",
        resolved_model="fake-local",
        usage=Usage(input_tokens=1, output_tokens=1, cost_micros=0),
        output={"text": text},
    )


class _AlwaysLeft:
    """A local policy that plays the same action every frame."""

    def __init__(self, action: int = 1) -> None:
        self.action = action
        self.asked = 0

    def decide(self, observation: object) -> int:
        self.asked += 1
        return self.action


def _view(env: Any, agent_id: str) -> str:
    return cast("str", env.text_view(agent_id))


def _kitchen(length: int = _EPISODE_LEN, *, fps: int = 0) -> MultiSeatGame:
    """Return the environment the seats sit in, with nobody in it yet."""
    return MultiSeatGame(
        make_env=lambda: _Kitchen(length),
        channel_key="kitchen",
        action_bindings={"ArrowLeft": 1, "ArrowRight": 2},
        default_action=0,
        decision_timeout=1.0,
        fps=fps,
        max_steps=length + 4,
    )


# -- what the author writes -------------------------------------------------------


def test_the_study_says_which_agent_each_player_takes() -> None:
    """Three kinds of player, each named against the agent it plays."""
    compiled = seat_game(
        _kitchen(),
        {
            "chef-0": Human(),
            "chef-1": Model(_Partner(), adapter=_Adapter()),
            "chef-2": Bot(_AlwaysLeft()),
        },
        activity_key="play",
        derived_id=lambda kind, words: f"{kind}_{words}",
    )

    # Each player takes the agent it was written against, and the seat is recorded
    # under that agent -- so a record says which part of the game it was.
    assert [one.agent_id for one in compiled.human_seats] == ["chef-0"]
    assert [one.agent_id for one in compiled.seats] == ["chef-1"]
    assert [one.agent_id for one in compiled.bots] == ["chef-2"]
    assert compiled.human_seats[0].seat_key == "chef-0"
    assert compiled.seats[0].seat_key == "chef-1"
    assert compiled.bots[0].seat_key == "chef-2"
    # Nothing about the model seat had to be written but the agent itself.
    assert compiled.seats[0].ids.agent_key == "partner"
    assert compiled.seats[0].actor_id == "actor_play:chef-1"


def test_a_study_may_not_say_who_sits_where_twice() -> None:
    """One statement of the seating, or the two of them can disagree."""
    with pytest.raises(ValueError, match="name the human seats once"):
        AgentGameSpec(
            channel_key="kitchen",
            make_env=_Kitchen,
            human=HumanSeatSpec(agent_id="chef-0", seat_key="seat-1"),
            humans=(HumanSeatSpec(agent_id="chef-1", seat_key="seat-2"),),
        )


def test_a_game_with_nobody_in_it_is_refused() -> None:
    """An environment with no seat is a run nobody is in, so it is not a game."""
    with pytest.raises(ValueError, match="at least one seat"):
        AgentGameSpec(channel_key="kitchen", make_env=_Kitchen)


# -- the table several people share -----------------------------------------------


class _Held:
    """A seat input that holds one action, standing in for a person's keys."""

    def __init__(self, action: int = 0) -> None:
        self.action = action

    def decide(self, observation: object) -> int:
        return self.action


async def _two_seat_table() -> _Table:
    """Return a table that seats two people, with nobody at it yet."""
    return _Table(interaction_id="interaction_x", size=2)


def test_a_table_waits_until_every_seat_has_somebody_at_it() -> None:
    """One person is not a full table, and the run must not start without the other.

    The fill guard is what makes this true. Without it the first person to sit
    starts the run alone, and the seat the second person was about to take is
    stepped by nobody -- a two-person study that quietly ran as a one-person one.
    """

    async def sit_down() -> tuple[bool, bool]:
        table = await _two_seat_table()
        table.sit("seat-1", cast("Any", _Held()))
        waiting = asyncio.ensure_future(table.seated())
        await asyncio.sleep(0)
        alone = waiting.done()
        table.sit("seat-2", cast("Any", _Held()))
        await asyncio.wait_for(waiting, timeout=1)
        return alone, waiting.done()

    alone, together = asyncio.run(sit_down())
    assert not alone, "the run would have started with one seat unplayed"
    assert together


def test_exactly_one_connection_at_a_table_runs_the_episode() -> None:
    """Everybody waits for the same run, and only one of them starts it."""

    async def claim_twice() -> list[bool]:
        table = await _two_seat_table()
        return [table.claim(), table.claim(), table.claim()]

    assert asyncio.run(claim_twice()) == [True, False, False]


def test_a_connection_that_goes_away_stops_waiting_for_the_run() -> None:
    """It holds no task for a run nobody is reading, and it advances nothing.

    The other side of this is what the reconnection depends on: the connection
    that went away moves the visit nowhere, so the one that comes back is the one
    that reads the run and moves it on.
    """

    async def leave_first() -> str:
        table = await _two_seat_table()
        gone: asyncio.Task[None] = asyncio.ensure_future(asyncio.sleep(0))
        try:
            await _watched(table, gone)
        except _Gone:
            return "gone"
        return "waited"

    assert asyncio.run(leave_first()) == "gone"


def test_a_connection_that_stays_reads_the_run_it_waited_for() -> None:
    """The same wait returns the shared run when the connection is still there."""

    async def stay() -> str | None:
        table = await _two_seat_table()
        reader: asyncio.Task[None] = asyncio.ensure_future(asyncio.sleep(5))
        table.settle("stream_one")
        try:
            return await _watched(table, reader)
        finally:
            reader.cancel()

    assert asyncio.run(stay()) == "stream_one"


def test_a_seating_written_as_a_list_is_refused() -> None:
    """Order is not a statement of who plays what, so it is not accepted as one.

    This is the whole reason the seating is a map. Driving the car and running the
    traffic light are different tasks with different data, and a list would let a
    study swap them by reordering two lines with nothing in the records to say it
    had happened.
    """
    with pytest.raises(ValueError, match="which agent each player takes"):
        Game("play", _kitchen(), seats=[Human(), Human()])


def test_a_seating_with_nobody_in_it_is_refused() -> None:
    """An activity that names a seating names somebody in it."""
    with pytest.raises(ValueError, match="nobody in it"):
        Game("play", _kitchen(), seats={})


def test_which_agent_a_player_takes_survives_being_written_in_another_order() -> None:
    """The same seating written differently compiles to the same seats.

    A list would fail this: reversing two lines would hand each player the other's
    part. The map says what it means, so the order it is written in carries no
    meaning at all.
    """

    def compile_it(seats: dict[str, Any]) -> dict[str, str]:
        built = seat_game(
            _kitchen(),
            seats,
            activity_key="play",
            derived_id=lambda kind, words: f"{kind}_{words}",
        )
        return {
            **{one.agent_id: "human" for one in built.human_seats},
            **{one.agent_id: "model" for one in built.seats},
            **{one.agent_id: "bot" for one in built.bots},
        }

    written = {"chef-0": Human(), "chef-2": Bot(_AlwaysLeft())}
    reversed_order = {"chef-2": Bot(_AlwaysLeft()), "chef-0": Human()}
    assert compile_it(written) == compile_it(reversed_order)
    assert compile_it(written) == {"chef-0": "human", "chef-2": "bot"}


def test_the_same_study_compiles_the_same_seats_twice() -> None:
    """A model seat's recorded identity is derived, so a replay names what ran."""
    seats = {"chef-0": Human(), "chef-1": Model(_Partner(), adapter=_Adapter())}
    first = seat_game(
        _kitchen(),
        seats,
        activity_key="play",
        derived_id=lambda kind, words: f"{kind}_{words}",
    )
    second = seat_game(
        _kitchen(),
        seats,
        activity_key="play",
        derived_id=lambda kind, words: f"{kind}_{words}",
    )
    assert first.seats[0].actor_id == second.seats[0].actor_id
    assert first.seats[0].ids == second.seats[0].ids


# -- the running application ------------------------------------------------------


def _study(
    seats: dict[str, Any],
    *,
    chat: ChatSpec | None = None,
    length: int = _EPISODE_LEN,
    fps: int = 0,
) -> Study:
    """Return the study whose one game activity seats the given players."""
    return Study(
        Game("play", _kitchen(length, fps=fps), seats=seats, chat=chat),
        Page("debrief", "# Thanks"),
    )


def _client(store: Store, study: Study) -> TestClient:
    return TestClient(build_study_app(study=study, store=store, gateway=Gateway()))


def _at_the_game(socket: WebSocketTestSession) -> str:
    """Read past the handshake to the game delivery, and return the resume token."""
    handshake = socket.receive_json()
    assert handshake["type"] == "handshake_ack"
    assert socket.receive_json()["delivery"]["kind"] == "game"
    return cast("str", handshake["resume_token"])


def _drain(socket: WebSocketTestSession) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Collect the stepped frames this connection is pushed, then what follows."""
    frames: list[dict[str, Any]] = []
    message = cast("dict[str, Any]", socket.receive_json())
    while message.get("type") == "frame":
        frames.append(message)
        message = cast("dict[str, Any]", socket.receive_json())
    return frames, message


def _episodes(store: Store) -> list[dict[str, Any]]:
    """Return every recorded episode head, as typed mappings."""
    found: list[dict[str, Any]] = []
    for aggregate_id, state in store.scan_aggregates():
        if aggregate_id.startswith("episode_") and isinstance(state, dict):
            found.append(cast("dict[str, Any]", state))
    return found


def _of_kind(store: Store, name: str) -> list[dict[str, Any]]:
    """Return every recorded head of one schema name."""
    found: list[dict[str, Any]] = []
    for _id, state in store.scan_aggregates():
        if not isinstance(state, dict):
            continue
        head = cast("dict[str, Any]", state)
        schema = head.get("schema")
        if isinstance(schema, dict) and cast("dict[str, Any]", schema).get(
            "name"
        ) == name:
            found.append(head)
    return found


def test_two_participants_and_a_model_partner_share_one_environment() -> None:
    """The proof: two people and a model in one interaction over one stepped run."""
    store = InMemoryStore()
    adapter = _Adapter()
    study = _study(
        {
            "chef-0": Human(),
            "chef-1": Human(),
            "chef-2": Model(_Partner(), adapter=adapter, text_view=_view),
        }
    )
    client = _client(store, study)
    with (
        client,
        client.websocket_connect("/ws") as first,
        client.websocket_connect("/ws") as second,
    ):
        _at_the_game(first)
        _at_the_game(second)
        first_frames, first_next = _drain(first)
        second_frames, second_next = _drain(second)

    # One run, not two: both connections watched the same stepped timeline.
    assert len(_episodes(store)) == 1
    assert len(first_frames) == _EPISODE_LEN
    assert [frame["frame_number"] for frame in first_frames] == [
        frame["frame_number"] for frame in second_frames
    ]
    # Every seat acted on every frame, the model's beside the two people's.
    assert all(set(frame["actions"]) == set(_AGENTS) for frame in first_frames)
    assert adapter.prompts, "the model seat was never asked to decide"
    # Both flows advanced past the game on the one run they shared.
    assert first_next["delivery"]["kind"] == "content"
    assert second_next["delivery"]["kind"] == "content"


def test_the_two_people_are_cast_into_one_interaction() -> None:
    """Both are members of the game channel of one interaction, and it is recorded."""
    store = InMemoryStore()
    study = _study({"chef-0": Human(), "chef-1": Human()})
    client = _client(store, study)
    with (
        client,
        client.websocket_connect("/ws") as first,
        client.websocket_connect("/ws") as second,
    ):
        _at_the_game(first)
        _at_the_game(second)
        _drain(first)
        _drain(second)

    interactions = _of_kind(store, "mug.api-06.interaction")
    assert len(interactions) == 1
    memberships = _of_kind(store, "mug.api-06.membership")
    assert {one["channel_key"] for one in memberships} == {"kitchen"}
    assert len({one["actor_id"] for one in memberships}) == 2
    assert {one["access"] for one in memberships} == {"read_write"}


def test_a_bot_seat_plays_beside_a_person() -> None:
    """A study's own policy sits in the environment without reaching a provider."""
    store = InMemoryStore()
    policy = _AlwaysLeft(action=1)
    study = _study(
        {"chef-0": Human(), "chef-1": Bot(policy), "chef-2": Bot(_AlwaysLeft(action=2))}
    )
    client = _client(store, study)
    with client, client.websocket_connect("/ws") as socket:
        _at_the_game(socket)
        frames, following = _drain(socket)

    assert len(frames) == _EPISODE_LEN
    assert policy.asked >= _EPISODE_LEN
    # The bot's own action is on every frame it played.
    assert all(frame["actions"]["chef-1"] == 1 for frame in frames)
    assert all(frame["actions"]["chef-2"] == 2 for frame in frames)
    assert following["delivery"]["kind"] == "content"


def test_one_person_alone_still_plays_the_seats_beside_them() -> None:
    """A game with one human seat waits for nobody, which is what it always did."""
    store = InMemoryStore()
    study = _study({"chef-0": Human(), "chef-1": Bot(_AlwaysLeft())})
    client = _client(store, study)
    with client, client.websocket_connect("/ws") as socket:
        _at_the_game(socket)
        frames, following = _drain(socket)

    assert len(frames) == _EPISODE_LEN
    assert following["delivery"]["kind"] == "content"


class _Coach(LLMAgent):
    """A model that only ever talks: it plays no seat in the environment."""

    provider = Provider.OSS
    model = "fake-local"

    def get_prompt(
        self,
        env: object,
        agent_id: str,
        history: History,
        chat: Chat,
        thoughts: Thoughts,
    ) -> str:
        return "; ".join(message.text for message in chat.last(5)) or "say hello"


def _coach_seat(adapter: Any, channel: str) -> ChatSeatSpec:
    """Return the chat-only coach seat, on the channel the study names."""
    return ChatSeatSpec(
        agent=_Coach(),
        adapter=adapter,
        ids=AgentIds(
            agent_version_id="agentver_" + _UUID.format(0x900),
            agent_definition_id="agentdef_" + _UUID.format(0x901),
            agent_key="coach",
            version_number=1,
            prompt_version_id="promptver_" + _UUID.format(0x902),
            fallback_policy_key="coach-fallback",
        ),
        actor_id="actor_" + _UUID.format(0x903),
        channel=channel,
    )


def test_a_coach_talks_in_a_channel_it_does_not_play_in() -> None:
    """The whole story: two people, a partner that plays and talks, a coach.

    The coach is a seat of the conversation and of nothing else -- it is not in the
    environment, so the run steps three seats and the room holds four members. That
    is what "different visibility" means here: a member of the interaction that
    plays no part in the game channel.
    """
    store = InMemoryStore()
    study = _study(
        {
            "chef-0": Human(),
            "chef-1": Human(),
            "chef-2": Model(_Partner(), adapter=_Adapter(), text_view=_view),
        },
        chat=ChatSpec(
            channel_key="team",
            seats=(_coach_seat(_Adapter(say="watch the pot"), "team"),),
        ),
    )
    client = _client(store, study)
    with (
        client,
        client.websocket_connect("/ws") as first,
        client.websocket_connect("/ws") as second,
    ):
        _at_the_game(first)
        _at_the_game(second)
        frames, _ = _drain(first)
        _drain(second)

    # Three seats are in the environment. The coach is not one of them.
    assert all(set(frame["actions"]) == set(_AGENTS) for frame in frames)
    memberships = _of_kind(store, "mug.api-06.membership")
    coach = "actor_" + _UUID.format(0x903)

    def access(channel: str, actor: str) -> str:
        for one in memberships:
            if one["channel_key"] == channel and one["actor_id"] == actor:
                return cast("str", one["access"])
        raise AssertionError(f"no membership of {channel!r} for {actor!r}")

    talkers = {one["actor_id"] for one in memberships if one["channel_key"] == "team"}
    assert len(talkers) == 4, "two people, a playing partner, and a coach"
    # Everybody talks; the coach is written down on the game channel with no access
    # to it. Absence is not the record -- a refusal is (W5).
    assert access("team", coach) == "read_write"
    assert access("kitchen", coach) == "none"
    players = {
        one["actor_id"]
        for one in memberships
        if one["channel_key"] == "kitchen" and one["access"] == "read_write"
    }
    assert len(players) == 3
    assert coach not in players


def test_the_model_partner_plays_and_talks_to_both_people() -> None:
    """The north-star story in full: two people, a playing partner, one channel."""
    store = InMemoryStore()
    adapter = _Adapter(say="I have the onions")
    study = _study(
        {
            "chef-0": Human(),
            "chef-1": Human(),
            "chef-2": Model(_Partner(), adapter=adapter, text_view=_view),
        },
        # The conversation does not say how many people are in it. The game
        # seats them, so a room that formed for one would be two rooms here.
        chat=ChatSpec(channel_key="team"),
    )
    client = _client(store, study)
    with (
        client,
        client.websocket_connect("/ws") as first,
        client.websocket_connect("/ws") as second,
    ):
        _at_the_game(first)
        _at_the_game(second)
        _drain(first)
        _drain(second)

    said = _of_kind(store, "mug.api-08.chat-message")
    assert len(said) == 1, "the playing partner said nothing"
    assert said[0]["channel_key"] == "team"
    # The conversation and the game are one interaction with two channels.
    interactions = _of_kind(store, "mug.api-06.interaction")
    assert len(interactions) == 1
    channels = {one["channel_key"] for one in _of_kind(store, "mug.api-06.membership")}
    assert channels == {"team", "kitchen"}


def test_a_reconnection_sits_back_down_at_the_seat_it_left() -> None:
    """The proof asked for: two people finish a run with a drop in the middle.

    One participant's connection goes away while the environment is still
    stepping. The run belongs to the table rather than to either socket, so the
    other person plays on; the seat that was left holds no key and does nothing.
    When the participant comes back they are given the seat they already had, they
    read the run that finished, and the visit moves on **once** -- the connection
    that went away advances nothing.
    """
    store = InMemoryStore()
    study = _study({"chef-0": Human(), "chef-1": Human()}, length=40, fps=25)
    client = _client(store, study)
    with client, client.websocket_connect("/ws") as second:
        with client.websocket_connect("/ws") as first:
            token = _at_the_game(first)
            _at_the_game(second)
            # Let the run get under way, then drop this connection.
            for _ in range(3):
                assert first.receive_json()["type"] == "frame"

        with client.websocket_connect(f"/ws?resume_token={token}") as back:
            assert back.receive_json()["type"] == "handshake_ack"
            assert back.receive_json()["delivery"]["kind"] == "game"
            _, following = _drain(back)
            _, other = _drain(second)

    # One run, and the participant who came back reads the screen after it.
    assert len(_episodes(store)) == 1
    assert following["delivery"]["kind"] == "content"
    assert other["delivery"]["kind"] == "content"
