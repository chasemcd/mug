"""Repair a desynchronized peer by transferring an authority snapshot (API-07).

The rollback engine records a frame ``disputed`` when the peers' state hashes for it
disagree, but it does not repair it. A disagreement over agreed inputs means one
peer's replica has drawn from state its snapshot does not cover, so its trajectory
has split from the mesh. This module is the repair: it transfers a snapshot from a
peer whose trajectory is trusted (the mesh authority) to the diverged peer, which
restores it and re-derives the frames forward, so the two replicas reconverge.

The repair is a pure state transfer over the engine's own snapshot seam. The
authority serves the nearest snapshot it holds at or before the divergence frame;
the diverged peer adopts it at that anchor, rewinds, and lets a later ``advance``
re-step the anchor frames from the repaired state with the already-agreed inputs.
Because the inputs agree and the state now agrees, the re-derived frames match the
authority's, and the peer's later hashes verify. There is no clock, no socket, and
no environment name here; the transfer moves one opaque snapshot between two engines
built over the same study factory, the assumption the mesh already makes.
"""

from __future__ import annotations

from mug.game.mesh import PeerEngine


def resync_peer(
    *, diverged: PeerEngine, authority: PeerEngine, target_frame: int
) -> int:
    """Repair a diverged peer from an authority snapshot and return the anchor.

    The authority serves its nearest snapshot at or before ``target_frame``; the
    diverged peer adopts it and rewinds to that anchor. A caller resumes stepping
    the diverged peer, which re-derives the frames from the repaired state with the
    agreed inputs and reconverges with the mesh.
    """
    anchor, snapshot = authority.repair_snapshot(target_frame)
    diverged.apply_repair(anchor, snapshot)
    return anchor


__all__ = ["resync_peer"]
