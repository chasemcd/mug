# Phase 45: Episode Completion Diagnosis & Fix - Research

**Researched:** 2026-02-02
**Domain:** Playwright browser automation, JavaScript visibility API, game loop timing
**Confidence:** HIGH

## Summary

The root cause of frames not advancing in E2E tests has been identified with HIGH confidence. The issue is a combination of:

1. **Primary cause (HIGH confidence):** In Playwright (even headed mode), `document.hidden` is `true` by default because the browser windows don't have user focus. The game's `FocusManager` class (Phase 25) checks this property and skips all frame processing when the tab is "backgrounded". This causes the game loop to return early on every tick, resulting in frame numbers staying at 0.

2. **Secondary cause (MEDIUM confidence):** Some tests (e.g., `test_multiplayer_basic.py`, `run_full_episode_flow()`) still call `complete_tutorial_and_advance()` even though the tutorial scene was removed from the test configuration. While this may cause button-click timing issues, the primary cause is the visibility check.

**Primary recommendation:** Call `set_tab_visibility(page, True)` for both players after the game object initializes to override `document.hidden` and signal the FocusManager that the tabs are visible.

## Root Cause Analysis

### Evidence Chain

1. **Game infrastructure works correctly:**
   - Matchmaking succeeds (players paired, same gameId)
   - WebRTC P2P connection established (validation passes)
   - Web Worker timer starts and sends ticks

2. **Frame processing is blocked at visibility check:**
   ```javascript
   // pyodide_multiplayer_game.js, _handleWorkerTick() (line 5796)
   if (this.focusManager && this.focusManager.isBackgrounded) {
       // ...periodic logging...
       return;  // <-- RETURNS EARLY, NO FRAME PROCESSING
   }
   ```

3. **FocusManager initializes from document.hidden:**
   ```javascript
   // pyodide_multiplayer_game.js, FocusManager constructor (line 190)
   this.isBackgrounded = document.hidden;
   ```

4. **Playwright's document.hidden is true:**
   - Even in headed mode, Playwright browser windows don't have user focus
   - `document.hidden` reports `true` unless explicitly overridden
   - No `visibilitychange` event fires because the state never changes

### Timeline of Issue

- **Phase 24 (v1.5):** Web Worker timer added for throttle-resistant game loop
- **Phase 25 (v1.5):** FocusManager added to handle background state
- **Phase 40 (v1.9):** Test infrastructure created; issue existed from start but wasn't diagnosed
- **Commit 607b60a:** Tutorial scene removed from test config; flow mismatch with some tests

## Standard Stack

No new dependencies needed. Fix uses existing infrastructure.

### Existing Infrastructure
| Component | Location | Purpose |
|-----------|----------|---------|
| `set_tab_visibility()` | tests/fixtures/network_helpers.py | Override document.hidden |
| `wait_for_focus_manager_state()` | tests/fixtures/network_helpers.py | Wait for FocusManager state |
| `FocusManager` | pyodide_multiplayer_game.js | Manage background/foreground state |

## Architecture Patterns

### Recommended Fix Pattern

**When:** After game object initializes in any E2E test
**Action:** Override document.hidden to false and trigger visibilitychange

```python
# After wait_for_game_object()
from tests.fixtures.network_helpers import set_tab_visibility

set_tab_visibility(page1, visible=True)
set_tab_visibility(page2, visible=True)
```

### Where to Apply Fix

The fix should be applied in the shared helper functions to avoid code duplication:

1. **`run_full_episode_flow_until_gameplay()`** in `game_helpers.py` - Add visibility override after `wait_for_game_object()`

2. **`run_full_episode_flow()`** in `test_latency_injection.py` and `test_data_comparison.py` - Same fix location

3. **Individual tests in `test_multiplayer_basic.py`** - Add visibility override where tests directly call `wait_for_game_object()`

### Anti-Patterns to Avoid

- **Don't modify FocusManager to ignore visibility in test mode** - This would require test-specific code in production JavaScript
- **Don't use CDP Page.setWebLifecycleState** - Less reliable than JavaScript property override (documented in Phase 42)
- **Don't call visibility override before game initialization** - FocusManager doesn't exist yet

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Visibility override | Custom document property patching | `set_tab_visibility()` | Already exists, battle-tested |
| State verification | Custom polling | `wait_for_focus_manager_state()` | Already exists, proper timeout handling |

## Common Pitfalls

### Pitfall 1: Calling set_tab_visibility Too Early
**What goes wrong:** Called before game object exists, FocusManager not yet created
**Why it happens:** Natural instinct to set visibility at page load
**How to avoid:** Always call AFTER `wait_for_game_object()` returns
**Warning signs:** Test passes visibility call but frames still don't advance

### Pitfall 2: Tutorial Flow Mismatch
**What goes wrong:** Tests call `complete_tutorial_and_advance()` but no tutorial scene exists
**Why it happens:** Test config removed tutorial, but some test flows weren't updated
**How to avoid:** Use `run_full_episode_flow_until_gameplay()` which has correct flow
**Warning signs:** Timeout waiting for startButton (already hidden after first click)

### Pitfall 3: Only Fixing One Player
**What goes wrong:** One player advances frames, the other doesn't
**Why it happens:** Forgot to call `set_tab_visibility()` on both pages
**How to avoid:** Always set visibility for both players
**Warning signs:** Assertion errors about players having different frame counts

## Code Examples

### Complete Fix for run_full_episode_flow_until_gameplay

```python
# tests/fixtures/game_helpers.py

from tests.fixtures.network_helpers import set_tab_visibility

def run_full_episode_flow_until_gameplay(page1: Page, page2: Page, base_url: str) -> None:
    """
    Progress both players from navigation to active gameplay.
    """
    # Navigate to game
    page1.goto(base_url)
    page2.goto(base_url)

    # Wait for socket connection
    wait_for_socket_connected(page1, timeout=30000)
    wait_for_socket_connected(page2, timeout=30000)

    # Pass instructions
    click_advance_button(page1, timeout=60000)
    click_advance_button(page2, timeout=60000)

    # Start multiplayer (tutorial scene is disabled in test config)
    click_start_button(page1, timeout=60000)
    click_start_button(page2, timeout=60000)

    # Wait for game to start
    wait_for_game_canvas(page1, timeout=120000)
    wait_for_game_canvas(page2, timeout=120000)
    wait_for_game_object(page1, timeout=60000)
    wait_for_game_object(page2, timeout=60000)

    # CRITICAL: Override document.hidden for Playwright
    # Without this, FocusManager thinks tab is backgrounded and skips all frame processing
    set_tab_visibility(page1, visible=True)
    set_tab_visibility(page2, visible=True)
```

### Test Flow Fix for test_multiplayer_basic.py

```python
# Remove complete_tutorial_and_advance calls (no tutorial scene in test config)
# Use the simpler flow matching run_full_episode_flow_until_gameplay:

def test_two_players_connect_and_complete_episode(flask_server, player_contexts):
    page1, page2 = player_contexts
    base_url = flask_server["url"]

    # Navigate and connect
    page1.goto(base_url)
    page2.goto(base_url)
    wait_for_socket_connected(page1)
    wait_for_socket_connected(page2)

    # Pass instructions (no tutorial in test config)
    click_advance_button(page1)
    click_advance_button(page2)

    # Start multiplayer directly
    click_start_button(page1)
    click_start_button(page2)

    # Wait for game
    wait_for_game_canvas(page1, timeout=90000)
    wait_for_game_canvas(page2, timeout=90000)
    wait_for_game_object(page1)
    wait_for_game_object(page2)

    # Override visibility for Playwright
    set_tab_visibility(page1, visible=True)
    set_tab_visibility(page2, visible=True)

    # Now frames will advance...
    wait_for_episode_complete(page1, episode_num=1, timeout=180000)
    wait_for_episode_complete(page2, episode_num=1, timeout=180000)
```

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| Assume browser is visible | FocusManager checks document.hidden | Phase 25 (v1.5) | Required for background handling |
| RAF-driven game loop | Web Worker timer | Phase 24 (v1.5) | Throttle-resistant but still checks visibility |

**Key insight:** Phase 24/25 changes (v1.5) made the game background-aware for better user experience, but this broke automated testing where browsers aren't "visible" to the OS.

## Open Questions

No significant open questions. Root cause is definitively identified.

1. **Should visibility be set automatically in a fixture?**
   - What we know: Could add to player_contexts fixture or a new fixture
   - What's unclear: Timing might be tricky (game object must exist first)
   - Recommendation: Fix in helper functions first, consider fixture later

## Sources

### Primary (HIGH confidence)
- `/Users/chasemcd/Repositories/interactive-gym/interactive_gym/server/static/js/pyodide_multiplayer_game.js` - FocusManager class (lines 188-318), _handleWorkerTick (lines 5746-5836)
- `/Users/chasemcd/Repositories/interactive-gym/tests/fixtures/network_helpers.py` - set_tab_visibility function (lines 202-234)
- `/Users/chasemcd/Repositories/interactive-gym/tests/fixtures/game_helpers.py` - run_full_episode_flow_until_gameplay (lines 232-274)

### Secondary (MEDIUM confidence)
- Code inspection of test flows and configuration

## Metadata

**Confidence breakdown:**
- Root cause identification: HIGH - Direct code path tracing from tick handler to visibility check
- Fix approach: HIGH - Uses existing infrastructure (set_tab_visibility already exists and works)
- Secondary issues: MEDIUM - Tutorial flow mismatch identified but may not be blocking

**Research date:** 2026-02-02
**Valid until:** Indefinite (core architecture unlikely to change)

## Fix Summary

### Required Changes

1. **`tests/fixtures/game_helpers.py`:**
   - Add import: `from tests.fixtures.network_helpers import set_tab_visibility`
   - Add visibility override after `wait_for_game_object()` in `run_full_episode_flow_until_gameplay()`

2. **`tests/e2e/test_latency_injection.py`:**
   - Add visibility override in `run_full_episode_flow()` after game object wait
   - Also: Remove `complete_tutorial_and_advance()` calls (tutorial doesn't exist)

3. **`tests/e2e/test_data_comparison.py`:**
   - Add visibility override in `run_full_episode_flow()` after game object wait
   - Also: Remove `complete_tutorial_and_advance()` calls

4. **`tests/e2e/test_multiplayer_basic.py`:**
   - Remove `complete_tutorial_and_advance()` calls from both tests
   - Add visibility override after `wait_for_game_object()`

5. **`tests/e2e/test_network_disruption.py`:**
   - Remove `complete_tutorial_and_advance()` calls
   - Add visibility override after game initialization

### Estimated Impact

- **Files to modify:** 5
- **Lines changed:** ~30-50 (mostly deletions of tutorial flow + addition of visibility calls)
- **Risk:** LOW - Using existing, tested infrastructure
- **Verification:** Run any E2E test; frames should advance past 0
