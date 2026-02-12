"""
E2E test configuration - automatically enables headed mode.

E2E tests using WebRTC REQUIRE headed mode because:
1. Playwright's headless mode sets document.hidden=true
2. FocusManager skips frame processing when document is hidden
3. This causes game loops to never progress

This conftest.py uses pytest-playwright's --headed option by default.
"""


from __future__ import annotations


def pytest_configure(config):
    """Force headed mode for E2E tests."""
    # Only set if not explicitly provided by user
    if not config.getoption("headed", default=False):
        # Use the internal playwright option
        config.option.headed = True
