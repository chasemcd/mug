"""
Smoke test validating test infrastructure works.

This test:
1. Verifies Flask server is running (via flask_server fixture)
2. Verifies two browser contexts can load the game page
3. Does NOT test game logic - just infrastructure
"""

from __future__ import annotations

import pytest


@pytest.mark.timeout(60)
def test_server_starts_and_contexts_connect(flask_server, player_contexts):
    """Verify Flask server runs and two browsers can connect."""
    page1, page2 = player_contexts
    base_url = flask_server["url"]

    # Navigate both players to the game
    page1.goto(base_url)
    page2.goto(base_url)

    # Verify both pages loaded (look for text-container which is always present)
    assert page1.locator(".text-container").is_visible(timeout=10000)
    assert page2.locator(".text-container").is_visible(timeout=10000)

    # Verify server process is still running
    assert flask_server["process"].poll() is None, "Server crashed during test"
