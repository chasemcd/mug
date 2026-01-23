import * as ui_utils from './ui_utils.js';



export class RemoteGame {
    constructor(config) {
        this.setAttributes(config);
        this.installed_packages = [];
        this.initialize(); 
    }

    setAttributes(config) {
        this.config = config;
        this.interactive_gym_globals = config.interactive_gym_globals;
        this.micropip = null;
        this.pyodideReady = false;
        this.state = null;
        this.objects_to_render = [];
        this.observations = [];
        this.render_state = null;
        this.num_episodes = 0;
        this.max_episodes = config.num_episodes;
        this.step_num = 0;
        this.max_steps = config.max_steps;
        this.cumulative_rewards = {};
        this.shouldReset = true;
    }

    isDone(){
        return this.state === "done";
    }

    async initialize() {
        this.pyodide = await loadPyodide();

        await this.pyodide.loadPackage("micropip");
        this.micropip = this.pyodide.pyimport("micropip");

        if (this.config.packages_to_install !== undefined) {
            console.log("Installing packages via micropip: ", this.config.packages_to_install);
            await this.micropip.install(this.config.packages_to_install);

            // Append the installed packages to the list of installed packages
            this.installed_packages.push(...this.config.packages_to_install);
        }

        this.pyodide.globals.set("interactive_gym_globals", this.interactive_gym_globals);


        // The code executed here must instantiate an environment `env`
        const env = await this.pyodide.runPythonAsync(`
import js
interactive_gym_globals = dict(js.window.interactiveGymGlobals.object_entries())

${this.config.environment_initialization_code}
env
        `);

        if (env == undefined) {
            throw new Error("The environment was not initialized correctly. Ensure the the environment_initialization_code correctly creates an `env` object.");
        }

        this.state = "ready";
        this.pyodideReady = true;
    }

    async reinitialize_environment(config) {
        this.pyodideReady = false;
        // If we need additional packages from micropip,
        // install them. Look at config.packages_to_install
        // and compare it to this.installed_packages.
        // If there are any packages in config.packages_to_install
        // that are not in this.installed_packages, then install them.
        if (config.packages_to_install !== undefined) {
            let new_packages = [];
            for (let pkg of config.packages_to_install) {
                if (!this.installed_packages.includes(pkg)) {
                    new_packages.push(pkg);
                }
            }

            if (new_packages.length > 0) {
                await this.micropip.install(new_packages);
                this.installed_packages.push(...new_packages);    
            }
        }
    
        // The code executed here must instantiate an environment `env`
        const env = await this.pyodide.runPythonAsync(`
import js
interactive_gym_globals = dict(js.window.interactiveGymGlobals.object_entries())
print("Globals on initialization: ", interactive_gym_globals)
${config.environment_initialization_code}
env
        `);

        console.log("env: ", env);
        if (env == undefined) {
            throw new Error("The environment was not initialized correctly. Ensure the the environment_initialization_code correctly creates an `env` object.");
        }

        this.setAttributes(config);
        this.shouldReset = true;
        this.state = "ready";
        this.pyodideReady = true;
    }

    /**
     * Show episode transition UI (waiting message and countdown).
     * Called at the start of reset() for subsequent episodes.
     *
     * @param {string} waitingMessage - Message to show while waiting (optional)
     * @returns {Promise} Resolves when countdown completes
     */
    async showEpisodeTransition(waitingMessage = null) {
        // Check if this is a subsequent episode (not the first one)
        const isSubsequentEpisode = this.num_episodes > 0;

        if (!isSubsequentEpisode) {
            // First episode - just ensure overlay is hidden
            ui_utils.hideEpisodeOverlay();
            return;
        }

        // Show waiting message if provided
        if (waitingMessage) {
            ui_utils.showEpisodeWaiting(waitingMessage);
        }

        // Show countdown before starting
        const episodeNum = this.num_episodes + 1;
        await ui_utils.showEpisodeCountdown(3, `Round ${episodeNum} starting!`);
    }

    async reset() {
        this.shouldReset = false;
        console.log("Resetting the environment");

        // Show episode transition for subsequent episodes
        await this.showEpisodeTransition();

        const startTime = performance.now();
        const result = await this.pyodide.runPythonAsync(`
import numpy as np
obs, infos = env.reset()
render_state = env.render()

if not isinstance(obs, dict):
    obs = obs.reshape(-1).astype(np.float32)
elif isinstance(obs, dict) and isinstance([*obs.values()][0], dict):
    obs = {k: {kk: vv.reshape(-1).astype(np.float32) for kk, vv in v.items()} for k, v in obs.items()}
elif isinstance(obs, dict):
    obs = {k: v.reshape(-1).astype(np.float32) for k, v in obs.items()}
else:
    raise ValueError(f"obs is not a valid type, got {type(obs)} but need array, dict, or dict of dicts.")


if not isinstance(obs, dict):
    obs = {"human": obs}

obs, infos, render_state
        `);
        const endTime = performance.now();
        console.log(`Reset operation took ${endTime - startTime} milliseconds`);
        let [obs, infos, render_state] = await this.pyodide.toPy(result).toJs();

        // Check if render_state is an RGB array (has shape and dtype properties)
        let game_image_binary = null;
        if (Array.isArray(render_state) && Array.isArray(render_state[0])) {
            // Assuming render_state is an array of arrays with [row][column][RGB values]
            const canvas = document.createElement('canvas');
            const context = canvas.getContext('2d');

            const height = render_state.length;
            const width = render_state[0].length;

            // Set canvas dimensions
            canvas.width = width;
            canvas.height = height;

            // Create ImageData object
            const imageData = context.createImageData(width, height);
            const data = imageData.data;

            // Populate the ImageData with pixel values from render_state
            for (let y = 0; y < height; y++) {
                for (let x = 0; x < width; x++) {
                    const pixelIndex = (y * width + x) * 4; // RGBA values in ImageData
                    const [r, g, b] = render_state[y][x];

                    data[pixelIndex] = r;     // Red
                    data[pixelIndex + 1] = g; // Green
                    data[pixelIndex + 2] = b; // Blue
                    data[pixelIndex + 3] = 255; // Alpha (fully opaque)
                }
            }

            // Put the image data on the canvas
            context.putImageData(imageData, 0, 0);

            // Convert canvas to Base64 image
            game_image_base64 = canvas.toDataURL('image/png'); // You can change 'image/png' to 'image/jpeg' if needed

        }


        render_state = {
            "game_state_objects": game_image_binary ? null : render_state.map(item => convertUndefinedToNull(item)),
            "game_image_base64": game_image_binary,
            "step": this.step_num,
        };

        this.step_num = 0;
        this.shouldReset = false;

        // Initialize or reset cumulative rewards based on hud_score_carry_over setting
        // Convert keys to strings for consistent lookup (Python may send int or string keys)
        const carryOver = this.config.hud_score_carry_over || false;
        for (let key of obs.keys()) {
            if (!carryOver || this.cumulative_rewards[key] === undefined) {
                this.cumulative_rewards[key] = 0;
            }
        }

        ui_utils.showHUD();
        ui_utils.updateHUDText(this.getHUDText());


        return [obs, infos, render_state]
    }


    async step(actions) {
        const pyActions = this.pyodide.toPy(actions);
        // const startTime = performance.now();
        const result = await this.pyodide.runPythonAsync(`
${this.config.on_game_step_code}
agent_actions = {int(k) if k.isnumeric() or isinstance(k, (float, int)) else k: v for k, v in ${pyActions}.items()}
obs, rewards, terminateds, truncateds, infos = env.step(agent_actions)
render_state = env.render()

if not isinstance(obs, dict):
    obs = obs.reshape(-1).astype(np.float32)
elif isinstance(obs, dict) and isinstance([*obs.values()][0], dict):
    obs = {k: {kk: vv.reshape(-1).astype(np.float32) for kk, vv in v.items()} for k, v in obs.items()}
elif isinstance(obs, dict):
    obs = {k: v.reshape(-1).astype(np.float32) for k, v in obs.items()}
else:
    raise ValueError(f"obs is not a valid type, got {type(obs)} but need array, dict, or dict of dicts.")

if isinstance(rewards, (float, int)):
    rewards = {"human": rewards}

if not isinstance(obs, dict):
    obs = {"human": obs}

if not isinstance(terminateds, dict):
    terminateds = {"human": terminateds}

if not isinstance(truncateds, dict):
    truncateds = {"human": truncateds}

obs, rewards, terminateds, truncateds, infos, render_state
        `);
        // const endTime = performance.now();
        // console.log(`Step operation took ${endTime - startTime} milliseconds`);

        // Convert everything from python objects to JS objects
        let [obs, rewards, terminateds, truncateds, infos, render_state] = await this.pyodide.toPy(result).toJs();

        for (let [key, value] of rewards.entries()) {
            this.cumulative_rewards[key] += value;
        }

        this.step_num = this.step_num + 1;

        // Check if render_state is an RGB array (has shape and dtype properties)
        // Check if render_state is an RGB array (has shape and dtype properties)
        let game_image_base64 = null;
        if (Array.isArray(render_state) && Array.isArray(render_state[0])) {
            // Assuming render_state is an array of arrays with [row][column][RGB values]
            const canvas = document.createElement('canvas');
            const context = canvas.getContext('2d');

            const height = render_state.length;
            const width = render_state[0].length;

            // Set canvas dimensions
            canvas.width = width;
            canvas.height = height;

            // Create ImageData object
            const imageData = context.createImageData(width, height);
            const data = imageData.data;

            // Populate the ImageData with pixel values from render_state
            for (let y = 0; y < height; y++) {
                for (let x = 0; x < width; x++) {
                    const pixelIndex = (y * width + x) * 4; // RGBA values in ImageData
                    const [r, g, b] = render_state[y][x];

                    data[pixelIndex] = r;     // Red
                    data[pixelIndex + 1] = g; // Green
                    data[pixelIndex + 2] = b; // Blue
                    data[pixelIndex + 3] = 255; // Alpha (fully opaque)
                }
            }

            // Put the image data on the canvas
            context.putImageData(imageData, 0, 0);

            // Convert canvas to Base64 image
            game_image_base64 = canvas.toDataURL('image/png'); // You can change 'image/png' to 'image/jpeg' if needed
        }

        

        render_state = {
            "game_state_objects": game_image_base64 ? null : render_state.map(item => convertUndefinedToNull(item)),
            "game_image_base64": game_image_base64,
            "step": this.step_num,
        };

        ui_utils.updateHUDText(this.getHUDText());

        // Check if the episode is complete
        // Episode ends when: environment terminates/truncates OR max_steps reached
        const all_terminated = Array.from(terminateds.values()).every(value => value === true);
        const all_truncated = Array.from(truncateds.values()).every(value => value === true);
        const max_steps_reached = this.step_num >= this.max_steps;

        if (all_terminated || all_truncated || max_steps_reached) {
            this.num_episodes += 1;

            if (this.num_episodes >= this.max_episodes) {
                this.state = "done";
            } else {
                this.shouldReset = true;
            }
            
        }

        return [obs, rewards, terminateds, truncateds, infos, render_state]
    };

    getHUDText() {
        // Calculate score based on hud_display_mode
        let score;

        // For multiplayer, use myPlayerId; for single-player, use first available key or default to 0
        if (this.myPlayerId !== undefined && this.cumulative_rewards[this.myPlayerId] !== undefined) {
            score = this.cumulative_rewards[this.myPlayerId];
        } else {
            // Single-player fallback: use first reward value or 0
            const rewardValues = Object.values(this.cumulative_rewards);
            score = rewardValues.length > 0 ? rewardValues[0] : 0;
        }

        let time_left = (this.max_steps - this.step_num) / this.config.fps;

        let formatted_score = Math.round(score).toString().padStart(2, '0');
        let formatted_time_left = time_left.toFixed(1).toString().padStart(5, '0');

        // Round number is 1-indexed for display
        // Cap at max to avoid showing "Round 3/2" after final episode increments num_episodes
        let current_round = Math.min(this.num_episodes + 1, this.max_episodes);
        let total_rounds = this.max_episodes;

        let hud_text = `Round: ${current_round}/${total_rounds} | Score: ${formatted_score} | Time left: ${formatted_time_left}s`;

        return hud_text
    };
};



// Helper function to convert Proxy(Map) to a plain object
function convertProxyToObject(obj) {
    if (obj instanceof Map) {
        return Array.from(obj).reduce((acc, [key, value]) => {
            acc[key] = value instanceof Object ? this.convertProxyToObject(value) : value;
            return acc;
        }, {});
    } else if (obj instanceof Object) {
        return Object.keys(obj).reduce((acc, key) => {
            acc[key] = obj[key] instanceof Object ? this.convertProxyToObject(obj[key]) : obj[key];
            return acc;
        }, {});
    }
    return obj; // Return value directly if it's neither Map nor Object
}


// Helper function to convert all `undefined` values in an object to `null`
export function convertUndefinedToNull(obj) {
    if (typeof obj !== 'object' || obj === null) {
        // Return the value as is if it's not an object or is already null
        return obj;
    }

    for (let key in obj) {
        if (obj[key] === undefined) {
            obj[key] = null; // Convert undefined to null
        } else if (typeof obj[key] === 'object') {
            // Recursively apply the conversion to nested objects
            obj[key] = convertUndefinedToNull(obj[key]);
        }
    }

    return obj;
}