import {actionFromONNX, initModelConfigs} from './onnx_inference.js';
import {drainInputDelayQueue} from './ui_utils.js';


var game_config = {
    type: Phaser.AUTO,
    pixelArt: true,
    audio: {
        noAudio: true
    },
    resolution: window.devicePixelRatio,
};

var game_graphics;
let stateBuffer = []
export function addStateToBuffer(state_data) {
    // Server-auth path: render_state contains the RenderPacket dict
    if (state_data.render_state) {
        if (state_data.render_state.game_state_objects !== undefined) {
            // New RenderPacket format: unwrap
            state_data.game_state_objects = state_data.render_state.game_state_objects;
            state_data.removed = state_data.render_state.removed || [];
        } else {
            // Fallback: treat render_state as flat list (legacy compat during transition)
            state_data.game_state_objects = state_data.render_state;
        }
    }
    if (state_data.game_state_objects == null) {
        console.warn("game_state is null, skipping frame");
        return;
    }
    stateBuffer.push(state_data);
}

export function clearStateBuffer() {
    stateBuffer = [];
}

// Contains an array for each bot that we'll shift to get the most recent action
// Bots are queried asynchronously!
let botActionBuffers = {};

let humanKeyPressBuffer = [];
const MAX_KEY_PRESS_BUFFER_SIZE = 1;
/**
 * Add a keypress to the buffer with timestamp (DIAG-01, DIAG-02).
 * @param {Object|string} input - Either {key, keypressTimestamp} object or legacy action string
 */
export function addHumanKeyPressToBuffer(input) {
    // TODO(chase): this should filter out actions that aren't allowed,
    // otherwise hitting an unrelated key could cancel out previous actions.
    // BUG FIX: Was comparing array to number, should compare length
    if (humanKeyPressBuffer.length >= MAX_KEY_PRESS_BUFFER_SIZE) {
        const dropped = humanKeyPressBuffer.shift(); // remove the oldest state
        console.warn(`[INPUT-DROPPED] key=${dropped.key} age=${(performance.now() - dropped.keypressTimestamp).toFixed(1)}ms - buffer full`);
    }
    // Support both new format {key, keypressTimestamp} and legacy string format
    if (typeof input === 'object' && input.key !== undefined) {
        humanKeyPressBuffer.push({
            key: input.key,
            keypressTimestamp: input.keypressTimestamp
        });
    } else {
        // Legacy format - use current time as timestamp
        humanKeyPressBuffer.push({
            key: input,
            keypressTimestamp: performance.now()
        });
    }
}

export var pressedKeys = {};
// DIAG-01: Track timestamps for when each key was first pressed
export var pressedKeyTimestamps = {};

/**
 * Update pressed keys with optional timestamp tracking (DIAG-01).
 * @param {Object} updatedPressedKeys - Map of key -> true for pressed keys
 * @param {number} keypressTimestamp - Optional timestamp for newly pressed keys
 */
export function updatePressedKeys(updatedPressedKeys, keypressTimestamp = null) {
    // Track timestamps for newly pressed keys
    if (keypressTimestamp !== null) {
        for (const key of Object.keys(updatedPressedKeys)) {
            // Only set timestamp if key is newly pressed (not already in pressedKeyTimestamps)
            if (pressedKeyTimestamps[key] === undefined) {
                pressedKeyTimestamps[key] = keypressTimestamp;
            }
        }
    }
    // Remove timestamps for released keys
    for (const key of Object.keys(pressedKeyTimestamps)) {
        if (!updatedPressedKeys[key]) {
            delete pressedKeyTimestamps[key];
        }
    }
    pressedKeys = updatedPressedKeys;
}

/**
 * Clear all human input buffers.
 * Called when game pauses (waiting for partner) to prevent input accumulation.
 */
export function clearHumanInputBuffers() {
    humanKeyPressBuffer = [];
    pressedKeys = {};
    pressedKeyTimestamps = {};
}

// Contains the last action submitted at each step
var previousSubmittedActions = {};


let currentObservations = {};

class RemoteGameDataLogger {
    constructor() {
        this.data = {
            observations: {},
            actions: {},
            rewards: {},
            terminateds: {},
            truncateds: {},
            infos: {},
            isFocused: {},  // Per-player focus state (true = focused, false = backgrounded)
            episode_num: [],
            t: [],
            timestamp: [],
            player_subjects: null  // Set once when available (player_id -> subject_id mapping)
        };
    }

    logData(gameData) {
        const logDataForField = (field) => {
            if (gameData[field] !== undefined ) {
                const data = gameData[field] instanceof Map ? Object.fromEntries(gameData[field]) : gameData[field];
                for (let agentId in data) {
                    if (!this.data[field][agentId]) {
                        this.data[field][agentId] = [];

                    }

                    if (field !== 'observations') {
                        this.data[field][agentId].push(data[agentId]);
                    }

                }
            }
        };

        ['observations', 'actions', 'rewards', 'terminateds', 'truncateds', 'isFocused'].forEach(logDataForField);

        if (gameData.infos !== undefined) {
            const infos = gameData.infos instanceof Map ? Object.fromEntries(gameData.infos) : gameData.infos;
            for (let agentId in infos) {
                if (!this.data.infos[agentId]) {
                    this.data.infos[agentId] = {};
                }
                for (let key in infos[agentId]) {
                    if (!this.data.infos[agentId][key]) {
                        this.data.infos[agentId][key] = [];
                    }
                    this.data.infos[agentId][key].push(infos[agentId][key]);
                }
            }
        }

        if (gameData.episode_num !== undefined) {
            this.data.episode_num.push(gameData.episode_num);
        }
        if (gameData.t !== undefined) {
            this.data.t.push(gameData.t);
        }

        // Store player_subjects mapping (only needs to be set once, not per-frame)
        if (gameData.player_subjects !== undefined && this.data.player_subjects === null) {
            this.data.player_subjects = gameData.player_subjects;
        }

        // Always add the current timestamp
        this.data.timestamp.push(Date.now());
    }

    getData() {
        return JSON.parse(JSON.stringify(this.data));
    }

    reset() {
        this.data = {
            observations: {},
            actions: {},
            rewards: {},
            terminateds: {},
            truncateds: {},
            infos: {},
            isFocused: {},
            episode_num: [],
            t: [],
            timestamp: [],
            player_subjects: null
        };
    }
}

let remoteGameLogger = new RemoteGameDataLogger();

export function getRemoteGameData() {
    let data = remoteGameLogger.getData();
    remoteGameLogger.reset();
    return data;
}

/**
 * Emit episode data incrementally to avoid large payloads at scene end.
 * Called at the end of each episode to send data in manageable chunks.
 * @param {string} sceneId - The scene ID for file organization
 * @param {number} episodeNum - The episode number (0-indexed)
 */
export function emitEpisodeData(sceneId, episodeNum) {
    if (!window.socket) {
        console.error('[emitEpisodeData] Socket not available');
        return;
    }

    // Get current data and reset logger for next episode
    const episodeData = remoteGameLogger.getData();
    remoteGameLogger.reset();

    // Skip if no data to send
    if (!episodeData || episodeData.t.length === 0) {
        console.log(`[emitEpisodeData] No data to emit for episode ${episodeNum}`);
        return;
    }

    // Encode to msgpack for efficient transmission
    const binaryData = msgpack.encode(episodeData);

    console.log(`[emitEpisodeData] Emitting episode ${episodeNum} data: ${episodeData.t.length} frames, ${binaryData.byteLength} bytes`);

    window.socket.emit("emit_episode_data", {
        data: binaryData,
        scene_id: sceneId,
        episode_num: episodeNum,
        session_id: window.sessionId,
        interactiveGymGlobals: window.interactiveGymGlobals
    });
}

export function graphics_start(graphics_config) {
    // Clean up any existing game instance before creating a new one
    // This prevents duplicate Phaser canvases from appearing
    if (game_graphics && game_graphics.game) {
        console.log("[graphics_start] Destroying existing game instance before creating new one");
        try {
            $("#gameContainer").empty();
            game_graphics.game.destroy(true);
        } catch (e) {
            console.warn("[graphics_start] Error destroying existing game:", e);
        }
        stateBuffer = [];
    }
    game_graphics = new GraphicsManager(game_config, graphics_config);
}


export function graphics_end() {
    $("#gameContainer").empty();
    if (game_graphics && game_graphics.game) {
        try {
            game_graphics.game.destroy(true);
        } catch (e) {
            console.warn("[graphics_end] Error destroying game:", e);
        }
    }
    game_graphics = null;
    stateBuffer = [];
}

class GraphicsManager {
    constructor(game_config, graphics_config) {
        game_config.scene = new GymScene(graphics_config);
        game_config.location_representation = graphics_config.location_representation;
        game_config.width = graphics_config.width;
        game_config.height = graphics_config.height;
        game_config.background = graphics_config.background;
        game_config.state_init = graphics_config.state_init;
        game_config.assets_dir = graphics_config.assets_dir;
        game_config.assets_to_preload = graphics_config.assets_to_preload;
        game_config.animation_configs = graphics_config.animation_configs;
        game_config.parent = graphics_config.parent;
        game_config.fps = graphics_config.fps;
        game_config.scene_metadata = graphics_config.scene_metadata;
        this.game = new Phaser.Game(game_config);
        // TODO(chase): Figure out proper resizing. Sprites must be resized as well but they aren't if we do this.
        // this.resizeGame();

        // // Add a resize event listener to adjust the game size dynamically
        // window.addEventListener('resize', this.resizeGame.bind(this));
    }

    // resizeGame() {
    //     // Example resize logic: Adjust game size while maintaining aspect ratio
    //     let width = window.innerWidth;
    //     let height = window.innerHeight;
    //     let gameRatio = this.game.config.width / this.game.config.height;
    //     let newWidth = width;
    //     let newHeight = width / gameRatio;

    //     if (newHeight > height) {
    //         newHeight = height;
    //         newWidth = height * gameRatio;
    //     }

    //     this.game.scale.resize(newWidth, newHeight);
    // }

}



class GymScene extends Phaser.Scene {

    constructor(config) {
        super({key: "GymScene"});
        this.objectMap = new Map();
        this.state = config.state_init;
        this.assets_dir = config.assets_dir;
        this.assets_to_preload = config.assets_to_preload;
        this.animation_configs = config.animation_configs;
        this.background = config.background;
        this.last_rendered_step = -1;
        this.scene_metadata = config.scene_metadata;
        initModelConfigs(this.scene_metadata);
        this.pyodide_remote_game = config.pyodide_remote_game;
        this.isProcessingPyodide = false;
        this.stateImageSprite = null;

        if (this.pyodide_remote_game) {
            this.pyodide_remote_game.reinitialize_environment(this.pyodide_remote_game.config);
        }
    }
    preload () {

        // Load images or atlases for sprite sheets
        this.assets_to_preload.forEach(obj_config => {
            if (obj_config.object_type == "img_spec") {
                this.load.image(obj_config.name, obj_config.img_path)
            } else if (obj_config.object_type == "spritesheet") {
                this.load.spritesheet(obj_config.name, obj_config.img_path, {frameWidth: obj_config.frame_width, frameHeight: obj_config.frame_height})
            } else if (obj_config.object_type == "atlas_spec") {
                this.load.atlas(obj_config.name, obj_config.img_path, obj_config.atlas_path)

            } else if (obj_config.object_type == "multi_atlas_spec") {
                this.load.multiatlas(obj_config.name, obj_config.atlas_path, obj_config.img_path)
            }
        });

        //
        // // Define any animations that we might use on our sprites
        // for (let anim in this.animation_configs) {
        //     this.anims.add(
        //          {
        //              key: anim.key,
        //              frames: anim.frames,
        //              frameRate: anim.frameRate,
        //              repeat: anim.repeat,
        //              hideOnComplete: anim.hideOnComplete,
        //          }
        //      )
        // }
    };

    create() {
        // Store the canvas, width, and height for easy access
        this.canvas = this.sys.game.canvas;
        this.canvas.id = "phaser-canvas";
        this.height = this.canvas.height;
        this.width = this.canvas.width;
        this.stateImageSprite = this.add.image(0, 0, "curStateImage").setOrigin(0, 0);

        // Expose scene for debugging and E2E test introspection
        window._phaserScene = this;

        // Check if the background is just a color, if so fill
        if (this._checkIfHex(this.background)) {
            this.cameras.main.setBackgroundColor(this._strToHex(this.background));
        } else {
            // If the background isn't a color, load the specified image
            this._addTexture(this.background);
            this.add.image(this.height / 2, this.width / 2, this.background);
        }

        // Draw the initial state, if anything
        if (stateBuffer.length > 0) {
            this.state = stateBuffer.shift(); // get the oldest state from the buffer
            this.drawState()
        }

        // Register Worker tick callback for multiplayer games (Phase 24)
        // Worker timing ensures game logic advances even when tab is backgrounded
        if (this.pyodide_remote_game?.registerTickCallback) {
            this.pyodide_remote_game.registerTickCallback(() => this.onWorkerTick());
        }
    };

    /**
     * Handle a tick from the Web Worker timer (Phase 24).
     * Called by MultiplayerPyodideGame when Worker sends a tick.
     * Triggers game logic processing and clears the processing flag when done.
     */
    async onWorkerTick() {
        const tickProcessStart = performance.now();
        await this.processPyodideGame();
        const tickProcessTime = performance.now() - tickProcessStart;

        // Clear the processing flag after game step completes
        if (this.pyodide_remote_game) {
            this.pyodide_remote_game.isProcessingTick = false;

            // Warn if processing took longer than the frame budget
            const frame = this.pyodide_remote_game.frameNumber;
            const targetInterval = 1000 / (this.pyodide_remote_game.config?.fps || 10);
            if (tickProcessTime > targetInterval) {
                console.warn(`[TICK-OVERRUN] frame=${frame} processTime=${tickProcessTime.toFixed(1)}ms EXCEEDS budget=${targetInterval.toFixed(0)}ms - WILL CAUSE LAG`);
            }
        }
    }

    update() {

        if (this.pyodide_remote_game && this.pyodide_remote_game.state === "done") {
            this.removeAllObjects();
            return;
        };

        // For multiplayer games with Worker timing (Phase 24):
        // Game logic (processPyodideGame) is triggered by Worker ticks, not Phaser's RAF loop.
        // Worker ticks continue at full speed even when tab is backgrounded.
        // Phaser's update() only handles rendering in this case.
        const hasWorkerTiming = this.pyodide_remote_game?.timerWorker;

        // For single-player games or games without Worker: use original RAF-driven processing
        if (!hasWorkerTiming) {
            // Check if game is ready to process:
            // 1. pyodide_remote_game exists
            // 2. Not already processing
            // 3. Pyodide is ready
            // 4. P2P is ready (for multiplayer - waits for WebRTC connection or timeout)
            const p2pReady = !this.pyodide_remote_game?.isP2PReady || this.pyodide_remote_game.isP2PReady();
            if (this.pyodide_remote_game && !this.isProcessingPyodide && this.pyodide_remote_game.pyodideReady && p2pReady) {
                this.processPyodideGame();
            }
        }

        // Rendering always happens (will pause naturally when tab is backgrounded via RAF)
        this.processRendering();
    };



    async processPyodideGame() {
        this.isProcessingPyodide = true;
        if (this.pyodide_remote_game && this.pyodide_remote_game.pyodideReady) {
            let rewards, terminateds, truncateds, infos, render_state;
            if (this.pyodide_remote_game.shouldReset) {
                currentObservations = {};
                clearStateBuffer();
                this.removeAllObjects();
                const resetResult = await this.pyodide_remote_game.reset();

                // Handle null return (shouldn't happen for reset, but be safe)
                if (resetResult === null) {
                    this.isProcessingPyodide = false;
                    return;
                }

                [currentObservations, infos, render_state] = resetResult;
                console.debug("[MultiplayerPyodide] Reset result:", resetResult);
                remoteGameLogger.logData(
                    {
                        observations: currentObservations,
                        infos: infos,
                        episode_num: this.pyodide_remote_game.num_episodes,
                        t: this.pyodide_remote_game.step_num,
                        player_subjects: this.pyodide_remote_game.playerSubjects,
                        isFocused: this.pyodide_remote_game.getFocusStatePerPlayer?.() || {}
                    });
            } else {
                const actions = await this.buildPyodideActionDict();
                previousSubmittedActions = actions;

                // DIAG-02: Pass input timestamps to step() for pipeline tracking
                const inputTimestamps = this._pendingInputTimestamps;
                this._pendingInputTimestamps = null;  // Clear after reading

                // Pass timestamps to pyodide_remote_game for latency tracking
                if (inputTimestamps && this.pyodide_remote_game.setInputTimestamps) {
                    this.pyodide_remote_game.setInputTimestamps(inputTimestamps);
                }

                const stepResult = await this.pyodide_remote_game.step(actions);

                // Handle null return (e.g., game paused for resync)
                if (stepResult === null) {
                    this.isProcessingPyodide = false;
                    return;
                }

                // stepResult may include synchronized actions (7th element) from multiplayer games
                let syncedActions;
                if (stepResult.length >= 7) {
                    [currentObservations, rewards, terminateds, truncateds, infos, render_state, syncedActions] = stepResult;
                } else {
                    [currentObservations, rewards, terminateds, truncateds, infos, render_state] = stepResult;
                    syncedActions = actions;  // Fallback to local actions for single-player
                }

                // Check if this is a multiplayer game with rollback support
                // For multiplayer, frame data is stored inside step() to ensure correct frame number
                // Only use remoteGameLogger for single-player mode
                const isMultiplayerWithRollback = this.pyodide_remote_game.storeFrameData !== undefined;

                if (!isMultiplayerWithRollback) {
                    // Single-player mode: use standard logger (no rollback concerns)
                    remoteGameLogger.logData(
                        {
                            observations: currentObservations,
                            actions: syncedActions,
                            rewards: rewards,
                            terminateds: terminateds,
                            truncateds: truncateds,
                            infos: infos,
                            episode_num: this.pyodide_remote_game.num_episodes,
                            t: this.pyodide_remote_game.step_num,
                            player_subjects: this.pyodide_remote_game.playerSubjects,
                            isFocused: this.pyodide_remote_game.getFocusStatePerPlayer?.() || {}
                        });
                }
                // Note: For multiplayer, data is stored in step() before frameNumber++ to ensure correct frame
            }
            addStateToBuffer(render_state);
        }
        this.isProcessingPyodide = false;
    };

    async buildPyodideActionDict() {
        let actions = {};
        // DIAG-02: Store input timestamps for pipeline latency tracking
        this._pendingInputTimestamps = null;

        // In multiplayer mode, only collect keyboard input for THIS player's agent
        let isMultiplayer = this.pyodide_remote_game && this.pyodide_remote_game.myPlayerId !== undefined;
        let myPlayerId = isMultiplayer ? String(this.pyodide_remote_game.myPlayerId) : null;

        // Loop over all agents in the policy mapping
        for (let [agentID, policy] of Object.entries(this.scene_metadata.policy_mapping)) {
            if (policy == "human") {
                // In multiplayer, only get keyboard input for MY player
                if (isMultiplayer) {
                    if (agentID == myPlayerId) {
                        const humanActionResult = this.getHumanAction();
                        actions[agentID] = humanActionResult.action;
                        // Store timestamps if this was a real input (not default action)
                        if (humanActionResult.hasRealInput && humanActionResult.keypressTimestamp !== null) {
                            this._pendingInputTimestamps = {
                                playerId: agentID,
                                keypressTimestamp: humanActionResult.keypressTimestamp,
                                queueExitTimestamp: humanActionResult.queueExitTimestamp
                            };
                        }
                    } else {
                        // Other human players - use default action (will be replaced by server)
                        actions[agentID] = this.scene_metadata.default_action || 0;
                    }
                } else {
                    // Single player - get keyboard input for this human
                    const humanActionResult = this.getHumanAction();
                    actions[agentID] = humanActionResult.action;
                    // Store timestamps if this was a real input (not default action)
                    if (humanActionResult.hasRealInput && humanActionResult.keypressTimestamp !== null) {
                        this._pendingInputTimestamps = {
                            playerId: agentID,
                            keypressTimestamp: humanActionResult.keypressTimestamp,
                            queueExitTimestamp: humanActionResult.queueExitTimestamp
                        };
                    }
                }
            } else {
                // Bot agent
                actions[agentID] = this.getBotAction(agentID);
            }
        }

        return actions;
    }

    getBotAction(agentID) {
        let policy_mapping = this.scene_metadata.policy_mapping;

        // If the bot is action on this step (according to frame skip), calculate an action.
        if (this.pyodide_remote_game && this.pyodide_remote_game.step_num % this.scene_metadata.frame_skip == 0) {
            let policyID = policy_mapping[agentID];
            // Check if the policy mapping ends with .onnx to indicate an ONNX model
            if (policyID.endsWith(".onnx")) {
                // Cast the agent ID to an integer
                let observation = currentObservations.get(isNaN(agentID) ? agentID : parseInt(agentID));
                this.queryBotPolicy(agentID, policyID, observation);
            } else if (policyID === "random") {
                // If the policy is random, return a random action
                return Math.floor(Math.random() * Object.keys(this.scene_metadata.action_mapping).length + 1) - 1;
            }
        }

        // If the bot was queried asynchronously, we may now have an action to execute
        if (botActionBuffers[agentID] !== undefined && botActionBuffers[agentID].length > 0) {
            return botActionBuffers[agentID].shift();
        } else {
            // Otherwise, just return the default as specified by the settings

            // If we're using previous_action as population method, return the previous action
            if (
                this.scene_metadata.action_population_method === "previous_submitted_action" &&
                previousSubmittedActions[agentID] !== undefined
            ) {
                return previousSubmittedActions[agentID];
            } else {
                // If we're using default_action as population method, return the default action
                return this.scene_metadata.default_action;
            }
        }
    }

    async queryBotPolicy(agentID, policyID, observation) {

        if (botActionBuffers[agentID] === undefined) {
            botActionBuffers[agentID] = [];
        }

        // Calculate the action and add it to the buffer
        let action = await actionFromONNX(policyID, observation, agentID);
        botActionBuffers[agentID].push(action);
    }

    /**
     * Get the current human action with timestamps for latency tracking (DIAG-01, DIAG-02).
     * @returns {Object} {action, keypressTimestamp, queueExitTimestamp, hasRealInput}
     */
    getHumanAction() {
        let human_action;
        let keypressTimestamp = null;
        let hasRealInput = false;  // True if this is from actual user input (not default action)
        const queueExitTimestamp = performance.now();  // DIAG-02: Capture exit time

        // If single_keystroke, we'll get the action that was added to the buffer when the key was pressed
        if (this.scene_metadata.input_mode === "single_keystroke") {
            if (humanKeyPressBuffer.length > 0) {
                const bufferedInput = humanKeyPressBuffer.shift();
                // Get keypress timestamp and key from the buffered object
                keypressTimestamp = bufferedInput.keypressTimestamp;
                const key = bufferedInput.key;
                human_action = this.scene_metadata.action_mapping[key];
                if (human_action == undefined) {
                    human_action = this.scene_metadata.default_action;
                } else {
                    hasRealInput = true;
                }
            } else {
                human_action = this.scene_metadata.default_action;
            }
        } else if (this.scene_metadata.input_mode === "pressed_keys") {
            // If pressed_keys, we get the (potentially composite) action from the currently pressed keys
            if (pressedKeys == undefined || pressedKeys.length == 0 || Object.keys(pressedKeys).length === 0) {
                // if no keys are pressed, we'll use the default action
                human_action = this.scene_metadata.default_action;
            } else if (Object.keys(pressedKeys).length === 1) {
                const key = Object.keys(pressedKeys)[0];
                human_action = this.scene_metadata.action_mapping[key];
                // Get the earliest timestamp of currently pressed keys
                keypressTimestamp = pressedKeyTimestamps[key] || null;
                if (human_action == undefined) {
                    human_action = this.scene_metadata.default_action;
                } else {
                    hasRealInput = true;
                }
            } else {
                // multiple keys are pressed so check for a composite action
                const compositeKey = this.generateCompositeAction()[0];
                human_action = this.scene_metadata.action_mapping[compositeKey];
                // Get the earliest timestamp of all currently pressed keys
                const timestamps = Object.values(pressedKeyTimestamps).filter(t => t !== undefined);
                keypressTimestamp = timestamps.length > 0 ? Math.min(...timestamps) : null;
                if (human_action == undefined) {
                    human_action = this.scene_metadata.default_action;
                } else {
                    hasRealInput = true;
                }
            }
        }

        return {
            action: human_action,
            keypressTimestamp: keypressTimestamp,
            queueExitTimestamp: queueExitTimestamp,
            hasRealInput: hasRealInput
        };
    }

    generateCompositeAction() {
        // TODO: Set this in the config so we don't recalculate every time
        let compPressedKeys = undefined;
        const maxCompositeActionSize = Math.max(
            ...Object.keys(this.scene_metadata.action_mapping)
                .filter(key => typeof key === 'string' && key.includes(','))
                .map(key => key.split(',').length),
            0
        );

        if (maxCompositeActionSize > 1) {
            const compositeActions = Object.keys(this.scene_metadata.action_mapping)
            .filter(key => typeof key === 'string' && key.includes(','))

            let curKeys = Object.keys(pressedKeys);
            let combinations = [];
            for (let k = 2; k <= maxCompositeActionSize; k++) {
                combinations = combinations.concat(combinationsOf(curKeys, k));
            }

            for (const combination of combinations) {
                const sortedCombination = combination.sort().join(',');
                if (compositeActions.includes(sortedCombination)) {
                    compPressedKeys = [sortedCombination];
                    break;
                }
            }
        }

        // If we don't get a composite action, check if any single-keys within the composite work
        if (compPressedKeys == undefined) {
            // For single key actions, find the first pressed key that has a valid mapping
            const validKeys = Object.keys(pressedKeys).filter(key =>
                key in this.scene_metadata.action_mapping
            );
            if (validKeys.length > 0) {
                compPressedKeys = [validKeys[0]];
            } else {
                compPressedKeys = [undefined];
            }
        }
        return compPressedKeys;
    }

    processRendering() {
        const frame = this.pyodide_remote_game?.frameNumber || 0;

        // Server-auth input delay: drain queued actions on each render tick
        if (window.serverAuthoritative && window.serverAuthInputDelay > 0) {
            drainInputDelayQueue();
        }

        // FIX: Drain buffer by rendering multiple states when behind
        // This catches up without skipping visual frames
        const targetBufferSize = 1;  // Ideal: always render the latest
        const maxRenderPerFrame = 5; // Safety limit to avoid long frames

        let renderCount = 0;
        const startBufferLen = stateBuffer.length;

        while (stateBuffer.length > targetBufferSize && renderCount < maxRenderPerFrame) {
            this.state = stateBuffer.shift();
            this.drawState();
            renderCount++;
        }

        if (renderCount > 1) {
            console.log(`[RENDER-CATCHUP] frame=${frame} rendered ${renderCount} states to catch up (was ${startBufferLen} behind)`);
        }

        // Render the final state with latency tracking
        if (stateBuffer.length > 0) {
            // DIAG-05: Capture render begin timestamp
            const renderBeginTimestamp = performance.now();

            this.state = stateBuffer.shift();
            this.drawState();

            // DIAG-06: Capture render complete timestamp
            const renderCompleteTimestamp = performance.now();

            // DIAG-07: Log pipeline latency if pyodide_remote_game supports it
            if (this.pyodide_remote_game?.logPipelineLatency) {
                this.pyodide_remote_game.logPipelineLatency(renderBeginTimestamp, renderCompleteTimestamp);
            }
        }
    }

    drawState() {

        /*
        Iterate over the objects defined in the state and
        add them to the environment and update as necessary.
         */

        // Retrieve the list of object contexts
        if (this.state == null || this.state == undefined) {
            console.debug("No state to render.");
            return;
        }

        let game_state_objects = this.state.game_state_objects;
        let game_state_image = this.state.game_image_binary;

        // If we don't have any object contexts, we render the image from `env.render()`
        // NOTE: This approach is very inefficient and not good practice! It's oriented
        //  to testing or local experiments.
        if (game_state_objects == null && !(game_state_image == null)) {

            const blob = new Blob([game_state_image], { type: 'image/jpeg' });
            const url = URL.createObjectURL(blob);

            // Create an image element to load Blob URL
            const img = new Image();
            img.crossOrigin = "anonymous"; // Prevent CORS issues
            img.src = url;

            img.onload = () => {
                console.debug("Image loaded successfully:", img.width, img.height);

                // Create a temporary canvas to ensure it's WebGL-compatible
                const canvas = document.createElement("canvas");
                const ctx = canvas.getContext("2d");

                // Set canvas dimensions to match the image
                canvas.width = img.width;
                canvas.height = img.height;
                ctx.drawImage(img, 0, 0);

                // Ensure old texture is removed first
                if (this.textures.exists("curStateImage")) {
                    this.textures.remove("curStateImage");
                }

                // Now safely add the new texture
                this.textures.addImage("curStateImage", canvas);

                if (this.stateImageSprite) {
                    this.stateImageSprite.setTexture("curStateImage");
                } else {
                    this.stateImageSprite = this.add.image(0, 0, "curStateImage").setOrigin(0, 0);
                }

                // Cleanup URL to prevent memory leaks
                URL.revokeObjectURL(url);

            };

            img.onerror = (err) => {
                console.error("Failed to load image:", err);
            };

        } else if (game_state_objects != null) {
            let removedIds = this.state.removed || [];

            // 1. Process explicit removals (persistent objects removed by Surface.remove())
            for (const id of removedIds) {
                if (this.objectMap.has(id)) {
                    this.objectMap.get(id).destroy();
                    this.objectMap.delete(id);
                }
            }

            // 2. Destroy non-permanent objects from previous frame that aren't in current frame
            let currentFrameIds = new Set(game_state_objects.map(o => o.uuid));
            for (const [id, obj] of this.objectMap) {
                if (!obj.permanent && !currentFrameIds.has(id)) {
                    obj.destroy();
                    this.objectMap.delete(id);
                }
            }

            // 3. Add or update each object
            for (const objConfig of game_state_objects) {
                if (!this.objectMap.has(objConfig.uuid)) {
                    this._addObject(objConfig);
                }
                this._updateObject(objConfig);
            }
        }
    };

    removeAllObjects() {
        for (const [uuid, obj] of this.objectMap) {
            obj.destroy();
        }
        this.objectMap.clear();
    }

    _addObject(object_config) {
        if (object_config.object_type === "sprite") {
            this._addSprite(object_config);
        } else if (object_config.object_type === "animation") {
            this._addAnimation(object_config);
        } else if (object_config.object_type === "line") {
            this._addLine(object_config);
        } else if (object_config.object_type === "circle") {
            this._addCircle(object_config);
        } else if (object_config.object_type === "rect" || object_config.object_type === "rectangle") {
            this._addRectangle(object_config);
        } else if (object_config.object_type === "polygon") {
            this._addPolygon(object_config);
        } else if (object_config.object_type === "text") {
            this._addText(object_config);
        } else {
            console.warn("Unrecognized object type in _addObject:", object_config.object_type);
        }
    }

    _updateObject(object_config) {
        if (object_config.object_type === "sprite") {
            this._updateSprite(object_config);
        } else if (object_config.object_type === "line") {
            this._updateLine(object_config);
        } else if (object_config.object_type === "circle") {
            this._updateCircle(object_config);
        } else if (object_config.object_type === "rect" || object_config.object_type === "rectangle") {
            this._updateRectangle(object_config);
        } else if (object_config.object_type === "polygon") {
            this._updatePolygon(object_config);
        } else if (object_config.object_type === "text") {
            this._updateText(object_config);
        } else {
            console.warn("Unrecognized object type in _updateObject:", object_config.object_type);
        }
    }

    _addSprite(object_config) {
        let uuid = object_config.uuid;

        let x = Math.floor(object_config.x * this.width);
        let y = Math.floor(object_config.y * this.height);

        // Add a blank sprite to the specified location, everything else
        // will be updated in _updateObject
        let sprite = this.add.sprite(
            {
                x: x,
                y: y,
                depth: object_config.depth,
            }
        );

        sprite.tween = null;
        sprite.x = x;
        sprite.y = y;
        sprite.permanent = object_config.permanent || false;
        this.objectMap.set(uuid, sprite);
    };

    _updateSprite(object_config) {
        let sprite = this.objectMap.get(object_config.uuid);

        sprite.angle = object_config.angle;

        // TODO(chase): enable animation playing
        // if (object_config.cur_animation !== null && obj.anims.getCurrentKey() !== object_config.cur_animation) {
        //     obj.play(object_config.cur_animation)
        // } else
        if (object_config.image_name !== null) {
            if (object_config.frame !== null) {
                sprite.setTexture(object_config.image_name, object_config.frame);
            } else {
                sprite.setTexture(object_config.image_name)
            }

            sprite.setDisplaySize(object_config.width, object_config.height);
            sprite.setOrigin(0);
        }

        let new_x = Math.floor(object_config.x * this.width);
        let new_y = Math.floor(object_config.y * this.height);

        this._applyPositionTween(sprite, new_x, new_y, object_config);
    }

    // _addTexture(texture_name) {
    //     // Load the asset with the filepath as the ID
    //     if (texture_name !== null && !this.textures.exists(texture_name)) {
    //         this.load.image(texture_name, `${this.assets_dir}${texture_name}`)
    //         this.load.start()
    //     }
    // }

    _addAnimation(anim_config) {
        // TODO: from an animation config, define an animation.
    }

    _addLine(line_config) {

        var graphics = this.add.graphics()
        var points = line_config.points.map((point) => new Phaser.Math.Vector2(point[0] * this.width, point[1] * this.height))

        graphics.setDepth(line_config.depth);

        // Set the line style (width and color)
        graphics.lineStyle(line_config.width, this._strToHex(line_config.color));

        // Draw the curve
        graphics.beginPath();
        graphics.moveTo(points[0].x, points[0].y);

        for (let i = 1; i < points.length; i++) {
            graphics.lineTo(points[i].x, points[i].y);
        }

        graphics.strokePath();

        if (line_config.fill_above === true) {
            var topY = 0;
            graphics.lineTo(points[points.length - 1].x, topY);
            graphics.lineTo(points[0].x, topY);
            graphics.closePath();

            // Fill the closed shape
            graphics.fillStyle(this._strToHex(line_config.color), 1);
            graphics.fillPath();
        }

        if (line_config.fill_below === true) {
            var bottomY = this.height;
            graphics.lineTo(points[points.length - 1].x, bottomY);
            graphics.lineTo(points[0].x, bottomY);
            graphics.closePath();

            // Fill the closed shape
            graphics.fillStyle(this._strToHex(line_config.color), 1);
            graphics.fillPath();
        }

        graphics.permanent = line_config.permanent || false;
        this.objectMap.set(line_config.uuid, graphics);
    }

    _updateLine(line_config) {
        // TODO
    }

    _addCircle(config) {
        let x = config.x * this.width;
        let y = config.y * this.height;
        let radius = config.radius * Math.max(this.width, this.height);
        let alpha = config.alpha ?? 1;

        // Create a container at the target position
        let container = this.add.container(x, y);
        container.setDepth(config.depth);

        // Create graphics and draw circle at origin (0,0) relative to container
        let graphics = this.add.graphics();
        graphics.fillStyle(this._strToHex(config.color), alpha);
        graphics.fillCircle(0, 0, radius);

        if (config.stroke_color && config.stroke_width > 0) {
            graphics.lineStyle(config.stroke_width, this._strToHex(config.stroke_color), alpha);
            graphics.strokeCircle(0, 0, radius);
        }

        container.add(graphics);

        // Store container in objectMap with tween tracking
        container.tween = null;
        container.graphics = graphics;  // Keep reference for redraws
        container.lastConfig = config;  // Store config for redraws
        container.permanent = config.permanent || false;
        this.objectMap.set(config.uuid, container);
    }

    _updateCircle(circle_config) {
        let container = this.objectMap.get(circle_config.uuid);

        let new_x = circle_config.x * this.width;
        let new_y = circle_config.y * this.height;
        let radius = circle_config.radius * Math.max(this.width, this.height);
        let alpha = circle_config.alpha ?? 1;

        // Check if color, radius, alpha, or stroke changed - need to redraw
        let lastConfig = container.lastConfig;
        if (lastConfig.color !== circle_config.color ||
            lastConfig.radius !== circle_config.radius ||
            lastConfig.alpha !== circle_config.alpha ||
            lastConfig.stroke_color !== circle_config.stroke_color ||
            lastConfig.stroke_width !== circle_config.stroke_width) {
            container.graphics.clear();
            container.graphics.fillStyle(this._strToHex(circle_config.color), alpha);
            container.graphics.fillCircle(0, 0, radius);

            if (circle_config.stroke_color && circle_config.stroke_width > 0) {
                container.graphics.lineStyle(circle_config.stroke_width, this._strToHex(circle_config.stroke_color), alpha);
                container.graphics.strokeCircle(0, 0, radius);
            }

            container.lastConfig = circle_config;
        }

        // Update depth if changed
        container.setDepth(circle_config.depth);

        // Handle position update with optional tweening
        this._applyPositionTween(container, new_x, new_y, circle_config);
    }

    _addRectangle(config) {
        let x = config.x * this.width;
        let y = config.y * this.height;
        let w = (config.w || 0) * this.width;
        let h = (config.h || 0) * this.height;
        let alpha = config.alpha ?? 1;

        let container = this.add.container(x, y);
        container.setDepth(config.depth || 0);

        let graphics = this.add.graphics();

        if (config.color) {
            graphics.fillStyle(this._strToHex(config.color), alpha);
            graphics.fillRect(0, 0, w, h);
        }

        if (config.stroke_color && config.stroke_width > 0) {
            graphics.lineStyle(config.stroke_width, this._strToHex(config.stroke_color), alpha);
            graphics.strokeRect(0, 0, w, h);
        }

        container.add(graphics);
        container.tween = null;
        container.graphics = graphics;
        container.lastConfig = config;
        container.permanent = config.permanent || false;
        this.objectMap.set(config.uuid, container);
    }

    _updateRectangle(config) {
        let container = this.objectMap.get(config.uuid);
        let newX = config.x * this.width;
        let newY = config.y * this.height;
        let newW = (config.w || 0) * this.width;
        let newH = (config.h || 0) * this.height;
        let alpha = config.alpha ?? 1;

        let lastConfig = container.lastConfig;
        // Redraw if color, size, stroke, or alpha changed
        if (lastConfig.color !== config.color ||
            lastConfig.w !== config.w ||
            lastConfig.h !== config.h ||
            lastConfig.alpha !== config.alpha ||
            lastConfig.stroke_color !== config.stroke_color ||
            lastConfig.stroke_width !== config.stroke_width) {
            container.graphics.clear();
            if (config.color) {
                container.graphics.fillStyle(this._strToHex(config.color), alpha);
                container.graphics.fillRect(0, 0, newW, newH);
            }
            if (config.stroke_color && config.stroke_width > 0) {
                container.graphics.lineStyle(config.stroke_width, this._strToHex(config.stroke_color), alpha);
                container.graphics.strokeRect(0, 0, newW, newH);
            }
            container.lastConfig = config;
        }

        container.setDepth(config.depth || 0);
        this._applyPositionTween(container, newX, newY, config);
    }

    _addPolygon(polygon_config) {
        // Calculate centroid of polygon for container position
        let points = polygon_config.points;
        let centroidX = points.reduce((sum, p) => sum + p[0], 0) / points.length * this.width;
        let centroidY = points.reduce((sum, p) => sum + p[1], 0) / points.length * this.height;
        let alpha = polygon_config.alpha ?? 1;

        // Create a container at the centroid
        let container = this.add.container(centroidX, centroidY);
        container.setDepth(polygon_config.depth);

        // Create graphics and draw polygon relative to container origin
        let graphics = this.add.graphics();
        let relativePoints = points.map((point) =>
            new Phaser.Math.Vector2(
                point[0] * this.width - centroidX,
                point[1] * this.height - centroidY
            )
        );

        graphics.fillStyle(this._strToHex(polygon_config.color), alpha);
        graphics.fillPoints(relativePoints, true);

        if (polygon_config.stroke_color && polygon_config.stroke_width > 0) {
            graphics.lineStyle(polygon_config.stroke_width, this._strToHex(polygon_config.stroke_color), alpha);
            graphics.strokePoints(relativePoints, true);  // true = auto-close
        }

        container.add(graphics);

        // Store container in objectMap with tween tracking
        container.tween = null;
        container.graphics = graphics;
        container.lastConfig = polygon_config;
        container.lastCentroid = { x: centroidX, y: centroidY };
        container.permanent = polygon_config.permanent || false;
        this.objectMap.set(polygon_config.uuid, container);
    }

    _updatePolygon(polygon_config) {
        let container = this.objectMap.get(polygon_config.uuid);

        // Calculate new centroid
        let points = polygon_config.points;
        let newCentroidX = points.reduce((sum, p) => sum + p[0], 0) / points.length * this.width;
        let newCentroidY = points.reduce((sum, p) => sum + p[1], 0) / points.length * this.height;
        let alpha = polygon_config.alpha ?? 1;

        // Check if polygon shape changed (color, alpha, stroke, or relative point positions)
        let lastConfig = container.lastConfig;
        let shapeChanged = lastConfig.color !== polygon_config.color ||
            lastConfig.alpha !== polygon_config.alpha ||
            lastConfig.points.length !== polygon_config.points.length ||
            lastConfig.stroke_color !== polygon_config.stroke_color ||
            lastConfig.stroke_width !== polygon_config.stroke_width;

        if (!shapeChanged) {
            // Check if relative positions changed (shape deformation)
            for (let i = 0; i < points.length; i++) {
                let lastRelX = lastConfig.points[i][0] * this.width - container.lastCentroid.x;
                let lastRelY = lastConfig.points[i][1] * this.height - container.lastCentroid.y;
                let newRelX = points[i][0] * this.width - newCentroidX;
                let newRelY = points[i][1] * this.height - newCentroidY;
                if (Math.abs(lastRelX - newRelX) > 0.1 || Math.abs(lastRelY - newRelY) > 0.1) {
                    shapeChanged = true;
                    break;
                }
            }
        }

        if (shapeChanged) {
            // Redraw the polygon
            container.graphics.clear();
            let relativePoints = points.map((point) =>
                new Phaser.Math.Vector2(
                    point[0] * this.width - newCentroidX,
                    point[1] * this.height - newCentroidY
                )
            );
            container.graphics.fillStyle(this._strToHex(polygon_config.color), alpha);
            container.graphics.fillPoints(relativePoints, true);

            if (polygon_config.stroke_color && polygon_config.stroke_width > 0) {
                container.graphics.lineStyle(polygon_config.stroke_width, this._strToHex(polygon_config.stroke_color), alpha);
                container.graphics.strokePoints(relativePoints, true);  // true = auto-close
            }

            container.lastConfig = polygon_config;
            container.lastCentroid = { x: newCentroidX, y: newCentroidY };
        }

        // Update depth if changed
        container.setDepth(polygon_config.depth);

        // Handle position update with optional tweening
        this._applyPositionTween(container, newCentroidX, newCentroidY, polygon_config);
    }

    _addText(text_config) {
        let text = this.add.text(
            text_config.x * this.width,
            text_config.y * this.height,
            text_config.text,
            { fontFamily: text_config.font, fontSize: text_config.size || 16, color: text_config.color || "#000000"}
        );
        text.setDepth(text_config.depth || 0);
        text.permanent = text_config.permanent || false;
        this.objectMap.set(text_config.uuid, text);
    }

    _updateText(text_config) {
        let text = this.objectMap.get(text_config.uuid);
        text.x = text_config.x * this.width;
        text.y = text_config.y * this.height;
        text.setText(text_config.text);
        text.setColor(text_config.color || "#000000");
        text.setFontSize(text_config.size || 16);
    }

    /**
     * Shared helper for applying position tweens with cancel-and-restart behavior.
     * First appearance places object at target (no tween from origin).
     * If tween=true and a tween is in progress, cancels old and starts new from current position.
     * If no tween requested and no tween in progress, snaps to position.
     */
    _applyPositionTween(container, newX, newY, config) {
        if (newX === container.x && newY === container.y) return;

        if (config.tween === true && config.tween_duration > 0) {
            // Cancel existing tween if in progress (locked decision)
            if (container.tween) {
                container.tween.stop();
                container.tween = null;
            }
            container.tween = this.tweens.add({
                targets: [container],
                x: newX,
                y: newY,
                duration: config.tween_duration,
                ease: 'Linear',
                onComplete: () => {
                    container.tween = null;
                }
            });
        } else if (!container.tween) {
            // No tween requested and no tween in progress: snap
            container.x = newX;
            container.y = newY;
        }
    }

    _checkIfHex(string_to_test) {
        var reg = /^#[0-9A-F]{6}[0-9a-f]{0,2}$/i
        return reg.test(string_to_test)
    }

    _strToHex(color_str) {
        return parseInt(color_str.replace(/^#/, ''), 16)
    }

}


function combinationsOf(arr, k) {
    if (k === 0) return [[]];
    if (arr.length === 0) return [[]];

    const [head, ...tail] = arr;
    const withoutHead = combinationsOf(tail, k);
    const withHead = combinationsOf(tail, k - 1).map(combination => [head, ...combination]);

    return [...withHead, ...withoutHead];
}

function arraysEqual(a, b) {
    if (a.length !== b.length) return false;
    for (let i = 0; i < a.length; i++) {
        if (a[i] !== b[i]) return false;
    }
    return true;
}
