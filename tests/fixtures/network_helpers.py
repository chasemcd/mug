"""
CDP-based network emulation helpers for latency injection tests.

These utilities use Chrome DevTools Protocol (CDP) to emulate network conditions,
enabling tests to validate game behavior under various latency scenarios.

Important notes:
- CDP only works with Chromium-based browsers (Chrome, Edge, Chromium)
- Tests using these helpers must run with Chromium (Playwright default)
- Network.enable must be called before emulateNetworkConditions
- Throughput of -1 means "no limit" (only latency is affected)

Usage:
    # Fixed latency
    cdp = apply_latency(page, latency_ms=200)

    # Jitter (variable latency)
    cdp = apply_latency(page, latency_ms=200)  # Base latency
    jitter = JitterEmulator(cdp, base_latency=200, jitter_range=100)
    jitter.start()
    # ... run test ...
    jitter.stop()
"""
from __future__ import annotations

import random
import threading
import time

from playwright.sync_api import CDPSession, Page


def apply_latency(page: Page, latency_ms: int) -> CDPSession:
    """
    Apply fixed network latency to a Playwright page via CDP.

    Creates a CDP session, enables the Network domain, and sets network
    emulation conditions with the specified latency.

    Args:
        page: Playwright Page object to apply latency to
        latency_ms: Network latency in milliseconds (minimum delay added to requests)

    Returns:
        CDPSession: The CDP session for later modification or cleanup.
                    Caller can detach() it or keep it for JitterEmulator.

    Example:
        cdp = apply_latency(page, 100)  # 100ms latency
        # ... run test ...
        cdp.detach()  # Optional cleanup (context.close() also cleans up)

    Notes:
        - Network.enable is required before emulateNetworkConditions
        - downloadThroughput/uploadThroughput set to -1 (no limit)
        - Only affects this specific page's requests
    """
    # Create CDP session for this page
    cdp = page.context.new_cdp_session(page)

    # Enable Network domain (required before emulation)
    cdp.send("Network.enable")

    # Apply network conditions with specified latency
    cdp.send("Network.emulateNetworkConditions", {
        "offline": False,
        "latency": latency_ms,
        "downloadThroughput": -1,  # -1 = no limit
        "uploadThroughput": -1,    # -1 = no limit
    })

    return cdp


class JitterEmulator:
    """
    Simulates network jitter by dynamically varying latency.

    Uses a background daemon thread to periodically update CDP network
    emulation with random latency values within a configured range.

    The latency varies between (base_latency - jitter_range) and
    (base_latency + jitter_range), clamped to a minimum of 0.

    Example:
        cdp = apply_latency(page, 200)  # Start with base latency
        jitter = JitterEmulator(cdp, base_latency=200, jitter_range=150)
        jitter.start(interval_ms=100)  # Update latency every 100ms
        # ... run test (latency varies 50-350ms) ...
        jitter.stop()

    Notes:
        - Uses daemon thread (auto-killed when main thread exits)
        - Always call stop() in test cleanup/finally block
        - Thread-safe: can be stopped from any thread
    """

    def __init__(self, cdp_session: CDPSession, base_latency: int, jitter_range: int):
        """
        Initialize the jitter emulator.

        Args:
            cdp_session: CDP session from apply_latency() or created manually
            base_latency: Base/center latency in milliseconds
            jitter_range: Maximum deviation from base (latency varies +/- this amount)
        """
        self.cdp = cdp_session
        self.base = base_latency
        self.range = jitter_range
        self._running = False
        self._thread = None

    def start(self, interval_ms: int = 100) -> None:
        """
        Start jitter emulation in a background thread.

        Args:
            interval_ms: How often to update latency (default 100ms = 10 updates/sec)
        """
        if self._running:
            return  # Already running

        self._running = True
        self._thread = threading.Thread(
            target=self._jitter_loop,
            args=(interval_ms,),
            daemon=True  # Auto-kill when main thread exits
        )
        self._thread.start()

    def stop(self) -> None:
        """
        Stop jitter emulation.

        Signals the background thread to stop and waits for it to finish.
        Safe to call multiple times.
        """
        self._running = False
        if self._thread is not None:
            self._thread.join(timeout=1.0)
            self._thread = None

    def _jitter_loop(self, interval_ms: int) -> None:
        """
        Background loop that periodically varies latency.

        Runs until stop() is called or the main thread exits.
        """
        interval_sec = interval_ms / 1000.0

        while self._running:
            # Calculate new latency with random jitter
            jitter = random.randint(-self.range, self.range)
            new_latency = max(0, self.base + jitter)  # Clamp to minimum 0

            try:
                self.cdp.send("Network.emulateNetworkConditions", {
                    "offline": False,
                    "latency": new_latency,
                    "downloadThroughput": -1,
                    "uploadThroughput": -1,
                })
            except Exception:
                # CDP session may be closed/detached - stop gracefully
                self._running = False
                break

            time.sleep(interval_sec)


def apply_packet_loss(
    page: Page,
    packet_loss_percent: float,
    latency_ms: int = 50
) -> CDPSession:
    """
    Apply WebRTC packet loss and optional base latency via CDP.

    Args:
        page: Playwright Page object
        packet_loss_percent: Packet loss percentage (0-100)
                            Recommended: 10-15% to trigger rollbacks without breaking connection
        latency_ms: Base latency in milliseconds (default 50ms for ordering effects)

    Returns:
        CDPSession for later modification or cleanup

    Note:
        packetLoss specifically affects WebRTC traffic (used for GGPO inputs).
        Higher values (>20%) risk breaking the P2P connection entirely.
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


def set_tab_visibility(page: Page, visible: bool) -> None:
    """
    Simulate tab visibility change by overriding document properties
    and dispatching visibilitychange event.

    Args:
        page: Playwright Page object
        visible: True for visible, False for hidden

    Note:
        This triggers the game's FocusManager which:
        - When hidden: buffers partner inputs, uses defaultAction for local player
        - When visible: triggers fast-forward to catch up with partner
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


def get_rollback_stats(page: Page) -> dict:
    """
    Get rollback statistics from the game.

    Returns dict with:
        - rollbackCount: Total rollbacks this session (persists across episodes)
        - maxRollbackFrames: Deepest rollback (frames replayed)
        - rollbackEvents: Array of rollback event details
        - rollbackInProgress: Whether rollback is currently executing

    Note: Uses sessionMetrics.rollbacks which persists across episode resets,
    unlike game.rollbackCount which resets on episode boundaries.
    """
    return page.evaluate("""() => {
        const game = window.game;
        if (!game) return null;

        return {
            rollbackCount: game.sessionMetrics?.rollbacks?.count || 0,
            maxRollbackFrames: game.sessionMetrics?.rollbacks?.maxFrames || 0,
            rollbackEvents: game.sessionMetrics?.rollbacks?.events || [],
            rollbackInProgress: game.rollbackInProgress || false,
        };
    }""")


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
