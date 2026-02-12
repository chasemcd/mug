// import * as ort from 'https://cdnjs.cloudflare.com/ajax/libs/onnxruntime-web/1.10.0/ort.min.js';

import * as seeded_random from './seeded_random.js';

// Store loaded models to avoid reloading
const loadedModels = {};
const hiddenStates = {};

export async function actionFromONNX(policyID, observation) {
    // Conduct forward inference
    const logits = await inferenceONNXPolicy(policyID, observation);

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

async function inferenceONNXPolicy(policyID, observation) {

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

    // TODO(chase): We need to add the onnx inputs to the configuration!
    const feeds = {
        'obs': inputTensor,
        // 'seq_lens': new window.ort.Tensor('float32', new Float32Array([1])),
        // 'state_ins': [new window.ort.Tensor('float32', new Float32Array([0]), [1])]
    };

    // Check if the model is recurrent by inspecting input names, we're following
    // the RLlib convention of naming hidden states as 'state_in_0', 'state_in_1', etc.
    const isRecurrent = session.inputNames.some(name => name.startsWith('state_in_'));
    
    if (isRecurrent) {
        // Load hidden states if available, otherwise initialize them
        if (!hiddenStates[policyID]) {
            hiddenStates[policyID] = {};
        }

        session.inputNames.forEach(name => {
            if (name.startsWith('state_in_')) {
                if (!hiddenStates[policyID][name]) {

                    // TODO(chase): retrieve the shape; this hardcodes hidden states to [1, 256]
                    const expectedShape = [1, 256] // inputMetadata[name].dimensions;

                    // Initialize the hidden state tensor with zeros
                    hiddenStates[policyID][name] = new window.ort.Tensor('float32', new Float32Array(expectedShape.reduce((a, b) => a * b)), expectedShape);
                } 
                feeds[name] = hiddenStates[policyID][name];
            }
        });

        feeds['seq_lens'] = new window.ort.Tensor('float32', new Float32Array([1]));
    } else {
        feeds['state_ins'] = new window.ort.Tensor('float32', new Float32Array([1]));

    }

    // Run inference
    const results = await session.run(feeds);

    // Get the output logits (assuming single output)
    const logits = results[session.outputNames[0]].data;

    return logits
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