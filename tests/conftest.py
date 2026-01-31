"""
Shared pytest fixtures for interactive-gym tests.

Provides:
- flask_server: Module-scoped fixture that starts/stops the Flask server
- player_contexts: Function-scoped fixture providing two isolated browser contexts
"""

import subprocess
import time
from http.client import HTTPConnection

import pytest


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
    process = subprocess.Popen(
        [
            "python",
            "-m",
            "interactive_gym.examples.cogrid.overcooked_human_human_multiplayer",
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
    """
    # Create two isolated browser contexts
    context1 = browser.new_context()
    context2 = browser.new_context()

    # Create a page in each context
    page1 = context1.new_page()
    page2 = context2.new_page()

    yield (page1, page2)

    # Teardown: close contexts
    context1.close()
    context2.close()
