# Phase 42: Network Disruption Tests - Research

**Researched:** 2026-01-31
**Domain:** WebRTC packet loss via CDP, tab visibility emulation via CDP/Playwright
**Confidence:** HIGH

## Summary

This research investigates how to implement network disruption tests that validate the game's rollback and fast-forward mechanisms under stress. The key findings are:

1. **CDP provides WebRTC packet loss** via `Network.emulateNetworkConditions` with `packetLoss` parameter (0-100%), specifically designed for WebRTC traffic
2. **CDP provides page lifecycle control** via `Page.setWebLifecycleState` (frozen/active) and `Emulation.setFocusEmulationEnabled` to simulate tab backgrounding
3. **Rollback events are observable** via the `sessionMetrics.rollbacks` object and `rollbackEvents` array in episode data exports
4. **Fast-forward events are logged** via `p2pLog.warn` with "FAST-FORWARD" prefix, and tracked via `frameNumber` jumps

The existing test infrastructure (Phase 40/41) provides all necessary fixtures. Phase 42 adds two targeted tests:
- NET-02: Packet loss injection to trigger rollbacks
- NET-03: Tab unfocus/refocus to exercise fast-forward path

**Primary recommendation:** Use CDP `packetLoss` parameter for rollback triggers and CDP `Page.setWebLifecycleState` or direct JavaScript event injection for visibility changes. Both rollback and fast-forward events are already observable via exports.

## Standard Stack

The established libraries/tools for this domain:

### Core
| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| Playwright | >=1.49 | Browser automation with CDP | Already in test deps (Phase 40) |
| CDP Network domain | N/A | Packet loss simulation | `packetLoss` parameter targets WebRTC specifically |
| CDP Page/Emulation domain | N/A | Visibility state control | `setWebLifecycleState`, `setFocusEmulationEnabled` |

### Supporting
| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| tests/fixtures/network_helpers.py | local | CDP latency injection | Extend for packet loss |
| tests/fixtures/game_helpers.py | local | Game state access | Observable event checking |

### Alternatives Considered
| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| CDP packetLoss | WebRTC stats injection | packetLoss is simpler, built-in CDP |
| Page.setWebLifecycleState | JavaScript dispatchEvent | CDP is more authentic, but JS works reliably |
| CDP Emulation.setFocusEmulationEnabled | page.evaluate visibilitychange | JS injection is more portable |

**Installation:**
No additional dependencies needed - existing Playwright + CDP infrastructure is sufficient.

## Architecture Patterns

### Recommended Project Structure
```
tests/
├── conftest.py                    # Existing: flask_server, player_contexts
├── fixtures/
│   ├── game_helpers.py            # Existing: game automation helpers
│   └── network_helpers.py         # Extend: add packet loss helpers, visibility helpers
└── e2e/
    ├── test_infrastructure.py     # Existing: smoke test
    ├── test_multiplayer_basic.py  # Existing: matchmaking, completion
    ├── test_latency_injection.py  # Existing (Phase 41): latency tests
    └── test_network_disruption.py # NEW: packet loss + visibility tests
```

### Pattern 1: Packet Loss Injection via CDP
**What:** Use CDP `packetLoss` parameter to simulate WebRTC packet loss, triggering rollbacks
**When to use:** Testing rollback scenarios under simulated network degradation
**Example:**
```python
# Source: https://chromedevtools.github.io/devtools-protocol/tot/Network/
def apply_packet_loss(page, packet_loss_percent: float):
    """
    Apply WebRTC packet loss to a Playwright page via CDP.

    Args:
        page: Playwright Page object
        packet_loss_percent: Packet loss percentage (0-100)
                            0 = no loss, 100 = drop all packets

    Returns:
        CDPSession for later modification or cleanup
    """
    cdp = page.context.new_cdp_session(page)
    cdp.send("Network.enable")
    cdp.send("Network.emulateNetworkConditions", {
        "offline": False,
        "latency": 50,  # Base latency to ensure ordering effects
        "downloadThroughput": -1,
        "uploadThroughput": -1,
        "packetLoss": packet_loss_percent,  # WebRTC packet loss (0-100)
    })
    return cdp
```

### Pattern 2: Tab Visibility Change via JavaScript Dispatch
**What:** Inject visibility change events directly via page.evaluate
**When to use:** Testing fast-forward on refocus (more reliable than CDP)
**Example:**
```python
# Source: Phase 40 research recommendation, MDN Page Visibility API
def set_tab_hidden(page, hidden: bool):
    """
    Simulate tab visibility change by dispatching visibilitychange event.

    Note: Playwright pages are always "visible" by default. We must
    override document.hidden and dispatch the event manually.
    """
    page.evaluate(f"""() => {{
        // Override the hidden property
        Object.defineProperty(document, 'hidden', {{
            configurable: true,
            get: () => {'true' if hidden else 'false'}
        }});
        Object.defineProperty(document, 'visibilityState', {{
            configurable: true,
            get: () => '{'hidden' if hidden else 'visible'}'
        }});
        // Dispatch the visibilitychange event
        document.dispatchEvent(new Event('visibilitychange'));
    }}""")
```

### Pattern 3: Tab Visibility Change via CDP (Alternative)
**What:** Use CDP Page.setWebLifecycleState to freeze/unfreeze page
**When to use:** More authentic simulation of browser tab backgrounding
**Example:**
```python
# Source: https://chromedevtools.github.io/devtools-protocol/tot/Page/
def set_page_lifecycle_state(cdp_session, state: str):
    """
    Set page lifecycle state via CDP.

    Args:
        cdp_session: Existing CDP session
        state: 'frozen' or 'active'
    """
    cdp_session.send("Page.enable")
    cdp_session.send("Page.setWebLifecycleState", {
        "state": state  # 'frozen' or 'active'
    })
```

### Pattern 4: Observable Event Verification
**What:** Check that rollback/fast-forward events occurred by examining game state
**When to use:** Verifying disruption tests triggered expected recovery mechanisms
**Example:**
```python
def get_rollback_stats(page) -> dict:
    """Get rollback statistics from game state."""
    return page.evaluate("""() => {
        const game = window.game;
        if (!game) return null;
        return {
            rollbackCount: game.rollbackCount,
            maxRollbackFrames: game.maxRollbackFrames,
            rollbackEvents: game.sessionMetrics?.rollbacks?.events || [],
        };
    }""")

def get_fast_forward_stats(page) -> dict:
    """Check for fast-forward by examining frame jumps."""
    return page.evaluate("""() => {
        const game = window.game;
        if (!game) return null;
        return {
            frameNumber: game.frameNumber,
            confirmedFrame: game.confirmedFrame,
            // Fast-forward flag (transient, may be false after completion)
            pendingFastForward: game._pendingFastForward,
        };
    }""")
```

### Anti-Patterns to Avoid
- **Testing with 100% packet loss:** Complete packet loss will break WebRTC entirely; use 5-20% for realistic disruption
- **Short visibility hidden periods:** Tab needs to be hidden long enough for partner to advance frames (3+ seconds recommended)
- **Not waiting after visibility restore:** Fast-forward is async; wait for frameNumber to stabilize
- **Checking rollback mid-episode:** Rollback stats are cumulative; check at episode end for accurate counts

## Don't Hand-Roll

Problems that look simple but have existing solutions:

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Packet loss simulation | Custom WebSocket interceptor | CDP `packetLoss` | Built into CDP, targets WebRTC specifically |
| Tab visibility toggle | Browser window minimize | JS event dispatch or CDP lifecycle | Playwright doesn't support real window minimize |
| Rollback detection | Custom frame tracking | `game.sessionMetrics.rollbacks` | Already instrumented in game code |
| Fast-forward verification | Timing-based heuristics | Frame number jumps | Direct observation via game state |

**Key insight:** The game already has comprehensive rollback and fast-forward instrumentation. Tests just need to trigger conditions and observe existing metrics.

## Common Pitfalls

### Pitfall 1: Packet Loss Not Affecting WebRTC
**What goes wrong:** Packet loss is applied but rollbacks don't occur
**Why it happens:** CDP `packetLoss` only affects WebRTC, not HTTP/WebSocket; may need higher loss percentage
**How to avoid:**
1. Ensure P2P DataChannel is used for inputs (game uses WebRTC DataChannel for GGPO inputs)
2. Start with 10-20% packet loss (low percentages may not trigger misprediction)
3. Verify via console logs (ROLLBACK messages in p2pLog.warn)
**Warning signs:** Episode completes without any rollback count increase

### Pitfall 2: Visibility Events Not Firing
**What goes wrong:** dispatchEvent fires but game doesn't detect tab hidden
**Why it happens:** Game uses document.hidden check, not just event listener
**How to avoid:**
1. Override BOTH document.hidden AND document.visibilityState properties
2. Dispatch the event AFTER property overrides
3. Verify via FocusManager state (`game.focusManager.isBackgrounded`)
**Warning signs:** FocusManager.isBackgrounded stays false after "hiding" tab

### Pitfall 3: Fast-Forward Doesn't Trigger
**What goes wrong:** Tab is restored but no fast-forward occurs
**Why it happens:** Need partner to send inputs while tab is hidden for fast-forward to have frames to process
**How to avoid:**
1. Keep OTHER player active during hidden period (they continue sending inputs)
2. Hide tab for long enough that partner advances multiple frames (3-5 seconds)
3. Verify partner is still stepping by checking their frameNumber
**Warning signs:** `bufferedInputs.length === 0` in fast-forward (no inputs to process)

### Pitfall 4: Race Conditions in Async Tests
**What goes wrong:** Test checks state before rollback/fast-forward completes
**Why it happens:** Both operations are async; test proceeds too quickly
**How to avoid:**
1. Wait for specific state changes (frameNumber stabilization, rollbackInProgress === false)
2. Use page.wait_for_function for reliable async waits
3. Add small delay after visibility restore for fast-forward to complete
**Warning signs:** Intermittent test failures, state checks return stale data

### Pitfall 5: CDP Session Conflicts
**What goes wrong:** Network emulation settings conflict between latency and packet loss
**Why it happens:** Multiple emulateNetworkConditions calls overwrite each other
**How to avoid:**
1. Use single call with ALL network parameters (latency + packetLoss together)
2. Keep reference to CDP session and update rather than recreate
3. For tests needing both, combine parameters in one call
**Warning signs:** Latency settings disappear when adding packet loss

## Code Examples

Verified patterns from official sources and existing infrastructure:

### Complete Packet Loss Helper
```python
# Source: CDP Network domain + existing network_helpers.py pattern
from playwright.sync_api import Page, CDPSession

def apply_packet_loss(
    page: Page,
    packet_loss_percent: float,
    latency_ms: int = 50
) -> CDPSession:
    """
    Apply WebRTC packet loss and optional latency via CDP.

    Args:
        page: Playwright Page object
        packet_loss_percent: Packet loss percentage (0-100)
        latency_ms: Base latency in milliseconds (default 50ms)

    Returns:
        CDPSession for later modification or cleanup

    Note:
        packetLoss specifically affects WebRTC traffic, which is used
        for GGPO input packets in interactive-gym multiplayer games.
    """
    cdp = page.context.new_cdp_session(page)
    cdp.send("Network.enable")
    cdp.send("Network.emulateNetworkConditions", {
        "offline": False,
        "latency": latency_ms,
        "downloadThroughput": -1,
        "uploadThroughput": -1,
        "packetLoss": packet_loss_percent,
    })
    return cdp
```

### Complete Visibility Change Helper
```python
# Source: MDN Page Visibility API + Phase 40 research recommendation
from playwright.sync_api import Page

def set_tab_visibility(page: Page, visible: bool) -> None:
    """
    Simulate tab visibility change by overriding document properties
    and dispatching visibilitychange event.

    Args:
        page: Playwright Page object
        visible: True for visible, False for hidden

    Note:
        This triggers the game's FocusManager which:
        - When hidden: buffers partner inputs, uses defaultAction
        - When visible: triggers fast-forward to catch up
    """
    hidden_value = 'false' if visible else 'true'
    visibility_state = 'visible' if visible else 'hidden'

    page.evaluate(f"""() => {{
        // Override document.hidden property
        Object.defineProperty(document, 'hidden', {{
            configurable: true,
            get: () => {hidden_value}
        }});

        // Override document.visibilityState property
        Object.defineProperty(document, 'visibilityState', {{
            configurable: true,
            get: () => '{visibility_state}'
        }});

        // Dispatch the visibilitychange event
        document.dispatchEvent(new Event('visibilitychange'));
    }}""")


def wait_for_focus_manager_state(page: Page, backgrounded: bool, timeout: int = 10000) -> None:
    """Wait for FocusManager to reflect expected state."""
    expected = 'true' if backgrounded else 'false'
    page.wait_for_function(
        f"() => window.game?.focusManager?.isBackgrounded === {expected}",
        timeout=timeout
    )
```

### Rollback Observation Helper
```python
# Source: pyodide_multiplayer_game.js sessionMetrics structure
def get_rollback_stats(page: Page) -> dict:
    """
    Get rollback statistics from the game.

    Returns dict with:
        - rollbackCount: Total rollbacks this episode
        - maxRollbackFrames: Deepest rollback (frames replayed)
        - rollbackEvents: Array of rollback event details
    """
    return page.evaluate("""() => {
        const game = window.game;
        if (!game) return null;

        return {
            rollbackCount: game.rollbackCount || 0,
            maxRollbackFrames: game.maxRollbackFrames || 0,
            rollbackEvents: game.sessionMetrics?.rollbacks?.events || [],
            rollbackInProgress: game.rollbackInProgress || false,
        };
    }""")


def wait_for_rollback_to_occur(page: Page, min_count: int = 1, timeout: int = 60000) -> None:
    """Wait for at least min_count rollbacks to occur."""
    page.wait_for_function(
        f"() => (window.game?.rollbackCount || 0) >= {min_count}",
        timeout=timeout
    )
```

### Fast-Forward Observation Helper
```python
# Source: pyodide_multiplayer_game.js _performFastForward implementation
def get_fast_forward_state(page: Page) -> dict:
    """
    Get fast-forward related state from the game.

    Returns dict with frame tracking info useful for detecting
    fast-forward has occurred (frame number jumps).
    """
    return page.evaluate("""() => {
        const game = window.game;
        if (!game) return null;

        return {
            frameNumber: game.frameNumber,
            confirmedFrame: game.confirmedFrame,
            pendingFastForward: game._pendingFastForward || false,
            isBackgrounded: game.focusManager?.isBackgrounded || false,
            bufferedInputCount: game.focusManager?.bufferedInputs?.length || 0,
        };
    }""")


def wait_for_fast_forward_complete(page: Page, expected_min_frame: int, timeout: int = 30000) -> None:
    """
    Wait for fast-forward to complete by checking frame number reaches target.

    Args:
        page: Playwright Page object
        expected_min_frame: Minimum frameNumber expected after fast-forward
        timeout: Maximum wait time in milliseconds
    """
    page.wait_for_function(
        f"""() => {{
            const game = window.game;
            return game &&
                   !game._pendingFastForward &&
                   !game.rollbackInProgress &&
                   game.frameNumber >= {expected_min_frame};
        }}""",
        timeout=timeout
    )
```

### Complete Test Example: Packet Loss Triggers Rollback
```python
import pytest
from tests.fixtures.network_helpers import apply_latency
from tests.fixtures.game_helpers import (
    wait_for_game_canvas,
    wait_for_episode_complete,
    get_game_state,
)

@pytest.mark.timeout(300)
def test_packet_loss_triggers_rollback(flask_server, player_contexts):
    """
    NET-02: Test that packet loss triggers rollback scenarios.

    Strategy:
    1. Start game with one player having packet loss
    2. Let episode run (players idle)
    3. Verify rollbacks occurred due to late/lost packets
    4. Verify episode still completes despite disruption
    """
    page1, page2 = player_contexts
    base_url = flask_server["url"]

    # Apply packet loss to player 2 BEFORE navigation
    cdp2 = apply_packet_loss(page2, packet_loss_percent=15, latency_ms=100)

    try:
        # Navigate and start game
        page1.goto(base_url)
        page2.goto(base_url)

        # ... (tutorial completion flow from Phase 41) ...

        # Wait for game to start
        wait_for_game_canvas(page1, timeout=120000)
        wait_for_game_canvas(page2, timeout=120000)

        # Wait for episode to complete
        wait_for_episode_complete(page1, episode_num=1, timeout=180000)
        wait_for_episode_complete(page2, episode_num=1, timeout=180000)

        # Verify rollbacks occurred (at least one player should have experienced rollback)
        stats1 = get_rollback_stats(page1)
        stats2 = get_rollback_stats(page2)

        total_rollbacks = (stats1['rollbackCount'] or 0) + (stats2['rollbackCount'] or 0)
        assert total_rollbacks > 0, "Expected rollbacks due to packet loss"

        # Verify episode completed successfully despite rollbacks
        final_state1 = get_game_state(page1)
        assert final_state1['numEpisodes'] >= 1

    finally:
        cdp2.detach()
```

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| Network.emulateNetworkConditions without packetLoss | Include packetLoss parameter | CDP stable | WebRTC-specific packet loss is now available |
| Fake visibility via page.bringToFront | JS property override + dispatchEvent | 2024+ | Reliable cross-browser simulation |
| Manual frame counting for rollback detection | Use game.sessionMetrics.rollbacks | v1.8+ | Built-in instrumentation for research data |

**Deprecated/outdated:**
- `page.bringToFront()` does NOT trigger visibility events (Playwright limitation)
- Relying on `Page.setWebLifecycleState` alone may not work reliably across all Chromium versions

## Open Questions

Things that couldn't be fully resolved:

1. **Optimal Packet Loss Percentage**
   - What we know: 0% = no effect, 100% = complete connection failure
   - What's unclear: Minimum % needed to reliably trigger rollbacks without breaking connection
   - Recommendation: Start with 10-15%, increase if no rollbacks; decrease if connection fails

2. **Fast-Forward Detection Reliability**
   - What we know: Frame number jumps indicate fast-forward occurred
   - What's unclear: How to distinguish fast-forward from normal frame advancement
   - Recommendation: Record frame number before hiding tab, compare after restore; jump > (hidden_duration * FPS) indicates fast-forward

3. **CDP Page.setWebLifecycleState Behavior**
   - What we know: Can set page to 'frozen' or 'active'
   - What's unclear: Whether this reliably triggers document.visibilitychange in game code
   - Recommendation: Use JS event dispatch as primary approach; CDP as fallback if needed

## Sources

### Primary (HIGH confidence)
- [Chrome DevTools Protocol - Network domain](https://chromedevtools.github.io/devtools-protocol/tot/Network/) - `packetLoss` parameter documented
- [Chrome DevTools Protocol - Page domain](https://chromedevtools.github.io/devtools-protocol/tot/Page/) - `setWebLifecycleState` method
- [Chrome DevTools Protocol - Emulation domain](https://chromedevtools.github.io/devtools-protocol/tot/Emulation/) - `setFocusEmulationEnabled` method
- [MDN Page Visibility API](https://developer.mozilla.org/en-US/docs/Web/API/Page_Visibility_API) - document.hidden, visibilitychange event

### Secondary (MEDIUM confidence)
- [Playwright GitHub Issue #2286](https://github.com/microsoft/playwright/issues/2286) - Visibility toggle feature request with workarounds
- [Playwright GitHub Issue #22634](https://github.com/microsoft/playwright/issues/22634) - visibilitychange events not firing (known limitation)
- Phase 40 RESEARCH.md - Anti-patterns section on Page Visibility API

### Tertiary (LOW confidence)
- Existing pyodide_multiplayer_game.js implementation - rollback and fast-forward instrumentation (verified by reading code)

## Metadata

**Confidence breakdown:**
- Packet loss via CDP: HIGH - Documented parameter, specifically for WebRTC
- Visibility toggle via JS dispatch: HIGH - Standard DOM API, verified pattern
- Rollback observability: HIGH - Verified in game code (sessionMetrics.rollbacks)
- Fast-forward observability: MEDIUM - Frame jumps observable, but no explicit event
- CDP Page.setWebLifecycleState: MEDIUM - Documented but experimental, JS dispatch is more reliable

**Research date:** 2026-01-31
**Valid until:** 2026-03-02 (30 days - CDP stable, game instrumentation already exists)
