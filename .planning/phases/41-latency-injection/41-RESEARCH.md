# Phase 41: Latency Injection Tests - Research

**Researched:** 2026-01-31
**Domain:** Chrome DevTools Protocol (CDP) network emulation via Playwright
**Confidence:** HIGH

## Summary

This research investigates how to implement latency injection tests using Chrome DevTools Protocol (CDP) through Playwright. The key findings are:

1. **CDP provides network emulation** via `Network.emulateNetworkConditions` method, accessible through Playwright's `CDPSession` API
2. **Fixed latency is straightforward** - the `latency` parameter adds minimum delay in milliseconds to all network requests
3. **Asymmetric latency requires per-page CDP sessions** - each browser context/page gets its own CDP session, enabling different latency per player
4. **Jitter requires dynamic latency changes** - CDP has no native jitter parameter; simulate by periodically changing latency values during test execution

**Primary recommendation:** Use Playwright's `page.context.new_cdp_session(page)` to create per-player CDP sessions, then call `Network.emulateNetworkConditions` with varying latency values. For jitter, use a background thread that periodically updates latency within a configured range.

## Standard Stack

The established libraries/tools for this domain:

### Core
| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| Playwright | >=1.49 | Browser automation with CDP support | Already in test deps, native CDP integration |
| pytest | >=8.0 | Test framework | Already in test deps |
| pytest-playwright | >=0.6 | Playwright-pytest integration | Already in test deps |

### Supporting
| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| threading | stdlib | Background jitter thread | For continuous latency variation |
| random | stdlib | Jitter value generation | For variable latency within range |

### Alternatives Considered
| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| CDP Network.emulateNetworkConditions | tc/netem (Linux) | System-level, works on all traffic but requires root and Linux |
| CDP Network.emulateNetworkConditions | Network Link Conditioner (macOS) | System-level, affects all traffic globally |
| Per-page CDP session | Proxy server | More complex setup, but could work cross-browser |

**Installation:**
No additional dependencies needed - Playwright already installed.

## Architecture Patterns

### Recommended Project Structure
```
tests/
├── conftest.py                    # Existing: flask_server, player_contexts
├── fixtures/
│   ├── game_helpers.py            # Existing: game automation helpers
│   └── network_helpers.py         # NEW: CDP latency injection helpers
└── e2e/
    ├── test_infrastructure.py     # Existing: smoke test
    ├── test_multiplayer_basic.py  # Existing: matchmaking, completion
    └── test_latency_injection.py  # NEW: latency injection tests
```

### Pattern 1: CDP Session Per Player
**What:** Create separate CDP sessions for each player's page to enable asymmetric latency
**When to use:** Any test requiring different network conditions per player
**Example:**
```python
# Source: https://playwright.dev/python/docs/api/class-cdpsession
def apply_latency(page, latency_ms: int):
    """Apply fixed latency to a page via CDP."""
    cdp = page.context.new_cdp_session(page)
    cdp.send("Network.enable")
    cdp.send("Network.emulateNetworkConditions", {
        "offline": False,
        "latency": latency_ms,
        "downloadThroughput": -1,  # -1 = no throttling
        "uploadThroughput": -1,
    })
    return cdp  # Return for later cleanup/modification
```

### Pattern 2: Asymmetric Latency Configuration
**What:** Apply different latency values to each player independently
**When to use:** Testing how the game handles mismatched network conditions
**Example:**
```python
# Each player gets their own CDP session with different latency
cdp1 = apply_latency(page1, latency_ms=100)  # Player 1: 100ms
cdp2 = apply_latency(page2, latency_ms=500)  # Player 2: 500ms

# Players now experience different network delays
```

### Pattern 3: Jitter via Dynamic Latency Updates
**What:** Simulate variable latency by periodically changing the latency value
**When to use:** Testing network jitter/instability
**Example:**
```python
import threading
import random
import time

class JitterEmulator:
    """Simulates network jitter by varying latency."""

    def __init__(self, cdp_session, base_latency: int, jitter_range: int):
        self.cdp = cdp_session
        self.base = base_latency
        self.range = jitter_range
        self._running = False
        self._thread = None

    def start(self, interval_ms: int = 100):
        """Start jitter emulation in background thread."""
        self._running = True
        self._thread = threading.Thread(target=self._jitter_loop, args=(interval_ms,), daemon=True)
        self._thread.start()

    def stop(self):
        """Stop jitter emulation."""
        self._running = False
        if self._thread:
            self._thread.join(timeout=1.0)

    def _jitter_loop(self, interval_ms: int):
        """Background loop that varies latency."""
        while self._running:
            jitter = random.randint(-self.range, self.range)
            new_latency = max(0, self.base + jitter)
            self.cdp.send("Network.emulateNetworkConditions", {
                "offline": False,
                "latency": new_latency,
                "downloadThroughput": -1,
                "uploadThroughput": -1,
            })
            time.sleep(interval_ms / 1000.0)
```

### Pattern 4: Parametrized Latency Tests
**What:** Use pytest parametrization to run same test with different latency values
**When to use:** Testing multiple fixed latency scenarios
**Example:**
```python
# Source: https://docs.pytest.org/en/stable/how-to/parametrize.html
import pytest

LATENCY_VALUES = [100, 200, 500]

@pytest.mark.parametrize("latency_ms", LATENCY_VALUES)
def test_episode_completion_under_latency(flask_server, player_contexts, latency_ms):
    """Test that episode completes under various fixed latencies."""
    page1, page2 = player_contexts

    # Apply same latency to both players (symmetric)
    cdp1 = apply_latency(page1, latency_ms)
    cdp2 = apply_latency(page2, latency_ms)

    # ... run test flow ...
```

### Anti-Patterns to Avoid
- **Creating CDP session before page.goto():** CDP session should be created after the page exists but before navigation for reliable interception
- **Forgetting Network.enable:** Must call `Network.enable` before `emulateNetworkConditions` or emulation won't work
- **Using CDP with Firefox/WebKit:** CDP only works with Chromium-based browsers; tests must use Chromium
- **Blocking main test thread with jitter:** Always use daemon threads for jitter loops to avoid hanging tests

## Don't Hand-Roll

Problems that look simple but have existing solutions:

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Network throttling | Custom proxy | CDP Network.emulateNetworkConditions | Already available via Playwright |
| Per-player isolation | Shared browser state | Separate browser contexts | Each context is isolated |
| Browser automation | Raw CDP calls | Playwright high-level API | Playwright handles complexity |

**Key insight:** Playwright's CDP integration provides direct access to Chrome DevTools Protocol without needing a separate CDP client library. The high-level Playwright API handles page lifecycle; CDP is only needed for network emulation not exposed in the high-level API.

## Common Pitfalls

### Pitfall 1: CDP Session Not Taking Effect
**What goes wrong:** Network emulation appears to be ignored, requests go through at normal speed
**Why it happens:** Either Network.enable was not called, or the CDP session was created at the wrong time
**How to avoid:**
1. Always call `Network.enable` first
2. Create CDP session after browser context exists
3. Verify with a simple test (e.g., time a large asset load)
**Warning signs:** Page loads faster than expected latency would allow

### Pitfall 2: Jitter Thread Continues After Test
**What goes wrong:** Background thread keeps running, affects subsequent tests
**Why it happens:** Thread not properly stopped in teardown
**How to avoid:**
1. Use daemon threads (automatically killed when main thread exits)
2. Implement explicit stop() method and call in test teardown
3. Use context managers for automatic cleanup
**Warning signs:** Subsequent tests show unexpected latency

### Pitfall 3: Throughput Throttling Masking Latency Effects
**What goes wrong:** Tests slow down much more than latency would explain
**Why it happens:** Throughput parameters defaulting to 0 instead of -1 (disabled)
**How to avoid:** Explicitly set `downloadThroughput: -1, uploadThroughput: -1` to disable throughput limiting
**Warning signs:** Tests take 10x longer than expected with 100ms latency

### Pitfall 4: WebSocket Traffic Not Affected
**What goes wrong:** Game communication unaffected by latency injection
**Why it happens:** CDP network throttling may not affect WebSocket traffic in some scenarios
**How to avoid:**
1. Verify latency is applied to WebSocket by logging round-trip times
2. If WebSocket unaffected, consider server-side latency injection as alternative
3. Document any limitations in test assumptions
**Warning signs:** Latency metrics in game telemetry don't match injected values

### Pitfall 5: Chromium-Only Limitation
**What goes wrong:** Tests fail silently on Firefox/WebKit
**Why it happens:** CDP is Chromium-specific
**How to avoid:**
1. Only run latency tests with Chromium (use `@pytest.mark.parametrize("browser_name", ["chromium"])` if needed)
2. Document browser requirement in test module docstring
**Warning signs:** `new_cdp_session` throws exception on non-Chromium browsers

## Code Examples

Verified patterns from official sources:

### Create CDP Session in Playwright Python
```python
# Source: https://playwright.dev/python/docs/api/class-cdpsession
from playwright.sync_api import Page

def create_cdp_session(page: Page):
    """Create a CDP session for a Playwright page."""
    client = page.context.new_cdp_session(page)
    return client
```

### Enable Network Emulation
```python
# Source: https://chromedevtools.github.io/devtools-protocol/tot/Network/
def enable_network_emulation(cdp_session, latency_ms: int):
    """Enable network emulation with specified latency."""
    # Must enable Network domain first
    cdp_session.send("Network.enable")

    # Apply network conditions
    cdp_session.send("Network.emulateNetworkConditions", {
        "offline": False,
        "latency": latency_ms,          # Minimum latency in ms
        "downloadThroughput": -1,       # -1 = no limit
        "uploadThroughput": -1,         # -1 = no limit
    })
```

### Fixture for Latency-Enabled Player Contexts
```python
# Pattern for extending existing player_contexts fixture
import pytest
from playwright.sync_api import Browser

@pytest.fixture(scope="function")
def player_contexts_with_latency(browser: Browser, request):
    """
    Create two browser contexts with configurable latency.

    Usage:
        @pytest.mark.parametrize("latency_config", [
            {"p1": 100, "p2": 100},  # symmetric
            {"p1": 100, "p2": 500},  # asymmetric
        ], indirect=True)
        def test_something(player_contexts_with_latency):
            ...
    """
    latency_config = getattr(request, "param", {"p1": 0, "p2": 0})

    chrome_ua = (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    )

    context1 = browser.new_context(user_agent=chrome_ua)
    context2 = browser.new_context(user_agent=chrome_ua)

    page1 = context1.new_page()
    page2 = context2.new_page()

    # Create CDP sessions
    cdp1 = page1.context.new_cdp_session(page1)
    cdp2 = page2.context.new_cdp_session(page2)

    # Enable and configure network emulation
    cdp1.send("Network.enable")
    cdp2.send("Network.enable")

    cdp1.send("Network.emulateNetworkConditions", {
        "offline": False,
        "latency": latency_config["p1"],
        "downloadThroughput": -1,
        "uploadThroughput": -1,
    })

    cdp2.send("Network.emulateNetworkConditions", {
        "offline": False,
        "latency": latency_config["p2"],
        "downloadThroughput": -1,
        "uploadThroughput": -1,
    })

    yield {
        "pages": (page1, page2),
        "cdp_sessions": (cdp1, cdp2),
        "latencies": (latency_config["p1"], latency_config["p2"]),
    }

    # Cleanup
    cdp1.detach()
    cdp2.detach()
    context1.close()
    context2.close()
```

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| Network.emulateNetworkConditions | Still current (deprecated but functional) | Ongoing | Works reliably; newer methods are experimental |
| Proxy-based throttling | CDP direct integration | Playwright 1.0+ | Simpler setup, no external proxy needed |

**Deprecated/outdated:**
- `Network.emulateNetworkConditions` is marked deprecated in favor of `emulateNetworkConditionsByRule` and `overrideNetworkState`, but:
  - The deprecated method still works reliably
  - The newer methods are marked "Experimental"
  - Most documentation and examples still use the deprecated method
  - **Recommendation:** Use deprecated method for stability; it's well-tested

## Open Questions

Things that couldn't be fully resolved:

1. **WebSocket Traffic Behavior**
   - What we know: CDP network throttling applies to HTTP requests
   - What's unclear: How reliably it affects WebSocket traffic (the P2P game uses WebSocket for signaling and potentially data)
   - Recommendation: Verify in first test iteration by comparing game latency telemetry to injected values; if WebSocket unaffected, document limitation

2. **Exact Jitter Update Frequency**
   - What we know: Can dynamically change latency by re-calling emulateNetworkConditions
   - What's unclear: Optimal frequency for realistic jitter simulation vs. CDP overhead
   - Recommendation: Start with 100ms interval (10 updates/second); tune based on performance

3. **Latency Precision**
   - What we know: Latency is documented as "minimum latency from request sent to response headers received"
   - What's unclear: Actual precision and whether it adds exactly N ms or approximately N ms
   - Recommendation: Treat as approximate; focus on relative differences (100ms vs 500ms) not precise measurements

## Sources

### Primary (HIGH confidence)
- [Chrome DevTools Protocol - Network domain](https://chromedevtools.github.io/devtools-protocol/tot/Network/) - Network.emulateNetworkConditions parameters and behavior
- [Playwright Python CDPSession](https://playwright.dev/python/docs/api/class-cdpsession) - Python API for CDP access
- [Playwright CDPSession](https://playwright.dev/docs/api/class-cdpsession) - General CDPSession documentation

### Secondary (MEDIUM confidence)
- [Playwright GitHub Issue #15364](https://github.com/microsoft/playwright/issues/15364) - Confirmed network throttling works with proper parameters
- [The Green Report - CDP Network Throttling](https://www.thegreenreport.blog/articles/supercharging-playwright-tests-with-chrome-devtools-protocol/supercharging-playwright-tests-with-chrome-devtools-protocol.html) - Working examples with presets
- [sdetective.blog - Network Throttle in Playwright](https://sdetective.blog/blog/qa_auto/pw-cdp/networking-throttle_en) - JavaScript examples adaptable to Python
- [pytest Parametrization](https://docs.pytest.org/en/stable/how-to/parametrize.html) - Pattern for testing multiple latency values

### Tertiary (LOW confidence)
- [pytest Background Thread Fixtures](https://haseebmajid.dev/posts/2018-11-05-pytest-with-background-thread-fixtures/) - Pattern for jitter implementation (needs validation)

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH - Already using Playwright, CDP is documented and stable
- Architecture: HIGH - Per-page CDP sessions confirmed working pattern
- Fixed latency: HIGH - Well-documented, confirmed working in Playwright issues
- Asymmetric latency: HIGH - Natural extension of per-page sessions
- Jitter implementation: MEDIUM - Requires custom background thread, pattern is clear but needs validation
- WebSocket behavior: LOW - Needs empirical verification

**Research date:** 2026-01-31
**Valid until:** 2026-03-01 (60 days - stable technology, CDP rarely changes)
