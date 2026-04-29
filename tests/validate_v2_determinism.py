#!/usr/bin/env python3
"""Validate that OvercookedV2 envs produce deterministic recipe sequences
across paired Pyodide clients sharing a game seed.

The randomness in V2 fires only when a delivery happens: the
``build_target_recipe_tick`` resample path picks a new ``target_recipe``
via module-level ``np.random.randint(0, n_recipes)``. Tests that step the
env with noops never hit this path, so they pass trivially regardless of
whether seeding actually works. The tests in this file therefore force
delivery events on every comparison step, capture the resulting recipe,
and check that paired clients produce **byte-identical recipe sequences**
across many deliveries.

Why force deliveries instead of scripting full pickup-cook-plate-deliver?
The resample path keys on ``extra_state["overcooked.delivery_occurred"]``;
real deliveries set it via the reward pipeline, but the resample
randomness is the same module-RNG draw either way. Forcing the flag
exercises the exact code path with far less setup.

Important subtlety: in production each browser is its own Pyodide
process, so module-level numpy RNG state is per-client. To simulate that
in a single Python test process, ``isolated_step`` saves/restores numpy +
python random state between each client's step -- otherwise client-A's
``randint`` advances client-B's RNG too, a test artifact that would
masquerade as a divergence.

What "gameplay state" means here: every snapshot field except
``rng_key``. ``rng_key`` is JAX-mode metadata; on the numpy backend
cogrid runs in Pyodide it has no gameplay impact, but ``set_state``
doesn't restore the per-instance PCG64 (``self._np_random``) that feeds
it, so it drifts after rollback. The drift doesn't affect agents,
inventories, or recipes -- treat it as noise. ``GAMEPLAY_KEYS`` excludes
it from the comparison.

Usage::

    pytest tests/validate_v2_determinism.py -v
    python tests/validate_v2_determinism.py --seeds 42,1337,9001 --deliveries 80

Exits non-zero on any failure.
"""
from __future__ import annotations

import argparse
import dataclasses
import hashlib
import json
import os
import random
import sys
import traceback

import numpy as np
import pytest

REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, REPO_ROOT)

from examples.cogrid import overcooked_utils  # noqa: E402

# Cogrid action ids (cardinal_actions).
MOVE_N, MOVE_S, MOVE_W, MOVE_E, INTERACT, TOGGLE, NOOP = 0, 1, 2, 3, 4, 5, 6

# Parametrization defaults shared by the pytest wrappers and the CLI driver.
DEFAULT_SEEDS = (42, 1337, 9001)
DEFAULT_N_DELIVERIES = 50  # how many forced deliveries each comparison runs
DEFAULT_PRE_DELIVERIES = 10
DEFAULT_DIRTY_DELIVERIES = 5
DEFAULT_POST_DELIVERIES = 10
DEFAULT_REAL_CYCLES = 5  # full pickup-cook-plate-deliver loops in the real-pipeline test
ENV_IDS = tuple(eid for eid, _ in overcooked_utils.V2_LAYOUTS)

# Snapshot fields that affect what a player can observe / interact with.
# Explicitly excludes ``rng_key`` (see module docstring).
GAMEPLAY_KEYS = (
    "agent_pos",
    "agent_dir",
    "agent_inv",
    "wall_map",
    "object_type_map",
    "object_state_map",
    "extra_state",
    "time",
    "done",
    "t",
    "cumulative_score",
)


# ---------------------------------------------------------------------------
# Loading the env via the same template the Pyodide clients run
# ---------------------------------------------------------------------------
def load_env(env_id: str):
    code = overcooked_utils.make_v2_env_init_code(env_id)
    ns: dict = {"__name__": f"__v2_validation_{env_id}__"}
    exec(code, ns)
    return ns["env"]


def _seed_module_rngs(seed: int) -> None:
    np.random.seed(seed)
    random.seed(seed)


def make_paired_clients(env_id: str, seed: int):
    """Create two env instances with identical starting state and isolated
    per-client module RNG snapshots.

    Reproduces the multiplayer JS contract: ``np.random.seed(seed)`` and
    ``random.seed(seed)`` happen before ``env.reset(seed=seed)``, since
    cogrid's ``extra_state_init_fn`` reads module RNG to pick the initial
    ``target_recipe``. Both clients start from the same module-RNG state;
    their per-client ``rng_a`` / ``rng_b`` snapshots diverge only via
    their own consumption thereafter.
    """
    _seed_module_rngs(seed)
    initial_rng = capture_rng()

    env_a = load_env(env_id)
    restore_rng(initial_rng)
    env_a.reset(seed=seed)
    rng_a = capture_rng()

    env_b = load_env(env_id)
    restore_rng(initial_rng)
    env_b.reset(seed=seed)
    rng_b = capture_rng()

    return env_a, rng_a, env_b, rng_b


# ---------------------------------------------------------------------------
# Per-client RNG isolation
# ---------------------------------------------------------------------------
def capture_rng() -> dict:
    return {"np": np.random.get_state(), "py": random.getstate()}


def restore_rng(state: dict) -> None:
    np.random.set_state(state["np"])
    random.setstate(state["py"])


def isolated_step(env, actions, client_rng: dict) -> dict:
    """Step ``env`` as if it were the only consumer of the module RNG."""
    restore_rng(client_rng)
    env.step(actions)
    return capture_rng()


# ---------------------------------------------------------------------------
# Hashing
# ---------------------------------------------------------------------------
def gameplay_fingerprint(env) -> str:
    snap = env.get_state()
    fp = {k: snap[k] for k in GAMEPLAY_KEYS if k in snap}
    return hashlib.md5(
        json.dumps(fp, sort_keys=True, default=str).encode()
    ).hexdigest()[:12]


# ---------------------------------------------------------------------------
# Snapshot / restore (matches pyodide_multiplayer_game.js exactly)
# ---------------------------------------------------------------------------
def full_snapshot_json(env) -> str:
    np_state = np.random.get_state()
    payload = {
        "env_state": env.get_state(),
        "np_rng": (
            np_state[0],
            np_state[1].tolist(),
            int(np_state[2]),
            int(np_state[3]),
            float(np_state[4]),
        ),
        "py_rng": random.getstate(),
    }
    return json.dumps(payload, default=str)


def restore_full_snapshot(env, snapshot_json: str) -> None:
    snap = json.loads(snapshot_json)
    n = snap["np_rng"]
    np.random.set_state(
        (n[0], np.array(n[1], dtype=np.uint32), int(n[2]), int(n[3]), float(n[4]))
    )
    p = snap["py_rng"]
    if isinstance(p, list):
        p = (p[0], tuple(p[1]), p[2] if len(p) > 2 else None)
    random.setstate(p)
    env.set_state(snap["env_state"])


# ---------------------------------------------------------------------------
# Forced-delivery helpers
# ---------------------------------------------------------------------------
def force_delivery(env) -> None:
    """Set ``overcooked.delivery_occurred=1`` so the next tick resamples.

    Real deliveries set this flag via the reward pipeline; the resample
    randomness is the same module-RNG draw either way, so forcing the
    flag exercises the exact code path the user is concerned about.
    """
    st = env._env_state
    env._env_state = dataclasses.replace(
        st,
        extra_state={
            **st.extra_state,
            "overcooked.delivery_occurred": np.int32(1),
        },
    )


def step_with_delivery(env, actions, client_rng):
    """Force a delivery, step the env (which triggers resample), and
    return the new client RNG snapshot plus the resampled recipe.
    """
    force_delivery(env)
    new_rng = isolated_step(env, actions, client_rng)
    recipe = int(env._env_state.extra_state["overcooked.target_recipe"])
    return new_rng, recipe


def collect_recipe_sequence(env, client_rng, n_deliveries):
    """Drive ``n_deliveries`` forced deliveries on ``env`` and collect the
    sequence of resampled recipes. Returns ``(new_rng, [int, ...])``.
    """
    sequence = []
    for _ in range(n_deliveries):
        client_rng, recipe = step_with_delivery(
            env, {0: NOOP, 1: NOOP}, client_rng
        )
        sequence.append(recipe)
    return client_rng, sequence


# ---------------------------------------------------------------------------
# Scripted real-delivery cycle (TestTimeSimple-specific)
# ---------------------------------------------------------------------------
# TestTimeSimple's central wall column splits the kitchen, so only agent 1
# (right side) can reach the cooking apparatus. The script below drives
# agent 1 through one full pickup-cook-plate-deliver cycle for onion soup.
# Layout reference (rows x cols, 5x8)::
#
#   CCBCCCCC      (0, *)  - all walls
#   C  C=  O      (1, 4)= PlateStack, (1, 7)= OnionStack
#   R +Cu+ X      (2, 0)= RecipeIndicator, (2, 4)= OpenPot, (2, 7)= OpenDeliveryZone
#   C  C=  T      (3, 4)= PlateStack, (3, 7)= TomatoStack
#   CCBCCCCC      (4, *)  - all walls
#
# Agent 1 starts at (2, 5) facing North.

_TESTTIMESIMPLE_DELIVERY_SCRIPT = (
    # 3x onion: N E pickup S W drop  (each onion takes 6 ticks)
    *([MOVE_N, MOVE_E, INTERACT, MOVE_S, MOVE_W, INTERACT] * 3),
    # Wait 20 ticks for cooking_timer to count down from 20 to 0.
    *([NOOP] * 20),
    # Plate: N, W (blocked by stack -> rotates only), pickup
    MOVE_N, MOVE_W, INTERACT,
    # Soup pickup: S, W (blocked by pot -> rotates only), pickup with plate in hand
    MOVE_S, MOVE_W, INTERACT,
    # Deliver: E, E (blocked by delivery zone -> rotates only), drop
    MOVE_E, MOVE_E, INTERACT,
    # Trailing noop so the next tick fires the resample triggered by
    # ``overcooked.delivery_occurred=1`` set during the previous step.
    NOOP,
)


def _testtimesimple_actions(action_for_agent1: int) -> dict:
    """Action dict driving agent 1 with ``action_for_agent1`` and pinning agent 0 to noop."""
    return {0: NOOP, 1: action_for_agent1}


# ---------------------------------------------------------------------------
# Workers
# ---------------------------------------------------------------------------
def _check_cross_client_recipe_sequence(env_id, seed, n_deliveries):
    """Two paired clients must produce the same recipe sequence over many
    forced deliveries. This is the production invariant: same seed →
    same "spawn after delivery" sequence.
    """
    env_a, rng_a, env_b, rng_b = make_paired_clients(env_id, seed)

    if gameplay_fingerprint(env_a) != gameplay_fingerprint(env_b):
        raise AssertionError("  initial gameplay state mismatch after seeded reset")

    seq_a, seq_b = [], []
    for i in range(n_deliveries):
        rng_a, ra = step_with_delivery(env_a, {0: NOOP, 1: NOOP}, rng_a)
        rng_b, rb = step_with_delivery(env_b, {0: NOOP, 1: NOOP}, rng_b)
        seq_a.append(ra)
        seq_b.append(rb)
        if ra != rb:
            raise AssertionError(
                f"  recipe diverged at delivery {i}: client_a={ra} client_b={rb}\n"
                f"  preceding sequence (a): {seq_a[:i]}\n"
                f"  preceding sequence (b): {seq_b[:i]}"
            )
        fa = gameplay_fingerprint(env_a)
        fb = gameplay_fingerprint(env_b)
        if fa != fb:
            raise AssertionError(
                f"  gameplay state diverged at delivery {i}: {fa} vs {fb}"
            )

    # Sanity guard: if every recipe is identical, we're not actually exercising
    # randomness. The V2 envs in V2_LAYOUTS all have at least 2 target_recipes,
    # so a 50-step sequence should hit each recipe at least once.
    n_recipes_seen = len(set(seq_a))
    if n_recipes_seen < 2:
        raise AssertionError(
            f"  recipe sequence has only {n_recipes_seen} unique value(s) over "
            f"{n_deliveries} deliveries -- the randomness path may not be "
            f"firing; sequence head: {seq_a[:10]}"
        )


def _check_seed_varies_sequence(env_id, seed_a, seed_b, n_deliveries):
    """Different seeds must produce different recipe sequences -- a sanity
    guard that the seed actually controls the resampling RNG.
    """
    env_1, rng_1, _, _ = make_paired_clients(env_id, seed_a)
    _, seq_a = collect_recipe_sequence(env_1, rng_1, n_deliveries)

    env_2, rng_2, _, _ = make_paired_clients(env_id, seed_b)
    _, seq_b = collect_recipe_sequence(env_2, rng_2, n_deliveries)

    if seq_a == seq_b:
        raise AssertionError(
            f"  seeds {seed_a} and {seed_b} produced identical recipe "
            f"sequences over {n_deliveries} deliveries -- the seed isn't "
            f"controlling resampling RNG"
        )


def _check_real_delivery_pipeline(env_id, seed, n_cycles):
    """Two paired clients drive agent 1 through ``n_cycles`` full
    pickup-cook-plate-deliver loops via real game actions (not forced
    flags). The ``target_recipe`` after each cycle's resample must match
    across clients, and gameplay fingerprints must agree at every step.

    Layout-specific: only TestTimeSimple has its action sequence
    scripted. Other layouts could be added but each needs its own script.
    """
    if env_id != "OvercookedV2-TestTimeSimple-V0":
        pytest.skip(
            f"real-delivery script not written for {env_id} "
            "(only TestTimeSimple has a scripted action sequence)"
        )

    env_a, rng_a, env_b, rng_b = make_paired_clients(env_id, seed)

    seq_a, seq_b = [], []
    for cycle in range(n_cycles):
        for action in _TESTTIMESIMPLE_DELIVERY_SCRIPT:
            actions = _testtimesimple_actions(action)
            rng_a = isolated_step(env_a, actions, rng_a)
            rng_b = isolated_step(env_b, actions, rng_b)

        # Verify a delivery actually fired -- otherwise the script broke
        # (e.g. layout changed) and we'd be testing nothing.
        # The flag is reset to 0 by the resample tick, so by the trailing
        # noop it should be 0 again, but we can sanity-check via
        # cumulative_score: a successful (correct) onion delivery scores 20.
        recipe_a = int(env_a._env_state.extra_state["overcooked.target_recipe"])
        recipe_b = int(env_b._env_state.extra_state["overcooked.target_recipe"])
        seq_a.append(recipe_a)
        seq_b.append(recipe_b)

        if recipe_a != recipe_b:
            raise AssertionError(
                f"  recipe diverged after cycle {cycle}: "
                f"client_a={recipe_a} client_b={recipe_b}\n"
                f"  preceding sequence (a): {seq_a[:cycle]}\n"
                f"  preceding sequence (b): {seq_b[:cycle]}"
            )
        fa = gameplay_fingerprint(env_a)
        fb = gameplay_fingerprint(env_b)
        if fa != fb:
            raise AssertionError(
                f"  gameplay state diverged after cycle {cycle}: {fa} vs {fb}"
            )

    # Sanity: deliveries actually happened. cumulative_score includes the
    # delivery reward (20 per correct, -20 per incorrect). Over n_cycles
    # always-onion deliveries, with target oscillating, it should not be 0.
    score_a = float(env_a.get_state()["cumulative_score"])
    if abs(score_a) < 1e-6:
        raise AssertionError(
            f"  cumulative_score is 0 after {n_cycles} scripted cycles -- "
            "the script ran but no delivery reward fired. The action sequence "
            "may have broken (layout changed?)."
        )

    # Sanity: the recipe sequence has variability (not stuck on one value).
    if len(set(seq_a)) < 2 and n_cycles >= 5:
        # With 2 target_recipes, P(all same in N draws) = 2 / 2^N.
        # For N=5 that's 2/32 = 6.25% -- low but not impossible. We only
        # raise here if n_cycles is large enough that an always-same
        # sequence is implausible (2/2^10 = 0.2% at 10 cycles).
        if n_cycles >= 10:
            raise AssertionError(
                f"  recipe sequence over {n_cycles} real deliveries is all "
                f"{seq_a[0]} -- the resample RNG may not be firing"
            )


def _check_rollback_through_deliveries(env_id, seed, n_pre, n_dirty, n_post):
    """Rollback must preserve the recipe sequence across delivery events.

    Snapshot mid-game after ``n_pre`` deliveries. Run ``n_dirty`` more
    (which advance module RNG and consume real resamples). Restore.
    Continue with ``n_post`` deliveries. The total recipe sequence
    (pre + post, with dirty discarded) must equal a fresh-seeded run that
    did ``n_pre + n_post`` deliveries straight through.
    """
    # Path 1: snapshot, dirty, restore, continue.
    env, _, _, _ = make_paired_clients(env_id, seed)
    rng = capture_rng()

    rng, pre_seq = collect_recipe_sequence(env, rng, n_pre)

    snapshot = full_snapshot_json(env)
    fp_captured = gameplay_fingerprint(env)

    # Dirty deliveries that we'll discard.
    rng, _dirty_seq = collect_recipe_sequence(env, rng, n_dirty)

    restore_full_snapshot(env, snapshot)
    fp_restored = gameplay_fingerprint(env)
    if fp_restored != fp_captured:
        raise AssertionError(
            f"  state after restore != captured: {fp_restored} vs {fp_captured}"
        )
    rng = capture_rng()  # restore_full_snapshot wrote module RNG; sync our handle.

    rng, post_seq = collect_recipe_sequence(env, rng, n_post)
    rolled_back_seq = pre_seq + post_seq

    # Path 2: fresh-seeded straight-through run.
    env_fresh, rng_fresh, _, _ = make_paired_clients(env_id, seed)
    _, fresh_seq = collect_recipe_sequence(env_fresh, rng_fresh, n_pre + n_post)

    if rolled_back_seq != fresh_seq:
        # Find first divergence for actionable reporting.
        first_diff = next(
            (i for i, (a, b) in enumerate(zip(rolled_back_seq, fresh_seq)) if a != b),
            min(len(rolled_back_seq), len(fresh_seq)),
        )
        raise AssertionError(
            f"  rolled-back sequence diverged from fresh at index {first_diff}\n"
            f"  rolled-back: {rolled_back_seq[:first_diff + 3]}...\n"
            f"  fresh:       {fresh_seq[:first_diff + 3]}..."
        )


# ---------------------------------------------------------------------------
# Pytest wrappers
# ---------------------------------------------------------------------------
# Helper functions above are named ``_check_*`` so pytest doesn't try to
# auto-collect them as tests with un-fixturable parameters. The tests below
# are the discoverable ones; each (env_id, seed) pair gets its own case so
# failures pinpoint the specific combination that broke.


@pytest.mark.parametrize("env_id", ENV_IDS)
@pytest.mark.parametrize("seed", DEFAULT_SEEDS)
def test_cross_client_recipe_sequence(env_id: str, seed: int) -> None:
    _check_cross_client_recipe_sequence(env_id, seed, DEFAULT_N_DELIVERIES)


@pytest.mark.parametrize("env_id", ENV_IDS)
def test_seed_varies_sequence(env_id: str) -> None:
    # Use the first two of DEFAULT_SEEDS so we don't double the matrix size.
    _check_seed_varies_sequence(
        env_id, DEFAULT_SEEDS[0], DEFAULT_SEEDS[1], DEFAULT_N_DELIVERIES
    )


@pytest.mark.parametrize("env_id", ENV_IDS)
@pytest.mark.parametrize("seed", DEFAULT_SEEDS)
def test_rollback_through_deliveries(env_id: str, seed: int) -> None:
    _check_rollback_through_deliveries(
        env_id,
        seed,
        DEFAULT_PRE_DELIVERIES,
        DEFAULT_DIRTY_DELIVERIES,
        DEFAULT_POST_DELIVERIES,
    )


# Real-pipeline test is layout-specific (scripted action sequence). Only
# TestTimeSimple is scripted; other envs would skip via pytest.skip.
@pytest.mark.parametrize("env_id", ["OvercookedV2-TestTimeSimple-V0"])
@pytest.mark.parametrize("seed", DEFAULT_SEEDS)
def test_real_delivery_pipeline(env_id: str, seed: int) -> None:
    _check_real_delivery_pipeline(env_id, seed, DEFAULT_REAL_CYCLES)


# ---------------------------------------------------------------------------
# CLI driver
# ---------------------------------------------------------------------------
def run_all(env_ids, seeds, n_deliveries):
    failures = 0
    total = 0
    for env_id in env_ids:
        print(f"\n=== {env_id} ===")
        for seed in seeds:
            cases = [
                ("cross-client recipe sequence",
                 lambda eid=env_id, s=seed: _check_cross_client_recipe_sequence(eid, s, n_deliveries)),
                ("rollback through deliveries",
                 lambda eid=env_id, s=seed: _check_rollback_through_deliveries(
                     eid, s,
                     DEFAULT_PRE_DELIVERIES,
                     DEFAULT_DIRTY_DELIVERIES,
                     DEFAULT_POST_DELIVERIES,
                 )),
            ]
            # Real-pipeline cycle is scripted only for TestTimeSimple.
            if env_id == "OvercookedV2-TestTimeSimple-V0":
                cases.append(
                    ("real delivery pipeline",
                     lambda eid=env_id, s=seed: _check_real_delivery_pipeline(
                         eid, s, DEFAULT_REAL_CYCLES,
                     ))
                )
            for name, fn in cases:
                total += 1
                try:
                    fn()
                    print(f"  [seed={seed:>5}] OK    {name}")
                except AssertionError as e:
                    failures += 1
                    print(f"  [seed={seed:>5}] FAIL  {name}")
                    print(str(e))
                except Exception:
                    failures += 1
                    print(f"  [seed={seed:>5}] ERROR {name}")
                    traceback.print_exc()
        # One seed-varies check per env (independent of seed loop).
        total += 1
        try:
            _check_seed_varies_sequence(env_id, seeds[0], seeds[1], n_deliveries)
            print(f"  [seeds={seeds[0]}vs{seeds[1]}] OK    seed varies sequence")
        except AssertionError as e:
            failures += 1
            print(f"  [seeds={seeds[0]}vs{seeds[1]}] FAIL  seed varies sequence")
            print(str(e))

    print(f"\n{total - failures}/{total} checks passed")
    if failures == 0:
        print(
            "\nAll cross-client and rollback invariants hold across forced "
            f"delivery sequences ({n_deliveries} per check). The "
            "'spawn after delivery' randomness is deterministic across paired "
            "clients given a shared seed."
        )
    return failures


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--seeds", default="42,1337,9001")
    parser.add_argument("--deliveries", type=int, default=DEFAULT_N_DELIVERIES)
    parser.add_argument("--envs", default=None)
    args = parser.parse_args()

    seeds = [int(s) for s in args.seeds.split(",")]
    if len(seeds) < 2:
        parser.error("Need at least 2 seeds for the seed-varies check.")
    env_ids = args.envs.split(",") if args.envs else list(ENV_IDS)

    return 1 if run_all(env_ids, seeds, args.deliveries) else 0


if __name__ == "__main__":
    sys.exit(main())
