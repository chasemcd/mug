/**
 * The browser (Pyodide) execution runtime.
 *
 * Given the server's public manifest, it boots Pyodide, installs the pinned
 * packages once, runs the study source bundle, and steps the environment in the
 * browser -- no server round trip per frame. It draws each frame through the same
 * renderer the server path uses and builds the same normalized transition and
 * boundary records. On the episode end it hands the finished run back, so the
 * client reports it over `game.capture`. The client is the writer; the server
 * validates and commits the run under a fence.
 *
 * The state and action hashes come from a shared Python hook the manifest ships,
 * so the server re-computes identical hashes when it verifies the run. The
 * render-packet digest uses the kernel twin, so it matches the server's digest of
 * the same commands.
 */

import { Chord, resolveAction } from "./bindings.js";
import { computeDigest, Digest, HashBytes, JsonValue } from '../kernel/index.js';
import { Renderer, SurfaceCommand } from './renderer.js';

const PYODIDE_VERSION = 'v0.26.2';

// A small Python driver injected after the study bundle and the state-hash hook.
// It keeps the environment on the Python side, so the JavaScript loop passes only
// plain integers and reads plain lists -- no live proxy juggling across the
// boundary. The hashes come from the shared hook (`_mug_state_hash_hex`), so the
// server re-computes the identical hash when it verifies the run.
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

/** The public game manifest, projected server-side for the browser. */
export interface BrowserManifest {
  mode: 'browser';
  episode_id: string;
  interaction_id: string;
  seat_key: string;
  channel_key: string;
  seed: number;
  max_steps: number;
  // How many frames the client plays before it reports what it has played.
  frames_per_part?: number | undefined;
  fps: number;
  countdown_seconds: number;
  action_bindings: { [key: string]: number };
  /** Chords: sequences of keys held together, each with the action it means. */
  action_chords?: readonly Chord[];
  default_action: number;
  hooks: string[];
  requires: string[];
  source_bundle: string;
  state_hash_source: string;
}

/** One normalized frame transition the client reports. */
export interface GameTransition {
  interaction_id: string;
  channel_key: string;
  episode_id: string;
  frame_number: number;
  action_digest: Digest;
  state_digest: Digest;
  authority: 'browser';
  applied_decisions: [];
  recorded_at: string;
}

/** The end-of-episode boundary the client reports. */
export interface EpisodeBoundary {
  episode_id: string;
  interaction_id: string;
  kind: 'terminal' | 'reset';
  end_frame_exclusive: number;
  authority: 'browser';
  state_hash: Digest;
}

/** The finished run the client hands back for capture. */
export interface EpisodeRun {
  transitions: GameTransition[];
  boundary: EpisodeBoundary;
  actions: number[];
}

// A minimal view of the Pyodide interop surface this module uses.
interface PyProxy {
  toJs(options?: { create_proxies?: boolean }): unknown;
}
interface PyodideInterface {
  loadPackage(name: string): Promise<void>;
  pyimport(name: string): { install(requirement: string): Promise<void> };
  runPythonAsync(code: string): Promise<unknown>;
  globals: { get(name: string): unknown };
}

/** The ready Pyodide runtime handle the step loop uses. */
export interface BrowserRuntime {
  reset: (seed: number) => unknown;
  step: (action: number) => PyProxy;
  commands: () => PyProxy;
  obsHash: () => string;
  actionHash: (action: number) => string;
}

/** One slice of a run, as it is reported while the episode is played. */
export interface EpisodePart {
  first_frame: number;
  final: boolean;
  transitions: GameTransition[];
  actions: number[];
  boundary?: EpisodeBoundary | undefined;
}

/** Options for the browser episode. */
export interface EpisodeOptions {
  renderer?: Renderer | undefined;
  pressed: Set<string>;
  hash: HashBytes;
  onStatus?: ((text: string) => void) | undefined;
  // Called with each slice of the run, and with the last one when the episode
  // ends. Reporting while the round is played is what makes leaving early cost
  // the tail rather than everything: a run held in the tab until the end is lost
  // in full if the tab does not reach the end.
  onPart?: ((part: EpisodePart) => Promise<void> | void) | undefined;
}

function actionFor(manifest: BrowserManifest, pressed: Set<string>): number {
  return resolveAction(
    pressed,
    manifest.action_bindings,
    manifest.default_action,
    manifest.action_chords ?? [],
  );
}

function transitionFor(
  manifest: BrowserManifest,
  runtime: BrowserRuntime,
  frame: number,
  action: number,
): GameTransition {
  // The state and action digests come from the shared Python hook, so the server
  // re-computes the identical values when it re-executes the run to verify it.
  return {
    interaction_id: manifest.interaction_id,
    channel_key: manifest.channel_key,
    episode_id: manifest.episode_id,
    frame_number: frame,
    action_digest: { algorithm: 'sha-256', hex: runtime.actionHash(action) },
    state_digest: { algorithm: 'sha-256', hex: runtime.obsHash() },
    authority: 'browser',
    applied_decisions: [],
    recorded_at: new Date().toISOString().replace('Z', '000Z'),
  };
}

async function loadPyodideRuntime(): Promise<PyodideInterface> {
  const url = 'https://cdn.jsdelivr.net/pyodide/' + PYODIDE_VERSION + '/full/pyodide.mjs';
  const module = (await import(/* @vite-ignore */ url)) as {
    loadPyodide(options: { indexURL: string }): Promise<PyodideInterface>;
  };
  return module.loadPyodide({
    indexURL: 'https://cdn.jsdelivr.net/pyodide/' + PYODIDE_VERSION + '/full/',
  });
}

/**
 * Boot Pyodide, install the pinned packages, and load the study bundle. This is
 * the slow part, so it runs eagerly while the participant is on the forms. It
 * returns a ready runtime handle the step loop uses with no further wait.
 */
export async function preloadBrowserGame(
  manifest: BrowserManifest,
  options: { onStatus?: (text: string) => void } = {},
): Promise<BrowserRuntime> {
  const onStatus = options.onStatus;
  onStatus?.('loading the python runtime...');
  const pyodide = await loadPyodideRuntime();
  await pyodide.loadPackage('micropip');
  const micropip = pyodide.pyimport('micropip');
  for (const requirement of manifest.requires) {
    onStatus?.('installing ' + requirement + '...');
    await micropip.install(requirement);
  }
  await pyodide.runPythonAsync(manifest.source_bundle);
  // The state-hash hook the server ships, so the client hashes state the exact
  // way the server re-computes it. It runs before the driver, which uses it.
  await pyodide.runPythonAsync(manifest.state_hash_source);
  await pyodide.runPythonAsync(DRIVER);
  onStatus?.('environment ready');
  return {
    reset: pyodide.globals.get('_reset') as (seed: number) => unknown,
    step: pyodide.globals.get('_step') as (action: number) => PyProxy,
    commands: pyodide.globals.get('_commands') as () => PyProxy,
    obsHash: pyodide.globals.get('_obs_hash') as () => string,
    actionHash: pyodide.globals.get('_action_hash') as (action: number) => string,
  };
}

/**
 * Run one browser episode to its end and return the transitions, the boundary,
 * and the action sequence. The runtime must already be preloaded, so the canvas
 * is never blank on a download.
 */
export async function playBrowserEpisode(
  runtime: BrowserRuntime,
  manifest: BrowserManifest,
  options: EpisodeOptions,
): Promise<EpisodeRun> {
  const { renderer, pressed, hash, onStatus, onPart } = options;
  const toCommands = (): SurfaceCommand[] =>
    runtime.commands().toJs({ create_proxies: false }) as SurfaceCommand[];
  const drawFrame = async (frame: number, keyframe: boolean): Promise<void> => {
    if (!renderer) {
      return;
    }
    const commands = toCommands();
    const renderDigest = await computeDigest(commands as unknown as JsonValue, hash);
    renderer.draw({ commands, ...packetMeta(manifest, frame, keyframe, renderDigest) });
  };

  onStatus?.('playing...');
  runtime.reset(manifest.seed);
  const transitions: GameTransition[] = [];
  // The action sequence the client reports, so the server re-executes the run
  // under the same inputs and verifies the state-hash chain it produced.
  const actions: number[] = [];
  let frame = 0;
  let solved = false;

  // The server sets the cadence, because the server is what has to hold the
  // parts; a client choosing its own could report once at the end.
  const perPart = manifest.frames_per_part ?? 0;
  let reportedTo = 0;
  const report = async (final: boolean, boundary?: EpisodeBoundary): Promise<void> => {
    if (!onPart) return;
    if (!final && (perPart <= 0 || frame - reportedTo < perPart)) return;
    if (final && frame === reportedTo && !boundary) return;
    const part: EpisodePart = {
      first_frame: reportedTo + 1,
      final,
      transitions: transitions.slice(reportedTo),
      actions: actions.slice(reportedTo),
      boundary,
    };
    reportedTo = frame;
    await onPart(part);
  };

  await drawFrame(0, true);

  while (frame < manifest.max_steps) {
    const action = actionFor(manifest, pressed);
    const outcome = runtime.step(action).toJs() as [unknown, unknown, boolean, boolean];
    const terminated = outcome[2];
    const truncated = outcome[3];
    frame += 1;

    // The hash reads the post-step observation the driver holds, so it binds to
    // this frame; take it before the next step overwrites the driver state.
    transitions.push(transitionFor(manifest, runtime, frame, action));
    actions.push(action);
    await drawFrame(frame, false);
    await report(false, undefined);

    if (terminated) {
      solved = true;
      break;
    }
    if (truncated) {
      break;
    }
    if (manifest.fps > 0) {
      await new Promise((resolve) => setTimeout(resolve, 1000 / manifest.fps));
    }
  }

  const boundary: EpisodeBoundary = {
    episode_id: manifest.episode_id,
    interaction_id: manifest.interaction_id,
    kind: solved ? 'terminal' : 'reset',
    end_frame_exclusive: frame,
    authority: 'browser',
    state_hash: { algorithm: 'sha-256', hex: runtime.obsHash() },
  };
  await report(true, boundary);
  onStatus?.(solved ? 'reached the goal' : 'episode ended');
  return { transitions, boundary, actions };
}

// The extra render-packet fields the browser path carries alongside the commands.
// The renderer reads only the commands; these ride along for parity with the
// server render packet.
function packetMeta(
  manifest: BrowserManifest,
  frame: number,
  keyframe: boolean,
  renderDigest: Digest,
): {
  episode_id: string;
  seat_key: string;
  frame_number: number;
  render_digest: Digest;
  keyframe: boolean;
} {
  return {
    episode_id: manifest.episode_id,
    seat_key: manifest.seat_key,
    frame_number: frame,
    render_digest: renderDigest,
    keyframe,
  };
}
