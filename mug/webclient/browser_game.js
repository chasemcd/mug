// The browser (Pyodide) execution runtime. Given the server's public manifest, it
// boots Pyodide, installs the pinned packages once, runs the study source bundle,
// and steps the environment in the browser -- no server round trip per frame. It
// draws each frame through the same renderer the server path uses, and builds the
// same normalized GameTransition and EpisodeBoundary records. On the episode end it
// hands the finished run back so the client can report it over game.capture. The
// client is the writer; the server validates and commits the run under a fence.

const PYODIDE_VERSION = "v0.26.2";

// A small Python driver injected after the study bundle and the state-hash hook.
// It keeps the environment on the Python side, so the JS loop passes only plain
// integers and reads plain lists -- no live proxy juggling across the boundary.
// The state and action hashes come from the shared hook (``_mug_state_hash_hex``),
// so the server re-computes the identical hash when it verifies the run.
const DRIVER = `
_env = None
_last_obs = None


def _reset(seed):
    global _env, _last_obs
    _env = make_env()
    obs, _info = _env.reset(seed=seed)
    _last_obs = obs
    return [float(x) for x in obs]


def _step(action):
    global _last_obs
    obs, reward, terminated, truncated, _info = _env.step(int(action))
    _last_obs = obs
    return [
        [float(x) for x in obs],
        float(reward),
        bool(terminated),
        bool(truncated),
    ]


def _commands():
    return draw(_last_obs)


def _obs_hash():
    return _mug_state_hash_hex([float(x) for x in _last_obs])


def _action_hash(action):
    return _mug_state_hash_hex(int(action))
`;

async function sha256Hex(value) {
  const canonical = canonicalJson(value);
  const data = new TextEncoder().encode(canonical);
  const buffer = await crypto.subtle.digest("SHA-256", data);
  return [...new Uint8Array(buffer)]
    .map((b) => b.toString(16).padStart(2, "0"))
    .join("");
}

// A stable, sorted-key JSON serialization, so a digest is reproducible.
function canonicalJson(value) {
  if (Array.isArray(value)) return `[${value.map(canonicalJson).join(",")}]`;
  if (value && typeof value === "object") {
    const keys = Object.keys(value).sort();
    return `{${keys.map((k) => `${JSON.stringify(k)}:${canonicalJson(value[k])}`).join(",")}}`;
  }
  return JSON.stringify(value);
}

async function digest(value) {
  return { algorithm: "sha-256", hex: await sha256Hex(value) };
}

function actionFor(manifest, pressed) {
  for (const key of pressed) {
    if (key in manifest.action_bindings) return manifest.action_bindings[key];
  }
  return manifest.default_action;
}

function renderPacket(manifest, frame, keyframe, commands, renderDigest) {
  return {
    episode_id: manifest.episode_id,
    seat_key: manifest.seat_key,
    frame_number: frame,
    render_digest: renderDigest,
    keyframe,
    commands,
  };
}

function transitionFor(manifest, runtime, frame, action) {
  // The state and action digests come from the shared Python hook, so the server
  // re-computes the identical values when it re-executes the run to verify it.
  return {
    interaction_id: manifest.interaction_id,
    channel_key: manifest.channel_key,
    episode_id: manifest.episode_id,
    frame_number: frame,
    action_digest: { algorithm: "sha-256", hex: runtime.actionHash(action) },
    state_digest: { algorithm: "sha-256", hex: runtime.obsHash() },
    authority: "browser",
    applied_decisions: [],
    recorded_at: new Date().toISOString().replace("Z", "000Z"),
  };
}

async function loadPyodideRuntime() {
  const url = `https://cdn.jsdelivr.net/pyodide/${PYODIDE_VERSION}/full/pyodide.mjs`;
  const module = await import(/* @vite-ignore */ url);
  return module.loadPyodide({
    indexURL: `https://cdn.jsdelivr.net/pyodide/${PYODIDE_VERSION}/full/`,
  });
}

// Boot Pyodide, install the pinned packages, and load the study bundle. This is
// the slow part, so it runs eagerly while the participant is on the forms. It
// returns a ready runtime handle; the game step loop uses it with no further wait.
export async function preloadBrowserGame(manifest, { onStatus } = {}) {
  onStatus?.("loading the python runtime...");
  const pyodide = await loadPyodideRuntime();
  await pyodide.loadPackage("micropip");
  const micropip = pyodide.pyimport("micropip");
  for (const requirement of manifest.requires) {
    onStatus?.(`installing ${requirement}...`);
    await micropip.install(requirement);
  }
  await pyodide.runPythonAsync(manifest.source_bundle);
  // The state-hash hook the server ships, so the client hashes state the exact
  // way the server re-computes it. It runs before the driver, which uses it.
  await pyodide.runPythonAsync(manifest.state_hash_source);
  await pyodide.runPythonAsync(DRIVER);
  onStatus?.("environment ready");
  return {
    reset: pyodide.globals.get("_reset"),
    step: pyodide.globals.get("_step"),
    commands: pyodide.globals.get("_commands"),
    obsHash: pyodide.globals.get("_obs_hash"),
    actionHash: pyodide.globals.get("_action_hash"),
  };
}

// Run one browser episode to its end and return { transitions, boundary }. The
// runtime must already be preloaded, so the canvas is never blank on a download.
export async function playBrowserEpisode(runtime, manifest, { renderer, pressed, onStatus } = {}) {
  const { reset, step } = runtime;
  const toCommands = () => runtime.commands().toJs({ create_proxies: false });

  onStatus?.("playing...");
  reset(manifest.seed);
  const transitions = [];
  // The action sequence the client reports, so the server re-executes the run
  // under the same inputs and verifies the state-hash chain it produced.
  const actions = [];
  let frame = 0;
  let solved = false;

  const startCommands = toCommands();
  renderer?.draw(
    renderPacket(manifest, 0, true, startCommands, await digest(startCommands)),
  );

  while (frame < manifest.max_steps) {
    const action = actionFor(manifest, pressed);
    const outcome = step(action).toJs();
    const terminated = outcome[2];
    const truncated = outcome[3];
    frame += 1;

    // The hash reads the post-step observation the driver holds, so it binds to
    // this frame; take it before the next step overwrites the driver state.
    transitions.push(transitionFor(manifest, runtime, frame, action));
    actions.push(action);
    const commands = toCommands();
    renderer?.draw(
      renderPacket(manifest, frame, false, commands, await digest(commands)),
    );

    if (terminated) {
      solved = true;
      break;
    }
    if (truncated) break;
    if (manifest.fps > 0) {
      await new Promise((resolve) => setTimeout(resolve, 1000 / manifest.fps));
    }
  }

  const boundary = {
    episode_id: manifest.episode_id,
    interaction_id: manifest.interaction_id,
    kind: solved ? "terminal" : "reset",
    end_frame_exclusive: frame,
    authority: "browser",
    state_hash: { algorithm: "sha-256", hex: runtime.obsHash() },
  };
  onStatus?.(solved ? "reached the goal" : "episode ended");
  return { transitions, boundary, actions };
}
