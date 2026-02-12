// import * as ort from 'https://cdnjs.cloudflare.com/ajax/libs/onnxruntime-web/1.10.0/ort.min.js';

import * as seeded_random from './seeded_random.js';

// Store loaded models to avoid reloading
const loadedModels = {};
const hiddenStates = {};

// Cache compiled custom inference functions (keyed by agentID)
const compiledCustomFns = {};

// Store policy configs from scene_metadata (keyed by agent ID)
let policyConfigs = {};

/**
 * Initialize model configs from scene_metadata.
 * Called once during scene setup to store policy_configs for inference.
 * @param {Object} sceneMetadata - The scene_metadata object from the server
 */
export function initModelConfigs(sceneMetadata) {
    if (sceneMetadata && sceneMetadata.policy_configs) {
        policyConfigs = sceneMetadata.policy_configs;
    }
}

/**
 * Look up the model config for a given agent ID.
 * @param {string} agentID - The agent ID (same keys as policy_mapping)
 * @returns {Object|null} The model config dict, or null if not found
 */
function getModelConfig(agentID) {
    if (agentID !== undefined && policyConfigs[agentID]) {
        return policyConfigs[agentID];
    }
    return null;
}

export async function actionFromONNX(policyID, observation, agentID) {
    // Look up model config for this agent
    const modelConfig = getModelConfig(agentID);

    // Custom inference escape hatch: if custom_inference_fn is set, compile and
    // call it directly, bypassing inferenceONNXPolicy, softmax, and sampleAction.
    if (modelConfig && modelConfig.custom_inference_fn) {
        // Load the ONNX session if not already loaded
        if (!loadedModels[policyID]) {
            loadedModels[policyID] = await window.ort.InferenceSession.create(
                policyID, {executionProviders: ["wasm"],}
            );
        }
        const session = loadedModels[policyID];

        // Compile the custom function once and cache it
        if (!compiledCustomFns[agentID]) {
            const AsyncFunction = Object.getPrototypeOf(async function(){}).constructor;
            compiledCustomFns[agentID] = new AsyncFunction(
                'session', 'observation', 'modelConfig',
                modelConfig.custom_inference_fn
            );
        }

        // Call the custom function -- it has full control over inference
        const action = await compiledCustomFns[agentID](session, observation, modelConfig);
        return action;
    }

    // Conduct forward inference
    const logits = await inferenceONNXPolicy(policyID, observation, modelConfig, agentID);

    // Apply softmax to convert logits to probabilities
    const probabilities = softmax(logits);

    // Sample an action based on the probabilities
    const action = sampleAction(probabilities);

    // Log RNG usage in multiplayer mode for verification
    if (seeded_random.isMultiplayer()) {
        console.debug(`[ONNX] Sampled action ${action} using seeded RNG (state: ${seeded_random.getRNGState()})`);
    }

    return action;
}

async function inferenceONNXPolicy(policyID, observation, modelConfig, agentID) {

    // If the observation is an Array of Arrays or a dictionary with some values being Arrays of Arrays,
    // flatten them to a single Array
    if (Array.isArray(observation)) {
        observation = observation.flat(Infinity);
    } else if (typeof observation === 'object') {
        for (let key in observation) {
            if (Array.isArray(observation[key])) {
                observation[key] = observation[key].flat(Infinity);
            }
        }
    }

    // Ensure observation is a Float32Array
    if (typeof observation === 'object' && !Array.isArray(observation)) {
        // If observation is a dictionary
        for (let key in observation) {
            if (Array.isArray(observation[key])) {
                observation[key] = new Float32Array(observation[key]);
            }
        }
    } else if (Array.isArray(observation)) {
        // If observation is already an array
        observation = new Float32Array(observation);
    } else {
        throw new Error('Observation must be either an object or an array');
    }

    // If there are any image observations, make sure that they are appropriately shaped
    // toJs will return an Array full of Array objects, but we need a single 3-D array
    
    // Load the model if not already loaded
    if (!loadedModels[policyID]) {
        loadedModels[policyID] = await window.ort.InferenceSession.create(
            policyID, {executionProviders: ["wasm"],}
          );
    }
    
    const session = loadedModels[policyID];
    
    // If the observation is a dictionary, flatten all the values into a single array
    if (typeof observation === 'object' && !Array.isArray(observation)) {
        observation = flattenObservation(observation);
    }



    // Observation should be shape (observationSize,), reshape to add batch dimension of 1
    // and convert to an ort.Tensor
    const inputTensor = new window.ort.Tensor('float32', observation, [1, observation.length]);

    const feeds = {};

    if (modelConfig) {
        // Declarative path: use config-driven tensor names and shapes
        feeds[modelConfig.obs_input] = inputTensor;

        if (modelConfig.state_inputs && modelConfig.state_inputs.length > 0) {
            // Recurrent model: set up hidden state feeds
            if (!hiddenStates[agentID]) {
                hiddenStates[agentID] = {};
            }

            modelConfig.state_inputs.forEach(name => {
                if (!hiddenStates[agentID][name]) {
                    const shape = modelConfig.state_shape;
                    const size = shape.reduce((a, b) => a * b);
                    hiddenStates[agentID][name] = new window.ort.Tensor(
                        'float32', new Float32Array(size), shape
                    );
                }
                feeds[name] = hiddenStates[agentID][name];
            });
        }
        // Non-recurrent with config: no state feeds needed
    } else {
        // Legacy fallback (no config): keep old hardcoded behavior
        feeds['obs'] = inputTensor;

        // Check if the model is recurrent by inspecting input names, following
        // the RLlib convention of naming hidden states as 'state_in_0', 'state_in_1', etc.
        const isRecurrent = session.inputNames.some(name => name.startsWith('state_in_'));

        if (isRecurrent) {
            if (!hiddenStates[agentID]) {
                hiddenStates[agentID] = {};
            }

            session.inputNames.forEach(name => {
                if (name.startsWith('state_in_')) {
                    if (!hiddenStates[agentID][name]) {
                        const expectedShape = [1, 256];
                        hiddenStates[agentID][name] = new window.ort.Tensor(
                            'float32',
                            new Float32Array(expectedShape.reduce((a, b) => a * b)),
                            expectedShape
                        );
                    }
                    feeds[name] = hiddenStates[agentID][name];
                }
            });

            feeds['seq_lens'] = new window.ort.Tensor('float32', new Float32Array([1]));
        } else {
            feeds['state_ins'] = new window.ort.Tensor('float32', new Float32Array([1]));
        }
    }

    // Run inference
    const results = await session.run(feeds);

    // Extract output logits
    const logitName = modelConfig ? modelConfig.logit_output : session.outputNames[0];
    const logits = results[logitName].data;

    // Update hidden states from output (legacy path)
    if (!modelConfig) {
        const stateOutNames = session.outputNames.filter(name => name.startsWith('state_out_'));
        if (stateOutNames.length > 0) {
            if (!hiddenStates[agentID]) {
                hiddenStates[agentID] = {};
            }
            stateOutNames.forEach(outName => {
                // Map state_out_N -> state_in_N
                const inName = outName.replace('state_out_', 'state_in_');
                hiddenStates[agentID][inName] = results[outName];
            });
        }
    }

    // Update hidden states from output (declarative path only)
    if (modelConfig && modelConfig.state_outputs) {
        if (!hiddenStates[agentID]) {
            hiddenStates[agentID] = {};
        }
        modelConfig.state_outputs.forEach((outputName, idx) => {
            const inputName = modelConfig.state_inputs[idx];
            hiddenStates[agentID][inputName] = results[outputName];
        });
    }

    return logits;
}

// Softmax function to convert logits to probabilities
function softmax(logits) {
    const maxLogit = Math.max(...logits);
    const exps = logits.map(logit => Math.exp(logit - maxLogit));
    const sumExps = exps.reduce((a, b) => a + b, 0);
    return exps.map(exp => exp / sumExps);
}

// Function to sample an action based on probabilities
function sampleAction(probabilities) {
    const cumulativeProbabilities = probabilities.reduce((acc, prob) => {
        if (acc.length === 0) {
            return [prob];
        } else {
            return [...acc, acc[acc.length - 1] + prob];
        }
    }, []);

    // Use seeded RNG in multiplayer, Math.random() in single-player
    const randomValue = seeded_random.getRandom();

    for (let i = 0; i < cumulativeProbabilities.length; i++) {
        if (randomValue < cumulativeProbabilities[i]) {
            return i;
        }
    }

    // Fallback in case of floating-point precision issues
    return cumulativeProbabilities.length - 1;
}


function flattenObservation(observation) {
    // Initialize an empty Float32Array
    let concatenatedArray = new Float32Array(0);

    // Sort the keys of the observation dictionary
    const sortedKeys = Object.keys(observation).sort();

    // Iterate over each value (which should be an array) in the sorted observation dictionary
    for (const key of sortedKeys) {
        const array = observation[key];
        // Continuously concatenate each array using Float32Concat
        concatenatedArray = Float32Concat(concatenatedArray, new Float32Array(array));
    }

    return concatenatedArray;
}

function Float32Concat(first, second)
{
    var firstLength = first.length,
        result = new Float32Array(firstLength + second.length);

    result.set(first);
    result.set(second, firstLength);

    return result;
}