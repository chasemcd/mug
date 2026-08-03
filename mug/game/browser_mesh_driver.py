"""The browser-side driver for one peer of a full-mesh game (API-07).

The rollback engine (``mug.game.mesh``) owns the GGPO contract, and the packet
codec (``mug.game.wire``) owns the wire shape. This module is the third piece the
browser needs: one synchronous object that binds an engine, a replica, and a set
of data channels into a per-frame call the browser makes.

The browser owns the clock, not this module. JavaScript reads the held key, calls
``receive`` for each message a data channel delivered, and calls ``tick`` once per
frame; ``tick`` returns the text to send to every peer. So the driver holds no
loop, no timer, and no socket, and a test drives a whole mesh in one process with
no browser at all.

This module ships to the browser **verbatim**, beside the engine and the codec
(see ``mug.game.browser_mesh``). It therefore imports only the standard library
and those two modules, which the browser prelude satisfies. There is exactly one
implementation of the rollback contract, so a browser peer and a server peer can
never drift apart.

The study supplies the replica. Its ``step`` takes the frozen action set and
returns ``(observation, rewards, terminated, truncated, info)``; its ``snapshot``
and ``restore`` must cover the environment and every random-number generator, or
the mesh reports a disputed frame rather than a silently split record.
"""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any, cast

from mug.game.determinism import state_hash
from mug.game.mesh import HashPacket, InputPacket, PeerEngine, ReplicaFrame
from mug.game.wire import decode, encode_end, encode_hash, encode_input
from mug.kernel import Digest

CAPTURE_SCHEMA = "mug.browser-mesh.capture"
CAPTURE_VERSION = 1

# The engine binds a mesh digest and a record timestamp onto the records it can
# build. A browser never asks it for one, and it holds neither value, so these
# stand in for them. The server stamps the real values on the records it builds
# from the reported trajectory.
_ROOM_DIGEST = Digest(algorithm="sha-256", hex="0" * 64)
_UNSET_INSTANT = "1970-01-01T00:00:00.000000Z"


@dataclass(frozen=True)
class MeshRunConfig:
    """Everything one browser peer needs to run its own engine for one episode.

    Every field is a plain value the server assigned, so the browser invents no
    identity. ``peer_actor_ids`` is the frozen peer set in canonical sorted order,
    and ``local_actor_id`` is this browser's member of it. Both are the room's
    public handles: a browser holds no contract actor identity, and the server
    binds a handle back to its own actor when it records the episode.
    """

    local_actor_id: str
    peer_actor_ids: tuple[str, ...]
    channel_key: str
    room_handle: str
    negotiation_generation: int
    seed: int
    input_delay: int = 2
    snapshot_interval: int = 5
    default_action: int = 0
    max_steps: int = 200
    redundancy: int = 10


class MeshDriverError(RuntimeError):
    """A driver refusal the browser reports as a failed room attempt."""


def _frame_of(result: object) -> ReplicaFrame:
    """Adapt one study step result to the engine's frame contract.

    The study returns a plain tuple, so its bundle names no platform type. An
    object that already carries the four fields passes through, which is what an
    in-process replica supplies.
    """
    if isinstance(result, (tuple, list)):
        parts = cast("Sequence[Any]", result)
        if not 4 <= len(parts) <= 5:
            raise MeshDriverError("a replica step must return four or five values")
        rewards = cast("Mapping[str, float]", parts[1])
        return ReplicaFrame(
            observation=parts[0],
            rewards=dict(rewards),
            terminated=bool(parts[2]),
            truncated=bool(parts[3]),
            info=parts[4] if len(parts) == 5 else None,
        )
    if isinstance(result, ReplicaFrame):
        return result
    raise MeshDriverError("a replica step must return a tuple of values")


class MeshDriver:
    """Drive one peer's engine over a browser's data channels, one frame a call.

    The call order matches the wire tier's (``mug.game.wire.PeerNode``): the
    messages that arrived since the last frame are drained first, then the local
    input is submitted and packed, the engine advances one frame, and the newly
    confirmed hashes and the end announcement are packed. The caller sends every
    returned text to every peer.
    """

    def __init__(
        self,
        config: MeshRunConfig,
        replica: Any,
        draw: Any = None,
    ) -> None:
        self._config = config
        self._replica = replica
        self._draw = draw
        self._pending: list[tuple[str, dict[str, Any]]] = []
        # The engine names its room, not the server's interaction or episode. Those
        # identities only reach the records the server builds from the reported
        # trajectory, and the browser builds no record.
        self._engine = PeerEngine(
            actor_id=config.local_actor_id,
            peer_actor_ids=config.peer_actor_ids,
            interaction_id=config.room_handle,
            episode_id=config.room_handle,
            channel_key=config.channel_key,
            mesh_membership_digest=_ROOM_DIGEST,
            membership_generation=config.negotiation_generation,
            step=self._step,
            snapshot=replica.snapshot,
            restore=replica.restore,
            recorded_at=_UNSET_INSTANT,
            input_delay=config.input_delay,
            snapshot_interval=config.snapshot_interval,
            default_action=config.default_action,
            redundancy=config.redundancy,
            max_steps=config.max_steps,
        )

    # -- the per-frame call ----------------------------------------------------

    def receive(self, remote_actor_id: str, text: str) -> None:
        """Hold one message a data channel delivered, for the next frame to drain.

        The caller names the channel the message arrived on. The drain checks the
        packet's own sender against that name, so a peer cannot speak for another
        peer over its own channel.
        """
        try:
            loaded: Any = json.loads(text)
        except ValueError as error:
            raise MeshDriverError("a peer message is not valid json") from error
        if not isinstance(loaded, dict):
            raise MeshDriverError("a peer message is not an object")
        self._pending.append((remote_actor_id, cast("dict[str, Any]", loaded)))

    def tick(self, action: int) -> list[str]:
        """Run one frame and return the text to send to every peer."""
        self._drain()
        outbound: list[Mapping[str, Any]] = []
        if not self._engine.ended():
            outbound.append(encode_input(self._engine.submit_local(int(action))))
        else:
            # The episode's length is fixed, so nothing new is scheduled -- but this
            # peer keeps repeating what it played until the barrier closes. The tail
            # of an episode is otherwise its least protected part: mid-episode a lost
            # input is repeated by the packets that follow it, and nothing follows
            # the last one.
            repeat = self._engine.resend_recent()
            if repeat is not None:
                outbound.append(encode_input(repeat))
        self._engine.advance()
        for hash_packet in self._engine.outbound_hashes():
            outbound.append(encode_hash(hash_packet))
        end_packet = self._engine.announce_end()
        if end_packet is not None:
            outbound.append(encode_end(end_packet))
        return [json.dumps(message, separators=(",", ":")) for message in outbound]

    def _drain(self) -> None:
        """Route every held message into the engine, with no step between them."""
        pending = self._pending
        self._pending = []
        for remote, message in pending:
            packet = decode(message)
            if packet.sender != remote:
                raise MeshDriverError(
                    "a peer packet sender does not match its data channel"
                )
            if isinstance(packet, InputPacket):
                self._engine.receive_input(packet)
            elif isinstance(packet, HashPacket):
                self._engine.receive_hash(packet)
            else:
                self._engine.receive_end(packet)

    def _step(self, actions: Mapping[str, int]) -> ReplicaFrame:
        """Step the study replica once for the whole frozen action set."""
        return _frame_of(self._replica.step(dict(actions)))

    # -- the episode barrier ---------------------------------------------------

    def ended(self) -> bool:
        """Return whether this peer's own episode has ended."""
        return self._engine.ended()

    def ready_to_finalize(self) -> bool:
        """Say whether the barrier is agreed and every frame in it is confirmed."""
        return self._engine.ended() and self._engine.ready_to_finalize()

    def finalize(self) -> None:
        """Close the episode on the agreed minimum end frame."""
        self._engine.finalize()

    # -- outputs ---------------------------------------------------------------

    def frame_count(self) -> int:
        """Return how many canonical frames the trajectory holds."""
        return len(self._engine.canonical_trajectory())

    def frame_hashes(self) -> list[str]:
        """Return one digest per canonical frame, in order.

        Each value binds the whole canonical frame -- its actions, its rewards, its
        flags, and its state hash -- through the shared hook both sides compute the
        same way. The caller digests this list of strings to name the trajectory,
        so the identity of a run never depends on how a language writes a number.
        """
        return [
            state_hash(record.canonical()).hex
            for record in self._engine.canonical_trajectory()
        ]

    def capture_payload(self) -> dict[str, Any]:
        """Return the whole trajectory the designated owner submits for capture.

        The payload names peers by their public room handles, never by a contract
        actor identity: the browser holds no such identity, and the server binds
        the handles back to its own actors when it records the episode. So the
        payload carries what the browser can honestly claim, and no more.
        """
        return {
            "schema": CAPTURE_SCHEMA,
            "version": CAPTURE_VERSION,
            "channel_key": self._config.channel_key,
            "room_handle": self._config.room_handle,
            "negotiation_generation": self._config.negotiation_generation,
            "frozen_peer_handles": list(self._config.peer_actor_ids),
            "frames": [
                record.canonical() for record in self._engine.canonical_trajectory()
            ],
            "boundary": self.boundary(),
        }

    def boundary(self) -> dict[str, Any]:
        """Return the closing boundary the agreed minimum end frame implies."""
        end = self._engine.final_end_frame()
        if end is None:
            raise MeshDriverError("close the episode barrier before reading it")
        trajectory = self._engine.canonical_trajectory()
        last = trajectory[-1] if trajectory else None
        return {
            "kind": "terminal" if last is not None and last.terminated else "reset",
            "end_frame_exclusive": end,
            "state_hash": last.state_hash.hex if last is not None else None,
            "peer_end_frames": dict(sorted(self._engine.peer_end_frames().items())),
        }

    def capture_payload_json(self) -> str:
        """Return the capture payload as the exact text the owner submits."""
        return json.dumps(self.capture_payload(), separators=(",", ":"), sort_keys=True)

    def commands(self) -> Any:
        """Return the study's drawing commands for the replica's current state."""
        return None if self._draw is None else self._draw(self._replica)

    def rollback_count(self) -> int:
        """Return how many rollbacks this peer ran, for the client status line."""
        return self._engine.rollback_count()

    def max_rollback_depth(self) -> int:
        """Return the deepest replay this peer ran, in frames."""
        return self._engine.max_rollback_depth()

    def disputed_frames(self) -> list[int]:
        """Return the canonical frames whose peer state hashes disagree."""
        return self._engine.disputed_frames()


def boot_mesh_driver(
    config_json: str, make_replica: Any, draw: Any = None
) -> MeshDriver:
    """Build one driver from the manifest values the browser holds as text.

    The browser passes plain text over the Python boundary, so no live proxy
    crosses it. The study's ``make_replica`` takes the frozen peer set and the
    shared seed, so every peer starts from the identical state.
    """
    loaded: Any = json.loads(config_json)
    if not isinstance(loaded, dict):
        raise MeshDriverError("the mesh run configuration is not an object")
    values: dict[str, Any] = dict(cast("dict[str, Any]", loaded))
    values["peer_actor_ids"] = tuple(cast("Sequence[str]", values["peer_actor_ids"]))
    config = MeshRunConfig(**values)
    replica = make_replica(config.peer_actor_ids, config.seed)
    return MeshDriver(config, replica, draw)


__all__ = [
    "CAPTURE_SCHEMA",
    "CAPTURE_VERSION",
    "MeshDriver",
    "MeshDriverError",
    "MeshRunConfig",
    "boot_mesh_driver",
]
