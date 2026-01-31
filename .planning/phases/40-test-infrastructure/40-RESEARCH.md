# Phase 40: Test Infrastructure Foundation - Research

**Researched:** 2026-01-30
**Domain:** E2E Testing with Playwright for Multiplayer Games
**Confidence:** HIGH

## Summary

This phase establishes Playwright-based test infrastructure for automating multiplayer game sessions in interactive-gym. The key challenges are:

1. **Dual browser contexts** - Testing multiplayer requires two independent browser sessions connecting to the same game
2. **Flask server lifecycle** - Tests must manage starting/stopping the Flask+SocketIO server
3. **Game automation** - Simulating user interactions through matchmaking and gameplay to completion

Playwright Python with pytest-playwright provides the foundation. Browser contexts enable isolated user sessions, and subprocess management with health checks handles server lifecycle. The project has no existing test infrastructure, so this will be greenfield.

**Primary recommendation:** Use pytest-playwright with custom fixtures for dual-context management and Flask server subprocess lifecycle.

## Standard Stack

The established libraries/tools for this domain:

### Core
| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| playwright | 1.49+ | Browser automation | Official Microsoft browser testing tool, CDP access |
| pytest-playwright | 0.6+ | pytest integration | Official Playwright pytest plugin with fixtures |
| pytest | 8.0+ | Test framework | Standard Python test framework |

### Supporting
| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| pytest-timeout | 2.3+ | Test timeouts | Prevent hanging tests |
| python-slugify | 8.0+ | Filename generation | Screenshot naming on failure |

### Alternatives Considered
| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| pytest-playwright | Raw playwright API | Less boilerplate, but no fixture system |
| subprocess Flask | pytest-flask live_server | pytest-flask has known hang issues with Playwright teardown |

**Installation:**
```bash
pip install pytest playwright pytest-playwright pytest-timeout python-slugify
playwright install chromium
```

## Architecture Patterns

### Recommended Project Structure
```
tests/
├── conftest.py              # Shared fixtures (server, dual contexts)
├── e2e/
│   ├── __init__.py
│   ├── test_multiplayer_basic.py   # Phase 40 tests
│   ├── test_latency.py             # Phase 41 tests
│   ├── test_disruption.py          # Phase 42 tests
│   └── test_data_comparison.py     # Phase 43 tests
└── fixtures/
    └── game_helpers.py      # Game automation utilities
```

### Pattern 1: Dual Browser Context for Multiplayer
**What:** Two isolated browser contexts representing two players
**When to use:** Any multiplayer game test
**Example:**
```python
# Source: https://playwright.dev/python/docs/browser-contexts
import pytest
from playwright.sync_api import Browser

@pytest.fixture
def player_contexts(browser: Browser):
    """Create two isolated browser contexts for multiplayer testing."""
    context1 = browser.new_context()
    context2 = browser.new_context()

    page1 = context1.new_page()
    page2 = context2.new_page()

    yield page1, page2

    context1.close()
    context2.close()
```

### Pattern 2: Flask Server Subprocess with Health Check
**What:** Start Flask server before tests, poll for readiness, teardown after
**When to use:** E2E tests requiring the full server
**Example:**
```python
# Source: https://til.simonwillison.net/pytest/subprocess-server
import pytest
import subprocess
import time
from http.client import HTTPConnection

@pytest.fixture(scope="session")
def flask_server():
    """Start Flask server in subprocess with health check."""
    process = subprocess.Popen(
        ["python", "-m", "interactive_gym.examples.cogrid.overcooked_human_human_multiplayer", "--port", "5702"],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )

    # Poll for server readiness
    base_url = "localhost:5702"
    retries = 30  # 30 seconds max
    while retries > 0:
        try:
            conn = HTTPConnection(base_url, timeout=1)
            conn.request("HEAD", "/")
            response = conn.getresponse()
            if response.status < 500:
                break
        except (ConnectionRefusedError, OSError):
            pass
        time.sleep(1)
        retries -= 1

    if retries == 0:
        process.terminate()
        raise RuntimeError("Flask server failed to start")

    yield {"url": f"http://{base_url}", "process": process}

    process.terminate()
    process.wait(timeout=5)
```

### Pattern 3: Wait for WebSocket Connection
**What:** Wait for SocketIO connection before proceeding with game automation
**When to use:** After page load, before game interactions
**Example:**
```python
def wait_for_socket_connected(page, timeout=10000):
    """Wait for SocketIO connection to be established."""
    # Wait for the socket.connected property to be true
    page.wait_for_function(
        "() => window.socket && window.socket.connected",
        timeout=timeout
    )
```

### Pattern 4: Wait for Game State
**What:** Wait for specific game state elements before proceeding
**When to use:** Waiting for matchmaking completion, game start, episode end
**Example:**
```python
def wait_for_game_start(page, timeout=60000):
    """Wait for game canvas to become visible (game started)."""
    page.wait_for_selector("#phaser-game canvas", state="visible", timeout=timeout)

def wait_for_episode_complete(page, timeout=120000):
    """Wait for episode completion overlay or state."""
    page.wait_for_function(
        "() => window.pyodideMultiplayerGame && window.pyodideMultiplayerGame.isEpisodeComplete()",
        timeout=timeout
    )
```

### Anti-Patterns to Avoid
- **Single context for multiplayer:** Creates shared state between players, breaks test validity
- **Fixed sleep instead of polling:** Unreliable, slow tests - always use explicit waits
- **pytest-flask live_server with Playwright:** Known hang issues on teardown, use subprocess instead
- **Relying on Page Visibility API:** `visibilitychange` events don't fire in Playwright (known limitation)

## Don't Hand-Roll

Problems that look simple but have existing solutions:

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Browser automation | Custom Selenium scripts | Playwright | Modern, auto-wait, CDP access |
| Multiple user sessions | Cookie manipulation | Browser contexts | True isolation, official pattern |
| Server health checks | Simple time.sleep() | HTTPConnection polling | Reliable, fast when server ready |
| Test fixtures | Manual setup/teardown | pytest fixtures | Proper scoping, cleanup guarantees |
| Network throttling | Custom proxy | CDP Network.emulateNetworkConditions | Built into browser, accurate |

**Key insight:** Playwright provides primitives for all multiplayer test scenarios. The complexity is in orchestrating them correctly, not building custom tooling.

## Common Pitfalls

### Pitfall 1: Async Requests Not Completing Before Test End
**What goes wrong:** Test ends while browser has pending async operations (SocketIO messages, data export)
**Why it happens:** Playwright closes context immediately when test ends
**How to avoid:** Add explicit waits for network requests or state changes before test completion
**Warning signs:** Flaky tests that pass when run slowly, fail in CI

### Pitfall 2: Server Port Conflicts
**What goes wrong:** Multiple test runs or leftover processes occupy the port
**Why it happens:** Previous test run didn't clean up properly
**How to avoid:** Use dynamic port allocation or ensure cleanup with terminate() + wait()
**Warning signs:** "Address already in use" errors on test startup

### Pitfall 3: Page Visibility API Doesn't Work in Playwright
**What goes wrong:** Tests for tab focus/unfocus scenarios don't trigger visibilitychange events
**Why it happens:** Known Playwright limitation - all pages are considered "visible"
**How to avoid:** For Phase 42 (tab unfocus tests), use CDP to inject events or evaluate JavaScript directly
**Warning signs:** Focus loss timeout never triggers in tests

### Pitfall 4: pytest-flask + Playwright Teardown Hang
**What goes wrong:** Tests hang indefinitely during teardown
**Why it happens:** Interaction between pytest-flask's live_server fixture and Playwright's cleanup
**How to avoid:** Use subprocess-based server fixture instead of pytest-flask
**Warning signs:** Tests complete but pytest doesn't exit

### Pitfall 5: Race Conditions in Multiplayer Matchmaking
**What goes wrong:** One player connects before the other, leading to timeout or wrong state
**Why it happens:** Parallel navigation without synchronization
**How to avoid:** Use barriers or sequential navigation with explicit state checks
**Warning signs:** "Partner not found" or matchmaking timeouts in tests

## Code Examples

Verified patterns from official sources:

### Creating CDP Session for Network Control
```python
# Source: https://playwright.dev/python/docs/api/class-cdpsession
async def setup_network_throttling(page, latency_ms: int):
    """Configure network latency via CDP."""
    client = await page.context.new_cdp_session(page)
    await client.send("Network.enable")
    await client.send("Network.emulateNetworkConditions", {
        "offline": False,
        "downloadThroughput": -1,  # No limit
        "uploadThroughput": -1,    # No limit
        "latency": latency_ms,
    })
    return client
```

### Synchronous Dual-Context Navigation
```python
# Source: https://playwright.dev/python/docs/browser-contexts
def test_multiplayer_connection(player_contexts, flask_server):
    page1, page2 = player_contexts
    base_url = flask_server["url"]

    # Navigate both players to the game
    page1.goto(f"{base_url}/player1-uuid")
    page2.goto(f"{base_url}/player2-uuid")

    # Wait for both to establish socket connections
    wait_for_socket_connected(page1)
    wait_for_socket_connected(page2)

    # Progress through start scene
    page1.click("button:has-text('Continue')")
    page2.click("button:has-text('Continue')")

    # Wait for both to reach waitroom
    page1.wait_for_selector(".waitroom-status")
    page2.wait_for_selector(".waitroom-status")
```

### Complete Test Structure Example
```python
import pytest
from playwright.sync_api import Browser, Page

@pytest.fixture(scope="module")
def flask_server():
    """Start Flask server for test module."""
    # ... server startup code ...
    yield server_info
    # ... cleanup ...

@pytest.fixture
def player_contexts(browser: Browser):
    """Create two isolated player contexts."""
    ctx1 = browser.new_context()
    ctx2 = browser.new_context()
    yield ctx1.new_page(), ctx2.new_page()
    ctx1.close()
    ctx2.close()

def test_two_players_can_complete_game(player_contexts, flask_server):
    """Verify two players can connect and complete a game session."""
    page1, page2 = player_contexts

    # Connect both players
    page1.goto(flask_server["url"])
    page2.goto(flask_server["url"])

    # Wait for game start (matchmaking complete)
    page1.wait_for_selector("#phaser-game canvas", timeout=60000)
    page2.wait_for_selector("#phaser-game canvas", timeout=60000)

    # Let game run (players idle, game will timeout or complete)
    page1.wait_for_function(
        "() => window.pyodideMultiplayerGame?.isGameComplete?.()",
        timeout=180000
    )

    # Verify both players reached completion
    assert page1.evaluate("() => window.pyodideMultiplayerGame.isGameComplete()")
    assert page2.evaluate("() => window.pyodideMultiplayerGame.isGameComplete()")
```

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| Selenium WebDriver | Playwright | 2020+ | Faster, more reliable, CDP access |
| pytest-flask live_server | Subprocess server | 2024 | Avoids hang issues with Playwright |
| Sleep-based waits | Auto-wait + explicit conditions | 2020+ | Faster, more reliable tests |
| Single browser instance | Browser contexts | Always | True isolation for multiplayer |

**Deprecated/outdated:**
- Selenium for new projects: Playwright is faster and has better API
- pytest-flask with Playwright: Known compatibility issues

## Open Questions

Things that couldn't be fully resolved:

1. **Page Visibility API in Playwright**
   - What we know: visibilitychange events don't fire in Playwright (known bug #22634)
   - What's unclear: Best workaround for Phase 42 tab unfocus tests
   - Recommendation: Use JavaScript evaluation to directly set document.hidden and dispatch events, or skip actual visibility and test the app's response via mocked events

2. **Optimal Wait Strategy for Game States**
   - What we know: Need to wait for SocketIO connection, matchmaking, game start
   - What's unclear: Best selectors/functions for interactive-gym's specific UI elements
   - Recommendation: Inspect actual game page to identify reliable wait targets

3. **Episode Completion Detection**
   - What we know: Need to detect when episode ends and data is exported
   - What's unclear: Exact JavaScript API exposed by pyodideMultiplayerGame
   - Recommendation: Review pyodide_multiplayer_game.js for exposed methods

## Sources

### Primary (HIGH confidence)
- [Playwright Python Browser Contexts](https://playwright.dev/python/docs/browser-contexts) - Isolation, multi-context examples
- [Playwright Python CDP Session](https://playwright.dev/python/docs/api/class-cdpsession) - CDP session creation and usage
- [pytest-playwright Plugin](https://playwright.dev/python/docs/test-runners) - Fixtures, configuration

### Secondary (MEDIUM confidence)
- [Flask Server Subprocess Fixture](https://til.simonwillison.net/pytest/subprocess-server) - Server lifecycle pattern
- [Network Throttling with CDP](https://sdetective.blog/blog/qa_auto/pw-cdp/networking-throttle_en) - Network.emulateNetworkConditions example
- [pytest-flask + Playwright Issue](https://github.com/microsoft/playwright-pytest/issues/187) - Known hang issue

### Tertiary (LOW confidence)
- [Page Visibility API Bug](https://github.com/microsoft/playwright/issues/22634) - Visibility events not firing
- [Multiple Browser Contexts Feature Request](https://github.com/microsoft/playwright-pytest/issues/209) - Plugin limitations

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH - Official Playwright documentation consulted
- Architecture patterns: HIGH - Patterns from official docs and verified examples
- Pitfalls: MEDIUM - Some from GitHub issues, need validation in practice
- CDP network throttling: HIGH - Official CDP protocol, documented examples

**Research date:** 2026-01-30
**Valid until:** 2026-03-01 (Playwright updates frequently but patterns are stable)
