# Phase 71: Test Infrastructure Fix - Research

**Researched:** 2026-02-06
**Domain:** pytest fixture lifecycle, subprocess management, port cleanup, Playwright navigation
**Confidence:** HIGH

## Summary

The Phase 71 goal is to eliminate Page.goto timeout failures that occur when running E2E test suites back-to-back, caused by stale server processes and port conflicts between test modules. After thorough investigation of the test infrastructure, the root cause is clear and the fix is straightforward.

The primary problem is the `flask_server` fixture (module-scoped, port 5702) used by 5 different test modules (`test_infrastructure`, `test_multiplayer_basic`, `test_data_comparison`, `test_latency_injection`, `test_network_disruption`). When one module's server is torn down and the next module creates a new one on the same port, several things can go wrong: (1) the old process may not have fully released the port due to TCP TIME_WAIT, (2) the old process may have spawned child threads/greenlets via eventlet that outlive the `terminate()` signal, (3) the teardown code lacks port-availability verification before returning.

The `test_focus_loss_episode_boundary_parity` failure when run after other suites is a specific manifestation of this: the `test_data_comparison` module's 4 earlier tests use the same `flask_server` instance, but when this module's teardown races with the next module that also requests `flask_server`, the Page.goto call hits a server that is not yet ready or is still the old dying process.

**Primary recommendation:** Add robust process cleanup with forced kill, port-availability polling, and process-tree termination to ALL server fixtures in `tests/conftest.py`. Add a shared helper function so the fix is DRY across all 5 fixture variants.

## Standard Stack

The established libraries/tools for this domain:

### Core
| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| pytest | current | Test framework | Already in use |
| pytest-playwright | current | Browser automation | Already in use |
| subprocess (stdlib) | Python 3.10 | Server process management | Already in use |
| signal (stdlib) | Python 3.10 | Process signals | Available, not yet used for SIGKILL |
| socket (stdlib) | Python 3.10 | Port availability checking | Available, not yet used |

### Supporting
| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| os (stdlib) | Python 3.10 | Process group operations (os.killpg) | Kill child processes |
| time (stdlib) | Python 3.10 | Polling delays | Already in use |

### Alternatives Considered
| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| stdlib socket check | psutil | psutil not installed; stdlib socket is sufficient |
| os.killpg | psutil.Process.children() | psutil not installed; process groups work without it |
| Manual port polling | pytest-server-fixtures | Over-engineering; fixture already works, just needs better cleanup |

**Installation:**
No new dependencies required. All tools are Python stdlib.

## Architecture Patterns

### Current Fixture Port Allocation

```
Port 5702 - flask_server (module-scoped)
  Used by: test_infrastructure, test_multiplayer_basic, test_data_comparison,
           test_latency_injection, test_network_disruption

Port 5703 - flask_server_multi_episode (module-scoped)
  Used by: (no current test files directly)

Port 5704 - flask_server_focus_timeout (module-scoped)
  Used by: test_lifecycle_stress (test_focus_loss_timeout only)

Port 5705 - flask_server_fresh (function-scoped)
  Used by: test_multi_participant, test_lifecycle_stress

Port 5706 - flask_server_multi_episode_fresh (function-scoped)
  Used by: test_lifecycle_stress (test_multi_episode_completion only)
```

### Root Cause Analysis

**Problem 1: Port 5702 shared across 5 modules**

The `flask_server` fixture has `scope="module"`. When pytest runs test_data_comparison (5 tests on port 5702) then test_network_disruption (3 tests on port 5702), the sequence is:

1. test_data_comparison module starts -> `flask_server` creates process on 5702
2. All 5 tests in test_data_comparison run
3. test_data_comparison module ends -> `flask_server` teardown: `process.terminate()` + `process.wait(timeout=5)`
4. test_network_disruption module starts -> `flask_server` creates NEW process on 5702
5. Port 5702 may still be in TIME_WAIT or old eventlet greenlets still hold sockets
6. New process fails to bind or old process interferes -> health check passes but server is broken
7. page.goto() to localhost:5702 times out (30s default)

**Problem 2: eventlet process tree**

The server uses `eventlet.monkey_patch()` and `flask_socketio.SocketIO` with eventlet async mode. When `process.terminate()` sends SIGTERM, eventlet may:
- Not cleanly shut down all greenlets
- Leave socket file descriptors open
- Spawn child processes (less likely, but eventlet's monkey patching of `subprocess` module is known to cause issues)

**Problem 3: No port-release verification in teardown**

The current teardown code:
```python
# Current teardown (flask_server fixture)
process.terminate()
try:
    process.wait(timeout=5)
except subprocess.TimeoutExpired:
    process.kill()
    process.wait()
```

This code:
- Terminates, waits 5s, kills if still alive -- GOOD
- Does NOT verify the port is actually released -- BAD
- Does NOT kill child processes -- BAD
- The `flask_server_fresh` fixture adds `time.sleep(3)` which is a hack that sometimes works

**Problem 4: No process group management**

The server subprocess is started with `subprocess.Popen(...)` without `start_new_session=True`. This means child processes (if any) are not in a process group that can be killed together. While eventlet typically runs in a single process, the lack of explicit cleanup is a risk.

### Recommended Fix Pattern

```python
import os
import signal
import socket
import subprocess
import time

def _kill_server_and_wait_for_port(process, port, timeout_sec=10):
    """
    Reliably terminate a server subprocess and wait for its port to be released.

    Steps:
    1. Send SIGTERM (graceful shutdown)
    2. Wait up to 5s for process to exit
    3. If still alive, send SIGKILL
    4. Kill entire process group if started with start_new_session
    5. Poll port until it's free (up to timeout_sec)
    """
    # Step 1: Graceful terminate
    try:
        process.terminate()
    except OSError:
        pass  # Already dead

    # Step 2: Wait for exit
    try:
        process.wait(timeout=5)
    except subprocess.TimeoutExpired:
        # Step 3: Force kill
        process.kill()
        process.wait(timeout=5)

    # Step 4: Kill process group (catches child processes)
    try:
        os.killpg(os.getpgid(process.pid), signal.SIGKILL)
    except (OSError, ProcessLookupError):
        pass  # Process group already gone

    # Step 5: Poll until port is free
    deadline = time.monotonic() + timeout_sec
    while time.monotonic() < deadline:
        if _is_port_free(port):
            return
        time.sleep(0.2)

    raise RuntimeError(f"Port {port} still in use after {timeout_sec}s")


def _is_port_free(port):
    """Check if a TCP port is available for binding."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            s.bind(("localhost", port))
            return True
        except OSError:
            return False


def _kill_stale_process_on_port(port):
    """Kill any existing process listening on a port before starting a new server."""
    # Use lsof to find PID (macOS/Linux)
    try:
        result = subprocess.run(
            ["lsof", "-ti", f":{port}"],
            capture_output=True, text=True, timeout=5
        )
        if result.stdout.strip():
            pids = result.stdout.strip().split("\n")
            for pid in pids:
                try:
                    os.kill(int(pid), signal.SIGKILL)
                except (OSError, ValueError):
                    pass
            time.sleep(0.5)  # Brief wait for cleanup
    except (FileNotFoundError, subprocess.TimeoutExpired):
        pass  # lsof not available or timeout
```

### Recommended Project Structure (changes only)

```
tests/
├── conftest.py          # MODIFIED: Add _kill_server_and_wait_for_port helper
│                        # MODIFIED: All 5 fixture variants use shared helper
│                        # MODIFIED: start_new_session=True on Popen calls
│                        # MODIFIED: Pre-startup port cleanup
├── e2e/
│   ├── conftest.py      # No changes needed
│   └── ...              # No test changes needed
└── fixtures/
    └── ...              # No fixture changes needed
```

### Anti-Patterns to Avoid
- **time.sleep(N) as cleanup:** The `flask_server_fresh` already uses `time.sleep(3)` which is unreliable. Replace with port-availability polling.
- **terminate() without port verification:** terminate() alone does not guarantee the port is released. Always verify.
- **Separate kill logic per fixture:** Currently 5 fixture variants each have their own inline teardown. Use a shared helper.

## Don't Hand-Roll

Problems that look simple but have existing solutions:

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Port availability check | Raw socket connect test | `socket.bind()` test with SO_REUSEADDR | connect() can succeed even during TIME_WAIT; bind() is authoritative |
| Process tree kill | Iterating child PIDs | `os.killpg()` with `start_new_session=True` | Process groups handled by OS, no need for PID enumeration |
| Stale process detection | Polling HTTP health | `lsof -ti :PORT` before startup | HTTP health check could pass on stale server; lsof finds actual PIDs |

**Key insight:** The existing server startup code polls HTTP health to confirm readiness, which is correct. But the teardown code only calls terminate/kill without verifying the port is actually freed. The fix is symmetric: just as startup polls for readiness, teardown must poll for port release.

## Common Pitfalls

### Pitfall 1: TCP TIME_WAIT State
**What goes wrong:** After a TCP connection closes, the OS keeps the socket in TIME_WAIT for 2 minutes (on macOS). If a new process tries to bind to the same port during this window, it gets "Address already in use".
**Why it happens:** The OS retains the socket binding to prevent delayed packets from a previous connection being received by a new one.
**How to avoid:** Either (a) use SO_REUSEADDR when binding, or (b) wait for the port to be truly free. Eventlet/Flask-SocketIO may not set SO_REUSEADDR by default.
**Warning signs:** "Address already in use" in server stderr, or server starts but doesn't respond to requests.

### Pitfall 2: Eventlet Greenlet Leaks
**What goes wrong:** `eventlet.monkey_patch()` replaces standard library socket/threading with green versions. When SIGTERM arrives, eventlet's shutdown may not close all green sockets immediately.
**Why it happens:** Eventlet uses cooperative multitasking; greenlets that are blocked on I/O won't get a chance to clean up if the main greenlet exits.
**How to avoid:** Use SIGKILL as fallback after SIGTERM timeout. Verify port is free before considering cleanup complete.
**Warning signs:** `process.wait()` returns (process exited) but port is still bound.

### Pitfall 3: Module-Scoped Fixture Teardown Ordering
**What goes wrong:** Pytest tears down module fixtures in reverse dependency order. If browser context fixtures and server fixtures interact, the browser may try to navigate to a server that's being torn down.
**Why it happens:** The `player_contexts` fixture (function-scoped) depends on `browser` (session-scoped) but not on `flask_server` (module-scoped). Pytest tears down the module fixture (server) at module end, but the session browser persists.
**How to avoid:** Ensure server teardown happens cleanly (process dead, port free) BEFORE yielding control back to pytest. The fix is in the teardown code, not fixture ordering.
**Warning signs:** Page.goto timeout in the FIRST test of a new module (not within a module).

### Pitfall 4: Subprocess stdout/stderr Buffer Deadlock
**What goes wrong:** Server subprocesses are started with `stdout=subprocess.PIPE, stderr=subprocess.PIPE`. If the server writes enough output to fill the OS pipe buffer (typically 64KB), it blocks.
**Why it happens:** The pytest process never reads from the pipes (no `process.communicate()` or `process.stdout.read()`). With module-scoped fixtures running for minutes, the buffer can fill up.
**How to avoid:** Use `subprocess.DEVNULL` instead of `subprocess.PIPE` for stdout/stderr, OR redirect to files. The current code only reads them on crash (`process.communicate()` in the retry loop), but never during normal operation.
**Warning signs:** Server becomes unresponsive mid-test despite process being alive. More likely with verbose server logging.

### Pitfall 5: Process Group Kill Without start_new_session
**What goes wrong:** `os.killpg(os.getpgid(process.pid), signal.SIGKILL)` kills ALL processes in the group, which includes the pytest process itself if `start_new_session=True` was not used.
**Why it happens:** Without `start_new_session=True`, the child process inherits the parent's process group. `killpg` would kill pytest too.
**How to avoid:** Always pass `start_new_session=True` to `subprocess.Popen()` when you intend to use process group operations.
**Warning signs:** The test runner itself is killed when teardown runs.

## Code Examples

Verified patterns from official Python docs and stdlib:

### Port Availability Check
```python
# Source: Python stdlib socket module
import socket

def is_port_free(port: int, host: str = "localhost") -> bool:
    """Check if a TCP port is available for binding."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            s.bind((host, port))
            return True
        except OSError:
            return False
```

### Robust Server Teardown
```python
# Recommended replacement for all fixture teardown code
import os
import signal
import subprocess
import time

def teardown_server(process, port, timeout_sec=10):
    """Kill server process and wait for port release."""
    if process.poll() is not None:
        # Already dead - just verify port
        _wait_for_port_free(port, timeout_sec)
        return

    # Graceful shutdown
    process.terminate()
    try:
        process.wait(timeout=5)
    except subprocess.TimeoutExpired:
        process.kill()
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            pass  # Will be cleaned up by process group kill

    # Kill process group (catches eventlet child greenlets if any forked)
    try:
        os.killpg(os.getpgid(process.pid), signal.SIGKILL)
    except (OSError, ProcessLookupError):
        pass

    _wait_for_port_free(port, timeout_sec)


def _wait_for_port_free(port, timeout_sec=10):
    """Poll until port is available."""
    deadline = time.monotonic() + timeout_sec
    while time.monotonic() < deadline:
        if is_port_free(port):
            return
        time.sleep(0.2)
    # Last resort: try to find and kill any stale process
    _force_kill_on_port(port)
    time.sleep(0.5)
    if not is_port_free(port):
        raise RuntimeError(f"Port {port} still in use after {timeout_sec}s teardown")
```

### Pre-Startup Port Cleanup
```python
def ensure_port_available(port):
    """Kill any stale process on port before starting a new server."""
    if is_port_free(port):
        return

    # Find and kill stale processes
    try:
        result = subprocess.run(
            ["lsof", "-ti", f":{port}"],
            capture_output=True, text=True, timeout=5
        )
        if result.stdout.strip():
            for pid_str in result.stdout.strip().split("\n"):
                try:
                    pid = int(pid_str.strip())
                    os.kill(pid, signal.SIGKILL)
                except (ValueError, OSError):
                    pass
            time.sleep(1)
    except (FileNotFoundError, subprocess.TimeoutExpired):
        pass

    if not is_port_free(port):
        raise RuntimeError(f"Port {port} occupied by unkillable process")
```

### Subprocess with Process Group
```python
# Add start_new_session=True to all Popen calls
process = subprocess.Popen(
    ["python", "-m", "interactive_gym.examples.cogrid.overcooked_human_human_multiplayer_test",
     "--port", str(port)],
    stdout=subprocess.DEVNULL,  # Prevent pipe buffer deadlock
    stderr=subprocess.PIPE,     # Keep stderr for crash diagnostics
    start_new_session=True,     # Enable process group cleanup
)
```

### Updated Fixture Pattern
```python
@pytest.fixture(scope="module")
def flask_server():
    port = 5702
    base_url = f"http://localhost:{port}"

    # Pre-startup cleanup
    ensure_port_available(port)

    # Start server in new session for process group cleanup
    process = subprocess.Popen(
        ["python", "-m",
         "interactive_gym.examples.cogrid.overcooked_human_human_multiplayer_test",
         "--port", str(port)],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE,
        start_new_session=True,
    )

    # Wait for server ready (existing polling logic - keep as-is)
    max_retries = 30
    for attempt in range(max_retries):
        try:
            conn = HTTPConnection("localhost", port, timeout=1)
            conn.request("GET", "/")
            response = conn.getresponse()
            conn.close()
            if response.status < 500:
                break
        except (ConnectionRefusedError, OSError, TimeoutError):
            pass

        if process.poll() is not None:
            stdout = b""
            stderr = process.stderr.read() if process.stderr else b""
            raise RuntimeError(
                f"Flask server exited unexpectedly (code {process.returncode}).\n"
                f"stderr: {stderr.decode()}"
            )
        time.sleep(1)
    else:
        teardown_server(process, port)
        raise RuntimeError(f"Flask server failed to start after {max_retries} retries")

    yield {"url": base_url, "process": process}

    # Teardown with port verification
    teardown_server(process, port)
```

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| terminate() only | terminate() + kill() + port polling | This phase | Eliminates port conflicts |
| PIPE for stdout | DEVNULL for stdout | This phase | Prevents buffer deadlock |
| No pre-startup check | ensure_port_available() | This phase | Handles crashed test runs |
| time.sleep(3) hack | Port availability polling | This phase | Deterministic cleanup |
| Inline teardown per fixture | Shared helper function | This phase | DRY, consistent behavior |

**Deprecated/outdated:**
- `time.sleep(3)` in `flask_server_fresh` teardown: Replace with port polling
- Separate inline teardown in each fixture: Replace with shared `teardown_server()` helper

## Open Questions

Things that couldn't be fully resolved:

1. **Does eventlet socketio.run() set SO_REUSEADDR?**
   - What we know: Flask-SocketIO delegates to eventlet for server creation. Eventlet's `wsgi.server()` typically sets SO_REUSEADDR.
   - What's unclear: Whether the specific code path through `socketio.run()` with eventlet passes this option.
   - Recommendation: Doesn't matter for our fix. We verify port is free regardless. But if server startup itself fails with "Address in use", consider adding `allow_unsafe_werkzeug=True` or configuring the eventlet server.

2. **Can subprocess.PIPE buffer deadlock actually happen?**
   - What we know: The pipe buffer is ~64KB on macOS. Server runs for up to 300s per test module (5 tests * 60s each). If Flask/eventlet is logging to stdout at any rate, it could fill.
   - What's unclear: How verbose the server is in test mode (`app.config["DEBUG"]` is likely False in test config).
   - Recommendation: Switch stdout to DEVNULL as a precaution. Keep stderr as PIPE for crash diagnostics. LOW risk but zero-cost fix.

3. **Is start_new_session needed on macOS?**
   - What we know: On macOS/Linux, `start_new_session=True` creates a new process group. This is needed for `os.killpg()` safety.
   - What's unclear: Whether eventlet ever forks child processes (unlikely for pure async I/O).
   - Recommendation: Use it anyway. It's a safety measure that costs nothing.

## Fixture-by-Fixture Analysis

### Fixtures Needing Fix (ALL server fixtures)

| Fixture | Scope | Port | Used By | Current Teardown | Issue |
|---------|-------|------|---------|-----------------|-------|
| `flask_server` | module | 5702 | 5 modules | terminate+wait(5)+kill | No port verification |
| `flask_server_fresh` | function | 5705 | 2 modules | terminate+wait(5)+kill+sleep(3) | sleep(3) unreliable |
| `flask_server_multi_episode` | module | 5703 | 0 modules (unused?) | terminate+communicate(5)+kill | No port verification |
| `flask_server_multi_episode_fresh` | function | 5706 | 1 module | terminate+wait(5)+kill+sleep(3) | sleep(3) unreliable |
| `flask_server_focus_timeout` | module | 5704 | 1 module | terminate+wait(5)+kill | No port verification |

### Non-Server Fixtures (No Changes Needed)

| Fixture | Scope | Notes |
|---------|-------|-------|
| `browser_type_launch_args` | session | Browser config only |
| `player_contexts` | function | Browser contexts, properly cleaned up |
| `multi_participant_contexts` | function | Browser contexts with WebRTC cleanup, properly cleaned up |

## Sources

### Primary (HIGH confidence)
- Direct code analysis of `tests/conftest.py` (all 5 server fixtures, lines 53-444)
- Direct code analysis of `tests/e2e/*.py` (all 8 test files)
- Direct code analysis of `interactive_gym/server/app.py` (socketio.run configuration)
- Direct code analysis of `interactive_gym/examples/cogrid/overcooked_human_human_multiplayer_test.py` (eventlet.monkey_patch usage)
- Python stdlib documentation for `socket`, `subprocess`, `signal`, `os` modules
- pytest documentation on [fixture scopes](https://docs.pytest.org/en/stable/how-to/fixtures.html) and [teardown](https://docs.pytest.org/en/stable/how-to/fixtures.html#teardown-cleanup-aka-fixture-finalization)

### Secondary (MEDIUM confidence)
- [pytest-dev/pytest#3409](https://github.com/pytest-dev/pytest/issues/3409) - Cleanup code not executing in fixture
- [Baeldung - Close Socket in TIME_WAIT](https://www.baeldung.com/linux/close-socket-time_wait) - TCP TIME_WAIT behavior
- [Flask-SocketIO API Reference](https://flask-socketio.readthedocs.io/en/latest/api.html) - socketio.run() server options
- [Flask-SocketIO Deployment](https://flask-socketio.readthedocs.io/en/latest/deployment.html) - eventlet server behavior

### Tertiary (LOW confidence)
- [eventlet/eventlet#592](https://github.com/eventlet/eventlet/issues/592) - Monkey patching threading issues
- [Flask-SocketIO#1264](https://github.com/miguelgrinberg/Flask-SocketIO/issues/1264) - Monkey patching hangs
- [Real Python - Socket Programming](https://realpython.com/python-sockets/) - SO_REUSEADDR behavior

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH - All stdlib, no new dependencies, direct code analysis
- Architecture: HIGH - Root cause identified through code analysis of fixture lifecycle and port allocation
- Pitfalls: HIGH - TIME_WAIT, buffer deadlock, process groups are well-documented issues
- Fix approach: HIGH - Port polling is a proven pattern; the existing startup code already does health polling

**Research date:** 2026-02-06
**Valid until:** Indefinite (stdlib patterns, not library-version-dependent)
