"""
Shared pytest fixtures for interactive-gym tests.

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

import subprocess
import time
from http.client import HTTPConnection

import pytest


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


@pytest.fixture(scope="module")
def flask_server():
    """
    Start Flask server as subprocess before tests, stop after.

    Scope: module (starts once per test module, not per test)
    Yields: dict with 'url' and 'process' keys
    """
    port = 5702
    base_url = f"http://localhost:{port}"

    # Start the Flask server as a subprocess
    # Use test-specific config with relaxed constraints:
    # - No max_rtt limit (allows latency injection)
    # - No focus loss timeout (prevents disconnection)
    # - Shorter episodes (~15s instead of ~45s)
    process = subprocess.Popen(
        [
            "python",
            "-m",
            "interactive_gym.examples.cogrid.overcooked_human_human_multiplayer_test",
            "--port",
            str(port),
        ],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
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
            stdout, stderr = process.communicate()
            raise RuntimeError(
                f"Flask server exited unexpectedly (code {process.returncode}).\n"
                f"stdout: {stdout.decode()}\n"
                f"stderr: {stderr.decode()}"
            )

        time.sleep(1)
    else:
        # Max retries exceeded
        process.terminate()
        process.wait(timeout=5)
        raise RuntimeError(
            f"Flask server failed to start after {max_retries} retries"
        )

    yield {"url": base_url, "process": process}

    # Teardown: stop the server
    process.terminate()
    try:
        process.wait(timeout=5)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait()


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
        # Cleanup: close all contexts even on error
        for ctx in contexts:
            try:
                ctx.close()
            except Exception:
                pass
