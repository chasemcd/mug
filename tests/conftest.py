"""
Shared pytest fixtures for mug tests.

Provides:
- flask_server: Module-scoped fixture that starts/stops the Flask server
- browser_type_launch_args: Override browser launch args for WebRTC compatibility
- player_contexts: Function-scoped fixture providing two isolated browser contexts

IMPORTANT: E2E tests using WebRTC require HEADED mode!
WebRTC peer connections fail in headless Chromium due to ICE candidate
gathering limitations. Run E2E tests with:

    pytest tests/e2e/ --headed

Or set PWHEADED=1 environment variable.
"""

from __future__ import annotations

import os
import signal
import socket
import subprocess
import time
from http.client import HTTPConnection

import pytest

# ---------------------------------------------------------------------------
# Shared server lifecycle helpers
# ---------------------------------------------------------------------------


def _is_port_free(port):
    """
    Check if a TCP port is available for binding.

    Uses socket.bind() with SO_REUSEADDR as the authoritative check.
    A connect-based check can succeed during TCP TIME_WAIT, giving false
    negatives. Binding is the definitive test.
    """
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            s.bind(("localhost", port))
            return True
        except OSError:
            return False


def _ensure_port_available(port):
    """
    Ensure a port is available before starting a server.

    If the port is already free, returns immediately (common case).
    Otherwise, uses lsof to find stale PIDs and kills them.
    Raises RuntimeError if the port cannot be freed.
    """
    if _is_port_free(port):
        return

    # Port is occupied -- find and kill stale processes
    try:
        result = subprocess.run(
            ["lsof", "-ti", f":{port}"],
            capture_output=True,
            text=True,
            timeout=5,
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

    if not _is_port_free(port):
        raise RuntimeError(f"Port {port} occupied by unkillable process")


def _wait_for_port_free(port, timeout_sec=10):
    """
    Poll until a port is free, with last-resort stale process cleanup.

    Polls _is_port_free every 0.2s until the deadline. If the port is still
    occupied after timeout, calls _ensure_port_available as a last resort
    to kill any stale processes.
    """
    deadline = time.monotonic() + timeout_sec
    while time.monotonic() < deadline:
        if _is_port_free(port):
            return
        time.sleep(0.2)

    # Last resort: kill stale processes
    _ensure_port_available(port)
    time.sleep(0.5)

    if not _is_port_free(port):
        raise RuntimeError(
            f"Port {port} still in use after {timeout_sec}s teardown"
        )


def _teardown_server(process, port, timeout_sec=10):
    """
    Reliably terminate a server subprocess and wait for its port to be released.

    Steps:
    1. If process already dead, just wait for port release
    2. Send SIGTERM (graceful shutdown)
    3. Wait up to 5s for process to exit
    4. If still alive, send SIGKILL
    5. Kill entire process group (catches eventlet child greenlets)
    6. Poll port until free
    """
    if process.poll() is not None:
        # Already dead -- just verify port is released
        _wait_for_port_free(port, timeout_sec)
        return

    # Graceful terminate
    try:
        process.terminate()
    except OSError:
        pass

    # Wait for exit
    try:
        process.wait(timeout=5)
    except subprocess.TimeoutExpired:
        # Force kill
        process.kill()
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            pass

    # Kill process group (catches child processes started with start_new_session)
    try:
        os.killpg(os.getpgid(process.pid), signal.SIGKILL)
    except (OSError, ProcessLookupError):
        pass

    _wait_for_port_free(port, timeout_sec)


# ---------------------------------------------------------------------------
# Browser launch configuration
# ---------------------------------------------------------------------------


@pytest.fixture(scope="session")
def browser_type_launch_args(browser_type_launch_args):
    """
    Override browser launch arguments for WebRTC to work between isolated contexts.

    The key flags are:
    - --disable-features=WebRtcHideLocalIpsWithMdns: Use actual local IPs instead of
      mDNS .local addresses which don't resolve between isolated browser contexts
    - --use-fake-ui-for-media-stream: Auto-approve media permissions
    - --allow-insecure-localhost: Allow WebRTC on localhost

    This properly extends pytest-playwright's browser_type_launch_args fixture.
    See: https://playwright.dev/python/docs/test-runners
    """
    return {
        **browser_type_launch_args,
        "args": [
            # Disable mDNS ICE candidates - use actual local IPs instead
            # Without this, ICE candidates use unresolvable .local addresses
            "--disable-features=WebRtcHideLocalIpsWithMdns",
            # Auto-approve media permissions (avoids permission dialogs)
            "--use-fake-ui-for-media-stream",
            # Allow insecure localhost for WebRTC (useful for testing)
            "--allow-insecure-localhost",
        ],
    }


# ---------------------------------------------------------------------------
# Server fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(scope="function")
def flask_server():
    """
    Start Flask server as subprocess before each test, stop after.

    Scope: function (fresh server per test for isolation)
    Yields: dict with 'url' and 'process' keys

    Uses robust startup/teardown:
    - Pre-startup port cleanup via _ensure_port_available
    - Process group isolation via start_new_session=True
    - stdout=DEVNULL to prevent pipe buffer deadlock
    - Port-verified teardown via _teardown_server
    """
    port = 5702
    base_url = f"http://localhost:{port}"

    # Pre-startup: ensure port is available (kill stale processes if needed)
    _ensure_port_available(port)

    # Start the Flask server as a subprocess
    # Use test-specific config with relaxed constraints:
    # - No max_rtt limit (allows latency injection)
    # - No focus loss timeout (prevents disconnection)
    # - Shorter episodes (~15s instead of ~45s)
    process = subprocess.Popen(
        [
            "python",
            "-m",
            "tests.fixtures.overcooked_human_human_multiplayer_test",
            "--port",
            str(port),
        ],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE,
        start_new_session=True,
    )

    # Wait for server to be ready (poll health endpoint)
    max_retries = 30
    for attempt in range(max_retries):
        try:
            conn = HTTPConnection("localhost", port, timeout=1)
            conn.request("GET", "/")
            response = conn.getresponse()
            conn.close()
            if response.status < 500:
                # Server is responding
                break
        except (ConnectionRefusedError, OSError, TimeoutError):
            pass

        # Check if process crashed
        if process.poll() is not None:
            stderr = process.stderr.read() if process.stderr else b""
            raise RuntimeError(
                f"Flask server exited unexpectedly (code {process.returncode}).\n"
                f"stderr: {stderr.decode()}"
            )

        time.sleep(1)
    else:
        # Max retries exceeded
        _teardown_server(process, port)
        raise RuntimeError(
            f"Flask server failed to start after {max_retries} retries"
        )

    yield {"url": base_url, "process": process}

    # Teardown: stop the server with port verification
    _teardown_server(process, port)


@pytest.fixture(scope="function")
def flask_server_fresh():
    """
    Start Flask server as subprocess for each test function.

    Scope: function (fresh server per test for test isolation)
    Yields: dict with 'url' and 'process' keys

    Use this fixture for multi-participant stress tests that require
    clean server state between tests. The module-scoped flask_server
    can accumulate state that causes later tests to fail.

    Uses robust startup/teardown:
    - Pre-startup port cleanup via _ensure_port_available
    - Process group isolation via start_new_session=True
    - stdout=DEVNULL to prevent pipe buffer deadlock
    - Port-verified teardown via _teardown_server (replaces sleep-based hack)
    """
    port = 5705  # Different port from other fixtures to avoid conflicts
    base_url = f"http://localhost:{port}"

    # Pre-startup: ensure port is available
    _ensure_port_available(port)

    # Start the Flask server as a subprocess
    process = subprocess.Popen(
        [
            "python",
            "-m",
            "tests.fixtures.overcooked_human_human_multiplayer_test",
            "--port",
            str(port),
        ],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE,
        start_new_session=True,
    )

    # Wait for server to be ready (poll health endpoint)
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
            stderr = process.stderr.read() if process.stderr else b""
            raise RuntimeError(
                f"Flask server exited unexpectedly (code {process.returncode}).\n"
                f"stderr: {stderr.decode()}"
            )

        time.sleep(1)
    else:
        _teardown_server(process, port)
        raise RuntimeError(
            f"Flask server failed to start after {max_retries} retries"
        )

    yield {"url": base_url, "process": process}

    # Teardown: stop the server with port verification (no more sleep-based hack)
    _teardown_server(process, port)


@pytest.fixture(scope="function")
def player_contexts(browser):
    """
    Create two isolated browser contexts for multiplayer testing.

    Scope: function (fresh contexts for each test)
    Yields: tuple of (page1, page2)

    Note: Uses a Chrome user agent to pass browser entry screening.
    Headless Chromium reports as "Chrome Headless" which may fail
    browser allowlist checks that only permit "Chrome".
    """
    # Use a standard Chrome user agent to pass browser entry screening
    # Headless Chrome reports as "Chrome Headless" which may fail allowlists
    chrome_ua = (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    )

    # Create two isolated browser contexts with Chrome user agent
    context1 = browser.new_context(user_agent=chrome_ua)
    context2 = browser.new_context(user_agent=chrome_ua)

    # Create a page in each context
    page1 = context1.new_page()
    page2 = context2.new_page()

    yield (page1, page2)

    # Teardown: close contexts
    context1.close()
    context2.close()


@pytest.fixture(scope="function")
def flask_server_scene_isolation():
    """
    Start Flask server for scene isolation testing.

    Scope: function (fresh server per test for clean state)
    Yields: dict with 'url' and 'process' keys

    Uses overcooked_human_human_multiplayer_scene_isolation_test config with:
    - Multi-scene flow: StartScene -> GymScene -> FeedbackScene -> EndScene
    - No RTT limit, no focus timeout, single short episode
    - Port 5707 (different from other test ports)

    Uses robust startup/teardown:
    - Pre-startup port cleanup via _ensure_port_available
    - Process group isolation via start_new_session=True
    - stdout=DEVNULL to prevent pipe buffer deadlock
    - Port-verified teardown via _teardown_server
    """
    port = 5707
    base_url = f"http://localhost:{port}"

    # Pre-startup: ensure port is available
    _ensure_port_available(port)

    process = subprocess.Popen(
        [
            "python",
            "-m",
            "tests.fixtures.overcooked_human_human_multiplayer_scene_isolation_test",
            "--port",
            str(port),
        ],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE,
        start_new_session=True,
    )

    # Wait for server to be ready (poll health endpoint)
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
            stderr = process.stderr.read() if process.stderr else b""
            raise RuntimeError(
                f"Scene isolation Flask server exited unexpectedly (code {process.returncode}).\n"
                f"stderr: {stderr.decode()}"
            )

        time.sleep(1)
    else:
        _teardown_server(process, port)
        raise RuntimeError(
            f"Scene isolation Flask server failed to start after {max_retries} retries"
        )

    yield {"url": base_url, "process": process}

    # Teardown with port verification
    _teardown_server(process, port)


@pytest.fixture(scope="function")
def flask_server_multi_episode_fresh():
    """
    Start multi-episode Flask server as subprocess for each test function.

    Scope: function (fresh server per test for test isolation)
    Yields: dict with 'url', 'process', 'num_episodes', 'experiment_id' keys

    Use this fixture for lifecycle stress tests that require clean server state.

    Uses robust startup/teardown:
    - Pre-startup port cleanup via _ensure_port_available
    - Process group isolation via start_new_session=True
    - stdout=DEVNULL to prevent pipe buffer deadlock
    - Port-verified teardown via _teardown_server (replaces sleep-based hack)
    """
    port = 5706  # Different port for fresh multi-episode server
    base_url = f"http://localhost:{port}"

    # Pre-startup: ensure port is available
    _ensure_port_available(port)

    process = subprocess.Popen(
        [
            "python",
            "-m",
            "tests.fixtures.overcooked_human_human_multiplayer_multi_episode_test",
            "--port",
            str(port),
        ],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE,
        start_new_session=True,
    )

    # Wait for server to be ready
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
            stderr = process.stderr.read() if process.stderr else b""
            raise RuntimeError(
                f"Multi-episode Flask server exited unexpectedly (code {process.returncode}).\n"
                f"stderr: {stderr.decode()}"
            )

        time.sleep(1)
    else:
        _teardown_server(process, port)
        raise RuntimeError(
            f"Multi-episode Flask server failed to start after {max_retries} retries"
        )

    yield {
        "url": base_url,
        "process": process,
        "num_episodes": 2,
        "experiment_id": "overcooked_multiplayer_hh_multi_episode_test",
    }

    # Teardown with port verification (no more sleep-based hack)
    _teardown_server(process, port)


@pytest.fixture(scope="module")
def flask_server_focus_timeout():
    """
    Start focus timeout Flask server as subprocess before tests, stop after.

    Scope: module (starts once per test module, not per test)
    Yields: dict with 'url', 'process', 'focus_timeout_ms' keys

    Uses overcooked_human_human_multiplayer_focus_timeout_test config with:
    - focus_loss_config(timeout_ms=10000) for 10 second focus timeout
    - No RTT limit, single episode
    - Port 5704 (different from other test ports)

    Uses robust startup/teardown:
    - Pre-startup port cleanup via _ensure_port_available
    - Process group isolation via start_new_session=True
    - stdout=DEVNULL to prevent pipe buffer deadlock
    - Port-verified teardown via _teardown_server
    """
    port = 5704
    base_url = f"http://localhost:{port}"

    # Pre-startup: ensure port is available
    _ensure_port_available(port)

    process = subprocess.Popen(
        [
            "python",
            "-m",
            "tests.fixtures.overcooked_human_human_multiplayer_focus_timeout_test",
            "--port",
            str(port),
        ],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE,
        start_new_session=True,
    )

    # Wait for server to be ready (poll health endpoint)
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
            stderr = process.stderr.read() if process.stderr else b""
            raise RuntimeError(
                f"Focus timeout Flask server exited unexpectedly (code {process.returncode}).\n"
                f"stderr: {stderr.decode()}"
            )

        time.sleep(1)
    else:
        _teardown_server(process, port)
        raise RuntimeError(
            f"Focus timeout Flask server failed to start after {max_retries} retries"
        )

    yield {"url": base_url, "process": process, "focus_timeout_ms": 10000}

    # Teardown with port verification
    _teardown_server(process, port)


# ---------------------------------------------------------------------------
# Browser context fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(scope="function")
def multi_participant_contexts(browser):
    """
    Create 6 isolated browser contexts for multi-participant stress testing.

    Scope: function (fresh contexts for each test)
    Yields: tuple of 6 pages (page1, page2, page3, page4, page5, page6)

    Intended grouping: (page1, page2) = Game 1, (page3, page4) = Game 2, (page5, page6) = Game 3

    Note: Uses standard Chrome user agent to pass browser entry screening.
    Browser contexts are lightweight (KB not MB) so 6 contexts per browser is safe.
    """
    chrome_ua = (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    )

    contexts = []
    pages = []

    try:
        for i in range(6):
            ctx = browser.new_context(user_agent=chrome_ua)
            page = ctx.new_page()
            contexts.append(ctx)
            pages.append(page)

        yield tuple(pages)

    finally:
        # Cleanup: close WebRTC connections before closing contexts
        # This ensures cleaner teardown and prevents resource leaks
        for page in pages:
            try:
                # Close any active WebRTC connections
                page.evaluate("""() => {
                    // Close WebRTC peer connections
                    if (window.webrtcManager && window.webrtcManager.peerConnection) {
                        window.webrtcManager.peerConnection.close();
                    }
                    // Close probe connections if any
                    if (window.probeConnection && window.probeConnection.peerConnection) {
                        window.probeConnection.peerConnection.close();
                    }
                    // Disconnect socket
                    if (window.socket && window.socket.connected) {
                        window.socket.disconnect();
                    }
                }""")
            except Exception:
                pass  # Page may already be closed

        # Close all contexts
        for ctx in contexts:
            try:
                ctx.close()
            except Exception:
                pass

        # Pause to allow server-side cleanup to process disconnect events
        # This is critical for test isolation - ensures all WebRTC connections
        # are fully cleaned up before next test starts
        time.sleep(5)


@pytest.fixture(scope="function")
def flask_server_probe(tmp_path):
    """
    Start Flask server with P2P probe-enabled matchmaking for each test function.

    Scope: function (fresh server per test for isolation)
    Yields: dict with 'url', 'process', and 'stderr_path' keys

    Uses overcooked_human_human_multiplayer_probe_test config with:
    - FIFOMatchmaker(max_p2p_rtt_ms=100) for P2P RTT probing
    - No RTT limit, no focus timeout, single short episode
    - Port 5708 (different from other test ports)

    stderr is written to a temp file (not subprocess.PIPE) to avoid pipe buffer
    deadlock when 12+ clients generate heavy log output. Tests that need to parse
    [Probe:Track] lines can read from stderr_path after the server is stopped.
    """
    port = 5708
    base_url = f"http://localhost:{port}"

    # Pre-startup: ensure port is available
    _ensure_port_available(port)

    # Write stderr to a file to avoid pipe buffer deadlock with 12+ clients
    stderr_file_path = tmp_path / "server_stderr.log"
    stderr_fh = open(stderr_file_path, "w")

    process = subprocess.Popen(
        [
            "python",
            "-m",
            "tests.fixtures.overcooked_human_human_multiplayer_probe_test",
            "--port",
            str(port),
        ],
        stdout=subprocess.DEVNULL,
        stderr=stderr_fh,
        start_new_session=True,
    )

    # Wait for server to be ready (poll health endpoint)
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
            stderr_fh.close()
            stderr_content = stderr_file_path.read_text()
            raise RuntimeError(
                f"Probe Flask server exited unexpectedly (code {process.returncode}).\n"
                f"stderr: {stderr_content}"
            )

        time.sleep(1)
    else:
        stderr_fh.close()
        _teardown_server(process, port)
        raise RuntimeError(
            f"Probe Flask server failed to start after {max_retries} retries"
        )

    yield {"url": base_url, "process": process, "stderr_path": stderr_file_path}

    # Teardown with port verification
    _teardown_server(process, port)
    stderr_fh.close()


@pytest.fixture(scope="function")
def stress_test_contexts(browser):
    """
    Create 12 isolated browser contexts for waitroom stress testing.

    Scope: function (fresh contexts for each test)
    Yields: tuple of 12 pages

    Intended grouping: 6 pairs for probe-based matchmaking stress tests.

    Note: Uses standard Chrome user agent to pass browser entry screening.
    Browser contexts are lightweight (KB not MB) so 12 contexts per browser is safe.
    """
    chrome_ua = (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    )

    contexts = []
    pages = []

    try:
        for i in range(12):
            ctx = browser.new_context(user_agent=chrome_ua)
            page = ctx.new_page()
            contexts.append(ctx)
            pages.append(page)

        yield tuple(pages)

    finally:
        # Cleanup: close WebRTC connections before closing contexts
        for page in pages:
            try:
                page.evaluate("""() => {
                    // Close WebRTC peer connections
                    if (window.webrtcManager && window.webrtcManager.peerConnection) {
                        window.webrtcManager.peerConnection.close();
                    }
                    // Close probe connections if any
                    if (window.probeConnection && window.probeConnection.peerConnection) {
                        window.probeConnection.peerConnection.close();
                    }
                    // Disconnect socket
                    if (window.socket && window.socket.connected) {
                        window.socket.disconnect();
                    }
                }""")
            except Exception:
                pass  # Page may already be closed

        # Close all contexts
        for ctx in contexts:
            try:
                ctx.close()
            except Exception:
                pass

        # Pause to allow server-side cleanup to process disconnect events
        time.sleep(5)


# ---------------------------------------------------------------------------
# Human-AI (ONNX inference) fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(scope="function")
def flask_server_human_ai():
    """
    Start Flask server for human-AI ONNX inference testing.

    Scope: function (fresh server per test for clean state)
    Yields: dict with 'url' and 'process' keys

    Uses overcooked_human_ai_test config with:
    - Single human + ONNX AI partner (cramped_room_sp_0 with ModelConfig)
    - Short episode (200 steps)
    - No tutorial, no feedback
    - Port 5709 (different from other test ports)
    """
    port = 5709
    base_url = f"http://localhost:{port}"

    _ensure_port_available(port)

    process = subprocess.Popen(
        [
            "python",
            "-m",
            "tests.fixtures.overcooked_human_ai_test",
            "--port",
            str(port),
        ],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE,
        start_new_session=True,
    )

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
            stderr = process.stderr.read() if process.stderr else b""
            raise RuntimeError(
                f"Human-AI Flask server exited unexpectedly (code {process.returncode}).\n"
                f"stderr: {stderr.decode()}"
            )

        time.sleep(1)
    else:
        _teardown_server(process, port)
        raise RuntimeError(
            f"Human-AI Flask server failed to start after {max_retries} retries"
        )

    yield {"url": base_url, "process": process}

    _teardown_server(process, port)


@pytest.fixture(scope="function")
def flask_server_auth():
    """
    Start Flask server for server-authoritative E2E testing.

    Scope: function (fresh server per test for clean state)
    Yields: dict with 'url' and 'process' keys

    Uses overcooked_server_auth_test config with:
    - Server-authoritative mode (no Pyodide/P2P)
    - Short episode (200 steps, ~7 seconds at 30fps)
    - Single episode, no focus timeout
    - Port 5710 (different from other test ports: 5702-5709)

    Uses robust startup/teardown:
    - Pre-startup port cleanup via _ensure_port_available
    - Process group isolation via start_new_session=True
    - stdout=DEVNULL to prevent pipe buffer deadlock
    - Port-verified teardown via _teardown_server
    """
    port = 5710
    base_url = f"http://localhost:{port}"

    _ensure_port_available(port)

    process = subprocess.Popen(
        [
            "python",
            "-m",
            "tests.fixtures.overcooked_server_auth_test",
            "--port",
            str(port),
        ],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE,
        start_new_session=True,
    )

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
            stderr = process.stderr.read() if process.stderr else b""
            raise RuntimeError(
                f"Server-auth Flask server exited unexpectedly (code {process.returncode}).\n"
                f"stderr: {stderr.decode()}"
            )

        time.sleep(1)
    else:
        _teardown_server(process, port)
        raise RuntimeError(
            f"Server-auth Flask server failed to start after {max_retries} retries"
        )

    yield {"url": base_url, "process": process}

    _teardown_server(process, port)


@pytest.fixture(scope="function")
def single_player_context(browser):
    """
    Create a single browser context for human-AI testing.

    Scope: function (fresh context for each test)
    Yields: page

    No WebRTC needed (only one human player), just Chrome UA for screening.
    """
    chrome_ua = (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    )

    context = browser.new_context(user_agent=chrome_ua)
    page = context.new_page()

    yield page

    context.close()
