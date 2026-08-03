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


def _partner_obs():
    # The numbers the exported partner is scored on. Only a bundle that seats one
    # defines this; the driver asks for it only when the manifest declares a
    # partner, so a bundle without one is never asked.
    return [float(x) for x in partner_observation()]


def _partner_acts(action):
    partner_acts(int(action))
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

// The browser twin of `resolve_action` in `mug/game/runtime.py`. The two must
// agree: a browser run is verified by re-executing it on the server, so a client
// that read one action where the server read another would make an honest
// participant's run unverifiable.
//
// A chord is a **sequence of keys** held together, and it arrives as one: every
// key in it must be down. A chord beats a single key, and a longer chord beats a
// shorter one, so the most specific thing the player is doing is what the seat does.
function resolveAction(manifest, pressed) {
  const bindings = manifest.action_bindings;
  let bestSize = 0;
  let best;
  for (const chord of manifest.action_chords ?? []) {
    if (chord.keys.every((key) => pressed.has(key)) && chord.keys.length > bestSize) {
      bestSize = chord.keys.length;
      best = chord.action;
    }
  }
  if (best !== undefined) return best;
  for (const key of pressed) {
    if (key in bindings) return bindings[key];
  }
  return manifest.default_action;
}

// The browser twin of `InputState`. In `pressed_keys` a held key acts on every
// frame; in `single_keystroke` each press is worth one action however long the key
// is held, so a tap of the pick-up key picks one thing up rather than picking it
// up and putting it down for as long as the finger is down.
function actionFor(manifest, pressed, taps) {
  if (manifest.input_mode !== "single_keystroke") {
    return resolveAction(manifest, pressed);
  }
  return taps.length > 0 ? taps.shift() : manifest.default_action;
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

// --- the exported partner ------------------------------------------------
//
// The environment steps in Pyodide, where no ONNX runtime can be installed, so a
// seat driven by an exported network is scored by the browser's own runtime
// beside it. The model is a declared study asset: the study names it and the
// asset table answers where it is served, so nothing here builds an address.
//
// The decisions are collected and reported with the run. The server has no copy
// of this runtime, so it replays them when it re-executes the episode.

let ortLoading = null;

// Load the inference runtime once. It ships as a classic script rather than a
// module, so it is injected and read off the window -- which is also what lets a
// deployment serve its own copy from anywhere it likes.
function loadOrt(url) {
  if (window.ort) return Promise.resolve(window.ort);
  if (ortLoading) return ortLoading;
  ortLoading = new Promise((resolve, reject) => {
    const tag = document.createElement("script");
    tag.src = url;
    tag.async = true;
    tag.addEventListener("load", () =>
      window.ort ? resolve(window.ort) : reject(new Error("no inference runtime")),
    );
    tag.addEventListener("error", () => reject(new Error("the inference runtime did not load")));
    document.head.appendChild(tag);
  });
  return ortLoading;
}

// A small deterministic source of randomness, seeded from the episode seed, so a
// sampling partner plays the same way on a re-run of the same episode.
function seededDraw(seed) {
  let state = (seed >>> 0) || 1;
  return () => {
    state ^= state << 13;
    state ^= state >>> 17;
    state ^= state << 5;
    return ((state >>> 0) % 1000000) / 1000000;
  };
}

function softmaxPick(scores, temperature, draw) {
  const scaled = scores.map((value) => value / (temperature || 1));
  const peak = Math.max(...scaled);
  const weights = scaled.map((value) => Math.exp(value - peak));
  const total = weights.reduce((sum, value) => sum + value, 0);
  let cumulative = 0;
  const target = draw();
  for (let index = 0; index < weights.length; index++) {
    cumulative += weights[index] / total;
    if (target < cumulative) return index;
  }
  return weights.length - 1;
}

function argmaxPick(scores) {
  let best = 0;
  for (let index = 0; index < scores.length; index++) {
    if (scores[index] > scores[best]) best = index;
  }
  return best;
}

// Build the partner seat, or nothing at all. A partner that cannot be built --
// no runtime, no declared model -- is reported and the seat holds its default
// action, so a study loses its partner rather than the participant losing their
// session.
async function buildPartner(manifest, assets, onStatus) {
  const declared = manifest.partner;
  if (!declared) return null;
  const url = assets && typeof assets.url === "function" ? assets.url(declared.model) : null;
  if (!url) {
    onStatus?.(`the study declared no model named ${declared.model}`);
    return null;
  }
  onStatus?.("loading the partner...");
  let session;
  try {
    const ort = await loadOrt(declared.runtime_url);
    session = await ort.InferenceSession.create(url, { executionProviders: ["wasm"] });
  } catch (error) {
    onStatus?.(`the partner could not be loaded: ${error}`);
    return null;
  }
  const ort = window.ort;
  const draw = seededDraw(manifest.seed);
  let held = declared.default_action;
  let asked = 0;

  return {
    // One decision, paced. The seat is asked every frame and decides every
    // `decide_every` of them, holding what it chose between -- the browser twin
    // of the frame skip a server-side controller keeps.
    async decide(observation) {
      const due = asked % declared.decide_every === 0;
      asked += 1;
      if (!due) return held;
      const input = new ort.Tensor(
        "float32",
        Float32Array.from(observation),
        [1, observation.length],
      );
      const output = await session.run({ [declared.input_name]: input });
      const scores = Array.from(output[declared.output_name].data);
      held =
        declared.selection === "sample"
          ? softmaxPick(scores, declared.temperature, draw)
          : argmaxPick(scores);
      return held;
    },
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
export async function preloadBrowserGame(manifest, { onStatus, assets } = {}) {
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
  // The partner loads while the environment does, so the first frame is not the
  // frame that downloads a model.
  const partner = await buildPartner(manifest, assets, onStatus);
  onStatus?.("environment ready");
  return {
    reset: pyodide.globals.get("_reset"),
    step: pyodide.globals.get("_step"),
    commands: pyodide.globals.get("_commands"),
    obsHash: pyodide.globals.get("_obs_hash"),
    actionHash: pyodide.globals.get("_action_hash"),
    partner,
    partnerObservation: manifest.partner
      ? pyodide.globals.get("_partner_obs")
      : null,
    partnerActs: manifest.partner ? pyodide.globals.get("_partner_acts") : null,
  };
}

// Run one browser episode to its end, reporting what was played as it goes.
//
// `onPart` is called with each slice of the run, and with the last one when the
// episode ends. Reporting while the round is played is what makes leaving early
// cost the tail rather than everything: an episode held in the tab until the end
// is lost in full if the tab does not reach the end.
//
// The runtime must already be preloaded, so the canvas is never blank on a
// download.
export async function playBrowserEpisode(
  runtime,
  manifest,
  { renderer, pressed, taps, onStatus, onPart } = {},
) {
  const { reset, step } = runtime;
  const toCommands = () => runtime.commands().toJs({ create_proxies: false });

  onStatus?.("playing...");
  reset(manifest.seed);
  const transitions = [];
  // The action sequence the client reports, so the server re-executes the run
  // under the same inputs and verifies the state-hash chain it produced.
  const actions = [];
  // What the exported partner did, on the same frames. The server has no copy of
  // the inference runtime that produced these, so they travel with the run and
  // are replayed into the same bundle when it re-executes the episode.
  const partnerActions = [];
  let frame = 0;
  let solved = false;

  // What has been played and not yet reported. The server sets the cadence, and a
  // client that reported on its own schedule could report once at the end.
  const perPart = manifest.frames_per_part ?? 0;
  let reportedTo = 0;
  const report = async (final, boundary) => {
    if (!onPart) return;
    if (!final && (perPart <= 0 || frame - reportedTo < perPart)) return;
    if (final && frame === reportedTo && !boundary) return;
    const slice = {
      first_frame: reportedTo + 1,
      final,
      transitions: transitions.slice(reportedTo),
      actions: actions.slice(reportedTo),
      partner_actions: partnerActions.slice(reportedTo),
      boundary,
    };
    reportedTo = frame;
    await onPart(slice);
  };

  // The seat holds its default until it first decides, which is what the server
  // replays for that frame too.
  let partnerAction = manifest.partner ? manifest.partner.default_action : 0;

  const startCommands = toCommands();
  renderer?.draw(
    renderPacket(manifest, 0, true, startCommands, await digest(startCommands)),
  );

  while (frame < manifest.max_steps) {
    const action = actionFor(manifest, pressed, taps ?? []);
    if (manifest.partner) {
      if (runtime.partner) {
        const observation = runtime.partnerObservation().toJs();
        partnerAction = await runtime.partner.decide(observation);
      }
      runtime.partnerActs(partnerAction);
      partnerActions.push(partnerAction);
    }
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


    await report(false, undefined);

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
  await report(true, boundary);
  onStatus?.(solved ? "reached the goal" : "episode ended");
  return { transitions, boundary, actions, partnerActions };
}
