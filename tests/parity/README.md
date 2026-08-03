# The parity fixtures

`docs/architecture/functional-parity.md` requires ten reference fixtures before
the legacy runtime may be removed. This directory is those fixtures, and
`_parity_manifest.py` maps each one to the module that proves it. The map is not
documentation: `test_parity_manifest.py` reads the requirement document and fails
if a fixture is missing, unmapped, reworded, or renumbered.

These documents use ASD-STE100 Simplified Technical English.

```bash
uv run pytest tests/parity -q
```

## The map

| # | Requirement | Proved by |
| --- | --- | --- |
| 1 | A single human running a browser/Pyodide Gymnasium environment | `test_fixture_01_single_human.py` |
| 2 | A human and a browser-side ONNX or deterministic policy sharing an environment | `test_fixture_02_browser_policy.py` |
| 3 | A human and heuristic policy in both browser and server execution | `test_fixture_03_heuristic_both_modes.py` |
| 4 | Two humans completing a rollback-enabled P2P game under latency, packet loss, and focus loss | `test_fixture_04_p2p_under_fault.py` |
| 5 | Two humans completing a server-authoritative game with reconnect behaviour | `test_fixture_05_server_authoritative.py` |
| 6 | Multiple concurrent matches with waiting-room and eligibility behaviour | `test_fixture_06_concurrent_matches.py` |
| 7 | A static/form flow with randomization, repeated activities, participant state, completion, and redirect | `test_fixture_07_composed_flow.py` |
| 8 | A Surface-rendering conformance scene over every logical primitive, assets, deltas, removal, depth, and animation | `test_fixture_08_render_conformance.py` |
| 9 | A Unity/external-client activity, or an explicitly accepted successor | **withdrawn from v0** — `0016-external-client-activity.md` |
| 10 | An operator observing live and completed interactions, with identity and secrets absent | `test_fixture_10_operator_visibility.py` |

## What a fixture is, and what it is not

**A fixture proves a platform capability end to end.** A participant connects,
walks a study, and reaches the other side, or an operator reads a projection of
what really ran. That is the standard the 2026-07-26 requirements audit set after
it found three phases reported complete on the strength of a runtime with no
caller: *done means somebody can reach it*.

So a fixture:

- **runs in the gate.** It uses only environments this repository owns. A fixture
  that skipped because an optional package was absent would prove nothing on the
  day it mattered. The examples that need `cogrid` or `slime_volleyball` are
  examples, not fixtures — see `examples/README.md`.
- **states one scenario, not a matrix.** Fixture 4 runs latency *and* packet loss
  *and* a hidden tab together, because that is what a study in the field meets. The
  one-fault-at-a-time tests are in `tests/e2e_native`, and they are not this.
- **says what it proves in its own docstring**, naming its number. The manifest
  test enforces that too.

## The pieces

- `_parity_manifest.py` — the ten fixtures as data, and the parser that reads the
  requirement document.
- `_participant.py` — one participant walking a study: the command envelopes, the
  frame reads, and the honest browser client that runs a shipped bundle.
- `_environments.py` — one two-seat environment and one partner policy, written
  once as source and built into **both** execution modes. Fixture 3's claim is
  that the two decide the same thing, so neither mode may have a copy of its own.

Fixtures 4 and 6 drive the simulated browsers in `tests/e2e_native/browser_sim.py`.
Everything the server does there is real; only WebRTC and the data channels are
simulated, which is what lets a fixture *state* a packet-loss rate instead of
hoping for one.

## Fixture 9 and the gate

The parity gate passes only when every capability is accepted, replaced, or
removed **by an ADR approved by the product owner**. No test can approve one, and
this suite does not pretend otherwise: `decision_status` reads the status field
out of the ADR, so the gate opens because the document says `Accepted` and shuts
again if that word changes.

ADR-0016 was accepted on 2026-07-29. **v0 has no Unity or WebGL activity**, the
successor stays specified in the ADR for a later version, and fixture 9 is the
single withdrawal. The suite fails if that set changes without the parity
document changing with it.
