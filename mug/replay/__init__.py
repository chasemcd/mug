"""Replay capture, bundles, and validation (API-16, layer L1).

This family owns the records that pin and verify a deterministic replay: the
``ReplayManifest`` that pins one bundle, the ``P2PReplayEvidence`` a p2p replay
closes over, the ``DecisionTape`` of recorded actions, the two
``StateHashCheck`` outcomes, and the ``ReplayBundleValidation`` verdict. Each
record references the kernel (L0) types. It also carries the small builders and
verifiers over those records: ``build_decision_tape`` assembles the API-16 tape
from an episode's recorded model calls, ``build_replay_bundle`` assembles and
persists a whole replay bundle from an interaction's canonical streams, and
``verify_browser_episode`` (``mug.replay.verify``) re-executes a browser run.
"""

from __future__ import annotations

from mug.replay.bundle import (
    ExperiencedInput,
    ReplayBundle,
    build_replay_bundle,
    validate_replay_bundle,
)
from mug.replay.p2p import build_p2p_replay_bundle
from mug.replay.player import (
    BranchRun,
    ReplayRun,
    SnapshotEnv,
    fork_replay,
    replay_episode,
)
from mug.replay.tape import build_decision_tape, model_output_entry
from mug.replay.types import (
    DecisionTape,
    P2PReplayEvidence,
    ReplayBundleValidation,
    ReplayManifest,
    StateHashCheck,
    replay_schema,
)

__all__ = [
    "BranchRun",
    "DecisionTape",
    "ExperiencedInput",
    "P2PReplayEvidence",
    "ReplayBundle",
    "ReplayBundleValidation",
    "ReplayManifest",
    "ReplayRun",
    "SnapshotEnv",
    "StateHashCheck",
    "build_decision_tape",
    "build_p2p_replay_bundle",
    "build_replay_bundle",
    "fork_replay",
    "model_output_entry",
    "replay_episode",
    "replay_schema",
    "validate_replay_bundle",
]
