# Robustness

The legacy platform was trusted because of `tests/e2e`: two real browsers, a real
server, injected latency and packet loss, twelve concurrent participants, and an
offline comparison of the two players' exported data. This directory is the part of
that suite the rewrite did not already have, plus the map that says where the rest
of it went.

These documents use ASD-STE100 Simplified Technical English.

## What is here

| Module | What it holds the platform to |
| --- | --- |
| `test_recorded_data.py` | What a finished run wrote down is what the run produced: contiguous frames, every seat on every frame, the closing hash of the last frame, and an export that repeats byte for byte |
| `test_concurrent_participants.py` | Twelve people at once, in both execution modes: six tables and six rooms, each recording its own run, nobody paired twice |
| `test_lifecycle.py` | Two rounds back to back, a table that loses a seat while others play, a partner who leaves after the game, a room that aborts beside a room that finishes, and a walkout from the waiting room |
| `test_persistence.py` | The run outlives the process: a store reopened over the same file holds the same run and exports the same bytes; the same claims on Postgres when `MUG_PG_DSN` is set |
| `test_exported_policy.py` | An exported network plays a seat, is recorded under its own name, and the shipped `.onnx` really loads and scores |
| `test_legacy_coverage.py` | Every test in `tests/e2e` is mapped to what covers it now, and every replacement exists |

`_runs.py` plays whole studies through the real application and reads back what
they recorded. `_legacy_manifest.py` is the map.

## Running it

```bash
uv run pytest tests/robustness -q
```

Two cases need something this repository does not depend on, and say so when they
skip:

```bash
# The database a study is deployed on.
docker start mug-pg
MUG_PG_DSN="postgresql://postgres:mug@localhost:55432/mug" uv run pytest tests/robustness -q

# The exported-network seat.
uv pip install onnxruntime
```

## Why some replacements are not the same test

**The two-file comparison.** The legacy suite's source of truth was that both
players exported a file and the files matched. The rewrite records **one** run: the
peers agree on the trajectory, one of them is the capture owner, and the ledger
holds a single episode. So the claim becomes three: the peers agreed
(`tests/parity/test_fixture_04`), the record is what they agreed on
(`tests/e2e_native/test_browser_mesh_e2e.py`), and the record is complete and
re-exportable (here). Together that is stronger than two files being equal, because
two identical files can both be wrong.

**The focus-loss timeout.** The legacy client ended its own game after a period in
the background. The rewrite has no such timer: an empty seat holds no key and the
environment goes on, which is what the timeout was protecting the other participant
from. What is checked is the participant who **stayed**.

**Simulated data channels.** `tests/e2e_native/browser_sim.py` simulates WebRTC and
nothing else. The launch gate, matchmaking, the signalling relay, the start
barrier, and capture reconciliation all run for real, which is what makes a fault
injected there mean something about a deployment. The faults are *stated* rather
than hoped for, so a latency of six ticks is six ticks every time — the legacy
tests asked a real network for delay and got what it felt like giving.

## The rule this directory exists for

A test that counts connections, frames, or files proves that something ran. What a
study needs is that the right thing was **recorded**. Every test here ends by
reading what the deployment wrote down.
