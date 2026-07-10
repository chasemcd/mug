// Heuristic (Python code) policy execution against the Pyodide environment.
//
// Heuristic policies are HeuristicPolicy subclasses implementing
// `compute_action(self, env, agent_id)` (see HeuristicPolicy in
// mug/configurations/configuration_constants.py). The source of the module
// defining the subclass is shipped in scene_metadata.policy_configs and
// executed here inside the same Pyodide interpreter that hosts the
// environment, so the policy receives the live `env` instance directly.
// One instance is created per agent, so policies can hold per-agent state
// across steps.

export const HEURISTIC_POLICY_PREFIX = "heuristic:";

// Store policy configs from scene_metadata (keyed by agent ID)
let policyConfigs = {};

// Agent IDs whose policy instance already exists in the Pyodide registry
const registeredAgents = new Set();

/**
 * Initialize heuristic policy configs from scene_metadata.
 * Called once during scene setup, alongside initModelConfigs.
 * @param {Object} sceneMetadata - The scene_metadata object from the server
 */
export function initHeuristicPolicies(sceneMetadata) {
    if (sceneMetadata && sceneMetadata.policy_configs) {
        policyConfigs = sceneMetadata.policy_configs;
    }
    // Scene changed: force re-registration in case Pyodide was restarted
    registeredAgents.clear();
}

/**
 * Check whether a policy_mapping value denotes a heuristic policy.
 * @param {string} policyID - The policy_mapping value for an agent
 * @returns {boolean}
 */
export function isHeuristicPolicy(policyID) {
    return typeof policyID === "string" && policyID.startsWith(HEURISTIC_POLICY_PREFIX);
}

/**
 * Exec the policy's defining module in Pyodide and store an instance of the
 * subclass in the `_mug_heuristic_policies` registry (a dict in Pyodide
 * globals keyed by agent ID).
 */
function registerPolicy(pyodide, config, agentID) {
    pyodide.globals.set("_mug_heuristic_name", config.name);
    pyodide.globals.set("_mug_heuristic_code", config.code);
    pyodide.globals.set("_mug_heuristic_agent_id", String(agentID));
    pyodide.runPython(`
if "_mug_heuristic_policies" not in globals():
    _mug_heuristic_policies = {}

# The policy module imports HeuristicPolicy from mug; if the mug package
# installed in Pyodide predates it, inject a minimal stand-in so the
# import resolves.
import mug.configurations.configuration_constants as _mug_cc
if not hasattr(_mug_cc, "HeuristicPolicy"):
    class _MugHeuristicPolicyShim:
        def compute_action(self, env, agent_id):
            raise NotImplementedError
    _mug_cc.HeuristicPolicy = _MugHeuristicPolicyShim

_mug_heuristic_ns = {}
exec(_mug_heuristic_code, _mug_heuristic_ns)
_mug_heuristic_cls = _mug_heuristic_ns.get(_mug_heuristic_name)
if not (
    isinstance(_mug_heuristic_cls, type)
    and callable(getattr(_mug_heuristic_cls, "compute_action", None))
):
    raise ValueError(
        f"Heuristic policy code must define a class named "
        f"'{_mug_heuristic_name}' with a compute_action(env, agent_id) method."
    )
_mug_heuristic_policies[_mug_heuristic_agent_id] = _mug_heuristic_cls()
`);
}

/**
 * Compute an action for an agent by calling its heuristic policy with the
 * live Pyodide environment instance. Synchronous (heuristics are plain
 * Python; no async inference involved).
 *
 * @param {Object} pyodide - The Pyodide instance hosting the environment
 * @param {string} policyID - The policy_mapping value ("heuristic:<ClassName>")
 * @param {string} agentID - The agent ID (same keys as policy_mapping)
 * @returns {number} The selected action
 */
export function actionFromHeuristic(pyodide, policyID, agentID) {
    const config = policyConfigs[agentID];
    if (!config || config.type !== "heuristic") {
        throw new Error(`No heuristic policy config found for agent ${agentID}`);
    }

    if (!registeredAgents.has(agentID)) {
        registerPolicy(pyodide, config, agentID);
        registeredAgents.add(agentID);
    }

    pyodide.globals.set("_mug_heuristic_agent_id", String(agentID));
    // Mirror the agent ID coercion used in RemoteGame.step(): numeric string
    // keys become ints so the policy sees the same IDs the env does.
    const action = pyodide.runPython(`
_mug_agent_id = _mug_heuristic_agent_id
if _mug_agent_id.isnumeric():
    _mug_agent_id = int(_mug_agent_id)
_mug_action = _mug_heuristic_policies[_mug_heuristic_agent_id].compute_action(env, _mug_agent_id)
if hasattr(_mug_action, "item"):
    _mug_action = _mug_action.item()
_mug_action
`);
    return action;
}
