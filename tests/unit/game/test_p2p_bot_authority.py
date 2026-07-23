"""Bot authority single-sources a bot seat, and desync repair reconverges a peer.

These tests drive a small in-process mesh over the real ``PeerEngine`` with a
deterministic replica, no socket, and no clock. They prove the two P2P follow-ons:

- **Bot authority.** A bot seat has no human and no engine. Exactly one peer -- the
  one the ``P2PBotAuthority`` record designates -- produces the bot's action each
  frame and broadcasts it; every other peer applies the broadcast action. The test
  asserts only the authority peer ever ran the bot controller, yet both peers
  stepped the identical bot input and exported byte-identical trajectories.
- **Desync repair.** A peer built with the wrong seed diverges: the mesh records the
  frames ``disputed``. ``resync_peer`` transfers the authority's snapshot to the
  diverged peer, which re-derives the frames forward with the agreed inputs and
  reconverges, so its trajectory matches the authority's and the dispute clears.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any, cast

import pytest

from mug.game.bot_authority import BotSeat
from mug.game.desync_repair import resync_peer
from mug.game.mesh import PeerEngine, ReplicaFrame
from mug.kernel import Digest

_INTERACTION = "interaction_019b6000-0000-7000-8000-00000000010f"
_EPISODE = "episode_019b6000-0000-7000-8000-00000000010e"
_RECORDED_AT = "2026-07-21T00:00:00.000000Z"
_MESH_DIGEST = Digest(algorithm="sha-256", hex="a" * 64)

_Snapshot = tuple[tuple[tuple[str, int], ...], int, int]


def _actor(index: int) -> str:
    """Return the canonical actor id for one peer index."""
    return f"actor_019b6000-0000-7000-8000-0000000001{index:02x}"


class LineWorld:
    """A deterministic multi-seat replica whose state depends on a generator."""

    def __init__(self, actors: tuple[str, ...], *, seed: int, episode_len: int) -> None:
        self._actors = tuple(sorted(actors))
        self._episode_len = episode_len
        self._t = 0
        self._rng = seed & 0x7FFFFFFF
        self._pos: dict[str, int] = dict.fromkeys(self._actors, 0)

    def _noise(self) -> int:
        self._rng = (self._rng * 1103515245 + 12345) & 0x7FFFFFFF
        return self._rng % 3 - 1

    def step(self, actions: Mapping[str, int]) -> ReplicaFrame:
        self._t += 1
        noise = self._noise()
        for actor in self._actors:
            self._pos[actor] += (int(actions.get(actor, 1)) - 1) + noise
        observation = [self._pos[actor] for actor in self._actors]
        observation.extend((self._t, self._rng))
        return ReplicaFrame(
            observation=observation,
            rewards=dict.fromkeys(self._actors, -1.0),
            terminated=self._t >= self._episode_len,
            truncated=False,
            info={},
        )

    def snapshot(self) -> object:
        return (tuple(sorted(self._pos.items())), self._t, self._rng)

    def restore(self, state: object) -> None:
        positions, step, rng = cast("_Snapshot", state)
        self._pos = dict(positions)
        self._t = step
        self._rng = rng


def _engine(
    actor: str, actors: tuple[str, ...], *, seed: int, episode_len: int
) -> PeerEngine:
    """Build one peer engine over a line-world replica seeded as given."""
    replica = LineWorld(actors, seed=seed, episode_len=episode_len)
    return PeerEngine(
        actor_id=actor,
        peer_actor_ids=actors,
        interaction_id=_INTERACTION,
        episode_id=_EPISODE,
        channel_key="p2p-game",
        mesh_membership_digest=_MESH_DIGEST,
        membership_generation=1,
        step=replica.step,
        snapshot=replica.snapshot,
        restore=replica.restore,
        recorded_at=_RECORDED_AT,
        input_delay=1,
        snapshot_interval=5,
        default_action=1,
        max_steps=episode_len + 40,
    )


def _rows(engine: PeerEngine) -> list[object]:
    """Return one engine's parity-comparable canonical rows."""
    return [record.canonical() for record in engine.canonical_trajectory()]


def _settle(engines: Mapping[str, PeerEngine], *, rounds: int = 4) -> None:
    """Advance every engine a few extra passes so the tail frames promote.

    The final play tick leaves the last frame confirmed but not yet promoted, the
    same lag the synchronous coordinator drains in ``_settle``; these extra passes
    promote it, so the exported trajectory holds every frame.
    """
    for _ in range(rounds):
        for engine in engines.values():
            engine.advance()


# -- bot authority -------------------------------------------------------------


class CountingController:
    """A scripted controller that counts how often it decides, to prove authority."""

    def __init__(self) -> None:
        self.calls = 0

    def decide(self, observation: Any) -> int:
        self.calls += 1
        return self.calls % 3


def test_only_the_authority_peer_runs_the_bot_and_the_mesh_agrees() -> None:
    """One peer sources the bot; both peers step the identical bot input.

    Two human peers and one bot seat form the frozen mesh. The bot's authority is
    the highest eligible human peer; only it runs the controller, and it broadcasts
    the bot's action. The other human peer applies the broadcast action, so the two
    real engines export byte-identical trajectories.
    """
    human_a, human_b, bot = _actor(1), _actor(2), _actor(3)
    peers = (human_a, human_b, bot)
    length = 24
    engines = {
        human_a: _engine(human_a, peers, seed=7, episode_len=length),
        human_b: _engine(human_b, peers, seed=7, episode_len=length),
    }
    controller = CountingController()
    # The record designates the highest eligible human peer as the authority.
    bot_seat = BotSeat(
        bot_actor_id=bot, authority_actor_id=human_b, controller=controller
    )

    humans = (human_a, human_b)
    for tick in range(length):
        for index, actor in enumerate(humans):
            packet = engines[actor].submit_local((tick + index) % 3)
            for other in humans:
                if other != actor:
                    engines[other].receive_input(packet)
        # The bot's action is sourced only by its authority peer.
        for actor in humans:
            if bot_seat.holds_authority(actor):
                bot_packet = engines[actor].submit_for(bot, bot_seat.decide(None))
                for other in humans:
                    if other != actor:
                        engines[other].receive_input(bot_packet)
        for engine in engines.values():
            engine.advance()
    _settle(engines)

    # Only the authority peer ran the controller: one call per frame, not two.
    assert controller.calls == length
    assert _rows(engines[human_a]) == _rows(engines[human_b])
    assert len(_rows(engines[human_a])) == length


def test_submit_for_refuses_the_nodes_own_seat_and_a_stranger() -> None:
    """A node may source a bot only for another seat in the frozen peer set."""
    a, b = _actor(1), _actor(2)
    engine = _engine(a, (a, b), seed=1, episode_len=5)
    with pytest.raises(ValueError, match="use submit_local"):
        engine.submit_for(a, 0)
    with pytest.raises(ValueError, match="frozen peer set"):
        engine.submit_for(_actor(9), 0)


# -- desync repair -------------------------------------------------------------


def _drive_frame(engines: Mapping[str, PeerEngine], tick: int) -> None:
    """Submit each peer's action on its own engine, relay, and advance all."""
    actors = tuple(engines)
    for index, actor in enumerate(actors):
        packet = engines[actor].submit_local((tick + index) % 3)
        for other in actors:
            if other != actor:
                engines[other].receive_input(packet)
    for engine in engines.values():
        engine.advance()


def _exchange_hashes(engines: Mapping[str, PeerEngine]) -> None:
    """Relay every peer's confirmed-frame hashes across the whole mesh."""
    actors = tuple(engines)
    for actor in actors:
        for packet in engines[actor].outbound_hashes():
            for other in actors:
                if other != actor:
                    engines[other].receive_hash(packet)


def test_a_diverged_peer_is_repaired_from_an_authority_snapshot() -> None:
    """A wrong-seed peer diverges, is resynced, and reconverges with the mesh."""
    a, b = _actor(1), _actor(2)
    peers = (a, b)
    length = 30
    engines = {
        a: _engine(a, peers, seed=2024, episode_len=length),
        b: _engine(b, peers, seed=9999, episode_len=length),  # the wrong seed
    }

    for tick in range(length):
        _drive_frame(engines, tick)
    _settle(engines)
    _exchange_hashes(engines)

    # The wrong seed splits the trajectory: the mesh records the frames disputed.
    assert engines[a].disputed_frames()
    assert engines[b].disputed_frames()
    assert _rows(engines[a]) != _rows(engines[b])
    first_dispute = engines[b].disputed_frames()[0]

    # Repair: transfer the authority's snapshot and re-derive the diverged peer.
    resync_peer(diverged=engines[b], authority=engines[a], target_frame=first_dispute)
    assert engines[b].repair_count() == 1
    guard = 0
    while len(engines[b].canonical_trajectory()) < length and guard < length + 10:
        engines[b].advance()
        guard += 1

    # After the transfer the diverged peer holds the authority's trajectory.
    assert _rows(engines[b]) == _rows(engines[a])
    _exchange_hashes(engines)
    assert engines[b].disputed_frames() == []
    assert engines[a].disputed_frames() == []
