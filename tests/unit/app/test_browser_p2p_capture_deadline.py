"""How long a peer-to-peer room waits belongs to the game it plays.

A room aborts when its capture deadline passes, and an aborted room discards the
run. So a deadline the game cannot finish inside does not merely cut a round
short: it means that study can never record anything at all. A fixed number is
either too short for a long round or needlessly long for a short one, and an
author should not have to know it exists or keep it in step with ``max_steps``.

So the mount derives it from its own game specification, and refuses a number an
author names that the game could never finish inside.
"""

from __future__ import annotations

from dataclasses import replace

import pytest

from mug.game.browser_mesh import (
    CAPTURE_BUFFER_SECONDS,
    RUNTIME_ALLOWANCE_SECONDS,
    BrowserMeshSpec,
    capture_timeout_for,
    episode_seconds,
)
from mug.game.p2p_capture import VerifiedCapture
from mug.game.p2p_room_types import DEFAULT_CAPTURE_TIMEOUT_SECONDS, RoomLimits
from mug.kernel import Digest
from mug.participant_p2p_types import BrowserP2PConfig

_A_DIGEST = Digest(algorithm="sha-256", hex="c" * 64)

_BUNDLE = """
def make_replica(peer_actor_ids, seed):
    raise NotImplementedError
"""


def _spec(**overrides: object) -> BrowserMeshSpec:
    spec = BrowserMeshSpec(
        channel_key="game",
        source_bundle=_BUNDLE,
        action_bindings={"ArrowUp": 1},
        fps=30,
        max_steps=600,
        countdown_seconds=3,
    )
    return replace(spec, **overrides)  # type: ignore[arg-type]


def _mount(**overrides: object) -> BrowserP2PConfig:
    base: dict[str, object] = {"channel_key": "game", "size": 2, "game": _spec()}
    base.update(overrides)
    return BrowserP2PConfig(**base)  # type: ignore[arg-type]


def _verifier(payload_json: str) -> VerifiedCapture:
    return VerifiedCapture(trajectory_digest=_A_DIGEST, frame_count=0)


# -- the derivation ---------------------------------------------------------------


def test_the_deadline_covers_the_episode_the_game_actually_plays() -> None:
    """Twenty seconds of play is inside it, with the allowances around it."""
    spec = _spec(fps=30, max_steps=600, countdown_seconds=3)

    assert episode_seconds(spec) == 20.0
    assert capture_timeout_for(spec) == (
        RUNTIME_ALLOWANCE_SECONDS + 3 + 20.0 + CAPTURE_BUFFER_SECONDS
    )


def test_a_longer_round_is_given_longer() -> None:
    """The deadline follows the game, which is the whole point of deriving it.

    A ten-minute round under the old fixed minute could not record a single run:
    the room reached its deadline while the participants were still playing, and
    everything they had done was discarded.
    """
    short = _spec(fps=30, max_steps=600)
    long = _spec(fps=30, max_steps=18_000)

    assert episode_seconds(long) == 600.0
    assert capture_timeout_for(long) - capture_timeout_for(short) == 580.0
    assert capture_timeout_for(long) > episode_seconds(long)
    assert capture_timeout_for(short) < capture_timeout_for(long)


def test_every_shipped_game_length_gets_a_deadline_that_covers_it() -> None:
    """Whatever the frame rate and the length, the room outlasts the round."""
    for fps in (5, 10, 15, 30, 60):
        for max_steps in (20, 200, 3_000, 36_000):
            spec = _spec(fps=fps, max_steps=max_steps)
            assert capture_timeout_for(spec) > episode_seconds(spec), (
                f"a {max_steps}-step game at {fps} fps is given less time than it "
                "takes to play"
            )


def test_an_uncapped_frame_rate_is_counted_generously() -> None:
    """The server cannot know how fast a browser steps, so it allows a second.

    A deadline that is too long only delays reclaiming a room that is already
    dead. One that is too short throws away a run somebody played.
    """
    spec = _spec(fps=0, max_steps=200)

    assert episode_seconds(spec) == 200.0
    assert capture_timeout_for(spec) > 200.0


# -- what the mount hands the room -------------------------------------------------


def test_a_mount_that_names_a_game_derives_its_own_deadline() -> None:
    """The author writes no deadline and the room still gets the right one."""
    mount = _mount()

    assert mount.limits.capture_timeout_seconds is None
    assert mount.room_limits.capture_timeout_seconds == capture_timeout_for(_spec())


def test_deriving_the_deadline_changes_no_other_limit() -> None:
    """Only the one limit that depends on the game is filled in."""
    limits = RoomLimits(validation_timeout_seconds=9.0, max_signals_per_peer=64)
    mount = _mount(limits=limits)

    resolved = mount.room_limits
    assert resolved.validation_timeout_seconds == 9.0
    assert resolved.max_signals_per_peer == 64
    assert resolved.capture_timeout_seconds == capture_timeout_for(_spec())


def test_an_author_who_names_a_deadline_keeps_it() -> None:
    """A study that knows better than the platform is not overruled."""
    mount = _mount(limits=RoomLimits(capture_timeout_seconds=45.0))

    assert mount.room_limits.capture_timeout_seconds == 45.0


def test_a_mount_with_no_game_falls_back_rather_than_guessing() -> None:
    """A study that verifies its own payload names no episode length to read."""
    mount = BrowserP2PConfig(channel_key="game", size=2, verify_capture=_verifier)

    assert mount.room_limits.capture_timeout_seconds is None
    assert mount.room_limits.capture_deadline() == DEFAULT_CAPTURE_TIMEOUT_SECONDS


# -- the refusal --------------------------------------------------------------------


def test_a_deadline_the_game_cannot_finish_inside_is_refused() -> None:
    """Twenty seconds of play with a fifteen-second deadline records nothing."""
    with pytest.raises(ValueError, match="shorter than the episode"):
        _mount(limits=RoomLimits(capture_timeout_seconds=15.0))


def test_a_deadline_that_is_not_positive_is_still_refused() -> None:
    """The older rule survives the new one."""
    with pytest.raises(ValueError, match="must be positive"):
        _mount(limits=RoomLimits(capture_timeout_seconds=0.0))
