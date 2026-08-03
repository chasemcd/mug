"""Write the pinned data-check vectors. Run it only to re-pin them, deliberately.

    uv run python -m tests.datacheck.generate_vectors

The vectors are committed, and the data check compares what the platform recorded
against the **file**, not against a fresh computation. That is the whole point: a
change to how a value is hashed, canonicalized, ordered, or serialized shows up as a
failing check rather than as two computations quietly agreeing with each other.

So re-running this is a decision, not a fix. If the vectors change, something about
what the platform records changed, and the diff says exactly what.
"""

from __future__ import annotations

import json
from pathlib import Path

from mug.game.determinism import state_hash, state_hash_chain
from tests.datacheck.oracle import (
    BENCH_FRAMES,
    BENCH_SEED,
    bench_actions,
    bench_observations,
)

VECTORS = Path(__file__).with_name("vectors.json")


def build() -> dict[str, object]:
    """Build the vectors from the oracle alone."""
    actions = bench_actions()
    observations = bench_observations()
    state_digests = [state_hash(one).hex for one in observations]
    return {
        "seed": BENCH_SEED,
        "frames": BENCH_FRAMES,
        "actions": actions,
        "observations": observations,
        "action_digests": [state_hash(one).hex for one in actions],
        "state_digests": state_digests,
        "chain_digest": state_hash_chain(state_digests).hex,
        "final_state_hash": state_digests[-1],
    }


def main() -> None:
    VECTORS.write_text(json.dumps(build(), indent=1, sort_keys=True) + "\n")
    print(f"wrote {VECTORS} ({BENCH_FRAMES} frames)")


if __name__ == "__main__":
    main()
