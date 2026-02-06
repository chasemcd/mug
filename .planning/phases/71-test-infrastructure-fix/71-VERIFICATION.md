---
phase: 71-test-infrastructure-fix
verified: 2026-02-06T19:45:00Z
status: gaps_found
score: 3/4 must-haves verified
gaps:
  - truth: "test_focus_loss_episode_boundary_parity passes when run after other test suites"
    status: partial
    reason: "Test passes in isolation and after cross-module transitions, but fails when run as the 5th test within test_data_comparison.py due to server state accumulation after 4 game sessions on the same module-scoped flask_server instance. This is NOT a port teardown issue -- the port is properly freed between modules. It is a server-side state exhaustion issue (eventlet/socketio becomes unresponsive after serving multiple game sessions)."
    artifacts:
      - path: "tests/conftest.py"
        issue: "flask_server fixture is module-scoped; no mechanism to reset server state between tests within a module"
      - path: "tests/e2e/test_data_comparison.py"
        issue: "test_focus_loss_episode_boundary_parity is the 5th of 5 tests sharing the same module-scoped flask_server on port 5702"
    missing:
      - "Either make flask_server function-scoped for test_data_comparison.py (or just for the 5th test), or add server state reset between tests, or move test_focus_loss_episode_boundary_parity to its own module"
---

# Phase 71: Test Infrastructure Fix Verification Report

**Phase Goal:** Server startup and teardown between test suites completes cleanly, eliminating Page.goto timeout failures when running E2E test suites back-to-back.
**Verified:** 2026-02-06T19:45:00Z
**Status:** gaps_found
**Re-verification:** No -- initial verification

## Goal Achievement

### Observable Truths

| # | Truth | Status | Evidence |
|---|-------|--------|----------|
| 1 | Running test_data_comparison then test_multiplayer_basic back-to-back succeeds with no Page.goto timeouts | VERIFIED | Executor confirmed 6/6 tests pass across 2 modules sharing port 5702. `_teardown_server` properly frees port between modules. |
| 2 | No stale server processes remain on ports 5702-5706 after any fixture teardown | VERIFIED | `_teardown_server` polls `_is_port_free()` and raises `RuntimeError` if port still occupied. `_ensure_port_available` kills stale PIDs via `lsof` as last resort. Executor confirmed `lsof` shows all ports clean after test run. |
| 3 | All 5 server fixtures use identical robust teardown logic (DRY) | VERIFIED | All 5 fixtures (`flask_server`, `flask_server_fresh`, `flask_server_multi_episode`, `flask_server_multi_episode_fresh`, `flask_server_focus_timeout`) call `_ensure_port_available(port)` before `Popen`, `_teardown_server(process, port)` in both the `else` failure path and the post-`yield` teardown. 4 shared helpers (`_is_port_free`, `_ensure_port_available`, `_wait_for_port_free`, `_teardown_server`) are defined once and used by all fixtures. |
| 4 | test_focus_loss_episode_boundary_parity passes when run after other test suites (not just in isolation) | PARTIAL | The test passes in isolation (32.57s). Cross-module transitions work (e.g., running it alone after test_multiplayer_basic would work). But it FAILS when run as the 5th test within test_data_comparison.py because the module-scoped `flask_server` becomes unresponsive after serving 4 prior game sessions. This is server state accumulation, NOT a port teardown issue. |

**Score:** 3/4 truths verified (1 partial)

### Required Artifacts

| Artifact | Expected | Status | Details |
|----------|----------|--------|---------|
| `tests/conftest.py` -- `_is_port_free` | Port availability check via socket.bind() | VERIFIED | Lines 33-47, 15 lines, uses `socket.AF_INET`/`SO_REUSEADDR`/`bind()`, returns bool |
| `tests/conftest.py` -- `_ensure_port_available` | Pre-startup stale process cleanup | VERIFIED | Lines 50-81, 32 lines, uses `lsof -ti` to find/kill PIDs, raises RuntimeError on failure |
| `tests/conftest.py` -- `_wait_for_port_free` | Teardown port polling | VERIFIED | Lines 84-105, 22 lines, polls every 0.2s with deadline, falls back to `_ensure_port_available` |
| `tests/conftest.py` -- `_teardown_server` | Robust process termination with port verification | VERIFIED | Lines 108-148, 41 lines, terminate/wait/kill/killpg/wait_for_port_free chain |

All 4 helpers exist, are substantive (non-stub), and are wired into all 5 fixtures.

### Key Link Verification

| From | To | Via | Status | Details |
|------|----|-----|--------|---------|
| flask_server fixture teardown | `_teardown_server` helper | function call after yield | VERIFIED | Line 260: `_teardown_server(process, port)` |
| flask_server_fresh fixture teardown | `_teardown_server` helper | function call after yield | VERIFIED | Line 331: `_teardown_server(process, port)` |
| flask_server_multi_episode fixture teardown | `_teardown_server` helper | function call after yield | VERIFIED | Line 455: `_teardown_server(process, port)` (stderr read at 442-446 before teardown) |
| flask_server_multi_episode_fresh fixture teardown | `_teardown_server` helper | function call after yield | VERIFIED | Line 528: `_teardown_server(process, port)` |
| flask_server_focus_timeout fixture teardown | `_teardown_server` helper | function call after yield | VERIFIED | Line 599: `_teardown_server(process, port)` |
| flask_server fixture startup | `_ensure_port_available` helper | function call before Popen | VERIFIED | Line 207: `_ensure_port_available(port)` before Popen at line 214 |
| flask_server_fresh fixture startup | `_ensure_port_available` helper | function call before Popen | VERIFIED | Line 285 before Popen at line 288 |
| flask_server_multi_episode fixture startup | `_ensure_port_available` helper | function call before Popen | VERIFIED | Line 392 before Popen at line 394 |
| flask_server_multi_episode_fresh fixture startup | `_ensure_port_available` helper | function call before Popen | VERIFIED | Line 478 before Popen at line 480 |
| flask_server_focus_timeout fixture startup | `_ensure_port_available` helper | function call before Popen | VERIFIED | Line 554 before Popen at line 556 |
| All Popen calls | `start_new_session=True` | Popen kwarg | VERIFIED | 5 occurrences at lines 224, 298, 404, 490, 566 |
| All Popen calls | `stdout=subprocess.DEVNULL` | Popen kwarg | VERIFIED | 5 occurrences at lines 222, 296, 402, 488, 564 |
| All Popen calls | `stderr=subprocess.PIPE` | Popen kwarg | VERIFIED | 5 occurrences at lines 223, 297, 403, 489, 565 |
| All fixture failure paths | `_teardown_server` helper | function call in `else` clause | VERIFIED | 5 occurrences at lines 252, 323, 429, 515, 591 |

### Requirements Coverage

| Requirement | Status | Blocking Issue |
|-------------|--------|----------------|
| INFRA-01: Server startup/teardown between test suites completes reliably | SATISFIED | None -- `_ensure_port_available` + `_teardown_server` + port polling verified |
| INFRA-02: Page.goto navigation succeeds consistently (no 30s timeout between tests) | MOSTLY SATISFIED | Cross-module navigation verified working. Within-module 5th test still times out (server state issue, not port issue). |
| INFRA-03: Test fixtures properly clean up browser contexts, server processes, and temporary files | SATISFIED | `start_new_session` + process group kill + port polling + `stdout=DEVNULL`. Browser context cleanup was already correct (unchanged). |

### Anti-Patterns Found

| File | Line | Pattern | Severity | Impact |
|------|------|---------|----------|--------|
| tests/conftest.py | 279, 330, 472, 527 | References to "hack" in comments | Info | Comments about REMOVING the old sleep hack -- informational only, not a concern |

No TODO, FIXME, XXX, placeholder, or stub patterns found. No empty returns. File is 671 lines, fully substantive.

### Human Verification Required

### 1. Full module back-to-back execution
**Test:** Run `python -m pytest tests/e2e/test_data_comparison.py tests/e2e/test_multiplayer_basic.py --headed -x -v --timeout=300`
**Expected:** All tests pass with no Page.goto timeouts between modules
**Why human:** Requires headed Chromium with real WebRTC, takes several minutes

### 2. Targeted cross-module focus loss test
**Test:** Run `python -m pytest tests/e2e/test_multiplayer_basic.py tests/e2e/test_data_comparison.py::test_focus_loss_episode_boundary_parity --headed -v --timeout=300`
**Expected:** The focus loss test passes when run after another module (proving cross-module teardown works)
**Why human:** Requires headed Chromium, confirms the specific targeted scenario works even though full-module run does not

### 3. Port cleanliness after test run
**Test:** After any test run, execute `lsof -ti :5702 :5703 :5704 :5705 :5706 2>/dev/null || echo "All ports clean"`
**Expected:** "All ports clean" output
**Why human:** Requires running actual tests first

### Gaps Summary

**3 of 4 must-haves fully verified. 1 partial.**

The infrastructure fix is working exactly as designed for its primary purpose: eliminating Page.goto timeout failures at module boundaries. All 5 server fixtures use the shared helpers consistently. Port teardown is verified. No stale processes remain.

The one partial gap is that `test_focus_loss_episode_boundary_parity` still fails when run as the 5th test within its module (`test_data_comparison.py`). This is NOT a port teardown issue -- the module-scoped `flask_server` is never torn down between tests within the same module (by design -- that is what `scope="module"` means). The server becomes unresponsive after serving 4 game sessions due to eventlet/socketio state accumulation. This is a server-side issue that the port-based infrastructure fix cannot address.

The ROADMAP success criterion #4 says "test_focus_loss_episode_boundary_parity passes when run after other test suites (not just in isolation)." Interpreted strictly as "after other test suites [modules]," this likely passes (the test succeeds when run in isolation or after other modules complete). Interpreted as "within the full test_data_comparison.py module run," it fails. The gap is marked as partial because the infrastructure fix achieves the intended goal (clean between-module transitions) but the specific test still fails due to a different root cause (in-module server state accumulation).

**Recommendation:** This gap is best addressed in Phase 72+ by either: (a) moving `test_focus_loss_episode_boundary_parity` to its own module, (b) making `flask_server` function-scoped in `test_data_comparison.py`, or (c) adding server state reset logic between tests. It is NOT a Phase 71 infrastructure/teardown issue.

---

_Verified: 2026-02-06T19:45:00Z_
_Verifier: Claude (gsd-verifier)_
