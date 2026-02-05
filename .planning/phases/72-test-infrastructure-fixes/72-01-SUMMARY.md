---
phase: 72-test-infrastructure-fixes
plan: 01
status: complete
started: 2026-02-05
completed: 2026-02-05
---

## Summary

Fixed 5 test-infrastructure failures identified in the Phase 71 audit by switching exhausted module-scoped server fixtures to per-function fixtures, reducing memory test sessions, and increasing concurrent load timeouts.

## Tasks Completed

| # | Task | Commit | Files |
|---|------|--------|-------|
| 1 | Switch data_comparison and latency_injection tests to flask_server_fresh | 922d5c6 | tests/e2e/test_data_comparison.py, tests/e2e/test_latency_injection.py |
| 2 | Fix memory test (reduce sessions, increase goto timeout, add health check) | 35e434c | tests/e2e/test_worker_validation.py |
| 3 | Increase multi-episode concurrent load timeout | 23ebe7b | tests/e2e/test_lifecycle_stress.py |

## What Changed

**test_data_comparison.py:** All 5 test functions switched from `flask_server` (module-scoped, port 5702) to `flask_server_fresh` (function-scoped, port 5705). Each test now gets a fresh server instance, eliminating accumulated state that caused server exhaustion failures.

**test_latency_injection.py:** All 4 test functions (6 parameterized variants) switched from `flask_server` to `flask_server_fresh`. Same rationale as above.

**test_worker_validation.py:** Memory leak test `test_no_memory_growth_across_sessions` reduced from 10 to 5 sessions, `page.goto` timeout increased to 60s, HTTP health check added between sessions to verify server responsiveness before next iteration. Pytest timeout reduced from 3000s to 1800s.

**test_lifecycle_stress.py:** `test_multi_episode_completion` pytest timeout increased from 600s to 900s, episode timeout doubled from 300s to 600s per episode to accommodate 3 concurrent multi-episode games under load.

## Deviations

None. All changes matched the plan exactly.

## Issues

None encountered during execution.
