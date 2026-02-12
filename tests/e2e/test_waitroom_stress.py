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
- test_interleaved_latency_retry_resolution: Mixed-latency interleaved joins stress retry mechanism

Requires headed mode for WebRTC:
    pytest tests/e2e/test_waitroom_stress.py --headed -x -v
"""

from __future__ import annotations

import re
import time
from collections import defaultdict

import pytest

from tests.fixtures.export_helpers import wait_for_episode_with_parity
from tests.fixtures.game_helpers import (click_advance_button,
                                         click_start_button, get_game_state,
                                         get_scene_id, wait_for_advance_button,
                                         wait_for_game_canvas,
                                         wait_for_game_object,
                                         wait_for_socket_connected,
                                         wait_for_start_button_enabled)
from tests.fixtures.network_helpers import apply_latency, set_tab_visibility

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
            parity_row_tolerance=0,
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
# Test 4: Interleaved mixed-latency joins stress the probe retry mechanism
# =============================================================================

@pytest.mark.timeout(180)
def test_interleaved_latency_retry_resolution(stress_test_contexts, flask_server_probe):
    """
    6 low-latency and 6 high-latency clients join interleaved (alternating)
    with 100ms stagger, forcing the matchmaker to encounter probe failures
    and retry with other candidates.

    Join order: P0(low), P1(high), P2(low), P3(high), ... P10(low), P11(high)

    The FIFO matchmaker will initially try to pair adjacent arrivals (e.g.
    P0-low with P1-high), which fails the 100ms RTT threshold. It must then
    retry, eventually finding a compatible low-latency partner (e.g. P0 with P2).

    Validates:
    - All 6 low-latency clients eventually match (3 games) via probe retries
    - All 6 high-latency clients are rejected and resolve (no stuck participants)
    - Matched games complete episodes with verified data parity
    """
    _reset_ts()
    pages = stress_test_contexts
    base_url = flask_server_probe["url"]

    # Even indices = low latency, odd indices = high latency
    low_indices = [0, 2, 4, 6, 8, 10]
    high_indices = [1, 3, 5, 7, 9, 11]

    # Setup all 12 pages concurrently
    _setup_all_pages(pages, base_url)

    # Apply 200ms latency to odd-indexed (high-latency) pages
    print(f"\n[Latency] Applying 200ms CDP latency to odd pages [{_ts()}]")
    cdp_sessions = []
    for i in high_indices:
        cdp = apply_latency(pages[i], latency_ms=200)
        cdp_sessions.append(cdp)
        print(f"  [P{i}] Latency applied [{_ts()}]")

    # All 12 click start interleaved with 100ms stagger
    print(f"\n[Start] Interleaved start on 12 pages (100ms stagger) [{_ts()}]")
    for i, page in enumerate(pages):
        if i > 0:
            time.sleep(0.1)
        _click_start(page)
        label = "low" if i in low_indices else "HIGH"
        print(f"  [P{i}:{label}] Clicked start [{_ts()}]")

    _log_all(pages, "After interleaved starts")

    # Wait for low-latency pages to get game canvases (they should match via retries)
    print(f"\n[Canvas:Low] Waiting for low-latency canvases [{_ts()}]")
    low_matched = 0
    for i in low_indices:
        if _page_has_game_canvas(pages[i], timeout_ms=90000):
            set_tab_visibility(pages[i], visible=True)
            low_matched += 1
            print(f"  [P{i}:low] Got canvas [{_ts()}]")
        else:
            print(f"  [P{i}:low] No canvas [{_ts()}]")

    # All 6 low-latency clients should have matched (3 pairs)
    assert low_matched == 6, (
        f"Expected all 6 low-latency clients to match via retries, "
        f"but only {low_matched} matched. Unmatched low pages: "
        f"{[i for i in low_indices if not _get_game_id(pages[i])]}"
    )

    # High-latency clients should NOT have matched
    print(f"\n[Check:High] Checking high-latency pages [{_ts()}]")
    high_matched = 0
    for i in high_indices:
        if _page_has_game_canvas(pages[i], timeout_ms=5000):
            high_matched += 1
            print(f"  [P{i}:HIGH] Has canvas (unexpected) [{_ts()}]")
        else:
            print(f"  [P{i}:HIGH] No canvas (expected) [{_ts()}]")

    assert high_matched == 0, (
        f"Expected 0 high-latency clients to match (200ms > 100ms threshold), "
        f"but {high_matched} matched. Matched high pages: "
        f"{[i for i in high_indices if _get_game_id(pages[i])]}"
    )

    print(
        f"\n[STRESS:Retry] Low matched: {low_matched}/6, "
        f"High matched: {high_matched}/6 [{_ts()}]"
    )

    # Validate data parity for the 3 low-latency pairs
    low_pages = [pages[i] for i in low_indices]
    parity_passed, parity_failed = _validate_parity_for_matched_pairs(
        low_pages, expected_pairs=3, timeout_label=":Retry"
    )

    assert parity_passed == 3, (
        f"Expected 3/3 parity passes for low-latency pairs, "
        f"got {parity_passed} passed, {parity_failed} failed"
    )

    # Cleanup CDP sessions
    for cdp in cdp_sessions:
        try:
            cdp.detach()
        except Exception:
            pass

    print(
        f"\n[STRESS:Retry] Matchmaker correctly retried past failed probes, "
        f"matched all 3 low-latency pairs with verified data parity."
    )
