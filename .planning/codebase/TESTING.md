# Testing Patterns

**Analysis Date:** 2026-02-07

## Test Framework

**Runner:**
- pytest >= 8.0
- Config: `pytest.ini`

**Browser Automation:**
- Playwright >= 1.49 (via `pytest-playwright >= 0.6`)
- Used for E2E tests that drive browser-based multiplayer game sessions

**Timeout:**
- `pytest-timeout >= 2.3`
- Per-test timeouts via `@pytest.mark.timeout(N)` decorator

**Assertion Library:**
- Built-in `assert` statements (pytest native)
- No third-party assertion library

**Mocking:**
- `unittest.mock.MagicMock` for unit test mocking (see `tests/unit/test_latency_fifo_integration.py`)

**Run Commands:**
```bash
pytest tests/unit/             # Run unit tests only
pytest tests/e2e/ --headed     # Run E2E tests (MUST be headed mode)
pytest -v --tb=short           # Run all tests with verbose output (default addopts)
pytest tests/ -k "test_name"   # Run specific test by name
```

**CRITICAL: E2E tests MUST run in headed mode.** Playwright's headless mode sets `document.hidden=true`, which causes the game's FocusManager to skip frame processing. The `tests/e2e/conftest.py` forces `--headed` automatically for E2E tests.

## Test File Organization

**Location:**
- Separate `tests/` directory at project root (not co-located with source)
- Unit tests in `tests/unit/`
- E2E tests in `tests/e2e/`
- Shared fixtures/helpers in `tests/fixtures/`

**Naming:**
- Test files: `test_*.py` (configured in `pytest.ini`)
- Test classes: `Test*` (e.g., `TestLatencyFIFOMatchmaker`, `TestLatencyFIFOIntegration`)
- Test functions: `test_*` (e.g., `test_basic_match_within_threshold`)

**Structure:**
```
tests/
├── __init__.py
├── conftest.py                     # Shared fixtures (server lifecycle, browser contexts)
├── e2e/
│   ├── __init__.py
│   ├── conftest.py                 # E2E-specific config (force headed mode)
│   ├── test_infrastructure.py      # Smoke test for test infra
│   ├── test_multiplayer_basic.py   # Basic multiplayer flow
│   ├── test_data_comparison.py     # Export parity validation
│   ├── test_latency_injection.py   # Network latency stress tests
│   ├── test_focus_loss_data_parity.py  # Tab visibility tests
│   ├── test_lifecycle_stress.py    # Multi-episode lifecycle
│   ├── test_multi_participant.py   # 6-player concurrent stress
│   ├── test_network_disruption.py  # Packet loss / network disruption
│   └── test_scene_isolation.py     # Multi-scene flow validation
├── unit/
│   ├── __init__.py
│   ├── test_latency_fifo_matchmaker.py      # Matchmaker unit tests
│   └── test_latency_fifo_integration.py     # Matchmaker integration tests
└── fixtures/
    ├── __init__.py
    ├── game_helpers.py             # Game automation (wait_for_*, click_*, get_*)
    ├── network_helpers.py          # CDP latency/packet loss injection
    ├── input_helpers.py            # Keyboard action injection
    ├── export_helpers.py           # Export file collection and comparison
    └── multi_participant.py        # Multi-game orchestration helpers
```

## Test Structure

**Unit Test Pattern:**
```python
# tests/unit/test_latency_fifo_matchmaker.py
from interactive_gym.server.matchmaker import LatencyFIFOMatchmaker, MatchCandidate


class TestLatencyFIFOMatchmaker:
    """Tests for LatencyFIFOMatchmaker."""

    def test_basic_match_within_threshold(self):
        """Success Criteria 1+2: match when sum of RTTs <= threshold."""
        m = LatencyFIFOMatchmaker(max_server_rtt_ms=200)
        arriving = MatchCandidate(subject_id="a", rtt_ms=50)
        waiting = [MatchCandidate(subject_id="b", rtt_ms=80)]
        result = m.find_match(arriving, waiting, group_size=2)
        assert result is not None
        ids = [c.subject_id for c in result]
        assert "a" in ids
        assert "b" in ids
        assert len(result) == 2
```

**E2E Test Pattern:**
```python
# tests/e2e/test_multiplayer_basic.py
import pytest
from tests.fixtures.game_helpers import (
    wait_for_socket_connected,
    wait_for_game_canvas,
    wait_for_game_object,
    wait_for_episode_complete,
    get_game_state,
    click_advance_button,
    click_start_button,
)
from tests.fixtures.network_helpers import set_tab_visibility


@pytest.mark.timeout(300)  # 5 minutes max for full flow
def test_two_players_connect_and_complete_episode(flask_server, player_contexts):
    """Test that two players can connect, match, and complete an episode."""
    page1, page2 = player_contexts
    base_url = flask_server["url"]

    # Navigate
    page1.goto(base_url)
    page2.goto(base_url)

    # Wait for socket connections
    wait_for_socket_connected(page1)
    wait_for_socket_connected(page2)

    # Progress through UI
    click_advance_button(page1)
    click_advance_button(page2)
    click_start_button(page1)
    click_start_button(page2)

    # Wait for game
    wait_for_game_canvas(page1, timeout=90000)
    wait_for_game_canvas(page2, timeout=90000)
    wait_for_game_object(page1)
    wait_for_game_object(page2)

    # Override visibility for automation
    set_tab_visibility(page1, visible=True)
    set_tab_visibility(page2, visible=True)

    # Verify state
    state1 = get_game_state(page1)
    state2 = get_game_state(page2)
    assert state1["gameId"] == state2["gameId"]

    # Wait for completion
    wait_for_episode_complete(page1, episode_num=1, timeout=180000)
    wait_for_episode_complete(page2, episode_num=1, timeout=180000)
```

## Fixtures

### Server Fixtures (in `tests/conftest.py`)

**`flask_server` (module scope):**
- Starts Flask server as subprocess on port 5702
- Uses test-specific config: `overcooked_human_human_multiplayer_test`
- Polls health endpoint until ready (max 30 retries)
- Yields `{"url": base_url, "process": process}`
- Robust teardown: SIGTERM -> wait -> SIGKILL -> kill process group -> verify port free

**`flask_server_fresh` (function scope):**
- Same as `flask_server` but fresh per test (port 5705)
- Use for tests requiring clean server state between runs

**`flask_server_scene_isolation` (function scope):**
- Uses scene isolation test config (port 5707)
- Multi-scene flow: StartScene -> GymScene -> FeedbackScene -> EndScene

**`flask_server_multi_episode_fresh` (function scope):**
- Uses multi-episode test config (port 5706)
- Yields additional metadata: `num_episodes`, `experiment_id`

**`flask_server_focus_timeout` (module scope):**
- Uses focus timeout test config (port 5704)
- `focus_timeout_ms=10000` (10 second focus loss timeout)

### Browser Fixtures (in `tests/conftest.py`)

**`browser_type_launch_args` (session scope):**
- Override for WebRTC compatibility flags:
  - `--disable-features=WebRtcHideLocalIpsWithMdns`
  - `--use-fake-ui-for-media-stream`
  - `--allow-insecure-localhost`

**`player_contexts` (function scope):**
- Creates 2 isolated browser contexts with Chrome user agent
- Yields `(page1, page2)`
- Cleanup: closes contexts

**`multi_participant_contexts` (function scope):**
- Creates 6 isolated browser contexts for stress testing
- Yields `(page1, page2, page3, page4, page5, page6)`
- Cleanup: close WebRTC connections, disconnect sockets, close contexts, 5s pause for server cleanup

### Test-local Fixtures

**`clean_data_dir` (in `tests/e2e/test_data_comparison.py`):**
```python
@pytest.fixture
def clean_data_dir():
    """Clean data directory before each test to avoid stale export files."""
    experiment_id = get_experiment_id()
    data_dir = f"data/{experiment_id}"
    if os.path.exists(data_dir):
        shutil.rmtree(data_dir)
    os.makedirs(data_dir, exist_ok=True)
    yield data_dir
```

## Helper Modules (Test Fixtures)

### Game Helpers (`tests/fixtures/game_helpers.py`)

Core automation functions for driving the browser-based game:

| Function | Purpose |
|----------|---------|
| `wait_for_socket_connected(page)` | Wait for SocketIO connection |
| `wait_for_game_canvas(page, timeout)` | Wait for Phaser canvas visible |
| `wait_for_game_object(page, timeout)` | Wait for `window.game` initialized |
| `wait_for_episode_complete(page, episode_num, timeout)` | Wait for episode counter |
| `get_game_state(page)` | Get `{state, frameNumber, numEpisodes, gameId, playerId}` |
| `click_advance_button(page)` | Click `#advanceButton` (static scenes) |
| `click_start_button(page)` | Click `#startButton` (gym scenes, waits for enabled) |
| `run_full_episode_flow(page1, page2, base_url)` | Navigate -> connect -> advance -> match -> complete |
| `run_full_episode_flow_until_gameplay(page1, page2, base_url)` | Same but stops after game canvas ready |
| `get_page_debug_info(page)` | Comprehensive page state dump for debugging |

### Network Helpers (`tests/fixtures/network_helpers.py`)

CDP-based network emulation via Chrome DevTools Protocol:

| Function | Purpose |
|----------|---------|
| `apply_latency(page, latency_ms)` | Apply fixed latency via CDP; returns `CDPSession` |
| `JitterEmulator(cdp, base, range)` | Background thread varying latency +/- range |
| `apply_packet_loss(page, percent, latency_ms)` | WebRTC packet loss injection |
| `set_tab_visibility(page, visible)` | Override `document.hidden` for FocusManager |
| `wait_for_focus_manager_state(page, backgrounded)` | Wait for focus state |
| `get_rollback_stats(page)` | Get rollback count and events |
| `get_fast_forward_state(page)` | Get frame tracking for fast-forward detection |

### Input Helpers (`tests/fixtures/input_helpers.py`)

Keyboard action injection:

| Function | Purpose |
|----------|---------|
| `press_action(page, key)` | Single keypress |
| `inject_action_sequence(page, keys, delay_ms)` | Scripted sequence |
| `start_random_actions(page, interval_ms)` | Background JS interval pressing random keys |
| `stop_random_actions(page, interval_id)` | Stop random actions |
| `verify_non_noop_actions(page, min_count)` | Verify non-idle actions recorded |

### Export Helpers (`tests/fixtures/export_helpers.py`)

Export file validation:

| Function | Purpose |
|----------|---------|
| `get_experiment_id()` | Get test experiment ID |
| `get_subject_ids_from_pages(page1, page2)` | Extract subject IDs from game objects |
| `collect_export_files(experiment_id, scene_id, subject_ids, episode_num)` | Construct export file paths |
| `wait_for_export_files(...)` | Poll for export files to appear on disk |
| `run_comparison(path1, path2)` | Invoke comparison script and return `(exit_code, output)` |

## Mocking

**Framework:** `unittest.mock`

**Patterns:**
```python
# tests/unit/test_latency_fifo_integration.py
from unittest.mock import MagicMock

def test_needs_probe_true_when_p2p_set(self):
    """MATCH-03: needs_probe is True when max_p2p_rtt_ms is set."""
    matchmaker = LatencyFIFOMatchmaker(max_server_rtt_ms=200, max_p2p_rtt_ms=150)
    probe_coordinator = MagicMock()

    needs_probe = (
        probe_coordinator is not None
        and matchmaker.max_p2p_rtt_ms is not None
    )
    assert needs_probe is True
```

**What to Mock:**
- External coordinators/services that would require full server infrastructure (e.g., `ProbeCoordinator`)
- MagicMock used for presence checks (e.g., "is probe_coordinator not None?") rather than deep behavior mocking

**What NOT to Mock:**
- Core business logic (matchmakers, state machines) -- test with real instances
- Data classes and configuration objects -- instantiate directly
- For E2E tests, nothing is mocked; real server, real browser, real WebRTC

## Test Data and Factories

**Unit Tests:**
- Inline construction of dataclass instances:
```python
arriving = MatchCandidate(subject_id="a", rtt_ms=50)
waiting = [MatchCandidate(subject_id="b", rtt_ms=80)]
```
- No fixture files or factory libraries used
- Test data is minimal and purpose-built per test

**E2E Tests:**
- Real server with test-specific experiment configs:
  - `interactive_gym/examples/cogrid/overcooked_human_human_multiplayer_test.py` (basic test config)
  - `interactive_gym/examples/cogrid/overcooked_human_human_multiplayer_focus_timeout_test.py`
  - `interactive_gym/examples/cogrid/overcooked_human_human_multiplayer_multi_episode_test.py`
  - `interactive_gym/examples/cogrid/overcooked_human_human_multiplayer_scene_isolation_test.py`
- Test configs have relaxed constraints: no max RTT limit, no focus timeout, shorter episodes

## Coverage

**Requirements:** None enforced (no coverage configuration detected)

**View Coverage:**
```bash
pytest --cov=interactive_gym tests/   # If pytest-cov is installed (not in current deps)
```

## Test Types

**Unit Tests (`tests/unit/`):**
- Pure Python, no server or browser needed
- Test individual classes/functions in isolation
- Fast execution (~milliseconds per test)
- Currently covers: `LatencyFIFOMatchmaker` behavior, `GymScene` API integration
- Test class grouping: `TestLatencyFIFOMatchmaker`, `TestLatencyFIFOIntegration`

**E2E Tests (`tests/e2e/`):**
- Full system tests: real Flask server + real Chromium browsers + real WebRTC
- Slow execution (30 seconds to 5 minutes per test)
- Require headed mode (`--headed`) for WebRTC/FocusManager to work
- Test categories:
  - **Infrastructure** (`test_infrastructure.py`): Smoke test that server starts and browsers connect
  - **Multiplayer basic** (`test_multiplayer_basic.py`): Two players match and complete episode
  - **Data parity** (`test_data_comparison.py`): Both players export identical CSV data
  - **Latency** (`test_latency_injection.py`): Game works under 100ms/200ms/asymmetric/jitter latency
  - **Focus loss** (`test_focus_loss_data_parity.py`): Tab visibility changes handled correctly
  - **Lifecycle** (`test_lifecycle_stress.py`): Multi-episode game completion
  - **Multi-participant** (`test_multi_participant.py`): 6 players in 3 concurrent games
  - **Network disruption** (`test_network_disruption.py`): Packet loss handling
  - **Scene isolation** (`test_scene_isolation.py`): Multi-scene flow (Start -> Game -> Feedback -> End)

**Integration Tests (in `tests/unit/`):**
- `test_latency_fifo_integration.py` tests scene API + matchmaker wiring
- Uses `MagicMock` for components not under test
- Tests logical flow without full server

## Common Patterns

**Timeout-decorated E2E Tests:**
```python
@pytest.mark.timeout(300)  # 5 minutes max
def test_full_flow(flask_server, player_contexts):
    ...
```

**Parametrized Tests:**
```python
@pytest.mark.parametrize("latency_ms", [200, 100])
@pytest.mark.timeout(300)
def test_episode_under_latency(flask_server, player_contexts, latency_ms):
    ...
```

**Visibility Override (required for all E2E game tests):**
```python
# CRITICAL: Override document.hidden for Playwright
# Without this, FocusManager thinks tab is backgrounded and skips frame processing
set_tab_visibility(page1, visible=True)
set_tab_visibility(page2, visible=True)
```

**Browser-evaluated Assertions:**
```python
state = page.evaluate("""() => {
    const game = window.game;
    if (!game) return null;
    return {
        state: game.state,
        frameNumber: game.frameNumber,
        gameId: game.gameId,
        playerId: game.myPlayerId
    };
}""")
assert state["gameId"] == state2["gameId"]
```

**Success Criteria References in Test Docstrings:**
```python
def test_basic_match_within_threshold(self):
    """Success Criteria 1+2: match when sum of RTTs <= threshold."""
    ...

def test_needs_probe_true_when_p2p_set(self):
    """MATCH-03: needs_probe is True when max_p2p_rtt_ms is set."""
    ...
```

## Adding New Tests

**New Unit Test:**
1. Create `tests/unit/test_{module_name}.py`
2. Use `Test*` class grouping with descriptive method names
3. Import classes directly from source: `from interactive_gym.server.matchmaker import ...`
4. No fixtures needed for pure unit tests

**New E2E Test:**
1. Create `tests/e2e/test_{feature_name}.py`
2. Use `flask_server` (or `flask_server_fresh` for isolation) + `player_contexts` fixtures
3. Import helpers from `tests/fixtures/game_helpers.py` and `tests/fixtures/network_helpers.py`
4. Always add `@pytest.mark.timeout(N)` decorator
5. Always call `set_tab_visibility(page, visible=True)` after game canvas is visible
6. If new server config needed, create in `interactive_gym/examples/cogrid/` and add fixture in `tests/conftest.py`

**New Helper Function:**
1. Add to the appropriate `tests/fixtures/` module
2. Follow existing patterns: accept `page: Page` as first arg, use `page.evaluate()` or `page.wait_for_function()`
3. Document with Google-style docstring including Args/Returns

---

*Testing analysis: 2026-02-07*
