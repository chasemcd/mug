import * as ui_utils from './ui_utils.js';
import {startUnityScene, terminateUnityScene, shutdownUnityGame, preloadUnityGame} from './unity_utils.js';
import {graphics_start, graphics_end, addStateToBuffer, getRemoteGameData, pressedKeys} from './phaser_gym_graphics.js';
import {RemoteGame} from './pyodide_remote_game.js';
import {MultiplayerPyodideGame} from './pyodide_multiplayer_game.js';
import {ProbeConnection} from './probe_connection.js';

window.socket = io({
    transports: ['websocket'],
    upgrade: false
});
var socket = window.socket;

// ============================================
// Probe Manager for P2P RTT measurement during matchmaking
// Handles probe_prepare -> ProbeConnection -> measurement -> probe_result flow
// ============================================
const ProbeManager = {
    activeProbe: null,
    mySubjectId: null,
    socket: null,

    /**
     * Initialize probe handling with socket and subject identity.
     * @param {Object} socket - SocketIO socket
     * @param {string} subjectId - This participant's subject_id
     */
    init(socket, subjectId) {
        this.socket = socket;
        this.mySubjectId = subjectId;

        // Handle server requesting probe connection
        socket.on('probe_prepare', (data) => this._handleProbePrepare(data));

        // Handle server signaling probe start
        socket.on('probe_start', (data) => this._handleProbeStart(data));

        console.log('[ProbeManager] Initialized for subject', subjectId);
    },

    _handleProbePrepare(data) {
        const { probe_session_id, peer_subject_id, turn_username, turn_credential } = data;

        console.log(`[ProbeManager] Preparing probe ${probe_session_id} with peer ${peer_subject_id}`);

        // Close any existing probe
        if (this.activeProbe) {
            console.warn('[ProbeManager] Closing existing probe before new one');
            this.activeProbe.close();
        }

        // Create new probe connection
        this.activeProbe = new ProbeConnection(
            this.socket,
            probe_session_id,
            this.mySubjectId,
            peer_subject_id,
            { turnUsername: turn_username, turnCredential: turn_credential }
        );

        // Set up callbacks
        this.activeProbe.onConnected = () => this._onProbeConnected(probe_session_id);
        this.activeProbe.onFailed = () => this._onProbeFailed(probe_session_id);

        // Signal ready to server
        this.socket.emit('probe_ready', { probe_session_id });
    },

    _handleProbeStart(data) {
        const { probe_session_id } = data;

        if (!this.activeProbe || this.activeProbe.probeSessionId !== probe_session_id) {
            console.warn(`[ProbeManager] probe_start for unknown session ${probe_session_id}`);
            return;
        }

        console.log(`[ProbeManager] Starting probe ${probe_session_id}`);
        this.activeProbe.start();
    },

    async _onProbeConnected(probeSessionId) {
        console.log(`[ProbeManager] Probe ${probeSessionId} connected, measuring RTT via ping-pong`);

        // Measure RTT using ping-pong protocol (no stabilization delay needed)
        const rtt = await this.activeProbe.measureRTT();

        // Report result to server
        this.socket.emit('probe_result', {
            probe_session_id: probeSessionId,
            rtt_ms: rtt,
            success: rtt !== null,
        });

        // Clean up probe connection
        this._cleanupProbe();
    },

    _onProbeFailed(probeSessionId) {
        console.log(`[ProbeManager] Probe ${probeSessionId} failed`);

        // Report failure to server
        this.socket.emit('probe_result', {
            probe_session_id: probeSessionId,
            rtt_ms: null,
            success: false,
        });

        // Clean up probe connection
        this._cleanupProbe();
    },

    _cleanupProbe() {
        if (this.activeProbe) {
            this.activeProbe.close();
            this.activeProbe = null;
        }
    },
};

// ============================================
// Console log capture for admin dashboard
// Intercepts console.log/warn/error/info and sends to server
// ============================================
(function() {
    const originalConsole = {
        log: console.log.bind(console),
        warn: console.warn.bind(console),
        error: console.error.bind(console),
        info: console.info.bind(console)
    };

    // Rate limiting: max 10 logs per second to avoid flooding
    let logCount = 0;
    let lastResetTime = Date.now();
    const MAX_LOGS_PER_SECOND = 10;

    function sendToAdmin(level, args) {
        // Rate limiting
        const now = Date.now();
        if (now - lastResetTime >= 1000) {
            logCount = 0;
            lastResetTime = now;
        }
        if (logCount >= MAX_LOGS_PER_SECOND) {
            return; // Skip this log
        }
        logCount++;

        // Only send if socket is connected
        if (typeof socket !== 'undefined' && socket.connected) {
            try {
                const message = args.map(a => {
                    if (typeof a === 'object') {
                        try {
                            return JSON.stringify(a);
                        } catch (e) {
                            return String(a);
                        }
                    }
                    return String(a);
                }).join(' ');

                socket.emit('client_console_log', {
                    level: level,
                    message: message.substring(0, 500), // Truncate long messages
                    timestamp: Date.now() / 1000
                });
            } catch (e) {
                // Silently fail - don't want to cause infinite loops
            }
        }
    }

    // Override console methods
    console.log = function(...args) {
        originalConsole.log.apply(console, args);
        sendToAdmin('log', args);
    };

    console.warn = function(...args) {
        originalConsole.warn.apply(console, args);
        sendToAdmin('warn', args);
    };

    console.error = function(...args) {
        originalConsole.error.apply(console, args);
        sendToAdmin('error', args);
    };

    console.info = function(...args) {
        originalConsole.info.apply(console, args);
        sendToAdmin('info', args);
    };
})();

var latencyMeasurements = [];
var curLatency;
var maxLatency;


var pyodideRemoteGame = null;

// Pyodide pre-loading state (Phase 67)
window.pyodideInstance = null;
window.pyodideMicropip = null;
window.pyodideInstalledPackages = [];
window.pyodidePreloadStatus = 'idle'; // 'idle' | 'loading' | 'ready' | 'error'

// Unified loading gate (Phase 75) - coordinates screening + Pyodide readiness
const loadingGate = {
    screeningComplete: false,
    screeningPassed: null,       // true/false/null
    screeningMessage: null,      // exclusion message if failed
    pyodideComplete: false,
    pyodideSuccess: null,        // true/false/null
    timeoutId: null,
    gateResolved: false,         // prevents re-entry on reconnect
};

/**
 * Check if both loading signals (screening + Pyodide) are complete.
 * Called by both screening completion and Pyodide completion paths.
 * When both are done, resolves the gate: proceed to scene or show error.
 */
function checkLoadingGate() {
    if (loadingGate.gateResolved) return;

    // Update status text based on current state
    const statusEl = document.getElementById('loadingStatus');
    if (statusEl) {
        if (!loadingGate.screeningComplete && !loadingGate.pyodideComplete) {
            statusEl.textContent = 'Checking compatibility...';
        } else if (loadingGate.screeningComplete && !loadingGate.pyodideComplete) {
            statusEl.textContent = 'Loading Python runtime...';
        } else if (!loadingGate.screeningComplete && loadingGate.pyodideComplete) {
            statusEl.textContent = 'Checking compatibility...';
        }
    }

    // Both must be complete before we can resolve
    if (!loadingGate.screeningComplete || !loadingGate.pyodideComplete) {
        return;
    }

    // Gate is resolving -- mark resolved to prevent re-entry
    loadingGate.gateResolved = true;
    if (loadingGate.timeoutId) {
        clearTimeout(loadingGate.timeoutId);
        loadingGate.timeoutId = null;
    }

    // Hide loading screen
    const loadingScreen = document.getElementById('loadingScreen');
    if (loadingScreen) loadingScreen.style.display = 'none';

    // Screening failed -> show exclusion (existing behavior)
    if (!loadingGate.screeningPassed) {
        console.log('[LoadingGate] Screening failed:', loadingGate.screeningMessage);
        showExclusionMessage(loadingGate.screeningMessage);
        return;
    }

    // Pyodide failed -> show error page (LOAD-04)
    if (!loadingGate.pyodideSuccess) {
        console.log('[LoadingGate] Pyodide failed - showing error page');
        showExclusionMessage('Failed to load the Python runtime. Please refresh the page or try a different browser.');
        return;
    }

    // Both passed -> proceed to scene
    console.log('[LoadingGate] Both signals ready - proceeding');
    if (pendingSceneData) {
        processPendingScene();
    } else {
        console.log('[LoadingGate] No pending scene, requesting from server');
        socket.emit("request_current_scene", {});
    }
}

/**
 * Pre-load Pyodide during compatibility check screen (Phase 67).
 * Starts loadPyodide() + micropip.install() immediately when experiment_config
 * arrives, storing the result on window.pyodideInstance for Phase 68 to consume.
 *
 * @param {Object} pyodideConfig - {needs_pyodide: bool, packages_to_install: string[]}
 */
async function preloadPyodide(pyodideConfig) {
    if (!pyodideConfig || !pyodideConfig.needs_pyodide) {
        window.pyodidePreloadStatus = 'ready';
        loadingGate.pyodideComplete = true;
        loadingGate.pyodideSuccess = true;
        checkLoadingGate();
        return;
    }

    console.log('[PyodidePreload] Starting preload...');
    window.pyodidePreloadStatus = 'loading';

    // Signal server BEFORE blocking the main thread (GRACE-02)
    socket.emit('pyodide_loading_start', {});
    // Yield to event loop so the emit is actually sent before WASM compilation blocks
    await new Promise(resolve => setTimeout(resolve, 50));

    try {
        const pyodide = await loadPyodide();
        console.log('[PyodidePreload] Core loaded, installing micropip...');
        const statusEl = document.getElementById('loadingStatus');
        if (statusEl) statusEl.textContent = 'Installing packages...';

        await pyodide.loadPackage("micropip");
        const micropip = pyodide.pyimport("micropip");

        const packages = pyodideConfig.packages_to_install || [];
        if (packages.length > 0) {
            console.log('[PyodidePreload] Installing:', packages);
            await micropip.install(packages);
        }

        window.pyodideInstance = pyodide;
        window.pyodideMicropip = micropip;
        window.pyodideInstalledPackages = packages;
        window.pyodidePreloadStatus = 'ready';
        console.log('[PyodidePreload] Complete');
        loadingGate.pyodideComplete = true;
        loadingGate.pyodideSuccess = true;
        checkLoadingGate();

        // Signal server loading is done (GRACE-03)
        socket.emit('pyodide_loading_complete', {});

    } catch (error) {
        console.error('[PyodidePreload] Failed:', error);
        window.pyodidePreloadStatus = 'error';
        loadingGate.pyodideComplete = true;
        loadingGate.pyodideSuccess = false;
        checkLoadingGate();
        // Signal server loading is done (even on error) to clear grace state
        socket.emit('pyodide_loading_complete', { error: true });
    }
}

// Expose game instance for debugging (access via window.game)
Object.defineProperty(window, 'game', {
    get: function() { return pyodideRemoteGame; }
});

var documentInFocus = false;
document.addEventListener("visibilitychange", function() {
  if (document.hidden) {
    documentInFocus = false;
    // alert("Please return to the game tab to avoid interruptions and to facilitate a good experience for all players.");
  } else {
    documentInFocus = true;
  }
});

window.addEventListener('focus', function() {
    // The window has gained focus
    documentInFocus = true;
});

window.addEventListener('blur', function() {
    // The window has lost focus
    documentInFocus = false;
});

socket.on('pong', function(latencyData) {
    var latency = Date.now() - window.lastPingTime;
    latencyMeasurements.push(latency);

    var maxMeasurements = 20; // limit to last 50 measurements
    if (latencyMeasurements.length > maxMeasurements) {
        latencyMeasurements.shift(); // Remove the oldest measurement
    }

    // Calculate the median
    var medianLatency = calculateMedian(latencyMeasurements);

    // Update the latency (ping) display in the UI
    document.getElementById('latencyValue').innerText = medianLatency.toString().padStart(3, '0');
    document.getElementById('latencyContainer').style.display = 'block'; // Show the latency (ping) display
    curLatency = medianLatency;
    maxLatency = latencyData.max_latency;

    // Expose for continuous monitoring (Phase 16)
    window.currentPing = medianLatency;
});

function calculateMedian(arr) {
    const sortedArr = arr.slice().sort((a, b) => a - b);
    const mid = Math.floor(sortedArr.length / 2);
    let median;

    if (sortedArr.length % 2 !== 0) {
        median = sortedArr[mid];
    } else {
        median = (sortedArr[mid - 1] + sortedArr[mid]) / 2;
    }

    // Round to the nearest integer
    median = Math.round(median);
    return median;
}

// ============================================
// Entry Screening (Phase 15 + Phase 18 Callbacks)
// ============================================

/**
 * Run entry screening checks based on scene metadata.
 * Now async to support server-side callback execution (Phase 18).
 * Returns an object with { passed: boolean, failedRule: string | null, message: string | null }
 */
async function runEntryScreening(sceneMetadata) {
    // Run built-in checks first
    // UAParser is loaded via CDN as a global script, access via window in ES module context
    const parser = new window.UAParser();
    const result = parser.getResult();
    const deviceType = result.device.type; // "mobile", "tablet", or undefined (desktop)
    const browserName = result.browser.name; // "Chrome", "Safari", "Firefox", etc.

    console.debug("[EntryScreening] Device type:", deviceType || "desktop");
    console.debug("[EntryScreening] Browser:", browserName);

    // Check device exclusion
    if (sceneMetadata.device_exclusion === "mobile") {
        // Exclude mobile and tablet devices
        if (deviceType === "mobile" || deviceType === "tablet") {
            const message = sceneMetadata.exclusion_messages?.mobile ||
                "This study requires a desktop or laptop computer.";
            return { passed: false, failedRule: "mobile", message: message };
        }
    } else if (sceneMetadata.device_exclusion === "desktop") {
        // Exclude desktop devices (undefined device type = desktop)
        if (!deviceType) {
            const message = sceneMetadata.exclusion_messages?.desktop ||
                "This study requires a mobile device.";
            return { passed: false, failedRule: "desktop", message: message };
        }
    }

    // Check browser blocklist first (takes precedence)
    if (sceneMetadata.browser_blocklist && sceneMetadata.browser_blocklist.length > 0) {
        const blockedLower = sceneMetadata.browser_blocklist.map(b => b.toLowerCase());
        if (browserName && blockedLower.includes(browserName.toLowerCase())) {
            // Build helpful message with allowed browsers
            let message = sceneMetadata.exclusion_messages?.browser ||
                "Your browser is not supported for this study.";

            // Add allowed browsers info if requirements exist
            if (sceneMetadata.browser_requirements && sceneMetadata.browser_requirements.length > 0) {
                const allowedList = sceneMetadata.browser_requirements.join(", ");
                message += ` Supported browsers: ${allowedList}.`;
            }
            message += " You can open this same link in a different browser to continue.";

            return { passed: false, failedRule: "browser", message: message };
        }
    }

    // Check browser requirements (allowlist)
    if (sceneMetadata.browser_requirements && sceneMetadata.browser_requirements.length > 0) {
        const allowedLower = sceneMetadata.browser_requirements.map(b => b.toLowerCase());
        if (!browserName || !allowedLower.includes(browserName.toLowerCase())) {
            const allowedList = sceneMetadata.browser_requirements.join(", ");
            let message = sceneMetadata.exclusion_messages?.browser ||
                "Your browser is not supported for this study.";
            message += ` Supported browsers: ${allowedList}. You can open this same link in a different browser to continue.`;
            return { passed: false, failedRule: "browser", message: message };
        }
    }

    // Check max_ping at entry (wait for enough measurements)
    if (sceneMetadata.max_ping) {
        const minMeasurements = sceneMetadata.min_ping_measurements || 5;
        const maxPing = sceneMetadata.max_ping;

        // Wait for enough ping measurements (up to 10 seconds)
        const startTime = Date.now();
        const timeout = 10000; // 10 seconds max wait

        while (latencyMeasurements.length < minMeasurements && (Date.now() - startTime) < timeout) {
            await new Promise(resolve => setTimeout(resolve, 500));
        }

        if (latencyMeasurements.length >= minMeasurements) {
            const medianPing = calculateMedian(latencyMeasurements);
            console.debug(`[EntryScreening] Ping check: ${medianPing}ms (max: ${maxPing}ms, measurements: ${latencyMeasurements.length})`);

            if (medianPing > maxPing) {
                const message = sceneMetadata.exclusion_messages?.ping ||
                    "Your connection is too slow for this study.";
                return { passed: false, failedRule: "ping", message: message };
            }
        } else {
            console.warn(`[EntryScreening] Not enough ping measurements (${latencyMeasurements.length}/${minMeasurements}), skipping ping check`);
        }
    }

    // Phase 18: If built-in checks pass and entry callback is configured, call server
    if (sceneMetadata.has_entry_callback) {
        console.debug("[EntryScreening] Executing server-side entry callback...");
        const callbackResult = await executeEntryCallback(sceneMetadata);
        if (callbackResult.exclude) {
            return {
                passed: false,
                failedRule: 'custom_callback',
                message: callbackResult.message || 'You do not meet the requirements for this study.'
            };
        }
    }

    // All checks passed
    return { passed: true, failedRule: null, message: null };
}

/**
 * Execute server-side entry callback (Phase 18).
 * Sends participant context to server and awaits exclusion decision.
 *
 * @param {Object} sceneMetadata - Scene configuration
 * @returns {Promise<{exclude: boolean, message: string|null}>}
 */
function executeEntryCallback(sceneMetadata) {
    return new Promise((resolve) => {
        // Gather participant context
        // UAParser is loaded via CDN as a global script, access via window in ES module context
        const parser = new window.UAParser();
        const result = parser.getResult();

        const context = {
            ping: curLatency || 0,
            browser_name: result.browser.name || 'Unknown',
            browser_version: result.browser.version || 'Unknown',
            device_type: result.device.type || 'desktop',
            os_name: result.os.name || 'Unknown',
            os_version: result.os.version || 'Unknown'
        };

        // Set up one-time listener for response
        socket.once('entry_callback_result', (data) => {
            console.debug("[EntryScreening] Callback result:", data);
            resolve({
                exclude: data.exclude || false,
                message: data.message || null
            });
        });

        // Send to server
        socket.emit('execute_entry_callback', {
            session_id: window.sessionId,
            scene_id: sceneMetadata.scene_id,
            context: context
        });

        // Timeout after 5 seconds (fail open - allow entry)
        setTimeout(() => {
            console.warn("[EntryScreening] Entry callback timeout, allowing entry");
            resolve({ exclude: false, message: null });
        }, 5000);
    });
}

/**
 * Display exclusion message and hide all interactive elements.
 * Shows only the exclusion message to the participant.
 */
function showExclusionMessage(message) {
    // Hide all interactive elements
    $("#instructions").hide();
    $("#startButton").hide();
    $("#startButton").attr("disabled", true);
    $("#startButtonLoader").removeClass("visible");
    $("#advanceButton").hide();
    $("#redirectButton").hide();
    $("#sceneBody").hide();
    $("#waitroomText").hide();
    $("#gameContainer").hide();
    $("#invalidSession").hide();

    // Set headers - use existing header if present, otherwise use default
    const currentHeader = $("#sceneHeader").text().trim();
    if (!currentHeader) {
        $("#sceneHeader").text("Error!");
    }
    $("#sceneHeader").show();
    $("#sceneSubHeader").text("Unable to Continue");
    $("#sceneSubHeader").show();

    // Show the exclusion message in errorText
    $('#errorText').text(message);
    $('#errorText').css({
        'display': 'block',
        'text-align': 'left',
        'line-height': '1.6'
    });
}

// Track entry screening result (experiment-level, runs once at experiment start)
var experimentScreeningPassed = null;  // null = not yet checked, true/false = result
var experimentScreeningMessage = null;
var experimentScreeningConfig = null;  // Stores experiment-level config
var experimentScreeningComplete = false;  // True when screening is done (passed or failed)
var pendingSceneData = null;  // Store scene data if it arrives before screening completes

function sendPing() {
    window.lastPingTime = Date.now();
    socket.emit('ping', {ping_ms: curLatency, document_in_focus: documentInFocus});
}

// Send a ping every second
setInterval(sendPing, 1000);

function pyodideReadyIfUsing() {
    if (pyodideRemoteGame == null) {
        console.debug("pyodideRemoteGame is null")
        return true;
    }

    console.debug("Pyodide Ready:",pyodideRemoteGame.pyodideReady)
    return pyodideRemoteGame.pyodideReady;
}


$(function() {
    $('#startButton').click( () => {
        console.log("[StartButton] Clicked - attempting to join game. Session:", window.sessionId, "Subject:", window.subjectName || interactiveGymGlobals?.subjectName);
        $("#startButton").hide();
        $("#startButton").attr("disabled", true);
        $("#startButtonLoader").removeClass("visible");
        socket.emit("join_game", {session_id: window.sessionId});

    })
})

socket.on('server_session_id', function(sessionInfo) {
    window.sessionId = sessionInfo.session_id;
});

// Handle join_game errors - show start button again so user can retry
socket.on('join_game_error', function(errorInfo) {
    console.error("join_game_error:", errorInfo.message);
    $("#startButton").show();
    $("#startButton").attr("disabled", false);
    $("#startButtonLoader").removeClass("visible");
    $("#errorText").text(errorInfo.message);
    $("#errorText").show();
});

// Experiment-level configuration (including entry screening)
socket.on('experiment_config', async function(experimentConfig) {
    console.log("[ExperimentConfig] Received experiment configuration");

    // Guard against re-entry on reconnect (Pitfall 5)
    if (loadingGate.gateResolved) {
        console.log("[ExperimentConfig] Loading gate already resolved, skipping");
        return;
    }

    // Show unified loading screen (LOAD-01)
    const loadingScreen = document.getElementById('loadingScreen');
    if (loadingScreen) loadingScreen.style.display = 'flex';

    // Start Pyodide preload concurrently (fire and forget)
    if (experimentConfig.pyodide_config) {
        preloadPyodide(experimentConfig.pyodide_config);

        // Start timeout timer if Pyodide is needed (LOAD-03)
        if (experimentConfig.pyodide_config.needs_pyodide) {
            const timeoutS = experimentConfig.pyodide_config.pyodide_load_timeout_s || 60;
            loadingGate.timeoutId = setTimeout(() => {
                if (!loadingGate.pyodideComplete) {
                    console.error('[LoadingGate] Pyodide loading timed out after ' + timeoutS + 's');
                    window.pyodidePreloadStatus = 'error';
                    loadingGate.pyodideComplete = true;
                    loadingGate.pyodideSuccess = false;
                    // Signal server loading is done (timeout) to clear grace state
                    socket.emit('pyodide_loading_complete', { error: true, reason: 'timeout' });
                    checkLoadingGate();
                }
            }, timeoutS * 1000);
        }
    } else {
        // No Pyodide config -> immediately mark pyodide as complete
        loadingGate.pyodideComplete = true;
        loadingGate.pyodideSuccess = true;
    }

    // Run entry screening
    if (experimentConfig.entry_screening) {
        experimentScreeningConfig = experimentConfig.entry_screening;
        console.log("[ExperimentConfig] Entry screening config:", experimentScreeningConfig);

        const hasScreeningRules = experimentScreeningConfig.device_exclusion ||
            (experimentScreeningConfig.browser_requirements && experimentScreeningConfig.browser_requirements.length > 0) ||
            (experimentScreeningConfig.browser_blocklist && experimentScreeningConfig.browser_blocklist.length > 0) ||
            experimentScreeningConfig.max_ping ||
            experimentScreeningConfig.has_entry_callback;

        if (hasScreeningRules) {
            console.log("[ExperimentConfig] Running experiment-level entry screening...");

            // Update loading status
            const statusEl = document.getElementById('loadingStatus');
            if (statusEl) statusEl.textContent = 'Checking compatibility...';

            const result = await runEntryScreening(experimentScreeningConfig);
            experimentScreeningPassed = result.passed;
            experimentScreeningMessage = result.message;
            experimentScreeningComplete = true;

            // Update loading gate with screening result
            loadingGate.screeningComplete = true;
            loadingGate.screeningPassed = result.passed;
            loadingGate.screeningMessage = result.message;

            if (!result.passed) {
                console.log("[ExperimentConfig] Screening failed:", result.failedRule, result.message);
            }

            checkLoadingGate();
        } else {
            // No screening rules configured
            experimentScreeningPassed = true;
            experimentScreeningComplete = true;
            loadingGate.screeningComplete = true;
            loadingGate.screeningPassed = true;
            checkLoadingGate();
        }
    } else {
        // No entry screening config
        experimentScreeningPassed = true;
        experimentScreeningComplete = true;
        loadingGate.screeningComplete = true;
        loadingGate.screeningPassed = true;
        checkLoadingGate();
    }
});

/**
 * Process a pending scene that was queued while screening was in progress.
 */
function processPendingScene() {
    if (!pendingSceneData) return;
    const data = pendingSceneData;
    pendingSceneData = null;

    // Re-dispatch to the appropriate scene handler
    if (data.scene_type === 'GymScene' || data.scene_type === 'gym') {
        startGymScene(data);
    } else if (data.scene_type === 'EndScene' || data.scene_type === 'end') {
        startEndScene(data);
    } else {
        startStaticScene(data);
    }
}

socket.on('connect', function() {
    console.debug("connecting")
    // Emit an event to the server with the subject_id and current interactiveGymGlobals
    // This allows session restoration if reconnecting
    socket.emit('register_subject', {
        subject_id: subjectName,
        interactiveGymGlobals: window.interactiveGymGlobals || {}
    });

    // Initialize ProbeManager for P2P RTT probing during matchmaking
    ProbeManager.init(socket, subjectName);

    $("#invalidSession").hide();
    $('#hudText').hide()
});

// Handle session restoration from server
socket.on('session_restored', function(restoredSession) {
    console.log("Session restored from server:", restoredSession);

    // If screening failed, don't restore session - keep showing exclusion message
    if (experimentScreeningPassed === false) {
        console.log("[SessionRestore] Blocked by failed screening");
        return;
    }

    // Restore interactiveGymGlobals from server (server state is authoritative)
    if (restoredSession.interactiveGymGlobals) {
        window.interactiveGymGlobals = restoredSession.interactiveGymGlobals;
        console.log("Restored interactiveGymGlobals:", window.interactiveGymGlobals);
    }

    // Reset UI state to ensure clean slate before scene activation
    // Hide all buttons - the scene activation will show the appropriate ones
    $("#startButton").hide();
    $("#startButton").attr("disabled", true);
    $("#startButtonLoader").removeClass("visible");
    $("#advanceButton").hide();
    $("#advanceButton").attr("disabled", true);
    $("#redirectButton").hide();
    $("#waitroomText").hide();
    $("#errorText").hide();
    $("#gameContainer").hide();

    // The server will re-activate the appropriate scene via activate_scene event
});


// Handle duplicate session (participant already connected in another tab)
socket.on('duplicate_session', function(duplicateInfo) {
    console.error("Duplicate session detected:", duplicateInfo.message);

    // Hide all interactive elements
    $("#startButton").hide();
    $("#startButtonLoader").removeClass("visible");
    $("#advanceButton").hide();
    $("#redirectButton").hide();
    $("#gameContainer").hide();
    $("#waitroomText").hide();

    // Show error message
    $("#sceneHeader").html("Session Already Active");
    $("#sceneHeader").show();
    $("#sceneBody").html(
        "<p style='color: red; font-weight: bold;'>" + duplicateInfo.message + "</p>"
    );
    $("#sceneBody").show();

    // Disconnect the socket to prevent further attempts
    socket.disconnect();
});

socket.on('invalid_session', function(invalidInfo) {
    alert(invalidInfo.message);
    // $('#finalPageHeaderText').hide()
    // $('#finalPageText').hide()
    // $("#gameHeaderText").hide();
    // $("#gamePageText").hide();
    $("#gameContainer").hide();
    $("#invalidSession").show();
});

socket.on('start_game', function(gameStartData) {
    // Don't start game if screening failed
    if (experimentScreeningPassed === false) {
        console.log("[StartGame] Blocked by failed screening");
        return;
    }

    console.log("[StartGame] Game starting. Subject:", window.subjectName || interactiveGymGlobals?.subjectName,
        "GameID:", gameStartData.game_id || 'N/A',
        "Scene:", gameStartData.scene_metadata?.scene_id || 'unknown');

    // Clear the waitroomInterval to stop the waiting room timer
    if (waitroomInterval) {
        clearInterval(waitroomInterval);
    }

    let scene_metadata = gameStartData.scene_metadata

    // Set game_id on multiplayer game instance if present
    if (gameStartData.game_id && pyodideRemoteGame) {
        pyodideRemoteGame.gameId = gameStartData.game_id;
        console.debug(`[MultiplayerPyodide] Set game_id: ${gameStartData.game_id}`);
    }

    // Hide the sceneBody and any waiting room messages or errors
    if (scene_metadata.in_game_scene_body != undefined) {
        $("#sceneBody").html(scene_metadata.in_game_scene_body);
        $("#sceneBody").show();
    } else {
        $("#sceneBody").hide();
    }
    $("#waitroomText").hide();
    $('#errorText').hide()

    // Show the game container
    $("#gameContainer").show();

    // Detect server-authoritative mode
    if (scene_metadata.server_authoritative) {
        window.serverAuthoritative = true;
        console.log("[StartGame] Server-authoritative mode enabled");
    } else {
        window.serverAuthoritative = false;
    }

    // Initialize game
    let graphics_config = {
        'parent': 'gameContainer',
        'fps': {
            'target': scene_metadata.fps,
            'forceSetTimeOut': true
        },
        'height': scene_metadata.game_height,
        'width': scene_metadata.game_width,
        'background': scene_metadata.background,
        'state_init': scene_metadata.state_init,
        'assets_dir': scene_metadata.assets_dir,
        'assets_to_preload': scene_metadata.assets_to_preload,
        'animation_configs': scene_metadata.animation_configs,
        'pyodide_remote_game': window.serverAuthoritative ? null : pyodideRemoteGame,
        'scene_metadata': scene_metadata,
    };

    ui_utils.enableKeyListener(scene_metadata.input_mode)
    graphics_start(graphics_config);
});


var waitroomInterval;
var waitroomTimeoutMessage = null;  // Store custom timeout message from server

socket.on('match_found_countdown', function(countdownInfo) {
    console.log("[Countdown] Match found! Starting", countdownInfo.countdown_seconds, "second countdown");

    // Stop the waiting room timer
    if (waitroomInterval) {
        clearInterval(waitroomInterval);
    }

    var remaining = countdownInfo.countdown_seconds;
    var message = countdownInfo.message || "Players found!";

    // Show initial countdown state
    $("#waitroomText").text(message + " Starting in " + remaining + "...");
    $("#waitroomText").show();

    // Countdown interval
    var countdownInterval = setInterval(function() {
        remaining--;
        if (remaining > 0) {
            $("#waitroomText").text(message + " Starting in " + remaining + "...");
        } else {
            clearInterval(countdownInterval);
            $("#waitroomText").text(message + " Starting now!");
        }
    }, 1000);
});

socket.on("waiting_room", function(waitroomState) {
    console.log("[WaitingRoom] Added to waiting room. Subject:", window.subjectName || interactiveGymGlobals?.subjectName,
        "Players:", waitroomState.cur_num_players, "/", (waitroomState.cur_num_players + waitroomState.players_needed),
        "Timeout:", Math.floor(waitroomState.ms_remaining / 1000), "seconds");

    if (waitroomInterval) {
        clearInterval(waitroomInterval);
    }

    $("#instructions").hide();

    // Store custom timeout message if provided
    waitroomTimeoutMessage = waitroomState.waitroom_timeout_message || null;

    var timer = Math.floor(waitroomState.ms_remaining / 1000); // Convert milliseconds to seconds


    // Update the text immediately to reflect the current state
    updateWaitroomText(waitroomState, timer);

    // Set up a new interval
    waitroomInterval = setInterval(function () {
        timer--;
        updateWaitroomText(waitroomState, timer);

        // Stop the timer if it reaches zero
        if (timer <= 0) {
            clearInterval(waitroomInterval);
            // Prevent start button from being re-enabled after timeout
            if (refreshStartButton) {
                clearInterval(refreshStartButton);
            }
            console.log("[WaitroomTimeout] Waiting room timed out. Subject:", window.subjectName || interactiveGymGlobals?.subjectName, "Session:", window.sessionId);
            socket.emit("leave_game", {session_id: window.sessionId})

            // Display custom message if configured, otherwise use default
            var message = waitroomTimeoutMessage ||
                "Sorry, we could not find enough players for this study. " +
                "Please return the HIT now. You will be paid through a Compensation HIT. " +
                "Thank you for your interest in our study!";
            $("#waitroomText").html("<p>" + message + "</p>");

            // Disable start button to prevent rejoining after timeout
            $("#startButton").hide();
            $("#startButton").attr("disabled", true);
        }
    }, 1000);
    $("#waitroomText").show();

})


var singlePlayerWaitroomInterval;
socket.on("single_player_waiting_room", function(singlePlayerWaitroom) {
    if (singlePlayerWaitroomInterval) {
        clearInterval(singlePlayerWaitroomInterval);
    }


    $("#instructions").hide();


    var simulater_timer = Math.floor(singlePlayerWaitroom.ms_remaining / 1000); // Convert milliseconds to seconds
    var single_player_timer = Math.floor(singlePlayerWaitroom.wait_duration_s); // already in second

    // Update the text immediately to reflect the current state
    updateWaitroomText(singlePlayerWaitroom, simulater_timer);

    // Set up a new interval
    singlePlayerWaitroomInterval = setInterval(function () {
        simulater_timer--;
        single_player_timer--;
        updateWaitroomText(singlePlayerWaitroom, simulater_timer);

        if (single_player_timer <= 0) {
            clearInterval(singlePlayerWaitroomInterval);
            socket.emit('single_player_waiting_room_end', {})
        }

        // // Stop the timer if it reaches zero
        // if (simulater_timer <= 0) {
        //     clearInterval(singlePlayerWaitroomInterval);
        //     $("#waitroomText").text("Sorry, could not find enough players. You will be redirected shortly...");
        //     console.log("Single player waitroom timed out!")
        //     socket.emit("leave_game", {session_id: window.sessionId})
        //     socket.emit('end_game_request_redirect', {waitroom_timeout: true})
        // }
    }, 1000);
    $("#waitroomText").show();

})


socket.on("single_player_waiting_room_failure", function(failureInfo) {
    console.log("Leaving game due to waiting room failure (other player left)...")
    // Prevent start button from being re-enabled after failure
    if (refreshStartButton) {
        clearInterval(refreshStartButton);
    }
    socket.emit("leave_game", {session_id: window.sessionId})

    // Display custom message if configured, otherwise use default
    var message = waitroomTimeoutMessage ||
        "Sorry, you were matched with a player but they disconnected before the game could start. " +
        "Please return the HIT now. You will be paid through a Compensation HIT. " +
        "Thank you for your interest in our study!";
    $("#waitroomText").html("<p>" + message + "</p>");

    // Disable start button to prevent rejoining after failure
    $("#startButton").hide();
    $("#startButton").attr("disabled", true);
})


socket.on("waiting_room_player_left", function() {
    // Clear the waitroom countdown interval
    if (waitroomInterval) {
        clearInterval(waitroomInterval);
    }
    // Prevent start button from being re-enabled after player left
    if (refreshStartButton) {
        clearInterval(refreshStartButton);
    }

    console.log("Leaving game due to player leaving waiting room...")
    socket.emit("leave_game", {session_id: window.sessionId})

    // Display custom message if configured, otherwise use default
    var message = waitroomTimeoutMessage ||
        "Another player left the waiting room. " +
        "Please return the HIT now. You will be paid through a Compensation HIT. " +
        "Thank you for your interest in our study!";
    $("#waitroomText").html("<p>" + message + "</p>");

    // Disable start button to prevent rejoining after player left
    $("#startButton").hide();
    $("#startButton").attr("disabled", true);
})

// P2P Validation Status (Phase 19) - log only, no UI updates
socket.on('p2p_validation_status', function(validationStatus) {
    console.log("[P2P] Validation status:", validationStatus.status);
});

// P2P Validation Re-pool (Phase 19)
socket.on('p2p_validation_repool', function(repoolInfo) {
    console.log("[P2P] Re-pool requested:", repoolInfo.reason);

    // Clear any existing waitroom intervals
    if (waitroomInterval) {
        clearInterval(waitroomInterval);
        waitroomInterval = null;
    }

    // Show message to user
    var message = repoolInfo.message || "Finding new partner...";
    $("#waitroomText").text(message);
    $("#waitroomText").show();

    // Brief delay, then re-emit join_game to re-enter matchmaking
    setTimeout(function() {
        console.log("[P2P] Re-joining matchmaking pool");
        socket.emit("join_game", {session_id: window.sessionId});
    }, 2000);
});

// P2P Validation Complete (Phase 19)
socket.on('p2p_validation_complete', function(validationResult) {
    console.log("[P2P] Validation complete, game starting");
});


function updateWaitroomText(waitroomConfig, timer) {
    var minutes = parseInt(timer / 60, 10);
    var seconds = parseInt(timer % 60, 10);

    minutes = minutes < 10 ? "0" + minutes : minutes;
    seconds = seconds < 10 ? "0" + seconds : seconds;

    if (waitroomConfig.hide_lobby_count) {
        // Hide participant count, only show timer
        $("#waitroomText").text(`Waiting ${minutes}:${seconds} for more players to join...`);
    } else {
        // Show participant count and timer
        $("#waitroomText").text(`There are ${waitroomConfig.cur_num_players} / ${waitroomConfig.cur_num_players + waitroomConfig.players_needed} players in the lobby. Waiting ${minutes}:${seconds} for more to join...`);
    }
}

socket.on("game_reset", function(resetData) {
    graphics_end()
    $('#hudText').hide()
    ui_utils.disableKeyListener();

    let scene_metadata = resetData.scene_metadata

    if (!scene_metadata) {
        scene_metadata = resetData.config;
    }

    if (!scene_metadata) {
        console.log("scene_metadata is undefined on game reset!")
        return;
    }

    // Initialize game
    let graphics_config = {
        'parent': 'gameContainer',
        'fps': {
            'target': scene_metadata.fps,
            'forceSetTimeOut': true
        },
        'height': scene_metadata.game_height,
        'width': scene_metadata.game_width,
        'background': scene_metadata.background,
        'state_init': scene_metadata.state_init,
        'assets_dir': scene_metadata.assets_dir,
        'assets_to_preload': scene_metadata.assets_to_preload,
        'animation_configs': scene_metadata.animation_configs,
        'scene_metadata': scene_metadata,
    };

    let input_mode = scene_metadata.input_mode;

    startResetCountdown(resetData.timeout, function() {
        // This function will be called after the countdown
        ui_utils.enableKeyListener(input_mode);
        graphics_start(graphics_config);

        socket.emit("reset_complete", {room: resetData.room, session_id: window.sessionId});
    });


})


function startResetCountdown(timeout, callback) {
    var timer = Math.floor(timeout / 1000); // Convert milliseconds to seconds


    $("#resetGame").show();
    var minutes = parseInt(timer / 60, 10);
    var seconds = parseInt(timer % 60, 10);
    minutes = minutes < 10 ? "0" + minutes : minutes;
    seconds = seconds < 10 ? "0" + seconds : seconds;
    $("#resetGame").text("Waiting for the next round to start in " + minutes + ":" + seconds + "...");


    var interval = setInterval(function () {
        timer--;
        if (timer <= 0) {
            clearInterval(interval);
            $("#resetGame").hide();
            if (callback) callback(); // Call the callback function
        } else {
            minutes = parseInt(timer / 60, 10);
            seconds = parseInt(timer % 60, 10);

            minutes = minutes < 10 ? "0" + minutes : minutes;
            seconds = seconds < 10 ? "0" + seconds : seconds;
            $("#resetGame").text("Waiting for the next round to start in " + minutes + ":" + seconds + "...");
        }
    }, 1000);
}

socket.on("create_game_failed", function(failureData) {
    $("#welcomeHeader").show();
    $("#welcomeText").show();
    $("#instructions").show();
    $("#waitroomText").hide();

     $("#startButton").show();
     $("#startButton").attr("disabled", false);


    let err = failureData['error']
    $('#errorText').show()
    $('#errorText').text(`Sorry, game creation code failed with error: ${JSON.stringify(err)}. You may try again by pressing the start button.`);
})


socket.on('environment_state', function(stateUpdate) {
    $('#hudText').show()
    $('#hudText').text(stateUpdate.hud_text)
    addStateToBuffer(stateUpdate);
});

// Server-authoritative mode: receive rendered state from server game loop
socket.on('server_render_state', function(data) {
    if (data.hud_text) {
        $('#hudText').show();
        $('#hudText').text(data.hud_text);
    }
    addStateToBuffer(data);
});





socket.on('end_game', function(endGameInfo) {
    console.log("game ended!")
    // Hide game data and display game-over html
    graphics_end();
    $('#hudText').hide();
    ui_utils.disableKeyListener();
    socket.emit("leave_game", {session_id: window.sessionId});
    $("#gameContainer").hide();

    if (endGameInfo.message != undefined) {
        $('#errorText').text(endGameInfo.message);
        $('#errorText').show();
    }



    socket.emit('end_game_request_redirect', {waitroom_timeout: false})
});


socket.on('end_game_request_redirect', function(redirectInfo) {
    console.log("received redirect")
    setTimeout(function() {
        // Redirect to the specified URL after the timeout
        window.location.href = redirectInfo.redirect_url;
    }, redirectInfo.redirect_timeout);
});


socket.on('update_game_page_text', function(pageUpdate) {
    // Don't update if screening failed
    if (experimentScreeningPassed === false) return;

    $("#sceneBody").html(pageUpdate.game_page_text);
    $("#sceneBody").show();
})


socket.on('request_pressed_keys', function(keyRequest) {
    console.log("request_pressed_keys", ui_utils.pressedKeys, pressedKeys, window.sessionId)
    socket.emit('send_pressed_keys', {'pressed_keys': Object.keys(pressedKeys), session_id: window.sessionId});
});





//  UPDATED

var currentSceneMetadata = {};

socket.on("activate_scene", function(sceneData) {
    console.log("Activating scene", sceneData.scene_id)
    // Retrieve interactiveGymGlobals from the global scope
    console.log("interactiveGymGlobals", interactiveGymGlobals)
    if (typeof interactiveGymGlobals !== 'undefined') {
        // Add interactiveGymGlobals to sceneData.globals
        console.log("interactiveGymGlobals", interactiveGymGlobals)
        sceneData.globals = sceneData.globals || {};
        Object.assign(sceneData.globals, interactiveGymGlobals);
    }
    activateScene(sceneData);
});


socket.on("terminate_scene", function(terminationData) {
    // Sync globals to server before terminating scene
    socket.emit("sync_globals", {interactiveGymGlobals: window.interactiveGymGlobals});

    if (terminationData.element_ids && terminationData.element_ids.length > 0) {
        let retrievedData = getData(terminationData.element_ids);
        socket.emit("static_scene_data_emission", {data: retrievedData, scene_id: terminationData.scene_id, session_id: window.sessionId, interactiveGymGlobals: window.interactiveGymGlobals});
    }

    terminateScene(terminationData);
    console.log("Terminating scene", terminationData.scene_id);
});


function getData(elementIds) {
    let retrievedData = {};
    elementIds.forEach(id => {
        let element = document.getElementById(id);
        if (element) {
            switch(element.tagName.toLowerCase()) {
                case 'input':
                    switch(element.type.toLowerCase()) {
                        case 'checkbox':
                            retrievedData[id] = element.checked;
                            break;
                        case 'radio':
                            let checkedRadio = document.querySelector(`input[name="${element.name}"]:checked`);
                            retrievedData[id] = checkedRadio ? checkedRadio.value : null;
                            break;
                        case 'range':
                            retrievedData[id] = parseFloat(element.value);
                            break;
                        default:
                            retrievedData[id] = element.value;
                    }
                    break;
                case 'select':
                    retrievedData[id] = Array.from(element.selectedOptions).map(option => option.value);
                    break;
                case 'textarea':
                    retrievedData[id] = element.value;
                    break;
                case 'button':
                    retrievedData[id] = element.textContent;
                    break;
                default:
                    retrievedData[id] = element.textContent;
            }
        } else {
            console.warn(`Element with id '${id}' not found`);
            retrievedData[id] = null;
        }
    });
    return retrievedData;
};


function activateScene(data) {
    window.scrollTo(0, 0);

    // Add scene_id to debug container
    // $("#debugValue").show();
    // $("#debugValue").text(`scene: ${data.scene_id}`);
    // $("#debugContainer").show();

    // Add interactiveGymGlobals to the data object
    if (typeof window.interactiveGymGlobals !== 'undefined') {
        data.interactiveGymGlobals = window.interactiveGymGlobals;
    } else {
        console.warn('interactiveGymGlobals is not defined in the window object');
        data.interactiveGymGlobals = {};
    }

    console.log(data);
    currentSceneMetadata = data;

    // If loading gate hasn't resolved, queue the scene for later.
    // The gate requires both screening AND Pyodide to complete before proceeding.
    if (!loadingGate.gateResolved) {
        console.log("[Scene] Loading gate not resolved, queueing scene:", data.scene_type);
        pendingSceneData = data;
        return;
    }

    // If screening failed, don't proceed with any scene
    if (experimentScreeningPassed === false) {
        console.log("[Scene] Blocked by failed screening");
        return;
    }

    if (data.scene_type == "EndScene" || data.scene_type == "CompletionCodeScene") {
        startEndScene(data);
    } else if (data.scene_type == "GymScene") {
        startGymScene(data);
    } else if (data.scene_type == "UnityScene" || data.is_unity_scene) {
        startUnityScene(data);
    } else {
        // Treat all other scenes as static scenes
        startStaticScene(data);
    }
};


function startStaticScene(data) {
    // Don't proceed if screening failed
    if (experimentScreeningPassed === false) {
        console.log("[Scene] Blocked by experiment-level screening");
        return;
    }

    // In the Static and Start scenes, we only show
    // the advanceButton, sceneHeader, and sceneBody
    // Hide other buttons that shouldn't be visible
    $("#startButton").hide();
    $("#startButton").attr("disabled", true);
    $("#startButtonLoader").removeClass("visible");
    $("#redirectButton").hide();

    $("#sceneHeader").show();
    $("#sceneSubHeader").show();

    $("#sceneBody").show();

    $("#advanceButton").attr("disabled", false);
    $("#advanceButton").show();

    $("#sceneHeader").html(data.scene_header);
    $("#sceneSubHeader").html(data.scene_subheader);
    $("#sceneBody").html(data.scene_body);

    // Gate advance button on Pyodide readiness (Phase 67)
    if (window.pyodidePreloadStatus === 'loading') {
        $("#advanceButton").attr("disabled", true);
        const pyodideGateInterval = setInterval(() => {
            if (window.pyodidePreloadStatus !== 'loading') {
                $("#advanceButton").attr("disabled", false);
                clearInterval(pyodideGateInterval);
            }
        }, 500);
    }
};

function startEndScene(data) {
    // Don't proceed if screening failed
    if (experimentScreeningPassed === false) {
        console.log("[Scene] Blocked by experiment-level screening");
        return;
    }

    // Hide buttons that shouldn't be visible in EndScene
    $("#startButton").hide();
    $("#startButton").attr("disabled", true);
    $("#startButtonLoader").removeClass("visible");
    $("#advanceButton").hide();
    $("#advanceButton").attr("disabled", true);
    $("#redirectButton").hide();

    $("#sceneHeader").show();
    $("#sceneSubHeader").show();
    $("#sceneBody").show();

    $("#sceneHeader").html(data.scene_header);
    $("#sceneSubHeader").html(data.scene_subheader);

    $("#sceneBody").html(data.scene_body);

    if (data.url !== undefined && data.url !== null) {
        $("#redirectButton").show();

        let url = data.url;

        if (data.append_subject_id) {
            url = url + subjectName;
        }

        $("#redirectButton").show();

        $("#redirectButton").on("click", function() {
            // Replace this with the URL you want to redirect to
            redirect_subject(url);
        });
    };

};

async function startGymScene(data) {
    enableStartRefreshInterval();

    // Check experiment-level screening (runs once at experiment start)
    if (experimentScreeningPassed === false) {
        // Failed experiment-level screening
        console.log("[EntryScreening] Blocked by experiment-level screening");
        showExclusionMessage(experimentScreeningMessage);
        clearInterval(refreshStartButton);
        return;
    }

    // Initialize or increment the gym scene counter
    if (typeof window.interactiveGymGlobals === 'undefined') {
        window.interactiveGymGlobals = {};
    }
    if (typeof window.interactiveGymGlobals.gymSceneCounter === 'undefined') {
        window.interactiveGymGlobals.gymSceneCounter = 1;
    } else {
        window.interactiveGymGlobals.gymSceneCounter++;
    }

    // First, check if we need to initialize Pyodide
    if (data.run_through_pyodide) {
        initializePyodideRemoteGame(data);
        enableCheckPyodideDone();
    };


    // Set the text that we'll display:
    $("#sceneHeader").html(data.scene_header);
    $("#sceneSubHeader").html(data.scene_subheader);
    $("#sceneBody").html(data.scene_body);


    // Next, we display the startButton, header, and body
    // Hide other buttons that shouldn't be visible in GymScene
    $("#advanceButton").hide();
    $("#advanceButton").attr("disabled", true);
    $("#redirectButton").hide();

    $("#sceneHeader").show();
    $("#sceneSubHeader").show();
    $("#sceneBody").show();
    $("#startButton").show();
    // Show loader immediately while Pyodide loads (button starts disabled)
    $("#startButtonLoader").addClass("visible");

};




function terminateScene(data) {
    if (data.scene_type == "EndScene") {
        terminateEndScene(data);
    } else if (data.scene_type == "GymScene") {
        terminateGymScene(data);
    } else if (data.scene_type == "UnityScene") {
        terminateUnityScene(data);
    } else {
        // (data.scene_type == "StaticScene" || data.scene_type == "StartScene" || data.scene_type == "EndScene")
        // Treat all other scenes as static scenes
        terminateStaticScene(data);
    }
}

function terminateStaticScene(data) {
    $("#sceneHeader").hide();
    $("#sceneSubHeader").hide();
    $("#sceneBody").hide();

    $("#sceneHeader").html("");
    $("#sceneSubHeader").html("");
    $("#sceneBody").html("");


    $("#advanceButton").hide();
    $("#advanceButton").attr("disabled", true);
}

function terminateGymScene(data) {
    ui_utils.disableKeyListener();
    graphics_end();

    // Clear any pending checkPyodideDone interval to prevent stale checks
    if (checkPyodideDone) {
        clearInterval(checkPyodideDone);
        checkPyodideDone = null;
    }
    // Also clear refreshStartButton if still running
    if (refreshStartButton) {
        clearInterval(refreshStartButton);
        refreshStartButton = null;
    }

    // Phase 77 (P2P-01, P2P-02): Clean up P2P resources when exiting GymScene
    // Must happen before data emission so sceneExited flag is set before any
    // race-window p2p_game_ended events can trigger stale overlays
    if (pyodideRemoteGame && typeof pyodideRemoteGame.cleanupForSceneExit === 'function') {
        pyodideRemoteGame.cleanupForSceneExit();
    }

    // Sync globals to server before emitting game data
    socket.emit("sync_globals", {interactiveGymGlobals: window.interactiveGymGlobals});

    // Emit multiplayer metrics separately if this is a multiplayer game
    // Metrics are sent via dedicated socket event for proper JSON storage (not bundled with game CSV)
    if (pyodideRemoteGame && typeof pyodideRemoteGame.emitMultiplayerMetrics === 'function') {
        pyodideRemoteGame.emitMultiplayerMetrics(data.scene_id);
    }

    let remoteGameData = getRemoteGameData();
    const binaryData = msgpack.encode(remoteGameData);
    socket.emit("emit_remote_game_data", {data: binaryData, scene_id: data.scene_id, session_id: window.sessionId, interactiveGymGlobals: window.interactiveGymGlobals});

    $("#sceneHeader").show();
    $("#sceneHeader").html("");

    $("#sceneSubHeader").show();
    $("#sceneSubHeader").html("");

    $("#sceneBody").show();
    $("#sceneBody").html("");

    $("#startButton").hide();
    $("#startButtonLoader").removeClass("visible");
    $("#gameContainer").hide();

    $('#hudText').hide()
    $('#hudText').text("")
    $('#hudText').html("")


};


// Button Logic

$(function() {
    $('#advanceButton').click( () => {
        // Gate advancement on Pyodide readiness (Phase 67)
        if (window.pyodidePreloadStatus === 'loading') {
            console.log('[AdvanceScene] Blocked - Pyodide still loading');
            return;
        }
        $("#advanceButton").hide();
        $("#advanceButton").attr("disabled", true);
        console.log("[AdvanceScene] Continue button clicked. Subject:", window.subjectName || interactiveGymGlobals?.subjectName);
        socket.emit("advance_scene", {session_id: window.sessionId});
    })
})

// GymScene

async function initializePyodideRemoteGame(data) {
    // Check if we need to create a new game instance:
    // 1. No existing game
    // 2. Explicit restart requested
    // 3. Switching between single-player and multiplayer (different game types)
    const needsNewInstance =
        pyodideRemoteGame === null ||
        data.restart_pyodide === true ||
        (data.pyodide_multiplayer === true && !(pyodideRemoteGame instanceof MultiplayerPyodideGame)) ||
        (data.pyodide_multiplayer !== true && pyodideRemoteGame instanceof MultiplayerPyodideGame);

    if (needsNewInstance) {
        // Create MultiplayerPyodideGame if multiplayer, otherwise RemoteGame
        if (data.pyodide_multiplayer === true) {
            console.log("Initializing MultiplayerPyodideGame");
            pyodideRemoteGame = new MultiplayerPyodideGame(data);
        } else {
            console.log("Initializing RemoteGame");
            pyodideRemoteGame = new RemoteGame(data);
        }
    } else {
        console.log("Reusing existing game instance, reinitializing environment");
        await pyodideRemoteGame.reinitialize_environment(data);
    }
};

var checkPyodideDone;
function enableCheckPyodideDone() {
    // Clear any existing interval to prevent orphaned checks from previous scenes
    if (checkPyodideDone) {
        clearInterval(checkPyodideDone);
        checkPyodideDone = null;
    }
    checkPyodideDone = setInterval(() => {
        if (pyodideRemoteGame !== undefined && pyodideRemoteGame.isDone()) {
            clearInterval(checkPyodideDone);
            clearInterval(refreshStartButton);
            // pyodideRemoteGame = undefined;

            // Create and show the countdown popup
            const popup = document.createElement('div');
            popup.style.cssText = `
                position: absolute;
                top: 50%;
                left: 50%;
                transform: translate(-50%, -50%);
                background: rgba(0, 0, 0, 0.8);
                color: white;
                padding: 20px 40px;
                border-radius: 10px;
                font-family: Arial, sans-serif;
                font-size: 18px;
                text-align: center;
                z-index: 1000;
                box-shadow: 0 4px 6px rgba(0, 0, 0, 0.1);
            `;
            const gameContainer = document.getElementById('gameContainer');
            gameContainer.style.position = 'relative';
            gameContainer.appendChild(popup);

            let countdown = 3;
            const updatePopup = () => {
                popup.innerHTML = `
                    <h2 style="margin-bottom: 10px; color: white;">Done!</h2>
                    <p>Continuing in <span style="font-weight: bold; font-size: 24px;">${countdown}</span> seconds...</p>
                `;
                if (countdown === 0) {
                    gameContainer.removeChild(popup);
                    socket.emit("advance_scene", {session_id: window.sessionId});
                } else {
                    countdown--;
                    setTimeout(updatePopup, 1000);
                }
            };
            updatePopup();
        }
    }, 100);
}



// Check if we're enabling the start button
var refreshStartButton;
function enableStartRefreshInterval() {
    refreshStartButton = setInterval(() => {
        // Don't process if screening failed
        if (experimentScreeningPassed === false) {
            clearInterval(refreshStartButton);
            $("#startButtonLoader").removeClass("visible");
            return;
        }

        // Use configured min_ping_measurements or default to 5
        const minPingMeasurements = currentSceneMetadata.min_ping_measurements || 5;

        if (currentSceneMetadata.scene_type !== "GymScene") {
            $("#startButton").hide();
            $("#startButton").attr("disabled", true);
            $("#startButtonLoader").removeClass("visible");
        } else if (maxLatency != null && latencyMeasurements.length > minPingMeasurements && curLatency > maxLatency) {
            // Use configured ping exclusion message if available, otherwise use default
            const pingMessage = currentSceneMetadata.exclusion_messages?.ping ||
                "Sorry, your connection is too slow for this application. Please make sure you have a strong internet connection to ensure a good experience for all players in the game.";
            showExclusionMessage(pingMessage);
            clearInterval(refreshStartButton);
            $("#startButtonLoader").removeClass("visible");
        } else if (maxLatency != null && latencyMeasurements.length <= minPingMeasurements) {
            $("#startButton").show();
            $("#startButton").attr("disabled", true);
            // Show loader while measuring ping
            $("#startButtonLoader").addClass("visible");
        }
        else if (pyodideReadyIfUsing()){
            $('#errorText').hide()
            $("#startButton").show();
            $("#startButton").attr("disabled", false);
            // Hide loader when ready
            $("#startButtonLoader").removeClass("visible");
            clearInterval(refreshStartButton);
        } else {
            // Pyodide not ready yet, show button as disabled with loader
            $("#startButton").show();
            $("#startButton").attr("disabled", true);
            $("#startButtonLoader").addClass("visible");
        }
    }, 500);
}


function redirect_subject(url) {
    window.location.href = url;
};



const startButton = window.document.getElementById('startButton');


socket.on("update_unity_score", function(scoreUpdate) {
    console.log("Updating Unity score", scoreUpdate.score);
    window.interactiveGymGlobals.unityScore = scoreUpdate.score;


    let hudText = '';
    if (scoreUpdate.num_episodes && scoreUpdate.num_episodes > 1) {
        hudText += `Round ${window.interactiveGymGlobals.unityEpisodeCounter + 1}/${scoreUpdate.num_episodes}`;
    }

    if (window.interactiveGymGlobals.unityScore !== null) {
        if (hudText) hudText += ' | ';
        hudText += `Score: ${window.interactiveGymGlobals.unityScore}`;
    }

    $("#hudText").html(hudText);

});

socket.on("unity_episode_end", function(episodeEndData) {

    // Update the HUD text to show the round progress and score
    window.interactiveGymGlobals.unityEpisodeCounter++;

    let hudText = '';
    if (episodeEndData.num_episodes && episodeEndData.num_episodes > 1) {
        hudText += `Round ${window.interactiveGymGlobals.unityEpisodeCounter + 1}/${episodeEndData.num_episodes}`;
    }

    if (window.interactiveGymGlobals.unityScore !== null) {
        if (hudText) hudText += ' | ';
        hudText += `Score: ${window.interactiveGymGlobals.unityScore}`;
    }

    $("#hudText").html(hudText);



    if (episodeEndData.all_episodes_done) {
        // Clear the Unity game container
        $("#gameContainer").hide();
        shutdownUnityGame();
        $("#gameContainer").html("");

        $("#sceneSubHeader").hide();
        $("#sceneBody").hide();

        $("#hudText").hide();

        // Start countdown for 3 seconds before advancing
        let timer = 3;
        $("#resetGame").show();
        $("#resetGame").text(`Continuing in ${timer} seconds...`);

        let interval = setInterval(function() {
            timer--;
            if (timer <= 0) {
                clearInterval(interval);
                $("#resetGame").hide();
                socket.emit("advance_scene", {session_id: window.sessionId});
            } else {
                $("#resetGame").text(`Continuing in ${timer} seconds...`);
            }
        }, 1000);

    }


});

socket.on('preload_unity_game', (config) => {
    console.log(`Received preload request for Unity game: ${config.build_name}`);
    preloadUnityGame(config).catch(error =>
        console.error(`Failed to preload ${config.build_name}:`, error)
    );
});
