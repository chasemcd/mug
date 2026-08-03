"""Ship the peer-to-peer runtime to the browser and check what it sends back.

This is the browser half of the API-07 ``peer`` execution mode. Every peer steps
its own replica of the environment in its own browser, and the peers agree over
data channels with no authoritative server env. The server side is three things,
and this module is all three:

- it **ships the runtime**. The browser does not carry a second implementation of
  the rollback contract. It runs the platform's own modules -- the engine
  (``mug.game.mesh``), the packet codec (``mug.game.wire``), and the driver
  (``mug.game.browser_mesh_driver``) -- verbatim, under a small prelude that
  supplies the few platform names they import. So a browser peer and a server peer
  run the same code, and they cannot drift apart.
- it **projects the public manifest**. The projection is an explicit whitelist,
  so a private study field never reaches a participant by default.
- it **checks the capture**. The designated owner submits the whole trajectory,
  and ``verify_mesh_capture`` re-derives the trajectory identity from the payload
  rather than believing the claim beside it.

The trajectory is named by a chain of per-frame digests, not by a digest of the
frames themselves. Each per-frame digest comes from the shared state-hash hook,
which both sides compute in Python; the chain over those hex strings is then the
only value the browser's JavaScript digests. So the identity of a run never
depends on how a language writes a number.
"""

from __future__ import annotations

import inspect
import json
from collections.abc import Mapping
from dataclasses import dataclass, field
from types import ModuleType
from typing import Any, cast

from mug.game import browser_mesh_driver, mesh, wire
from mug.game.browser_mesh_driver import CAPTURE_SCHEMA, CAPTURE_VERSION
from mug.game.determinism import state_hash, state_hash_chain, state_hash_source
from mug.game.keys import Bindings, chords, single_keys
from mug.game.p2p_capture import VerifiedCapture
from mug.game.runtime import EpisodeSummary
from mug.game.types import (
    EpisodeBoundary,
    GameTransition,
    P2PEpisodeBarrier,
    P2PPeerEndFrame,
)
from mug.kernel import Digest, UtcInstant

# The maximum frames a submitted trajectory may carry. It bounds the work the
# verifier does before it can refuse a payload.
MAX_CAPTURE_FRAMES = 100_000

# The platform modules the browser runs verbatim, in dependency order. The codec
# imports the engine, and the driver imports both.
_RUNTIME_MODULES: tuple[tuple[str, ModuleType], ...] = (
    ("mug.game.mesh", mesh),
    ("mug.game.wire", wire),
    ("mug.game.browser_mesh_driver", browser_mesh_driver),
)

# The stand-in platform names the shipped modules import. The browser has no
# installed platform package, so the prelude registers these under the real
# module names before the shipped source runs. Only the fields the runtime reads
# are here: the browser holds records, and the server validates them.
_SHIM_SOURCE = '''
import sys as _mug_sys
import types as _mug_types


class Digest:
    """One structured digest: the browser copy of the platform value."""

    __slots__ = ("algorithm", "hex")

    def __init__(self, algorithm, hex):
        self.algorithm = algorithm
        self.hex = hex

    @classmethod
    def model_validate(cls, value):
        if isinstance(value, Digest):
            return value
        algorithm = value["algorithm"]
        digest_hex = value["hex"]
        if algorithm != "sha-256" or not isinstance(digest_hex, str):
            raise ValueError("a digest must be sha-256 hex")
        if len(digest_hex) != 64 or digest_hex.strip("0123456789abcdef"):
            raise ValueError("a digest must be sha-256 hex")
        return cls(algorithm=algorithm, hex=digest_hex)

    def model_dump(self, mode=None):
        return {"algorithm": self.algorithm, "hex": self.hex}

    def __eq__(self, other):
        return (
            isinstance(other, Digest)
            and other.algorithm == self.algorithm
            and other.hex == self.hex
        )

    def __hash__(self):
        return hash((self.algorithm, self.hex))

    def __repr__(self):
        return "Digest(" + self.algorithm + ", " + self.hex + ")"


def state_hash(value):
    """Return the structured state hash of a json-able value."""
    return Digest(algorithm="sha-256", hex=_mug_state_hash_hex(value))


class _MugRecord:
    """One held record. The browser reads its fields; the server validates it."""

    def __init__(self, **fields):
        self.__dict__.update(fields)


def _mug_module(name, **members):
    """Register one stand-in module under its platform name."""
    module = _mug_types.ModuleType(name)
    for key, value in members.items():
        setattr(module, key, value)
    _mug_sys.modules[name] = module
    parent, _, leaf = name.rpartition(".")
    if parent:
        setattr(_mug_sys.modules[parent], leaf, module)
    return module


def _mug_install_module(name, source):
    """Run one shipped platform module and register it under its own name."""
    module = _mug_types.ModuleType(name)
    _mug_sys.modules[name] = module
    exec(compile(source, name, "exec"), module.__dict__)
    parent, _, leaf = name.rpartition(".")
    if parent:
        setattr(_mug_sys.modules[parent], leaf, module)
    return module


_mug_module("mug")
_mug_module("mug.game")
_mug_module("mug.kernel", Digest=Digest, UtcInstant=str)
_mug_module("mug.game.determinism", state_hash=state_hash)
_mug_module(
    "mug.game.types",
    **{
        _name: type(_name, (_MugRecord,), {})
        for _name in (
            "EpisodeBoundary",
            "GameTransition",
            "P2PEpisodeBarrier",
            "P2PFrameFinality",
            "P2PPeerAction",
            "P2PPeerEndFrame",
            "P2PPeerHashEvidence",
        )
    },
)
'''


def mesh_prelude_source() -> str:
    """Return the Python the browser runs before the shipped platform modules.

    The prelude is the shared state-hash hook followed by the stand-in platform
    names. The hook comes from the one place that defines it, so the browser
    hashes state the exact way the server re-computes it.
    """
    return state_hash_source() + _SHIM_SOURCE


def mesh_runtime_modules() -> tuple[dict[str, str], ...]:
    """Return the platform modules the browser runs, verbatim and in order.

    The source is read from the installed module, so what ships is what this
    repository holds. There is no second copy to keep in step.
    """
    return tuple(
        {"name": name, "source": inspect.getsource(module)}
        for name, module in _RUNTIME_MODULES
    )


@dataclass(frozen=True)
class BrowserMeshSpec:
    """One browser-executed peer-to-peer game channel a study supplies.

    ``source_bundle`` is the Python the browser runs in Pyodide. It must define
    ``make_replica(peer_actor_ids, seed)``, which returns one deterministic
    replica, and it may define ``draw(replica)``, which returns the surface
    commands for the replica's current state. ``requires`` are the pinned packages
    the browser installs once. ``server_notes`` stands for private manifest data;
    it never reaches the public projection.
    """

    channel_key: str
    source_bundle: str
    action_bindings: Bindings
    requires: tuple[str, ...] = ()
    default_action: int = 0
    fps: int = 30
    max_steps: int = 200
    input_delay: int = 2
    snapshot_interval: int = 5
    redundancy: int = 10
    countdown_seconds: int = 3
    hooks: tuple[str, ...] = ("snapshot-restore", "state-hash")
    server_notes: str | None = field(default=None)

    def __post_init__(self) -> None:
        if self.max_steps < 1:
            raise ValueError("the maximum step count must be positive")
        if self.input_delay < 0:
            raise ValueError("the input delay must be nonnegative")
        if self.snapshot_interval < 1:
            raise ValueError("the snapshot interval must be at least one frame")
        if not 1 <= self.redundancy <= 32:
            raise ValueError("input redundancy must be from 1 to 32 frames")


# How long a room allows for its browsers to be ready before the first frame.
# The server releases the start barrier as soon as every peer's data channels are
# validated, and only then do the browsers download the Python runtime from a
# CDN. So the download is inside the room's deadline and the server cannot see it
# end. A participant opening their first study pays for it once.
RUNTIME_ALLOWANCE_SECONDS = 90.0

# How long it allows after the last frame: the closing barrier, one capture
# submission, and the ordinary slack of a frame loop that ran a little behind.
CAPTURE_BUFFER_SECONDS = 20.0


def capture_timeout_for(spec: BrowserMeshSpec) -> float:
    """Return how long one room of this game may take, from the start barrier.

    The deadline belongs to the game, not to a fixed number. It is how long the
    episode itself lasts, plus the countdown the participants read before it,
    plus what the room allows around both. A flat value is either too short for a
    long round -- and a round it cannot cover records nothing at all, because the
    room aborts and discards the run -- or needlessly long for a short one.

    An uncapped frame rate is counted as one frame a second. The server cannot
    know how fast a browser will step, and a deadline that is too long only
    delays reclaiming a room that is already dead.
    """
    return (
        RUNTIME_ALLOWANCE_SECONDS
        + spec.countdown_seconds
        + episode_seconds(spec)
        + CAPTURE_BUFFER_SECONDS
    )


def episode_seconds(spec: BrowserMeshSpec) -> float:
    """Return how long the episode itself lasts, with no allowance around it."""
    return spec.max_steps / spec.fps if spec.fps > 0 else float(spec.max_steps)


def browser_mesh_manifest(spec: BrowserMeshSpec) -> dict[str, Any]:
    """Project the public browser manifest for one browser-executed mesh channel.

    The projection is an explicit whitelist, so a new private field never leaks by
    default. The manifest holds nothing about a room, an actor, or a participant:
    it is the same for every browser, so the client downloads and boots it during
    the forms and the game never waits on a blank canvas.
    """
    return {
        "mode": "peer",
        "channel_key": spec.channel_key,
        "source_bundle": spec.source_bundle,
        "requires": list(spec.requires),
        "action_bindings": single_keys(spec.action_bindings),
        "action_chords": chords(spec.action_bindings),
        "default_action": spec.default_action,
        "fps": spec.fps,
        "countdown_seconds": spec.countdown_seconds,
        "hooks": list(spec.hooks),
        "max_steps": spec.max_steps,
        "input_delay": spec.input_delay,
        "snapshot_interval": spec.snapshot_interval,
        "redundancy": spec.redundancy,
        "prelude_source": mesh_prelude_source(),
        "runtime_modules": [dict(module) for module in mesh_runtime_modules()],
    }


def mesh_run_config(
    manifest: dict[str, Any],
    *,
    local_peer_handle: str,
    peer_handles: tuple[str, ...],
    room_handle: str,
    negotiation_generation: int,
    seed: int,
) -> dict[str, Any]:
    """Assemble one peer's run configuration from its manifest and its room.

    The browser holds only public handles, so the frozen peer set is the room's
    sorted handles and not a contract actor identity. The server binds a handle
    back to its own actor when it records the episode, which is the one place
    that mapping belongs. The client builds this same shape from the frames it
    already holds, so no new frame and no new schema field carries it.
    """
    frozen = tuple(sorted({*peer_handles, local_peer_handle}))
    return {
        "local_actor_id": local_peer_handle,
        "peer_actor_ids": list(frozen),
        "channel_key": manifest["channel_key"],
        "room_handle": room_handle,
        "negotiation_generation": negotiation_generation,
        "seed": seed,
        "input_delay": manifest["input_delay"],
        "snapshot_interval": manifest["snapshot_interval"],
        "default_action": manifest["default_action"],
        "max_steps": manifest["max_steps"],
        "redundancy": manifest["redundancy"],
    }


class MeshCaptureError(ValueError):
    """The submitted trajectory did not meet the capture contract."""


def _frames_of(payload: object) -> list[dict[str, Any]]:
    """Read the frame list from a submitted payload, or refuse it."""
    if not isinstance(payload, dict):
        raise MeshCaptureError("the capture payload is not an object")
    data = cast("dict[str, Any]", payload)
    if data.get("schema") != CAPTURE_SCHEMA or data.get("version") != CAPTURE_VERSION:
        raise MeshCaptureError("the capture payload names another contract")
    raw = data.get("frames")
    if not isinstance(raw, list):
        raise MeshCaptureError("the capture payload names no frames")
    frames = cast("list[Any]", raw)
    if len(frames) > MAX_CAPTURE_FRAMES:
        raise MeshCaptureError("the capture payload holds too many frames")
    for index, frame in enumerate(frames):
        if not isinstance(frame, dict):
            raise MeshCaptureError("a capture frame is not an object")
        entry = cast("dict[str, Any]", frame)
        if set(entry) != _FRAME_FIELDS:
            raise MeshCaptureError("a capture frame has missing or unknown fields")
        if entry["frame_number"] != index:
            raise MeshCaptureError("the capture frames are not a contiguous run")
    return cast("list[dict[str, Any]]", frames)


_FRAME_FIELDS = {
    "frame_number",
    "actions",
    "rewards",
    "terminated",
    "truncated",
    "info",
    "state_hash",
}


def trajectory_digest(frames: list[dict[str, Any]]) -> Digest:
    """Return the digest that names one trajectory, derived from its frames.

    The value is the chain over one digest per frame. Each per-frame digest comes
    from the shared state-hash hook, so every peer derives the identical value
    from its own canonical trajectory without exchanging the frames.
    """
    return state_hash_chain([state_hash(frame).hex for frame in frames])


@dataclass(frozen=True)
class MeshCaptureBinding:
    """Bind one reported trajectory back to the server's own identities.

    The browser reports public handles. Only the server holds the interaction,
    the episode, the actors, and the frozen membership digest the API-07 records
    need, so the binding is assembled here and never sent to a participant.
    """

    interaction_id: str
    episode_id: str
    channel_key: str
    actor_by_handle: Mapping[str, str]
    seat_by_handle: Mapping[str, str]
    reference_handle: str
    mesh_membership_digest: Digest
    membership_generation: int
    recorded_at: UtcInstant


def _actions_by_actor(
    frame: dict[str, Any], binding: MeshCaptureBinding
) -> dict[str, int]:
    """Map one frame's per-handle actions onto the server's own actor ids."""
    raw = frame["actions"]
    if not isinstance(raw, dict):
        raise MeshCaptureError("a capture frame names no action set")
    actions = cast("dict[str, Any]", raw)
    if set(actions) != set(binding.actor_by_handle):
        raise MeshCaptureError("a capture frame names another peer set")
    resolved: dict[str, int] = {}
    for handle, action in actions.items():
        if isinstance(action, bool) or not isinstance(action, int):
            raise MeshCaptureError("a capture action must be an integer")
        resolved[binding.actor_by_handle[handle]] = action
    return dict(sorted(resolved.items()))


def mesh_episode_summary(
    payload_json: str, *, binding: MeshCaptureBinding
) -> EpisodeSummary:
    """Build the API-07 records one reported mesh trajectory implies.

    The server is the writer of the record, not the browser: it reads the frames
    the peers agreed on and stamps its own interaction, episode, actors, and
    membership on them. So the ledger holds a peer-authority episode with the
    same shape a server-hosted mesh writes, and the export needs no special case.
    """
    try:
        payload: Any = json.loads(payload_json)
    except ValueError as error:
        raise MeshCaptureError("the capture payload is not valid json") from error
    frames = _frames_of(payload)
    frozen = sorted(binding.actor_by_handle.values())
    transitions = [
        GameTransition(
            interaction_id=binding.interaction_id,
            channel_key=binding.channel_key,
            episode_id=binding.episode_id,
            frame_number=frame["frame_number"],
            action_digest=state_hash(_actions_by_actor(frame, binding)),
            state_digest=Digest(algorithm="sha-256", hex=frame["state_hash"]),
            authority="peer",
            applied_decisions=[],
            replica_actor_id=binding.actor_by_handle[binding.reference_handle],
            mesh_membership_digest=binding.mesh_membership_digest,
            membership_generation=binding.membership_generation,
            recorded_at=binding.recorded_at,
        )
        for frame in frames
    ]
    boundary = _boundary_of(payload, frames, binding, frozen)
    return EpisodeSummary(
        channel_key=binding.channel_key,
        seat_key=binding.seat_by_handle[binding.reference_handle],
        frames=len(transitions),
        transitions=transitions,
        boundary=boundary,
        solved=boundary.kind == "terminal",
    )


def _boundary_of(
    payload: Any,
    frames: list[dict[str, Any]],
    binding: MeshCaptureBinding,
    frozen: list[str],
) -> EpisodeBoundary:
    """Build the closing boundary and its barrier from the reported end frames."""
    raw = cast("dict[str, Any]", payload).get("boundary")
    if not isinstance(raw, dict):
        raise MeshCaptureError("the capture payload names no boundary")
    closing = cast("dict[str, Any]", raw)
    ends = closing.get("peer_end_frames")
    if not isinstance(ends, dict) or set(cast("dict[str, Any]", ends)) != set(
        binding.actor_by_handle
    ):
        raise MeshCaptureError("the capture boundary names another peer set")
    end_frames = cast("dict[str, Any]", ends)
    if closing.get("end_frame_exclusive") != min(end_frames.values()):
        raise MeshCaptureError("the capture boundary is not the agreed minimum")
    if closing.get("end_frame_exclusive") != len(frames):
        raise MeshCaptureError("the capture boundary does not close the frames")
    last = frames[-1] if frames else None
    kind = "terminal" if last is not None and last["terminated"] else "reset"
    if closing.get("kind") != kind:
        raise MeshCaptureError("the capture boundary contradicts its last frame")
    return EpisodeBoundary(
        episode_id=binding.episode_id,
        interaction_id=binding.interaction_id,
        kind=kind,
        end_frame_exclusive=len(frames),
        authority="peer",
        state_hash=(
            Digest(algorithm="sha-256", hex=last["state_hash"])
            if last is not None
            else state_hash(None)
        ),
        p2p_barrier=P2PEpisodeBarrier(
            mesh_membership_digest=binding.mesh_membership_digest,
            membership_generation=binding.membership_generation,
            frozen_peer_actor_ids=frozen,
            rule="minimum-end-frame-exclusive",
            # The record keeps the peers in canonical actor order. A browser
            # reports handles, and a handle sorts unlike the actor behind it, so
            # the order is taken after the mapping and never before it.
            peer_end_frames=[
                P2PPeerEndFrame(peer_actor_id=actor, end_frame_exclusive=end)
                for actor, end in sorted(
                    (binding.actor_by_handle[handle], end)
                    for handle, end in end_frames.items()
                )
            ],
        ),
    )


def verify_mesh_capture(payload_json: str) -> VerifiedCapture:
    """Re-derive the trajectory identity from a submitted capture payload.

    The room reconciler calls this before it accepts the designated owner's
    payload. The identity comes from the frames themselves, never from the claim
    beside them, so an owner cannot submit one trajectory under another's name.
    """
    try:
        payload: Any = json.loads(payload_json)
    except ValueError as error:
        raise MeshCaptureError("the capture payload is not valid json") from error
    frames = _frames_of(payload)
    return VerifiedCapture(
        trajectory_digest=trajectory_digest(frames), frame_count=len(frames)
    )


__all__ = [
    "CAPTURE_BUFFER_SECONDS",
    "MAX_CAPTURE_FRAMES",
    "RUNTIME_ALLOWANCE_SECONDS",
    "BrowserMeshSpec",
    "MeshCaptureBinding",
    "MeshCaptureError",
    "browser_mesh_manifest",
    "capture_timeout_for",
    "episode_seconds",
    "mesh_episode_summary",
    "mesh_prelude_source",
    "mesh_run_config",
    "mesh_runtime_modules",
    "trajectory_digest",
    "verify_mesh_capture",
]
