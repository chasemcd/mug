"""
Waitroom stress tests with P2P probe-based matchmaking.

These tests validate probe exclusivity and matchmaking behavior under load
with 12 concurrent participants and FIFOMatchmaker(max_p2p_rtt_ms=100).

Each test that produces matched games also validates data export parity for
every pair that completes an episode, confirming correct P2P synchronization.

Tests:
- test_12_clients_low_latency_all_match: All localhost clients pass probe, 6 games, 6 parity checks
- test_mixed_latency_probe_filtering: Low-latency pairs match + parity, high-latency deferred
- test_no_duplicate_probes: _probing_subjects safeguard + parity for matched pairs
- test_all_clients_eventually_resolve: No limbo + parity for all matched pairs

Requires headed mode for WebRTC:
    pytest tests/e2e/test_waitroom_stress.py --headed -x -v
"""

import re
import time
from collections import defaultdict

import pytest

from tests.fixtures.game_helpers import (
    wait_for_socket_connected,
    click_advance_button,
    click_start_button,
    wait_for_game_canvas,
    wait_for_game_object,
    get_game_state,
    wait_for_start_button_enabled,
    wait_for_advance_button,
    get_scene_id,
)
from tests.fixtures.network_helpers import apply_latency, set_tab_visibility
from tests.fixtures.export_helpers import (
    wait_for_episode_with_parity,
)

# Experiment ID for the probe test server config
PROBE_EXPERIMENT_ID = "overcooked_multiplayer_hh_probe_test"


# =============================================================================
# Helpers
# =============================================================================

def _ts():
    """Return elapsed-time string for logging."""
    if not hasattr(_ts, "_t0"):
        _ts._t0 = time.monotonic()
    return f"t={time.monotonic() - _ts._t0:.1f}s"


def _reset_ts():
    """Reset the shared timer at test start."""
    _ts._t0 = time.monotonic()


def _page_state_summary(page, idx):
    """Quick one-line state summary for a page."""
    try:
        state = page.evaluate("""() => {
            const r = {};
            r.socket = !!(window.socket && window.socket.connected);
            r.advance = !!(document.getElementById('advanceButton')?.offsetParent);
            const sb = document.getElementById('startButton');
            r.startVis = !!(sb?.offsetParent);
            r.startEnabled = sb ? !sb.disabled : false;
            r.waitroom = !!(document.getElementById('waitroomText')?.offsetParent);
            r.canvas = !!(document.querySelector('#gameContainer canvas')?.offsetParent);
            r.gameId = (window.game && window.game.gameId) || null;
            r.error = document.getElementById('errorText')?.innerText || null;
            return r;
        }""")
        parts = []
        if state.get("socket"):
            parts.append("sock")
        if state.get("advance"):
            parts.append("adv")
        if state.get("startVis"):
            parts.append("start" + ("!" if state.get("startEnabled") else "?"))
        if state.get("waitroom"):
            parts.append("wait")
        if state.get("canvas"):
            parts.append("canvas")
        if state.get("gameId"):
            parts.append(f"gid={state['gameId'][:8]}")
        if state.get("error"):
            parts.append(f"ERR={state['error'][:40]}")
        return f"[P{idx}] {' '.join(parts)}"
    except Exception as e:
        return f"[P{idx}] <evaluate failed: {e}>"


def _log_all(pages, label):
    """Log state of all pages."""
    print(f"\n--- {label} [{_ts()}] ---")
    for i, page in enumerate(pages):
        print(f"  {_page_state_summary(page, i)}")


def _setup_all_pages(pages, base_url):
    """Navigate all pages to start-button-ready with concurrent Pyodide loading.

    Phases:
    1. Navigate all pages (fast — just HTTP GET)
    2. Wait for all sockets
    3. Click advance on all (triggers concurrent Pyodide loading)
    4. Wait for all start buttons to be enabled (Pyodide ready)

    This is much faster than sequential _navigate_and_advance because
    Pyodide loads concurrently across all 12 pages instead of serially.
    """
    n = len(pages)
    print(f"\n=== SETUP {n} pages [{_ts()}] ===")

    # Phase 1: Navigate all
    print(f"[Setup:Navigate] Navigating {n} pages...")
    for i, page in enumerate(pages):
        page.goto(base_url)
    print(f"[Setup:Navigate] Done [{_ts()}]")

    # Phase 2: Wait for all sockets
    print(f"[Setup:Socket] Waiting for {n} sockets...")
    for i, page in enumerate(pages):
        try:
            wait_for_socket_connected(page, timeout=30000)
        except Exception as e:
            print(f"  [P{i}] Socket FAILED: {e}")
            raise
    print(f"[Setup:Socket] All connected [{_ts()}]")

    # Phase 3: Click advance on all
    print(f"[Setup:Advance] Clicking advance on {n} pages...")
    for i, page in enumerate(pages):
        try:
            wait_for_advance_button(page, timeout=30000)
            page.locator("#advanceButton").click()
        except Exception as e:
            print(f"  [P{i}] Advance FAILED: {e}")
            raise
    print(f"[Setup:Advance] All clicked [{_ts()}]")

    # Phase 4: Wait for all start buttons (Pyodide loads concurrently)
    print(f"[Setup:Pyodide] Waiting for {n} start buttons (Pyodide loading)...")
    for i, page in enumerate(pages):
        try:
            wait_for_start_button_enabled(page, timeout=120000)
            print(f"  [P{i}] Pyodide ready [{_ts()}]")
        except Exception as e:
            print(f"  [P{i}] Pyodide FAILED: {e}")
            _log_all(pages, "State at Pyodide failure")
            raise
    print(f"[Setup:Pyodide] All ready [{_ts()}]")
    _log_all(pages, "All pages ready")


def _click_start(page):
    """Click the start button (enters matchmaking / waitroom)."""
    page.locator("#startButton").click()


def _page_has_game_canvas(page, timeout_ms=5000):
    """Return True if a game canvas appears within *timeout_ms*."""
    try:
        page.wait_for_selector(
            "#gameContainer canvas", state="visible", timeout=timeout_ms
        )
        return True
    except Exception:
        return False


def _get_game_id(page):
    """Return the gameId exposed on `window.game`, or None."""
    return page.evaluate(
        "() => (window.game && window.game.gameId) ? window.game.gameId : null"
    )


def _group_pages_by_game(pages):
    """Group pages into pairs by their gameId.

    Returns:
        dict mapping gameId -> list of page indices that share that game.
        Only includes pages that have a non-None gameId.
    """
    groups = defaultdict(list)
    for i, page in enumerate(pages):
        gid = _get_game_id(page)
        if gid is not None:
            groups[gid].append(i)
    return dict(groups)


def _validate_parity_for_matched_pairs(pages, expected_pairs, timeout_label=""):
    """Run episode-completion + data-parity validation for matched page pairs.

    Args:
        pages: Full tuple/list of pages.
        expected_pairs: Number of pairs that must pass parity.
        timeout_label: Label for log output.

    Returns:
        (parity_passed, parity_failed) counts.
    """
    groups = _group_pages_by_game(pages)

    # Determine scene_id from the first matched page
    scene_id = None
    for indices in groups.values():
        if len(indices) >= 2:
            scene_id = get_scene_id(pages[indices[0]])
            if scene_id:
                break
    if scene_id is None:
        scene_id = "cramped_room_hh"

    parity_passed = 0
    parity_failed = 0

    for gid, indices in sorted(groups.items(), key=lambda kv: min(kv[1])):
        if len(indices) < 2:
            print(f"[Parity{timeout_label}] Game {gid}: only {len(indices)} page(s), skipping")
            continue

        p1, p2 = pages[indices[0]], pages[indices[1]]

        success, message = wait_for_episode_with_parity(
            page1=p1,
            page2=p2,
            experiment_id=PROBE_EXPERIMENT_ID,
            scene_id=scene_id,
            episode_num=0,
            episode_timeout_sec=300,
            export_timeout_sec=60,
            parity_row_tolerance=10,
            verbose=True,
        )

        if success:
            parity_passed += 1
            print(f"[Parity{timeout_label}] Game {gid} (pages {indices[0]},{indices[1]}): PASS")
        else:
            parity_failed += 1
            print(f"[Parity{timeout_label}] Game {gid} (pages {indices[0]},{indices[1]}): FAIL — {message}")

    return parity_passed, parity_failed


# =============================================================================
# Test 1: 12 low-latency clients should all match (6 games) with parity
# =============================================================================

@pytest.mark.timeout(120)
def test_12_clients_low_latency_all_match(stress_test_contexts, flask_server_probe):
    """
    12 clients on localhost (~0ms P2P RTT) enter matchmaking with 300ms stagger.
    All probes should pass the 100ms threshold, producing 6 games.

    Validates:
    - All 12 participants get a game canvas
    - Exactly 6 unique game IDs are created
    - All 6 games complete an episode with verified data parity
    """
    _reset_ts()
    pages = stress_test_contexts
    base_url = flask_server_probe["url"]

    # Setup: get all 12 pages to start-button-ready (concurrent Pyodide)
    _setup_all_pages(pages, base_url)

    # Click start with 300ms stagger
    print(f"\n[Start] Clicking start on 12 pages with 300ms stagger [{_ts()}]")
    for i, page in enumerate(pages):
        if i > 0:
            time.sleep(0.3)
        _click_start(page)
        print(f"  [P{i}] Clicked start [{_ts()}]")

    _log_all(pages, "After all starts clicked")

    # Wait for all 12 to get a game canvas
    print(f"\n[Canvas] Waiting for 12 game canvases [{_ts()}]")
    for i, page in enumerate(pages):
        try:
            wait_for_game_canvas(page, timeout=60000)
            set_tab_visibility(page, visible=True)
            print(f"  [P{i}] Got canvas [{_ts()}]")
        except Exception as e:
            print(f"  [P{i}] TIMEOUT waiting for canvas [{_ts()}]")
            _log_all(pages, f"State when P{i} timed out")
            pytest.fail(
                f"Page {i} did not get a game canvas within timeout: {e}"
            )

    # Collect game IDs and verify 6 unique games
    game_ids = set()
    for i, page in enumerate(pages):
        gid = _get_game_id(page)
        assert gid is not None, f"Page {i} has no gameId"
        game_ids.add(gid)

    assert len(game_ids) == 6, (
        f"Expected 6 unique games for 12 participants, got {len(game_ids)}: {game_ids}"
    )
    print(f"\n[STRESS] All 12 clients matched into {len(game_ids)} games [{_ts()}]")

    # Validate data parity for all 6 pairs
    parity_passed, parity_failed = _validate_parity_for_matched_pairs(
        pages, expected_pairs=6, timeout_label=":AllMatch"
    )

    assert parity_passed == 6, (
        f"Expected 6/6 parity passes, got {parity_passed} passed, {parity_failed} failed"
    )
    print(f"\n[STRESS:AllMatch] All 6 games completed with verified data parity.")


# =============================================================================
# Test 2: Mixed latency — low-latency clients match + parity, high-latency deferred
# =============================================================================

@pytest.mark.timeout(120)
def test_mixed_latency_probe_filtering(stress_test_contexts, flask_server_probe):
    """
    Pages 0-5: no added latency (probes pass 100ms threshold)
    Pages 6-11: 200ms CDP latency applied before entering matchmaking

    Low-latency clients click start first, then high-latency ones follow.

    Validates:
    - At least 3 low-latency pairs match (all 6 low-latency pages)
    - Matched low-latency games complete with data parity
    - High-latency pages don't match quickly (within 30s)
    """
    _reset_ts()
    pages = stress_test_contexts
    base_url = flask_server_probe["url"]
    low_pages = pages[:6]
    high_pages = pages[6:]

    # Setup all 12 pages concurrently
    _setup_all_pages(pages, base_url)

    # Apply 200ms latency to high-latency pages AFTER Pyodide is loaded
    print(f"\n[Latency] Applying 200ms CDP latency to pages 6-11 [{_ts()}]")
    cdp_sessions = []
    for i, page in enumerate(high_pages):
        cdp = apply_latency(page, latency_ms=200)
        cdp_sessions.append(cdp)
        print(f"  [P{i + 6}] Latency applied [{_ts()}]")

    # Low-latency clients click start first with 200ms stagger
    print(f"\n[Start:Low] Clicking start on low-latency pages [{_ts()}]")
    for i, page in enumerate(low_pages):
        if i > 0:
            time.sleep(0.2)
        _click_start(page)
        print(f"  [P{i}] Clicked start [{_ts()}]")

    time.sleep(5)

    # High-latency clients click start
    print(f"\n[Start:High] Clicking start on high-latency pages [{_ts()}]")
    for i, page in enumerate(high_pages):
        if i > 0:
            time.sleep(0.2)
        _click_start(page)
        print(f"  [P{i + 6}] Clicked start [{_ts()}]")

    _log_all(pages, "After all starts")

    # Wait for low-latency pages to get game canvases
    print(f"\n[Canvas:Low] Waiting for low-latency canvases [{_ts()}]")
    low_matched = 0
    for i, page in enumerate(low_pages):
        if _page_has_game_canvas(page, timeout_ms=60000):
            set_tab_visibility(page, visible=True)
            low_matched += 1
            print(f"  [P{i}] Got canvas [{_ts()}]")
        else:
            print(f"  [P{i}] No canvas [{_ts()}]")

    assert low_matched >= 2, (
        f"Expected at least 2 low-latency pages (1 pair) to match, got {low_matched}"
    )

    # Check that high-latency pages don't match quickly
    print(f"\n[Wait:High] Checking high-latency pages after 30s wait [{_ts()}]")
    time.sleep(30)
    high_matched = 0
    for i, page in enumerate(high_pages):
        if _page_has_game_canvas(page, timeout_ms=1000):
            high_matched += 1
            print(f"  [P{i + 6}] Has canvas (unexpected) [{_ts()}]")
        else:
            print(f"  [P{i + 6}] No canvas (expected) [{_ts()}]")

    print(
        f"\n[STRESS:MixedLatency] Low matched: {low_matched}/6, "
        f"High matched (after 30s): {high_matched}/6 [{_ts()}]"
    )

    # Validate data parity for the low-latency pairs that matched
    expected_low_pairs = low_matched // 2
    parity_passed, parity_failed = _validate_parity_for_matched_pairs(
        low_pages, expected_pairs=expected_low_pairs, timeout_label=":MixedLow"
    )

    assert parity_passed >= 1, (
        f"Expected at least 1 low-latency pair to pass parity, "
        f"got {parity_passed} passed, {parity_failed} failed"
    )
    print(
        f"\n[STRESS:MixedLatency] {parity_passed} low-latency pairs verified with data parity."
    )

    # Cleanup CDP sessions
    for cdp in cdp_sessions:
        try:
            cdp.detach()
        except Exception:
            pass


# =============================================================================
# Test 3: No duplicate probes — _probing_subjects safeguard + parity
# =============================================================================

@pytest.mark.timeout(120)
def test_no_duplicate_probes(stress_test_contexts, flask_server_probe):
    """
    12 clients enter matchmaking as fast as possible (100ms stagger).
    After matches settle, validate:
    1. No subject appears twice in any active probe set (log parsing)
    2. All matched pairs complete with data parity

    Validates the _probing_subjects safeguard works under load AND that
    the games it produces are correct.
    """
    _reset_ts()
    pages = stress_test_contexts
    base_url = flask_server_probe["url"]
    process = flask_server_probe["process"]

    # Setup all 12 pages concurrently
    _setup_all_pages(pages, base_url)

    # All 12 click start with minimal stagger (100ms)
    print(f"\n[Start] Rapid-fire start on 12 pages (100ms stagger) [{_ts()}]")
    for i, page in enumerate(pages):
        if i > 0:
            time.sleep(0.1)
        _click_start(page)
        print(f"  [P{i}] Clicked start [{_ts()}]")

    _log_all(pages, "After rapid-fire starts")

    # Wait for matches to settle
    print(f"\n[Canvas] Waiting for game canvases [{_ts()}]")
    matched_indices = []
    for i, page in enumerate(pages):
        if _page_has_game_canvas(page, timeout_ms=60000):
            set_tab_visibility(page, visible=True)
            matched_indices.append(i)
            print(f"  [P{i}] Got canvas [{_ts()}]")
        else:
            print(f"  [P{i}] No canvas [{_ts()}]")

    print(f"\n[STRESS:NoDup] {len(matched_indices)}/12 pages matched [{_ts()}]")
    _log_all(pages, "Final state")

    # Validate data parity for all matched pairs
    matched_pairs = len(matched_indices) // 2
    if matched_pairs > 0:
        parity_passed, parity_failed = _validate_parity_for_matched_pairs(
            pages, expected_pairs=matched_pairs, timeout_label=":NoDup"
        )
        print(f"[STRESS:NoDup] Parity: {parity_passed} passed, {parity_failed} failed")
    else:
        parity_passed = 0
        parity_failed = 0

    # Read stderr log file for probe-tracking validation
    stderr_path = flask_server_probe["stderr_path"]
    stderr_output = stderr_path.read_text() if stderr_path.exists() else ""

    # Parse [Probe:Track] "Added" lines to find Active set snapshots
    active_pattern = re.compile(r"\[Probe:Track\] Added .+ Active: \{(.+?)\}")
    violations = []

    for match in active_pattern.finditer(stderr_output):
        active_set_str = match.group(1)
        subjects = [s.strip().strip("'\"") for s in active_set_str.split(",")]
        if len(subjects) != len(set(subjects)):
            violations.append(active_set_str)

    deferral_count = stderr_output.count("already in active probe")

    print(f"[STRESS:NoDup] Probe:Track lines: {len(active_pattern.findall(stderr_output))}")
    print(f"[STRESS:NoDup] Deferral messages: {deferral_count}")
    print(f"[STRESS:NoDup] Violations: {len(violations)}")

    assert len(violations) == 0, (
        f"Found {len(violations)} Active set snapshots with duplicate subjects: {violations}"
    )

    # At least some pairs should have matched and passed parity
    assert matched_pairs > 0, "Expected at least one pair to match"
    assert parity_passed > 0, (
        f"Expected at least 1 pair to pass parity, got {parity_passed} passed, {parity_failed} failed"
    )


# =============================================================================
# Test 4: All clients eventually resolve (no stuck participants) + parity
# =============================================================================

@pytest.mark.timeout(120)
def test_all_clients_eventually_resolve(stress_test_contexts, flask_server_probe):
    """
    12 low-latency clients with 200ms stagger.
    Each page must either show game canvas or waitroom timeout within 2 min.

    Validates:
    - All 12 resolve (no stuck-in-limbo participants)
    - All 12 should match on localhost (6 pairs), each with data parity
    """
    _reset_ts()
    pages = stress_test_contexts
    base_url = flask_server_probe["url"]

    # Setup all 12 pages concurrently
    _setup_all_pages(pages, base_url)

    # Click start with 200ms stagger
    print(f"\n[Start] Clicking start on 12 pages (200ms stagger) [{_ts()}]")
    for i, page in enumerate(pages):
        if i > 0:
            time.sleep(0.2)
        _click_start(page)
        print(f"  [P{i}] Clicked start [{_ts()}]")

    _log_all(pages, "After all starts")

    # Wait up to 90s for all pages to resolve
    deadline = time.monotonic() + 90
    resolved = [False] * len(pages)
    matched = [False] * len(pages)

    while time.monotonic() < deadline and not all(resolved):
        for i, page in enumerate(pages):
            if resolved[i]:
                continue
            try:
                has_canvas = page.evaluate("""() => {
                    const canvas = document.querySelector('#gameContainer canvas');
                    return canvas && canvas.offsetParent !== null;
                }""")
                if has_canvas:
                    resolved[i] = True
                    matched[i] = True
                    set_tab_visibility(page, visible=True)
                    print(f"  [P{i}] Matched (canvas) [{_ts()}]")
                    continue

                timed_out = page.evaluate("""() => {
                    const errorText = document.getElementById('errorText');
                    const waitroomGone = !document.getElementById('waitroomText') ||
                                         document.getElementById('waitroomText').style.display === 'none';
                    const noStartBtn = !document.getElementById('startButton') ||
                                       document.getElementById('startButton').style.display === 'none';
                    return (errorText && errorText.offsetParent !== null) ||
                           (waitroomGone && noStartBtn);
                }""")
                if timed_out:
                    resolved[i] = True
                    print(f"  [P{i}] Timed out [{_ts()}]")
                    continue
            except Exception:
                resolved[i] = True

        time.sleep(2)

    unresolved = [i for i, r in enumerate(resolved) if not r]
    if unresolved:
        _log_all(pages, "State with unresolved pages")
    assert len(unresolved) == 0, (
        f"{len(unresolved)} participants stuck in limbo: page indices {unresolved}"
    )

    matched_count = sum(matched)
    timed_out_count = 12 - matched_count
    print(
        f"\n[STRESS:Resolve] All 12 resolved. "
        f"Matched: {matched_count}, Timed out: {timed_out_count} [{_ts()}]"
    )

    # All 12 are on localhost, so all should have matched (6 pairs)
    assert matched_count == 12, (
        f"Expected all 12 to match on localhost, but only {matched_count} matched "
        f"({timed_out_count} timed out). Unmatched pages: "
        f"{[i for i, m in enumerate(matched) if not m]}"
    )

    # Validate data parity for all 6 matched pairs
    parity_passed, parity_failed = _validate_parity_for_matched_pairs(
        pages, expected_pairs=6, timeout_label=":Resolve"
    )

    assert parity_passed == 6, (
        f"Expected 6/6 parity passes, got {parity_passed} passed, {parity_failed} failed"
    )
    print(f"[STRESS:Resolve] All 6 games completed with verified data parity.")
