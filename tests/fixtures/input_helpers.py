"""
Keyboard input injection helpers for E2E tests.

Uses Playwright keyboard API to inject actions into the game.
Actions are buffered by ui_utils.js keydown handler.

Action mapping (from controllable_scenes.py):
- ArrowUp -> MoveUp (0)
- ArrowDown -> MoveDown (1)
- ArrowLeft -> MoveLeft (2)
- ArrowRight -> MoveRight (3)
- w/W -> PickupDrop (4)
- q/Q -> Toggle (5)
- (no key) -> Noop (6)
"""

from __future__ import annotations

# Key constants matching controllable_scenes.py action mapping
MOVEMENT_KEYS = ["ArrowUp", "ArrowDown", "ArrowLeft", "ArrowRight"]
ACTION_KEYS = ["w", "q"]
ALL_GAME_KEYS = MOVEMENT_KEYS + ACTION_KEYS


def press_action(page, key: str):
    """
    Press a single game key and release.

    Args:
        page: Playwright page
        key: Key name (ArrowUp, ArrowDown, ArrowLeft, ArrowRight, w, q)
    """
    page.keyboard.press(key)


def inject_action_sequence(page, keys: list, delay_ms: int = 100):
    """
    Inject a scripted sequence of actions with delay between each.

    Args:
        page: Playwright page
        keys: List of key names to press in order
        delay_ms: Delay between key presses (default 100ms)
    """
    for key in keys:
        page.keyboard.press(key)
        page.wait_for_timeout(delay_ms)


def start_random_actions(page, interval_ms: int = 200):
    """
    Start a background interval that presses random game keys.

    Uses page.evaluate to set up a JS interval that triggers
    jQuery keydown events (same method the game uses for input).
    Returns interval ID for later cleanup.

    Args:
        page: Playwright page
        interval_ms: Interval between random actions (default 200ms)

    Returns:
        Interval ID (for stop_random_actions)
    """
    return page.evaluate(
        f"""() => {{
        const keys = ['ArrowUp', 'ArrowDown', 'ArrowLeft', 'ArrowRight', 'w', 'q'];
        return setInterval(() => {{
            const key = keys[Math.floor(Math.random() * keys.length)];
            // Use jQuery trigger to match how game listens for input (ui_utils.js)
            const event = $.Event('keydown');
            event.key = key;
            $(document).trigger(event);
        }}, {interval_ms});
    }}"""
    )


def stop_random_actions(page, interval_id):
    """
    Stop random action injection.

    Args:
        page: Playwright page
        interval_id: ID returned from start_random_actions
    """
    page.evaluate(f"clearInterval({interval_id})")


def get_action_stats(page):
    """
    Get action statistics from game state.

    Returns dict with counts of each action type seen in frame data buffer.
    Keys are action codes as strings, values are counts.

    Returns:
        dict or None if game state not available
    """
    return page.evaluate(
        """() => {
        const game = window.game;
        if (!game || !game.frameDataBuffer) return null;

        const actionCounts = {};
        for (const [frame, data] of game.frameDataBuffer.entries()) {
            // actions is an object keyed by agentId: {0: action, 1: action}
            const actions = data.actions || {};
            for (const [agentId, action] of Object.entries(actions)) {
                actionCounts[action] = (actionCounts[action] || 0) + 1;
            }
        }
        return actionCounts;
    }"""
    )


def get_local_action_counts(page):
    """
    Get action counts for the local player only.

    This is useful for verifying that the local player's injected
    actions were actually recorded.

    Returns:
        dict with action counts for local player
    """
    return page.evaluate(
        """() => {
        const game = window.game;
        if (!game || !game.frameDataBuffer) return null;

        // Player ID is a string key in the actions object
        const localPlayerId = String(game.myPlayerId);
        const actionCounts = {};

        for (const [frame, data] of game.frameDataBuffer.entries()) {
            // actions is {playerId: action, ...}
            const actions = data.actions || {};
            const localAction = actions[localPlayerId];
            if (localAction !== null && localAction !== undefined) {
                actionCounts[localAction] = (actionCounts[localAction] || 0) + 1;
            }
        }
        return actionCounts;
    }"""
    )


def verify_non_noop_actions(page, min_non_noop: int = 1):
    """
    Verify that non-Noop actions were recorded.

    Args:
        page: Playwright page
        min_non_noop: Minimum number of non-Noop actions expected

    Returns:
        tuple (passed: bool, stats: dict, non_noop_count: int)
    """
    stats = get_action_stats(page)
    if stats is None:
        return (False, None, 0)

    # Non-Noop actions are 0-5 (movement and action keys)
    non_noop_actions = [0, 1, 2, 3, 4, 5]
    non_noop_count = sum(stats.get(str(a), 0) for a in non_noop_actions)

    passed = non_noop_count >= min_non_noop
    return (passed, stats, non_noop_count)
