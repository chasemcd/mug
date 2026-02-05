"""
Worker migration validation tests for VALID-03 and VALID-04.

These tests validate that the Pyodide Web Worker migration (v1.16) does not
degrade game loop performance or introduce memory leaks:

- VALID-03: Step latency with Worker is not degraded compared to direct Pyodide baseline.
  The Worker adds a postMessage round-trip to every step() call; this test measures
  whether that overhead is acceptable (< 50ms median, vs ~10-20ms baseline).

- VALID-04: No memory growth observed across 10 consecutive game sessions.
  Worker lifecycle management (init/destroy) must properly release resources.
  This test runs 10 sequential sessions and checks JS heap size stability.

IMPORTANT: These tests require headed mode for WebRTC.
Run with: PWHEADED=1 python -m pytest tests/e2e/test_worker_validation.py -v
"""
import time

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


@pytest.mark.timeout(300)
def test_step_latency_not_degraded(flask_server, player_contexts):
    """
    VALID-03: Measure step() round-trip time during a multiplayer game.

    The game has pipeline metrics instrumentation (Phase 28) that tracks
    stepCallTimestamp and stepReturnTimestamp on every frame. This test
    reads those metrics after 100+ frames of gameplay and asserts that
    the median step latency is under 50ms.

    Baseline: Direct Pyodide step() was ~10-20ms for Overcooked.
    Worker adds ~1-5ms overhead for postMessage serialization.
    Threshold: 50ms (conservative, catches real regressions).
    """
    page1, page2 = player_contexts
    base_url = flask_server["url"]

    # Step 1: Navigate and connect
    page1.goto(base_url)
    page2.goto(base_url)
    wait_for_socket_connected(page1)
    wait_for_socket_connected(page2)

    # Step 2: Pass instructions scene
    click_advance_button(page1)
    click_advance_button(page2)

    # Step 3: Start multiplayer
    click_start_button(page1)
    click_start_button(page2)

    # Step 4: Wait for game to start
    wait_for_game_canvas(page1, timeout=90000)
    wait_for_game_canvas(page2, timeout=90000)
    wait_for_game_object(page1)
    wait_for_game_object(page2)

    # Step 5: Set tab visibility for Playwright automation
    set_tab_visibility(page1, visible=True)
    set_tab_visibility(page2, visible=True)

    # Step 6: Wait for 100 frames of gameplay to accumulate
    page1.wait_for_function(
        "() => window.game && window.game.frameNumber >= 100",
        timeout=120000,
    )

    # Step 7: Sample step latency at 10 points during gameplay
    latency_samples = []
    for i in range(10):
        metrics = page1.evaluate("""() => {
            const game = window.game;
            if (!game || !game.pipelineMetrics) return null;
            return {
                stepCallTimestamp: game.pipelineMetrics.stepCallTimestamp,
                stepReturnTimestamp: game.pipelineMetrics.stepReturnTimestamp,
                lastStepMs: game.pipelineMetrics.stepReturnTimestamp - game.pipelineMetrics.stepCallTimestamp,
                frameNumber: game.frameNumber,
            };
        }""")

        if metrics and metrics.get("lastStepMs") is not None:
            step_ms = metrics["lastStepMs"]
            if step_ms > 0:  # Filter out invalid/zero measurements
                latency_samples.append(step_ms)
                print(
                    f"  Sample {i + 1}: step={step_ms:.2f}ms "
                    f"(frame {metrics['frameNumber']})"
                )

        time.sleep(0.05)  # 50ms between samples

    # Step 8: Calculate and assert median
    assert len(latency_samples) > 0, "Should have collected at least one latency sample"

    sorted_samples = sorted(latency_samples)
    n = len(sorted_samples)
    if n % 2 == 0:
        median_ms = (sorted_samples[n // 2 - 1] + sorted_samples[n // 2]) / 2.0
    else:
        median_ms = sorted_samples[n // 2]

    print(f"\n--- Step Latency Distribution ---")
    print(f"  Samples: {n}")
    print(f"  Min:    {sorted_samples[0]:.2f}ms")
    print(f"  Median: {median_ms:.2f}ms")
    print(f"  Max:    {sorted_samples[-1]:.2f}ms")
    print(f"  All:    {[f'{s:.2f}' for s in sorted_samples]}")
    print(f"  Threshold: 50ms")
    print(f"  Result: {'PASS' if median_ms < 50 else 'FAIL'}")

    assert median_ms < 50, (
        f"Median step latency {median_ms:.2f}ms exceeds 50ms threshold. "
        f"Worker postMessage overhead may be too high. "
        f"Samples: {[f'{s:.2f}' for s in sorted_samples]}"
    )


@pytest.mark.timeout(3000)
def test_no_memory_growth_across_sessions(flask_server_fresh, browser):
    """
    VALID-04: Run 10 consecutive game sessions and check for memory leaks.

    Each session creates two browser contexts, runs a full multiplayer episode,
    then closes the contexts (triggering Worker.destroy()). After each session,
    JS heap size is captured via the Performance API.

    Assertion: Iteration 10 heap size is not more than 2x iteration 1 heap size.
    If performance.memory is unavailable, the test still validates that 10
    consecutive sessions complete without crashes (basic stability check).
    """
    base_url = flask_server_fresh["url"]
    heap_sizes = []

    chrome_ua = (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    )

    for iteration in range(10):
        print(f"\n--- Session {iteration + 1}/10 ---")

        # Create fresh browser contexts for this session
        context1 = browser.new_context(user_agent=chrome_ua)
        context2 = browser.new_context(user_agent=chrome_ua)
        page1 = context1.new_page()
        page2 = context2.new_page()

        try:
            # Navigate and connect
            page1.goto(base_url)
            page2.goto(base_url)
            wait_for_socket_connected(page1, timeout=30000)
            wait_for_socket_connected(page2, timeout=30000)

            # Pass instructions
            click_advance_button(page1, timeout=30000)
            click_advance_button(page2, timeout=30000)

            # Start multiplayer
            click_start_button(page1, timeout=60000)
            click_start_button(page2, timeout=60000)

            # Wait for game
            wait_for_game_canvas(page1, timeout=120000)
            wait_for_game_canvas(page2, timeout=120000)
            wait_for_game_object(page1, timeout=60000)
            wait_for_game_object(page2, timeout=60000)

            # Set tab visibility
            set_tab_visibility(page1, visible=True)
            set_tab_visibility(page2, visible=True)

            # Wait for episode to complete
            wait_for_episode_complete(page1, episode_num=1, timeout=180000)
            wait_for_episode_complete(page2, episode_num=1, timeout=180000)

            # Capture heap size after episode completes
            memory_info = page1.evaluate("""() => {
                if (performance.memory) {
                    return {
                        usedJSHeapSize: performance.memory.usedJSHeapSize,
                        totalJSHeapSize: performance.memory.totalJSHeapSize,
                    };
                }
                return null;
            }""")

            if memory_info:
                used_mb = memory_info["usedJSHeapSize"] / (1024 * 1024)
                total_mb = memory_info["totalJSHeapSize"] / (1024 * 1024)
                heap_sizes.append(memory_info["usedJSHeapSize"])
                print(
                    f"  Heap: used={used_mb:.1f}MB, "
                    f"total={total_mb:.1f}MB"
                )
            else:
                print("  Warning: performance.memory not available (non-Chrome browser)")
                heap_sizes.append(None)

            # Get final state for logging
            state = get_game_state(page1)
            if state:
                print(
                    f"  Game: episodes={state['numEpisodes']}, "
                    f"frames={state['frameNumber']}"
                )

        finally:
            # Close contexts (triggers Worker.destroy())
            try:
                context1.close()
            except Exception:
                pass
            try:
                context2.close()
            except Exception:
                pass

        # Brief pause between sessions for server cleanup
        time.sleep(3)

    # Analyze heap growth
    valid_sizes = [s for s in heap_sizes if s is not None]

    print(f"\n--- Memory Growth Analysis ---")
    print(f"  Sessions completed: {len(heap_sizes)}")
    print(f"  Valid heap measurements: {len(valid_sizes)}")

    if len(valid_sizes) >= 2:
        first_heap = valid_sizes[0]
        last_heap = valid_sizes[-1]
        growth_ratio = last_heap / first_heap if first_heap > 0 else 0

        print(f"  First session heap: {first_heap / (1024 * 1024):.1f}MB")
        print(f"  Last session heap:  {last_heap / (1024 * 1024):.1f}MB")
        print(f"  Growth ratio: {growth_ratio:.2f}x")
        print(f"  Threshold: 2.0x")
        print(f"  Result: {'PASS' if growth_ratio < 2.0 else 'FAIL'}")

        # Log all measurements
        for i, size in enumerate(valid_sizes):
            print(f"  Session {i + 1}: {size / (1024 * 1024):.1f}MB")

        assert growth_ratio < 2.0, (
            f"Memory grew {growth_ratio:.2f}x between session 1 "
            f"({first_heap / (1024 * 1024):.1f}MB) and session "
            f"{len(valid_sizes)} ({last_heap / (1024 * 1024):.1f}MB). "
            f"Possible memory leak in Worker lifecycle."
        )
    else:
        print(
            "  Skipping heap assertion: performance.memory not available. "
            "10 consecutive sessions completed without crashes (basic stability check)."
        )
        # The test still validates that 10 sessions can complete without errors
