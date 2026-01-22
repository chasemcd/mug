/**
 * Continuous Monitor
 *
 * Monitors ping and tab visibility during gameplay, warning or excluding
 * participants when thresholds are exceeded.
 *
 * Key design decisions:
 * - Uses rolling window for ping to avoid false positives from transient spikes
 * - Requires sustained violations (N consecutive) before exclusion
 * - Tab monitoring uses visibilitychange event (not polling) for immediate detection
 * - Warning shown before exclusion to give participant chance to correct
 */

// Logging helper (matches pyodide_multiplayer_game.js pattern)
const monitorLog = {
    error: (...args) => console.error('[Monitor]', ...args),
    warn: (...args) => console.warn('[Monitor]', ...args),
    info: (...args) => console.log('[Monitor]', ...args),
    debug: (...args) => console.log('[Monitor]', ...args),
};

/**
 * ContinuousMonitor - Tracks ping and tab visibility during gameplay
 */
export class ContinuousMonitor {
    /**
     * Create a ContinuousMonitor instance.
     *
     * @param {Object} config - Configuration from scene metadata
     * @param {number|null} config.continuous_max_ping - Max ping threshold (null = disabled)
     * @param {number} config.continuous_ping_violation_window - Window size for tracking
     * @param {number} config.continuous_ping_required_violations - Consecutive violations needed
     * @param {number|null} config.continuous_tab_warning_ms - Tab hidden warning threshold (null = disabled)
     * @param {number|null} config.continuous_tab_exclude_ms - Tab hidden exclusion threshold (null = disabled)
     * @param {Object} config.continuous_exclusion_messages - Custom messages
     */
    constructor(config) {
        // Ping monitoring config
        this.maxPing = config.continuous_max_ping ?? null;
        this.pingViolationWindow = config.continuous_ping_violation_window ?? 5;
        this.pingRequiredViolations = config.continuous_ping_required_violations ?? 3;
        this.pingMeasurements = [];
        this.pingWarningShown = false;

        // Tab visibility config
        this.tabWarningMs = config.continuous_tab_warning_ms ?? 3000;
        this.tabExcludeMs = config.continuous_tab_exclude_ms ?? 10000;
        this.tabHiddenAt = null;
        this.tabWarningShown = false;

        // Exclusion messages
        this.messages = {
            ping_warning: config.continuous_exclusion_messages?.ping_warning ||
                "Your connection is unstable. Please close other applications.",
            ping_exclude: config.continuous_exclusion_messages?.ping_exclude ||
                "Your connection became too slow. The game has ended.",
            tab_warning: config.continuous_exclusion_messages?.tab_warning ||
                "Please return to the experiment window to continue.",
            tab_exclude: config.continuous_exclusion_messages?.tab_exclude ||
                "You left the experiment window for too long. The game has ended."
        };

        // State tracking
        this.enabled = config.continuous_monitoring_enabled ?? false;
        this.paused = false;  // Pause during episode transitions

        // Callbacks (set by game)
        this.onWarning = null;
        this.onExclude = null;

        // Custom callback config (Phase 18)
        this.hasCallback = config.has_continuous_callback ?? false;
        this.callbackIntervalFrames = config.continuous_callback_interval_frames ?? 30;
        this.framesSinceCallback = 0;
        this.callbackPending = false;  // Prevent overlapping calls

        // Callback result (set by game when server responds)
        this.callbackResult = null;

        // Set up tab visibility listener
        this._setupTabListener();

        monitorLog.info(`ContinuousMonitor initialized: ping=${this.maxPing}ms, tab_warn=${this.tabWarningMs}ms, tab_exclude=${this.tabExcludeMs}ms, has_callback=${this.hasCallback}`);
    }

    /**
     * Set up Page Visibility API listener for immediate tab switch detection.
     * Uses visibilitychange event (not polling) per research recommendations.
     */
    _setupTabListener() {
        document.addEventListener('visibilitychange', () => {
            if (!this.enabled || this.paused) return;

            if (document.hidden) {
                this.tabHiddenAt = Date.now();
                this.tabWarningShown = false;
                monitorLog.debug('Tab hidden at', this.tabHiddenAt);
            } else {
                // Tab returned to foreground
                const hiddenDuration = this.tabHiddenAt ? Date.now() - this.tabHiddenAt : 0;
                monitorLog.debug(`Tab visible after ${hiddenDuration}ms hidden`);
                this.tabHiddenAt = null;
                this.tabWarningShown = false;
            }
        });
    }

    /**
     * Record a ping measurement. Call this with each ping update.
     *
     * @param {number} pingMs - Current ping in milliseconds
     */
    recordPing(pingMs) {
        if (!this.enabled || this.maxPing === null) return;

        this.pingMeasurements.push(pingMs);
        if (this.pingMeasurements.length > this.pingViolationWindow) {
            this.pingMeasurements.shift();
        }
    }

    /**
     * Check monitoring status. Call this periodically (e.g., each frame or second).
     *
     * @returns {Object} Result with status
     *   - exclude: boolean - Should participant be excluded?
     *   - warn: boolean - Should warning be shown?
     *   - reason: string|null - 'sustained_ping', 'tab_hidden', 'custom_callback', etc.
     *   - message: string|null - Message to display
     */
    check() {
        const result = {
            exclude: false,
            warn: false,
            reason: null,
            message: null
        };

        if (!this.enabled || this.paused) {
            return result;
        }

        // Check callback result first if present (Phase 18)
        if (this.callbackResult) {
            const cbResult = this.callbackResult;
            this.callbackResult = null;  // Clear after reading

            if (cbResult.exclude) {
                return {
                    exclude: true,
                    warn: false,
                    reason: 'custom_callback',
                    message: cbResult.message || 'You have been excluded from this study.'
                };
            }
            if (cbResult.warn) {
                return {
                    exclude: false,
                    warn: true,
                    reason: 'custom_callback_warning',
                    message: cbResult.message || 'Please follow the study instructions.'
                };
            }
        }

        // Check tab visibility first (higher priority)
        const tabResult = this._checkTabVisibility();
        if (tabResult.exclude) {
            return tabResult;
        }
        if (tabResult.warn) {
            // Tab warning takes precedence over ping warning
            return tabResult;
        }

        // Check ping (only if tab is visible - hidden tabs have stale measurements)
        if (!this.tabHiddenAt) {
            const pingResult = this._checkPing();
            if (pingResult.exclude || pingResult.warn) {
                return pingResult;
            }
        }

        return result;
    }

    /**
     * Check if it's time to execute the continuous callback.
     * Call this each frame. Returns true when callback should be executed.
     * @returns {boolean}
     */
    shouldExecuteCallback() {
        if (!this.enabled || this.paused || !this.hasCallback || this.callbackPending) {
            return false;
        }

        this.framesSinceCallback++;
        if (this.framesSinceCallback >= this.callbackIntervalFrames) {
            this.framesSinceCallback = 0;
            return true;
        }
        return false;
    }

    /**
     * Set the callback pending state.
     * @param {boolean} pending - Whether a callback is pending
     */
    setCallbackPending(pending) {
        this.callbackPending = pending;
    }

    /**
     * Set the result from server callback execution.
     * @param {Object} result - {exclude: bool, warn: bool, message: string|null}
     */
    setCallbackResult(result) {
        this.callbackResult = result;
    }

    /**
     * Check tab visibility status.
     * @returns {Object} Result with exclude/warn/reason/message
     * @private
     */
    _checkTabVisibility() {
        const result = {
            exclude: false,
            warn: false,
            reason: null,
            message: null
        };

        if (!this.tabHiddenAt) {
            return result;
        }

        const hiddenDuration = Date.now() - this.tabHiddenAt;

        // Check exclusion threshold
        if (this.tabExcludeMs !== null && hiddenDuration >= this.tabExcludeMs) {
            result.exclude = true;
            result.reason = 'tab_hidden';
            result.message = this.messages.tab_exclude;
            monitorLog.warn(`Tab hidden exclusion: ${hiddenDuration}ms >= ${this.tabExcludeMs}ms threshold`);
            return result;
        }

        // Check warning threshold
        if (this.tabWarningMs !== null && hiddenDuration >= this.tabWarningMs && !this.tabWarningShown) {
            this.tabWarningShown = true;
            result.warn = true;
            result.reason = 'tab_hidden';
            result.message = this.messages.tab_warning;
            monitorLog.info(`Tab hidden warning: ${hiddenDuration}ms >= ${this.tabWarningMs}ms threshold`);
            return result;
        }

        return result;
    }

    /**
     * Check ping status for sustained violations.
     * @returns {Object} Result with exclude/warn/reason/message
     * @private
     */
    _checkPing() {
        const result = {
            exclude: false,
            warn: false,
            reason: null,
            message: null
        };

        if (this.maxPing === null || this.pingMeasurements.length === 0) {
            return result;
        }

        // Check for sustained violations (N consecutive measurements over threshold)
        if (this.pingMeasurements.length >= this.pingRequiredViolations) {
            const recent = this.pingMeasurements.slice(-this.pingRequiredViolations);
            const allOverThreshold = recent.every(ping => ping > this.maxPing);

            if (allOverThreshold) {
                result.exclude = true;
                result.reason = 'sustained_ping';
                result.message = this.messages.ping_exclude;
                const avgPing = Math.round(recent.reduce((a, b) => a + b, 0) / recent.length);
                monitorLog.warn(`Sustained ping exclusion: ${this.pingRequiredViolations} consecutive measurements > ${this.maxPing}ms (avg=${avgPing}ms)`);
                return result;
            }
        }

        // Check for single violation (warning only)
        const lastPing = this.pingMeasurements[this.pingMeasurements.length - 1];
        if (lastPing > this.maxPing && !this.pingWarningShown) {
            this.pingWarningShown = true;
            result.warn = true;
            result.reason = 'ping_spike';
            result.message = this.messages.ping_warning;
            monitorLog.info(`Ping warning: ${lastPing}ms > ${this.maxPing}ms threshold`);

            // Reset warning flag after a delay to allow re-warning
            setTimeout(() => {
                this.pingWarningShown = false;
            }, 5000);

            return result;
        }

        return result;
    }

    /**
     * Pause monitoring (e.g., during episode transitions).
     */
    pause() {
        this.paused = true;
        monitorLog.debug('Monitoring paused');
    }

    /**
     * Resume monitoring after pause.
     */
    resume() {
        this.paused = false;
        // Reset tab tracking to avoid false positives from pause duration
        this.tabHiddenAt = null;
        this.tabWarningShown = false;
        monitorLog.debug('Monitoring resumed');
    }

    /**
     * Reset all tracking state (e.g., on new episode).
     */
    reset() {
        this.pingMeasurements = [];
        this.pingWarningShown = false;
        this.tabHiddenAt = document.hidden ? Date.now() : null;
        this.tabWarningShown = false;
        monitorLog.debug('Monitor state reset');
    }
}
