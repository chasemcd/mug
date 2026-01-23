import {actionFromONNX} from './onnx_inference.js';


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
const MAX_BUFFER_SIZE = 1;
export function addStateToBuffer(state_data) {
    if (stateBuffer >= MAX_BUFFER_SIZE) {
        stateBuffer.shift(); // remove the oldest state
    }
    stateBuffer.push(state_data);
}

function clearStateBuffer() {
    stateBuffer = [];
}

// Contains an array for each bot that we'll shift to get the most recent action
// Bots are queried asynchronously!
let botActionBuffers = {};

let humanKeyPressBuffer = [];
const MAX_KEY_PRESS_BUFFER_SIZE = 1;
export function addHumanKeyPressToBuffer(action) {
    // TODO(chase): this should filter out actions that aren't allowed,
    // otherwise hitting an unrelated key could cancel out previous actions.
    if (humanKeyPressBuffer >= MAX_KEY_PRESS_BUFFER_SIZE) {
        humanKeyPressBuffer.shift(); // remove the oldest state
    }
    humanKeyPressBuffer.push(action);
}

export var pressedKeys = {};
export function updatePressedKeys(updatedPressedKeys) {
    pressedKeys = updatedPressedKeys;
}

/**
 * Clear all human input buffers.
 * Called when game pauses (waiting for partner) to prevent input accumulation.
 */
export function clearHumanInputBuffers() {
    humanKeyPressBuffer = [];
    pressedKeys = {};
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

export function graphics_start(graphics_config) {
    game_graphics = new GraphicsManager(game_config, graphics_config);
}


export function graphics_end() {
    $("#gameContainer").empty();
    game_graphics.game.destroy(true);
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
        this.temp_object_map = {};
        this.perm_object_map = {};
        this.state = config.state_init;
        this.assets_dir = config.assets_dir;
        this.assets_to_preload = config.assets_to_preload;
        this.animation_configs = config.animation_configs;
        this.background = config.background;
        this.last_rendered_step = -1;
        this.scene_metadata = config.scene_metadata;
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
        await this.processPyodideGame();
        // Clear the processing flag after game step completes
        if (this.pyodide_remote_game) {
            this.pyodide_remote_game.isProcessingTick = false;
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

                remoteGameLogger.logData(
                    {
                        observations: currentObservations,
                        actions: syncedActions,  // Use synchronized actions for accurate logging
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
            addStateToBuffer(render_state);
        }
        this.isProcessingPyodide = false;
    };

    async buildPyodideActionDict() {
        let actions = {};

        // In multiplayer mode, only collect keyboard input for THIS player's agent
        let isMultiplayer = this.pyodide_remote_game && this.pyodide_remote_game.myPlayerId !== undefined;
        let myPlayerId = isMultiplayer ? String(this.pyodide_remote_game.myPlayerId) : null;

        // Loop over all agents in the policy mapping
        for (let [agentID, policy] of Object.entries(this.scene_metadata.policy_mapping)) {
            if (policy == "human") {
                // In multiplayer, only get keyboard input for MY player
                if (isMultiplayer) {
                    if (agentID == myPlayerId) {
                        actions[agentID] = this.getHumanAction();
                    } else {
                        // Other human players - use default action (will be replaced by server)
                        actions[agentID] = this.scene_metadata.default_action || 0;
                    }
                } else {
                    // Single player - get keyboard input for this human
                    actions[agentID] = this.getHumanAction();
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
        let action = await actionFromONNX(policyID, observation);
        botActionBuffers[agentID].push(action);
    }

    getHumanAction() {
        let human_action;

        // If single_keystroke, we'll get the action that was added to the buffer when the key was pressed
        if (this.scene_metadata.input_mode === "single_keystroke") {
            if (humanKeyPressBuffer.length > 0) {
                human_action = this.scene_metadata.action_mapping[humanKeyPressBuffer.shift()];
                if (human_action == undefined) {
                    human_action = this.scene_metadata.default_action;
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
                human_action = this.scene_metadata.action_mapping[Object.keys(pressedKeys)[0]];
                if (human_action == undefined) {
                    human_action = this.scene_metadata.default_action;
                }
            } else {
                // multiple keys are pressed so check for a composite action
                human_action = this.scene_metadata.action_mapping[this.generateCompositeAction()[0]];
                if (human_action == undefined) {
                    human_action = this.scene_metadata.default_action;
                }
            }
        }

        return human_action;
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
        if (stateBuffer.length > 0) {
            this.state = stateBuffer.shift(); // get the oldest state from the buffer
            this.drawState();
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

            // // This will trigger when the new texture is added
            // this.textures.once('addtexture', function () {

            //     this.stateImageSprite.setTexture("curStateImage");
            //     console.log("set texture curstateImage");

            // }, this);

            // this.textures.addImage("curStateImage", url, () => {
            //     URL.revokeObjectURL(url);
            //     if (this.stateImageSprite) {
            //         this.stateImageSprite.setTexture("curStateImage");
            //     }
            //     console.log("set texture curstateImage in addBase64");
            //  });        
            
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

                // ✅ **Do NOT remove the old texture immediately!**
                // ✅ **Ensure old texture is removed first**
                if (this.textures.exists("curStateImage")) {
                    this.textures.remove("curStateImage");
                }

                // ✅ **Now safely add the new texture**
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

            // // Remove the current image
            // let oldImage;

            // if (this.temp_object_map.hasOwnProperty("curStateImage")) {
            //     oldImage = this.temp_object_map['curStateImage'];
            // }

            // // This will trigger when the new texture is added
            // this.textures.once('addtexture', function () {

            //     // Place the updated image and store so we can remove later
            //     this.temp_object_map['curStateImage'] = this.add.image(
            //         0,
            //         0,
            //         `curStateImage_${this.state.step}`
            //     );
            //     this.temp_object_map['curStateImage'].setOrigin(0, 0);

            //     // Remove the old image
            //     if (!(oldImage == null)) {
            //         oldImage.destroy();
            //     }

            // }, this);

            // // Load the new image
            // var base64String = this.state.game_image_base64.startsWith('data:image/png;base64,') ? 
            //     this.state.game_image_binary : 
            //     'data:image/png;base64,' + this.state.game_image_binary;

            // // Success here will trigger the `addtexture` callback
            // this.textures.addBase64(`curStateImage_${this.state.step}`, base64String);




        } else if (!(game_state_objects == null)) {
            // If we have game state objects, we'll render and update each object as necessary.
            game_state_objects.forEach((game_obj) => {

                var object_map;
                let permanent = game_obj.permanent;
                if (permanent === true) {
                    object_map = this.perm_object_map;
                } else {
                    object_map = this.temp_object_map;
                };


                // Check if we need to add a new object
                if (!object_map.hasOwnProperty(game_obj.uuid)) {
                    this._addObject(game_obj, object_map);
                }


                this._updateObject(game_obj, object_map);
            });

            // Remove any existing temporary objects that are no longer present
            let game_state_object_ids = game_state_objects.map(obj_config => obj_config.uuid)
            Object.keys(this.temp_object_map).forEach(obj_uuid => {
                if (!game_state_object_ids.includes(obj_uuid)) {
                    this.temp_object_map[obj_uuid].destroy();
                    delete this.temp_object_map[obj_uuid];
                }
            })

        }
    };

    removeAllObjects() {
        Object.keys(this.temp_object_map).forEach(obj_uuid => {
            this.temp_object_map[obj_uuid].destroy();
            delete this.temp_object_map[obj_uuid];
        })

        Object.keys(this.perm_object_map).forEach(obj_uuid => {
            this.perm_object_map[obj_uuid].destroy();
            delete this.perm_object_map[obj_uuid];
        })
    }

    _addObject(object_config, object_map) {
        if (object_config.object_type === "sprite") {
            this._addSprite(object_config, object_map);
        } else if (object_config.object_type === "animation") {
            this._addAnimation(object_config, object_map)
        } else if (object_config.object_type === "line") {
            this._addLine(object_config, object_map)
        } else if (object_config.object_type === "circle") {
            this._addCircle(object_config, object_map)
        } else if (object_config.object_type === "rectangle") {
            this._addRectangle(object_config, object_map)
        } else if (object_config.object_type === "polygon") {
            this._addPolygon(object_config, object_map)
        } else if (object_config.object_type === "text") {
            this._addText(object_config, object_map)
        } else {
            console.warn("Unrecognized object type in _addObject:", object_config.object_type)
        }
    }

    _updateObject(object_config, object_map) {

        if (object_config.object_type === "sprite") {
            this._updateSprite(object_config, object_map);
        } else if (object_config.object_type === "line") {
            this._updateLine(object_config, object_map)
        } else if (object_config.object_type === "circle") {
            this._updateCircle(object_config, object_map)
        } else if (object_config.object_type === "rectangle") {
            this._updateRectangle(object_config, object_map)
        } else if (object_config.object_type === "polygon") {
            this._updatePolygon(object_config, object_map)
        } else if (object_config.object_type === "text") {
            this._updateText(object_config, object_map)
        } else {
            console.warn("Unrecognized object type in _updateObject:", object_config.object_type)
        }
    }

    _addSprite(object_config, object_map) {
        let uuid = object_config.uuid;

        let x = Math.floor(object_config.x * this.width);
        let y = Math.floor(object_config.y * this.height);

        // Add a blank sprite to the specified location, everything else
        // will be updated in _updateObject
        object_map[uuid] = this.add.sprite(
            {
                x: x,
                y: y,
                depth: object_config.depth,
            }
        );

        object_map[uuid].tween = null;
        object_map[uuid].x = x;
        object_map[uuid].y = y;

    };

    _updateSprite(object_config, object_map) {
        let sprite = object_map[object_config.uuid];

        sprite.angle = object_config.angle;

        // this._addTexture(object_config.image_name)

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

        if (
            object_config.tween == true &&
            sprite.tween == null &&
            (new_x !== sprite.x || new_y !== sprite.y)
            ) {

            sprite.tween = this.tweens.add({
                targets: [sprite],
                x: new_x,
                y: new_y,
                duration: object_config.tween_duration,
                ease: 'Linear',
                onComplete: (tween, target, player) => {
                    sprite.tween = null;
                }
            })
        } else if (
            sprite.tween == null &&
            (new_x !== sprite.x || new_y !== sprite.y)
        ) {
            sprite.x = new_x;
            sprite.y = new_y;
        }

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

    _addLine(line_config, object_map) {

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


        object_map[line_config.uuid] = graphics;
    }

    _updateLine(line_config, object_map) {
        // TODO
    }

    _addCircle(circle_config, object_map) {
        let x = circle_config.x * this.width;
        let y = circle_config.y * this.height;

        // Create a container at the target position
        let container = this.add.container(x, y);
        container.setDepth(circle_config.depth);

        // Create graphics and draw circle at origin (0,0) relative to container
        let graphics = this.add.graphics();
        graphics.fillStyle(this._strToHex(circle_config.color), circle_config.alpha);
        graphics.fillCircle(0, 0, circle_config.radius);

        container.add(graphics);

        // Store container in object_map with tween tracking
        container.tween = null;
        container.graphics = graphics;  // Keep reference for redraws
        container.lastConfig = circle_config;  // Store config for redraws
        object_map[circle_config.uuid] = container;
    }

    _updateCircle(circle_config, object_map) {
        let uuid = circle_config.uuid;
        let container = object_map[uuid];

        let new_x = circle_config.x * this.width;
        let new_y = circle_config.y * this.height;

        // Check if color or radius changed - need to redraw
        let lastConfig = container.lastConfig;
        if (lastConfig.color !== circle_config.color ||
            lastConfig.radius !== circle_config.radius ||
            lastConfig.alpha !== circle_config.alpha) {
            container.graphics.clear();
            container.graphics.fillStyle(this._strToHex(circle_config.color), circle_config.alpha);
            container.graphics.fillCircle(0, 0, circle_config.radius);
            container.lastConfig = circle_config;
        }

        // Update depth if changed
        container.setDepth(circle_config.depth);

        // Handle position update with optional tweening
        if (
            circle_config.tween === true &&
            container.tween === null &&
            (new_x !== container.x || new_y !== container.y)
        ) {
            container.tween = this.tweens.add({
                targets: [container],
                x: new_x,
                y: new_y,
                duration: circle_config.tween_duration || 100,
                ease: 'Linear',
                onComplete: () => {
                    container.tween = null;
                }
            });
        } else if (
            container.tween === null &&
            (new_x !== container.x || new_y !== container.y)
        ) {
            container.x = new_x;
            container.y = new_y;
        }
    }

    _addRectangle(rectangle_config, object_map) {
        // TODO
    }

    _updateRectangle(rectangle_config, object_map) {
        // TODO
    }

    _addPolygon(polygon_config, object_map) {
        // Calculate centroid of polygon for container position
        let points = polygon_config.points;
        let centroidX = points.reduce((sum, p) => sum + p[0], 0) / points.length * this.width;
        let centroidY = points.reduce((sum, p) => sum + p[1], 0) / points.length * this.height;

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

        graphics.fillStyle(this._strToHex(polygon_config.color), polygon_config.alpha);
        graphics.fillPoints(relativePoints, true);

        container.add(graphics);

        // Store container in object_map with tween tracking
        container.tween = null;
        container.graphics = graphics;
        container.lastConfig = polygon_config;
        container.lastCentroid = { x: centroidX, y: centroidY };
        object_map[polygon_config.uuid] = container;
    }

    _updatePolygon(polygon_config, object_map) {
        let uuid = polygon_config.uuid;
        let container = object_map[uuid];

        // Calculate new centroid
        let points = polygon_config.points;
        let newCentroidX = points.reduce((sum, p) => sum + p[0], 0) / points.length * this.width;
        let newCentroidY = points.reduce((sum, p) => sum + p[1], 0) / points.length * this.height;

        // Check if polygon shape changed (color, alpha, or relative point positions)
        let lastConfig = container.lastConfig;
        let shapeChanged = lastConfig.color !== polygon_config.color ||
            lastConfig.alpha !== polygon_config.alpha ||
            lastConfig.points.length !== polygon_config.points.length;

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
            container.graphics.fillStyle(this._strToHex(polygon_config.color), polygon_config.alpha);
            container.graphics.fillPoints(relativePoints, true);
            container.lastConfig = polygon_config;
            container.lastCentroid = { x: newCentroidX, y: newCentroidY };
        }

        // Update depth if changed
        container.setDepth(polygon_config.depth);

        // Handle position update with optional tweening
        if (
            polygon_config.tween === true &&
            container.tween === null &&
            (newCentroidX !== container.x || newCentroidY !== container.y)
        ) {
            container.tween = this.tweens.add({
                targets: [container],
                x: newCentroidX,
                y: newCentroidY,
                duration: polygon_config.tween_duration || 100,
                ease: 'Linear',
                onComplete: () => {
                    container.tween = null;
                }
            });
        } else if (
            container.tween === null &&
            (newCentroidX !== container.x || newCentroidY !== container.y)
        ) {
            container.x = newCentroidX;
            container.y = newCentroidY;
        }
    }

    _addText(text_config, object_map) {
        object_map[text_config.uuid] = this.add.text(
            text_config.x * this.width,
            text_config.y * this.height,
            text_config.text,
            { fontFamily: text_config.font, fontSize: text_config.size, color: "#000"}
        );
        object_map[text_config.uuid].setDepth(3)
    }

    _updateText(text_config, object_map) {
        let text = object_map[text_config.uuid];
        text.x = text_config.x * this.width;
        text.y = text_config.y * this.height;
        text.setText(text_config.text);
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
