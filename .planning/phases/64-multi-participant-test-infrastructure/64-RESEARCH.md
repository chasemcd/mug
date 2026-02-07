# Phase 64: Multi-Participant Test Infrastructure - Research

**Researched:** 2026-02-03
**Domain:** Playwright concurrent browser contexts for 6-participant testing
**Confidence:** HIGH

## Summary

This phase extends the existing 2-player test infrastructure to support 6 concurrent participants (3 simultaneous games). The current infrastructure uses Playwright browser contexts with CDP-based network injection, which provides the foundation for scaling.

Playwright browser contexts are lightweight (kilobytes, not megabytes) and can run dozens simultaneously within a single browser process. The key challenges are: (1) fixture design for managing 6 contexts instead of 2, (2) orchestrating 3 concurrent games with staggered participant arrival, and (3) proper resource cleanup to prevent memory leaks.

The existing `player_contexts` fixture creates 2 contexts from a single browser. This pattern extends naturally to 6 contexts. The server already supports multiple concurrent games via the FIFO matchmaker - it simply pairs participants as they arrive. No server changes are needed.

**Primary recommendation:** Extend `conftest.py` with a `multi_participant_fixture` that creates 6 browser contexts from a single browser instance, paired with a `GameOrchestrator` helper class that manages staggered game creation.

## Standard Stack

The established libraries/tools for this domain:

### Core
| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| playwright | 1.49+ | Browser automation | Already used, supports multiple contexts natively |
| pytest-playwright | 0.6+ | pytest integration | Already used, provides `browser` fixture |
| pytest | 8.0+ | Test framework | Already used |

### Supporting
| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| pytest-timeout | 2.3+ | Test timeouts | Already used, may need longer timeouts (10+ min) |
| asyncio (stdlib) | - | Concurrent operations | Coordinate parallel page navigation |

### Alternatives Considered
| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| 6 contexts in 1 browser | 6 separate browsers | Separate browsers use 50-150MB each vs KB for contexts, much slower |
| pytest-xdist parallel workers | Single test with 6 contexts | Workers require test isolation; this test needs all 6 in same test |
| Async fixtures | Sync fixtures | Sync is simpler, async not needed for ~6 contexts |

**Installation:**
No new dependencies required. Existing stack handles 6 contexts.

## Architecture Patterns

### Recommended Fixture Structure
```
tests/
├── conftest.py              # Extended with multi_participant_fixture
├── fixtures/
│   ├── game_helpers.py      # Add multi-game orchestration helpers
│   ├── multi_participant.py # NEW: GameOrchestrator class
│   └── ...
└── e2e/
    └── test_multi_participant.py  # NEW: 6-participant stress tests
```

### Pattern 1: Multi-Participant Fixture
**What:** Pytest fixture that creates 6 isolated browser contexts
**When to use:** Tests requiring 6 concurrent participants (STRESS-01 through STRESS-07)
**Example:**
```python
# Source: Playwright docs + existing player_contexts pattern
@pytest.fixture(scope="function")
def multi_participant_contexts(browser):
    """
    Create 6 isolated browser contexts for multi-participant testing.

    Scope: function (fresh contexts for each test)
    Yields: tuple of 6 pages (page1, page2, page3, page4, page5, page6)
    """
    chrome_ua = (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    )

    contexts = []
    pages = []

    for i in range(6):
        ctx = browser.new_context(user_agent=chrome_ua)
        page = ctx.new_page()
        contexts.append(ctx)
        pages.append(page)

    yield tuple(pages)

    # Cleanup: close all contexts
    for ctx in contexts:
        ctx.close()
```

### Pattern 2: Game Orchestrator for Concurrent Games
**What:** Helper class that manages multiple simultaneous games
**When to use:** Orchestrating 3 games that need to progress together
**Example:**
```python
# Source: Custom pattern based on existing run_full_episode_flow_until_gameplay
class GameOrchestrator:
    """Manages multiple concurrent 2-player games."""

    def __init__(self, pages: tuple, base_url: str):
        """
        Args:
            pages: Tuple of 6 pages (will be paired: [0,1], [2,3], [4,5])
            base_url: Flask server URL
        """
        self.games = [
            (pages[0], pages[1]),  # Game 1
            (pages[2], pages[3]),  # Game 2
            (pages[4], pages[5]),  # Game 3
        ]
        self.base_url = base_url

    def navigate_all(self):
        """Navigate all 6 participants to the game URL."""
        for page1, page2 in self.games:
            page1.goto(self.base_url)
            page2.goto(self.base_url)

    def start_games_staggered(self, delay_between_games_ms: int = 500):
        """
        Start games with staggered timing.

        This simulates realistic arrival patterns where players
        don't all join at exactly the same instant.
        """
        for game_idx, (page1, page2) in enumerate(self.games):
            if game_idx > 0:
                time.sleep(delay_between_games_ms / 1000)

            # Progress both players to matchmaking
            run_full_episode_flow_until_gameplay(page1, page2, self.base_url)

    def wait_for_all_episodes_complete(self, episode_num: int = 1, timeout: int = 180000):
        """Wait for all 6 participants to complete specified episode."""
        for page1, page2 in self.games:
            wait_for_episode_complete(page1, episode_num=episode_num, timeout=timeout)
            wait_for_episode_complete(page2, episode_num=episode_num, timeout=timeout)
```

### Pattern 3: Staggered Participant Arrival
**What:** Participants join at realistic intervals, not all simultaneously
**When to use:** Testing server's ability to handle arrival bursts
**Example:**
```python
def navigate_with_staggered_arrival(pages: tuple, base_url: str,
                                     delay_ms: int = 200):
    """
    Navigate participants with staggered timing.

    This tests the server's waitroom and matchmaking under realistic
    conditions where players arrive at slightly different times.
    """
    for i, page in enumerate(pages):
        page.goto(base_url)
        if i < len(pages) - 1:
            time.sleep(delay_ms / 1000)
```

### Anti-Patterns to Avoid
- **All 6 navigating at exact same instant:** Unrealistic and may stress SocketIO in unexpected ways. Use 100-500ms stagger.
- **Not closing contexts in finally block:** Memory leaks accumulate across test runs.
- **Shared state between games:** Each game pair must be independent. Don't share CDP sessions or network conditions.
- **Single long timeout for all games:** Each game should have independent timeout tracking.

## Don't Hand-Roll

Problems that have existing solutions:

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Browser context isolation | Custom cookie/storage management | `browser.new_context()` | Playwright handles all isolation |
| Network condition injection | Custom proxy or mocking | Existing `apply_latency()` / `apply_packet_loss()` | CDP works per-context |
| Tab visibility simulation | Manual event dispatch | Existing `set_tab_visibility()` | Already handles FocusManager |
| Matchmaking orchestration | Custom server-side matching | FIFO matchmaker auto-pairs | Server already supports concurrent games |
| Episode completion waiting | Polling loops | Existing `wait_for_episode_complete()` | Already handles all edge cases |

**Key insight:** The existing test infrastructure already handles the hard problems. The multi-participant extension is primarily fixture organization, not new functionality.

## Common Pitfalls

### Pitfall 1: Context Memory Leaks
**What goes wrong:** Memory grows with each test run; eventually OOM or slowdown
**Why it happens:** Contexts not properly closed in finally blocks
**How to avoid:** Always use try/finally in fixture, close ALL contexts even on error
**Warning signs:** Test suite slows down over time; machine memory usage climbs
```python
@pytest.fixture
def multi_participant_contexts(browser):
    contexts = []
    pages = []
    try:
        for i in range(6):
            ctx = browser.new_context(...)
            contexts.append(ctx)
            pages.append(ctx.new_page())
        yield tuple(pages)
    finally:
        # Close ALL contexts, even on error
        for ctx in contexts:
            try:
                ctx.close()
            except Exception:
                pass
```

### Pitfall 2: Matchmaking Race Conditions
**What goes wrong:** Players pair incorrectly (player 1 matches with player 3 instead of player 2)
**Why it happens:** FIFO matchmaker pairs based on arrival order, not intended groupings
**How to avoid:** Navigate game partners together with minimal delay (<100ms between partners)
**Warning signs:** `gameId` mismatch assertions fail
```python
# GOOD: Partners navigate together
page1.goto(base_url)
page2.goto(base_url)  # Immediate follow-up
time.sleep(0.5)  # Wait before next game pair
page3.goto(base_url)
page4.goto(base_url)

# BAD: All navigate simultaneously
for page in all_pages:
    page.goto(base_url)  # Unpredictable pairing!
```

### Pitfall 3: Timeout Cascades
**What goes wrong:** One slow game causes all subsequent validations to timeout
**Why it happens:** Sequential waiting with single large timeout
**How to avoid:** Use per-game timeouts; consider parallel waiting patterns
**Warning signs:** Failures at game 2 or 3 when game 1 completed fine
```python
# GOOD: Per-game timeout tracking
for game_idx, (page1, page2) in enumerate(games):
    try:
        wait_for_episode_complete(page1, timeout=60000)
        wait_for_episode_complete(page2, timeout=60000)
    except TimeoutError:
        pytest.fail(f"Game {game_idx} did not complete")
```

### Pitfall 4: CDP Session Interference
**What goes wrong:** Network conditions from one context affect another
**Why it happens:** CDP sessions accidentally shared or applied to wrong page
**How to avoid:** Create new CDP session per-page, track sessions explicitly
**Warning signs:** Latency appears on pages that shouldn't have it
```python
# GOOD: Track CDP sessions per-game
cdp_sessions = {}
for game_idx, (page1, page2) in enumerate(games):
    if should_apply_latency[game_idx]:
        cdp_sessions[game_idx] = apply_latency(page1, latency_ms=100)

# Cleanup
for cdp in cdp_sessions.values():
    cdp.detach()
```

### Pitfall 5: Export File Collisions
**What goes wrong:** Export file paths conflict between concurrent games
**Why it happens:** Subject IDs or experiment IDs overlap
**How to avoid:** Extract subject IDs after game start, use game-specific validation
**Warning signs:** `FileNotFoundError` or wrong data in comparison
```python
# GOOD: Collect identifiers per-game after matchmaking
game_identifiers = []
for page1, page2 in games:
    ids = get_subject_ids_from_pages(page1, page2)
    game_identifiers.append(ids)

# Validate each game independently
for game_idx, (subject_ids) in enumerate(game_identifiers):
    file1, file2 = wait_for_export_files(
        experiment_id=EXPERIMENT_ID,
        scene_id=scene_id,
        subject_ids=subject_ids,
        episode_num=0
    )
    run_comparison(file1, file2)
```

## Code Examples

Verified patterns from official sources and existing codebase:

### Complete Multi-Participant Test Structure
```python
# Source: Extension of existing test_network_disruption.py patterns
import pytest
import time
from tests.fixtures.game_helpers import (
    run_full_episode_flow_until_gameplay,
    wait_for_episode_complete,
    get_game_state,
    get_scene_id,
)
from tests.fixtures.network_helpers import set_tab_visibility
from tests.fixtures.export_helpers import (
    get_experiment_id,
    get_subject_ids_from_pages,
    wait_for_export_files,
    run_comparison,
)

@pytest.mark.timeout(600)  # 10 minutes for 3 concurrent games
def test_three_simultaneous_games(multi_participant_contexts, flask_server):
    """
    STRESS-01: Test infrastructure supports 6 concurrent participants.

    Validates:
    - 6 browser contexts can connect simultaneously
    - Server handles 3 concurrent games
    - All games complete successfully
    - Export data parity verified for all games
    """
    pages = multi_participant_contexts  # 6 pages
    base_url = flask_server["url"]

    # Organize into game pairs
    games = [
        (pages[0], pages[1]),  # Game 1
        (pages[2], pages[3]),  # Game 2
        (pages[4], pages[5]),  # Game 3
    ]

    # Navigate and start games with staggered timing
    for game_idx, (page1, page2) in enumerate(games):
        # Stagger game starts by 1 second
        if game_idx > 0:
            time.sleep(1.0)

        # Progress to gameplay
        run_full_episode_flow_until_gameplay(page1, page2, base_url)

        # Verify pairing
        state1 = get_game_state(page1)
        state2 = get_game_state(page2)
        assert state1["gameId"] == state2["gameId"], f"Game {game_idx}: Players not matched"

        print(f"Game {game_idx}: Started, gameId={state1['gameId']}")

    # Wait for all episodes to complete
    for game_idx, (page1, page2) in enumerate(games):
        wait_for_episode_complete(page1, episode_num=1, timeout=180000)
        wait_for_episode_complete(page2, episode_num=1, timeout=180000)
        print(f"Game {game_idx}: Episode complete")

    # Validate export parity for all games
    experiment_id = get_experiment_id()
    scene_id = get_scene_id(pages[0])

    for game_idx, (page1, page2) in enumerate(games):
        subject_ids = get_subject_ids_from_pages(page1, page2)
        file1, file2 = wait_for_export_files(
            experiment_id=experiment_id,
            scene_id=scene_id,
            subject_ids=subject_ids,
            episode_num=0,
            timeout_sec=30
        )
        exit_code, output = run_comparison(file1, file2, verbose=True)
        assert exit_code == 0, f"Game {game_idx} parity failed: {output}"
        print(f"Game {game_idx}: Data parity verified")
```

### Fixture for 6 Participants
```python
# Source: tests/conftest.py extension
@pytest.fixture(scope="function")
def multi_participant_contexts(browser):
    """
    Create 6 isolated browser contexts for multi-participant stress testing.

    Returns tuple of 6 pages, intended to be organized as 3 game pairs.
    Each context is fully isolated with its own cookies/storage.
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
```

### Staggered Arrival Test
```python
def test_staggered_participant_arrival(multi_participant_contexts, flask_server):
    """
    Test that infrastructure handles participants arriving at different times.

    Simulates realistic scenario:
    - Game 1 players arrive, wait briefly, start
    - Game 2 players arrive 2s later
    - Game 3 players arrive 2s after that
    """
    pages = multi_participant_contexts
    base_url = flask_server["url"]

    STAGGER_DELAY_SEC = 2.0

    games = [
        (pages[0], pages[1]),
        (pages[2], pages[3]),
        (pages[4], pages[5]),
    ]

    # Start games with staggered arrival
    for game_idx, (page1, page2) in enumerate(games):
        if game_idx > 0:
            time.sleep(STAGGER_DELAY_SEC)

        # Navigate both players (close together to ensure correct pairing)
        page1.goto(base_url)
        time.sleep(0.1)  # Small gap, but same "arrival window"
        page2.goto(base_url)

        # Progress through UI
        wait_for_socket_connected(page1)
        wait_for_socket_connected(page2)
        click_advance_button(page1)
        click_advance_button(page2)
        click_start_button(page1)
        click_start_button(page2)

    # Wait for all to reach gameplay
    for page1, page2 in games:
        wait_for_game_canvas(page1, timeout=120000)
        wait_for_game_canvas(page2, timeout=120000)
        set_tab_visibility(page1, visible=True)
        set_tab_visibility(page2, visible=True)
```

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| 2 contexts per test | 6 contexts for stress tests | Phase 64 | Tests realistic concurrent load |
| Sequential game testing | Concurrent game orchestration | Phase 64 | Validates server multi-game handling |
| Single timeout | Per-game timeout tracking | Phase 64 | Better failure isolation |

**Current infrastructure limitations:**
- `player_contexts` fixture limited to 2 contexts
- No multi-game orchestration helper
- Test timeouts assume single-game duration

## Open Questions

Things that couldn't be fully resolved:

1. **Optimal number of contexts per browser instance**
   - What we know: Contexts are lightweight (KB), browsers can host 20-50+
   - What's unclear: Performance threshold for this specific game (WebRTC + Pyodide)
   - Recommendation: Start with 6 contexts/1 browser. Monitor memory. Scale if needed.

2. **Server scaling limits**
   - What we know: FIFO matchmaker handles concurrent arrivals
   - What's unclear: Maximum concurrent games server supports under load
   - Recommendation: 3 games (6 participants) is conservative. Monitor server logs.

3. **CDP session limits**
   - What we know: Each page can have its own CDP session
   - What's unclear: Maximum CDP sessions per browser instance
   - Recommendation: Track CDP sessions explicitly; detach in cleanup.

## Sources

### Primary (HIGH confidence)
- [Playwright Browser Contexts](https://playwright.dev/python/docs/browser-contexts) - Official isolation documentation
- [Playwright pytest Plugin](https://playwright.dev/python/docs/test-runners) - `new_context` fixture, scopes
- Existing `tests/conftest.py` - `player_contexts` fixture pattern
- Existing `tests/fixtures/game_helpers.py` - `run_full_episode_flow_until_gameplay`

### Secondary (MEDIUM confidence)
- [Scaling Headless Browsers: Contexts vs Instances](https://dev.to/deepak_mishra_35863517037/scaling-headless-browsers-managing-contexts-vs-instances-1d73) - Context memory (KB) vs browser (50-150MB)
- [BrowserStack Playwright Config Guide](https://www.browserstack.com/guide/playwright-config) - Worker configuration
- [Playwright Multi-User Testing Fixtures](https://dev.to/gustavomeilus/scaling-your-playwright-tests-a-fixture-for-multi-user-multi-context-worlds-53i4) - Worker-scoped fixture patterns

### Tertiary (LOW confidence)
- GitHub issues on Playwright memory leaks - May not apply with proper cleanup
- Medium articles on production scaling - Over-engineered for test scenarios

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH - Extending existing proven infrastructure
- Architecture patterns: HIGH - Based on working `player_contexts` pattern
- Pitfalls: MEDIUM - Some from community reports, need validation
- Resource limits: MEDIUM - Theoretical limits, 6 contexts should be well within

**Research date:** 2026-02-03
**Valid until:** 60 days (stable domain, infrastructure patterns don't change quickly)
