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
import random
import threading
import time

from playwright.sync_api import Page, CDPSession


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
