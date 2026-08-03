"""How long one key press lasts, which is the study's decision and not the loop's.

The rewrite read the keys a participant was **holding** and mapped them to an
action on every frame. For a game of continuous control that is right: a slime
holding left is moving left, and letting go is what stops it. For a game on a grid
it is wrong in a way a participant feels at once -- a tap of the pick-up key that
lasts 100 ms at thirty frames a second is three actions, so a dish is put down and
picked straight back up, and a tap of an arrow crosses the room.

The legacy platform had both, and so does the frozen contract: ``InputScheme.mode``
is ``pressed_keys`` or ``single_keystroke`` (API-09). Nothing produced that record
and nothing read that field, so every study got the held reading whatever it meant
to say.

These modules use ASD-STE100 Simplified Technical English.
"""

from __future__ import annotations

from mug.game.runtime import InputState

_BINDINGS = {"ArrowUp": 0, "ArrowLeft": 2, "w": 4, ("ArrowUp", "ArrowLeft"): 9}
_IDLE = 6


def _held(mode: str) -> InputState:
    """Return one seat's input in the named mode."""
    return InputState(dict(_BINDINGS), _IDLE, mode=mode)


def test_a_held_key_acts_on_every_frame_when_the_study_reads_what_is_held() -> None:
    """The mode a game of continuous control needs, and the one that was always on."""
    seat = _held("pressed_keys")
    seat.press(["ArrowLeft"])

    assert [seat.action() for _ in range(4)] == [2, 2, 2, 2]


def test_a_held_key_is_one_action_when_the_study_counts_presses() -> None:
    """The fault the owner met: one tap of a key must be one action.

    Holding the key down for four frames is still one press, so the frames after it
    are idle. Without this a tap of the pick-up key put a dish down and took it
    straight back.
    """
    seat = _held("single_keystroke")
    seat.press(["w"])

    assert [seat.action() for _ in range(4)] == [4, _IDLE, _IDLE, _IDLE]


def test_the_same_key_pressed_again_is_another_action() -> None:
    """A press is counted when the key arrives, so two taps are two moves."""
    seat = _held("single_keystroke")
    seat.press(["ArrowLeft"])
    assert seat.action() == 2
    seat.press([])
    assert seat.action() == _IDLE
    seat.press(["ArrowLeft"])

    assert seat.action() == 2


def test_a_key_still_held_while_another_arrives_does_not_count_again() -> None:
    """Only the key that arrived is a new press; what was already down is not.

    A participant who holds an arrow and then taps the pick-up key means one move
    and one pick-up, not a second move as well.
    """
    seat = _held("single_keystroke")
    seat.press(["ArrowLeft"])
    assert seat.action() == 2
    seat.press(["ArrowLeft", "w"])

    assert seat.action() == 4
    assert seat.action() == _IDLE


def test_a_chord_is_one_press_of_the_pair() -> None:
    """Counting presses must not lose the chord: the whole held set is resolved."""
    seat = _held("single_keystroke")
    seat.press(["ArrowLeft"])
    assert seat.action() == 2
    seat.press(["ArrowLeft", "ArrowUp"])

    assert seat.action() == 9, "the chord was read as its single key"


def test_taps_that_arrive_faster_than_the_game_steps_are_kept_in_order() -> None:
    """Two quick taps are two moves, and they are played in the order they came."""
    seat = _held("single_keystroke")
    seat.press(["ArrowLeft"])
    seat.press([])
    seat.press(["ArrowUp"])
    seat.press([])

    assert [seat.action() for _ in range(3)] == [2, 0, _IDLE]


def test_a_flood_of_taps_does_not_play_out_after_the_participant_stopped() -> None:
    """Some buffer makes a double tap two moves; an endless one is a runaway.

    A key that auto-repeats, or a moment of panic at the end of a round, must not
    leave the seat playing moves for seconds after the participant let go.
    """
    seat = _held("single_keystroke")
    for _ in range(50):
        seat.press(["ArrowLeft"])
        seat.press([])

    played = [seat.action() for _ in range(60)]

    assert played.count(2) <= 8, "the seat kept an unbounded queue of presses"
    assert played[-1] == _IDLE, "the seat was still playing after the presses ended"


def test_a_key_nobody_bound_is_not_a_press() -> None:
    """A participant typing beside the game does not move their chef."""
    seat = _held("single_keystroke")
    seat.press(["q"])

    assert seat.action() == _IDLE


def test_a_study_that_says_nothing_reads_what_is_held() -> None:
    """The default is what every study had before the mode was readable."""
    seat = InputState(dict(_BINDINGS), _IDLE)
    seat.press(["ArrowLeft"])

    assert [seat.action() for _ in range(3)] == [2, 2, 2]


def test_the_kitchen_counts_presses_and_the_court_reads_what_is_held() -> None:
    """The two shipped studies choose differently, and both are right.

    A kitchen is a grid, so one press is one move. A court is continuous control,
    where letting go of a direction is itself a decision -- and its diagonal jumps
    are chords a participant holds.
    """
    import pytest

    pytest.importorskip("cogrid", reason="uv pip install cogrid==0.3.2")
    from examples.cogrid.overcooked_server_auth import overcooked_server_auth_study

    kitchen = overcooked_server_auth_study().game_activities["play"]
    assert kitchen.held is False

    pytest.importorskip("slime_volleyball", reason="uv pip install slime_volleyball")
    from examples.slime_volleyball.human_heuristic import slime_heuristic_study

    court = slime_heuristic_study().game_activities["play"]
    assert court.held is True


# -- a chord is a sequence of keys --------------------------------------------


def test_a_chord_is_written_as_the_sequence_of_keys_it_is() -> None:
    """The whole point: a study writes the keys, not a name to be parsed apart."""
    from mug.game.runtime import resolve_action

    bindings = {"ArrowUp": 3, "ArrowLeft": 1, ("ArrowUp", "ArrowLeft"): 2}

    assert resolve_action(["ArrowUp", "ArrowLeft"], bindings, 0) == 2
    assert resolve_action(["ArrowUp"], bindings, 0) == 3
    assert resolve_action(["ArrowLeft"], bindings, 0) == 1


def test_a_key_name_with_a_separator_in_it_is_not_a_chord() -> None:
    """The old shape must not keep working by accident, or both would be in use.

    A key name is a key name. Reading a chord out of one put a character with a
    meaning inside a name, and the platform's own key-name rule forbids it.
    """
    from mug.game.runtime import resolve_action

    assert resolve_action(["ArrowUp", "ArrowLeft"], {"ArrowUp+ArrowLeft": 2}, 0) == 0


def test_a_chord_reaches_the_browser_as_a_sequence() -> None:
    """A chord cannot key a JSON object, so it travels as its own thing.

    The client must be able to read it without splitting a string, because the
    client and the server have to agree exactly: a browser run is verified by
    re-executing it.
    """
    from mug.game.browser import BrowserGameSpec, client_manifest

    spec = BrowserGameSpec(
        channel_key="court",
        source_bundle="def make_env():\n    return None\n",
        requires=(),
        action_bindings={"ArrowUp": 3, "ArrowLeft": 1, ("ArrowUp", "ArrowLeft"): 2},
        default_action=0,
        seed=11,
    )

    manifest = client_manifest(
        spec,
        episode_id="episode_019b6000-0000-7000-8000-00000000000a",
        interaction_id="interaction_019b6000-0000-7000-8000-00000000000b",
        seat_key="player",
    )

    assert manifest["action_bindings"] == {"ArrowUp": 3, "ArrowLeft": 1}
    assert manifest["action_chords"] == [
        {"keys": ["ArrowUp", "ArrowLeft"], "action": 2}
    ]
    assert not any("+" in key for key in manifest["action_bindings"]), (
        "a chord leaked into the key names the client reads"
    )
