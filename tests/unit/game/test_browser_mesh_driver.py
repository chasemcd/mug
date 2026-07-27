"""The browser mesh driver keeps every peer's trajectory equal over a real wire.

``tests/unit/game/test_p2p_rollback.py`` proves the rollback engine directly. This
module proves the piece the browser actually runs: the driver, over the real
packet codec, carrying real text messages between peers. So it covers the whole
path a data channel carries -- encode, drop, delay, reorder, decode, route -- and
not only the engine's own bookkeeping.

The replica is the shipped Tandem example, so these tests also protect the example
study a browser downloads. Its token moves under a generator the snapshot covers,
and both seats move every frame, so a wrong prediction changes the observation and
a rollback that failed to restore the generator would break parity at once.

The legacy suite drove these same failure modes through two real browsers:
``test_latency_injection`` (fixed, asymmetric, and jittered latency),
``test_network_disruption`` (packet loss and the deep rollback a hidden tab
forces), and ``test_data_comparison`` (both players export the same rows). Here
they are deterministic: no socket, no WebRTC, no real clock, and no browser.
"""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any, cast

import pytest

from examples.tandem.browser_mesh_env import tandem_mesh_spec
from mug.game.browser_mesh import (
    BrowserMeshSpec,
    browser_mesh_manifest,
    mesh_run_config,
    verify_mesh_capture,
)
from mug.game.browser_mesh_driver import MeshDriver, MeshDriverError, boot_mesh_driver

_ROOM = "room_019b6000000000000000000000A"


def _handle(index: int) -> str:
    """Return one room's public peer handle for a peer index."""
    return f"handle_00000000000000000000{index:02d}A"


class _Rng:
    """A small deterministic generator, so a test never uses the global one."""

    def __init__(self, seed: int) -> None:
        self._state = seed & 0x7FFFFFFF or 1

    def unit(self) -> float:
        """Return the next value in the half-open unit interval."""
        self._state = (self._state * 48271) % 2147483647
        return self._state / 2147483647


def _no_windows() -> dict[str, tuple[int, int]]:
    """Return the empty silent-window map, typed for the strict checker."""
    return {}


def _no_delays() -> dict[tuple[str, str], int]:
    """Return the empty per-direction delay map, typed for the strict checker."""
    return {}


@dataclass(frozen=True)
class Link:
    """How the simulated data channels carry packets between the peers.

    ``latency`` is the delivery delay in ticks and ``jitter`` spreads it. ``loss``
    drops a fraction of messages. ``silent`` hides one peer's outbound messages for
    a tick window and flushes them at its end, which is what a hidden browser tab
    does to its peers. ``slow`` overrides the latency for one ordered pair, so a
    test can make one direction slower than the other.
    """

    latency: int = 0
    jitter: int = 0
    loss: float = 0.0
    silent: Mapping[str, tuple[int, int]] = field(default_factory=_no_windows)
    slow: Mapping[tuple[str, str], int] = field(default_factory=_no_delays)
    lose_every_kind: bool = False


def build_drivers(
    handles: Sequence[str],
    *,
    spec: BrowserMeshSpec | None = None,
    seed: int = 7,
) -> dict[str, MeshDriver]:
    """Boot one driver per handle from the public manifest, as a browser does."""
    manifest = browser_mesh_manifest(spec or tandem_mesh_spec())
    study: dict[str, Any] = {}
    exec(manifest["source_bundle"], study)
    return {
        handle: boot_mesh_driver(
            json.dumps(
                mesh_run_config(
                    manifest,
                    local_peer_handle=handle,
                    peer_handles=tuple(handles),
                    room_handle=_ROOM,
                    negotiation_generation=1,
                    seed=seed,
                )
            ),
            study["make_replica"],
            study.get("draw"),
        )
        for handle in handles
    }


def run_browser_mesh(
    *,
    handles: Sequence[str],
    scripts: Mapping[str, Sequence[int]] | None = None,
    link: Link | None = None,
    spec: BrowserMeshSpec | None = None,
    seed: int = 7,
    ticks: int = 400,
    drivers: dict[str, MeshDriver] | None = None,
) -> dict[str, MeshDriver]:
    """Run one browser mesh to its barrier and return every peer's driver.

    Each tick every peer receives whatever the link has delivered, ticks once, and
    hands its outbound text to the link. The loop stops once every peer is ready to
    finalize, and then every peer closes the barrier.
    """
    link = link or Link()
    scripts = scripts or {}
    peers = list(handles)
    drivers = drivers or build_drivers(peers, spec=spec, seed=seed)
    rng = _Rng(seed ^ 0x5BF03635)
    queue: list[tuple[int, str, str, str]] = []

    for tick in range(ticks):
        for due, receiver, sender, text in queue:
            if due == tick:
                drivers[receiver].receive(sender, text)
        queue = [item for item in queue if item[0] > tick]

        for sender in peers:
            script = scripts.get(sender, ())
            action = script[tick] if tick < len(script) else 0
            window = link.silent.get(sender)
            hidden = window is not None and window[0] <= tick < window[1]
            for text in drivers[sender].tick(action):
                held = json.loads(text)["kind"] == "input" or link.lose_every_kind
                for receiver in peers:
                    if receiver == sender:
                        continue
                    if hidden:
                        assert window is not None
                        queue.append((window[1] + 1, receiver, sender, text))
                        continue
                    if held and link.loss > 0.0 and rng.unit() < link.loss:
                        continue
                    queue.append(
                        (
                            _due(tick, sender, receiver, link, rng),
                            receiver,
                            sender,
                            text,
                        )
                    )

        if all(driver.ready_to_finalize() for driver in drivers.values()):
            break

    for driver in drivers.values():
        driver.finalize()
    return drivers


def _due(tick: int, sender: str, receiver: str, link: Link, rng: _Rng) -> int:
    """Return the tick one message arrives on, under the link's delay model."""
    latency = link.slow.get((sender, receiver), link.latency)
    spread = 0 if link.jitter <= 0 else int(rng.unit() * (2 * link.jitter + 1))
    return max(tick + 1, tick + latency + spread - link.jitter)


def assert_parity(drivers: Mapping[str, MeshDriver]) -> list[str]:
    """Assert every peer agreed on one trajectory, and return its frame digests."""
    hashes = {handle: driver.frame_hashes() for handle, driver in drivers.items()}
    reference = min(hashes)
    for handle, values in hashes.items():
        assert values == hashes[reference], f"peer {handle} diverged from {reference}"
    payloads = {
        handle: driver.capture_payload() for handle, driver in drivers.items()
    }
    for handle, payload in payloads.items():
        assert payload == payloads[reference], f"peer {handle} reported another run"
    assert hashes[reference], "the mesh recorded no frames"
    return hashes[reference]


def _script(index: int, length: int = 200) -> list[int]:
    """Build a deterministic, varying action sequence for one peer."""
    return [(tick * 7 + index * 3) % 5 for tick in range(length)]


def _two() -> tuple[tuple[str, str], dict[str, list[int]]]:
    """Return two peer handles and a varying action script for each."""
    handles = (_handle(1), _handle(2))
    return handles, {handle: _script(i) for i, handle in enumerate(handles)}


# -- the reproduced legacy parity suite ----------------------------------------


def test_two_peers_agree_on_one_trajectory_over_a_clean_link() -> None:
    """With no delay and no loss, both browsers export the identical run."""
    handles, scripts = _two()
    drivers = run_browser_mesh(handles=handles, scripts=scripts)

    frames = assert_parity(drivers)
    assert len(frames) == tandem_mesh_spec().max_steps
    assert all(driver.rollback_count() == 0 for driver in drivers.values())


def test_the_input_delay_absorbs_a_short_round_trip() -> None:
    """A round trip inside the input delay costs no rollback."""
    handles, scripts = _two()
    drivers = run_browser_mesh(
        handles=handles, scripts=scripts, link=Link(latency=2)
    )

    assert_parity(drivers)
    assert all(driver.rollback_count() == 0 for driver in drivers.values())


@pytest.mark.parametrize("latency", [4, 8, 16])
def test_fixed_latency_forces_rollbacks_yet_parity_holds(latency: int) -> None:
    """A round trip past the input delay predicts and rolls back, and still agrees."""
    handles, scripts = _two()
    drivers = run_browser_mesh(
        handles=handles, scripts=scripts, link=Link(latency=latency)
    )

    assert_parity(drivers)
    assert all(driver.rollback_count() > 0 for driver in drivers.values())


def test_asymmetric_latency_keeps_parity() -> None:
    """One slow direction and one fast one still reach the same trajectory."""
    handles, scripts = _two()
    left, right = handles
    drivers = run_browser_mesh(
        handles=handles,
        scripts=scripts,
        link=Link(latency=2, slow={(left, right): 14}),
    )

    assert_parity(drivers)
    assert drivers[right].rollback_count() > 0


def test_jitter_reorders_packets_yet_parity_holds() -> None:
    """Packets that arrive out of order do not split the trajectory."""
    handles, scripts = _two()
    drivers = run_browser_mesh(
        handles=handles, scripts=scripts, link=Link(latency=6, jitter=5)
    )

    assert_parity(drivers)


def test_packet_loss_is_recovered_by_the_redundant_history() -> None:
    """A third of the input packets are dropped and the run still agrees."""
    handles, scripts = _two()
    drivers = run_browser_mesh(
        handles=handles, scripts=scripts, link=Link(latency=3, loss=0.34)
    )

    assert_parity(drivers)


def test_loss_on_every_packet_kind_keeps_parity() -> None:
    """Dropping hashes and end packets too still leaves one agreed trajectory.

    The end announcement repeats every tick once a peer has ended, so the barrier
    still closes; the input history carries its own redundancy. A dropped hash is
    never re-sent, so some frames stay confirmed rather than verified -- which is
    the honest outcome, not a failure.
    """
    handles, scripts = _two()
    drivers = run_browser_mesh(
        handles=handles,
        scripts=scripts,
        link=Link(latency=2, loss=0.25, lose_every_kind=True),
    )

    assert_parity(drivers)
    assert all(driver.disputed_frames() == [] for driver in drivers.values())


def test_a_hidden_tab_forces_a_deep_rollback_and_still_agrees() -> None:
    """A peer that goes silent and floods its backlog forces a deep replay."""
    handles, scripts = _two()
    left = handles[0]
    drivers = run_browser_mesh(
        handles=handles,
        scripts=scripts,
        link=Link(latency=1, silent={left: (10, 45)}),
    )

    assert_parity(drivers)
    # One rollback, but a deep one: the whole silent window replays at once.
    assert drivers[handles[1]].rollback_count() > 0
    assert drivers[handles[1]].max_rollback_depth() > 20


def test_three_peers_agree_under_latency() -> None:
    """A three-peer full mesh reaches one trajectory as a two-peer mesh does."""
    handles = (_handle(1), _handle(2), _handle(3))
    scripts = {handle: _script(index) for index, handle in enumerate(handles)}
    drivers = run_browser_mesh(
        handles=handles, scripts=scripts, link=Link(latency=5)
    )

    assert_parity(drivers)


def test_peers_that_end_apart_close_on_the_minimum_end_frame() -> None:
    """The barrier is the exclusive minimum, so both peers export one range."""
    handles, scripts = _two()
    spec = BrowserMeshSpec(
        channel_key="tandem",
        source_bundle=tandem_mesh_spec().source_bundle,
        action_bindings={},
        max_steps=30,
        input_delay=1,
    )
    drivers = run_browser_mesh(handles=handles, scripts=scripts, spec=spec)

    frames = assert_parity(drivers)
    assert len(frames) == 30
    for driver in drivers.values():
        boundary = driver.boundary()
        assert boundary["end_frame_exclusive"] == 30
        assert boundary["kind"] == "reset"
        assert set(boundary["peer_end_frames"]) == set(handles)


def test_a_terminal_environment_closes_the_barrier_as_terminal() -> None:
    """A replica that reports termination gives the boundary its terminal kind."""
    handles, scripts = _two()
    spec = BrowserMeshSpec(
        channel_key="stop",
        source_bundle=_TERMINAL_BUNDLE,
        action_bindings={},
        max_steps=50,
        input_delay=1,
    )
    drivers = run_browser_mesh(handles=handles, scripts=scripts, spec=spec)

    assert_parity(drivers)
    for driver in drivers.values():
        assert driver.boundary()["kind"] == "terminal"


# -- what the server later checks ----------------------------------------------


def test_the_reported_trajectory_verifies_against_the_server_verifier() -> None:
    """Each peer derives the digest the server re-derives from the payload."""
    handles, scripts = _two()
    drivers = run_browser_mesh(
        handles=handles, scripts=scripts, link=Link(latency=7)
    )

    digests: set[str] = set()
    for driver in drivers.values():
        verified = verify_mesh_capture(driver.capture_payload_json())
        assert verified.frame_count == driver.frame_count()
        digests.add(verified.trajectory_digest.hex)
    assert len(digests) == 1


def test_the_capture_payload_names_no_server_identity() -> None:
    """The browser reports handles only: no actor, visit, or interaction."""
    handles, scripts = _two()
    drivers = run_browser_mesh(handles=handles, scripts=scripts)

    payload = json.dumps(drivers[handles[0]].capture_payload())
    for term in ("actor_", "visit_", "interaction_", "enrollment_", "episode_"):
        assert term not in payload


# -- refusals ------------------------------------------------------------------


def test_a_peer_cannot_speak_for_another_over_its_own_channel() -> None:
    """A packet whose sender is not the channel's own peer is refused."""
    handles = (_handle(1), _handle(2), _handle(3))
    drivers = build_drivers(handles)
    forged = drivers[handles[2]].tick(1)[0]

    drivers[handles[0]].receive(handles[1], forged)
    with pytest.raises(MeshDriverError, match="does not match its data channel"):
        drivers[handles[0]].tick(0)


def test_a_message_that_is_not_json_is_refused() -> None:
    """The driver refuses malformed text rather than holding a broken packet."""
    handles, _ = _two()
    drivers = build_drivers(handles)

    with pytest.raises(MeshDriverError, match="not valid json"):
        drivers[handles[0]].receive(handles[1], "{")


def test_a_message_that_is_not_an_object_is_refused() -> None:
    """A bare array or number is not a packet."""
    handles, _ = _two()
    drivers = build_drivers(handles)

    with pytest.raises(MeshDriverError, match="not an object"):
        drivers[handles[0]].receive(handles[1], "[1,2]")


def test_an_unknown_packet_kind_is_refused() -> None:
    """The shipped codec refuses a wire message it does not define."""
    handles, _ = _two()
    drivers = build_drivers(handles)
    drivers[handles[0]].receive(handles[1], '{"kind":"invent","sender":"x"}')

    with pytest.raises(ValueError, match="unknown wire message kind"):
        drivers[handles[0]].tick(0)


def test_a_replica_that_returns_the_wrong_shape_is_refused() -> None:
    """A study step that returns two values names no frame."""
    handles, _ = _two()
    spec = BrowserMeshSpec(
        channel_key="bad", source_bundle=_SHORT_BUNDLE, action_bindings={}
    )
    drivers = build_drivers(handles, spec=spec)

    with pytest.raises(MeshDriverError, match="four or five values"):
        drivers[handles[0]].tick(0)


def test_the_boundary_is_refused_before_the_barrier_closes() -> None:
    """A peer cannot report a boundary the mesh has not agreed on."""
    handles, _ = _two()
    drivers = build_drivers(handles)

    with pytest.raises(MeshDriverError, match="before reading it"):
        drivers[handles[0]].boundary()


# -- divergence ----------------------------------------------------------------


def test_an_uncovered_generator_shows_up_as_a_disputed_frame() -> None:
    """A snapshot that misses a generator diverges the peers, and they say so.

    This is the property the whole mesh rests on: a replica that draws from state
    its snapshot does not cover cannot stay in step through a rollback. The peers
    do not paper over it -- the state hashes disagree and the frames report it.
    """
    handles, scripts = _two()
    spec = BrowserMeshSpec(
        channel_key="leaky",
        source_bundle=_LEAKY_BUNDLE,
        action_bindings={},
        max_steps=40,
        input_delay=0,
    )
    drivers = run_browser_mesh(
        handles=handles, scripts=scripts, spec=spec, link=Link(latency=6)
    )

    assert any(driver.disputed_frames() for driver in drivers.values())
    left, right = (drivers[handle].frame_hashes() for handle in handles)
    assert left != right


def test_the_drawing_seam_reaches_the_study_bundle() -> None:
    """The client asks the driver to draw, and the study's own commands come back."""
    handles, _ = _two()
    drivers = build_drivers(handles)
    drivers[handles[0]].tick(1)

    commands = cast("list[dict[str, Any]]", drivers[handles[0]].commands())
    assert isinstance(commands, list)
    assert {command["id"] for command in commands} >= {"board", "token"}


# The study bundles the refusal and divergence tests need.
_SHORT_BUNDLE = """
class Replica:
    def step(self, actions):
        return (1, 2)
    def snapshot(self):
        return None
    def restore(self, snapshot):
        pass

def make_replica(peers, seed):
    return Replica()
"""

_TERMINAL_BUNDLE = """
class Replica:
    def __init__(self, peers, seed):
        self.peers = tuple(sorted(peers))
        self.frame = 0
    def step(self, actions):
        self.frame += 1
        return (
            {"frame": self.frame, "actions": dict(actions)},
            {peer: 0.0 for peer in self.peers},
            self.frame >= 12,
            False,
            None,
        )
    def snapshot(self):
        return self.frame
    def restore(self, snapshot):
        self.frame = snapshot

def make_replica(peers, seed):
    return Replica(peers, seed)
"""

# The generator lives outside the snapshot, so a rollback replay cannot restore it.
_LEAKY_BUNDLE = """
class Replica:
    def __init__(self, peers, seed):
        self.peers = tuple(sorted(peers))
        self.frame = 0
        self.hidden = seed or 1
    def step(self, actions):
        self.frame += 1
        self.hidden = (self.hidden * 48271) % 2147483647
        return (
            {"frame": self.frame, "noise": self.hidden % 7,
             "actions": dict(actions)},
            {peer: 0.0 for peer in self.peers},
            False,
            False,
            None,
        )
    def snapshot(self):
        return self.frame
    def restore(self, snapshot):
        self.frame = snapshot

def make_replica(peers, seed):
    return Replica(peers, seed)
"""
