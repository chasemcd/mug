/**
 * The browser peer-to-peer executor: play one mesh episode over open channels.
 *
 * The transport (`p2pEdge.ts`) opens and validates a data channel to every peer
 * and hands them over. This module is what consumes that handoff. It boots the
 * platform's own rollback runtime in Pyodide, runs one frame per tick, moves the
 * packets over the channels, closes the barrier, and reports the trajectory.
 *
 * There is **no rollback engine in TypeScript**. The engine, the packet codec,
 * and the frame driver are the platform's own Python modules, shipped verbatim in
 * the manifest and run in Pyodide beside the environment. So a browser peer and a
 * server peer run the same code, and a snapshot never crosses the language
 * boundary -- only plain text does. This file owns the clock, the keys, the
 * canvas, and the channels, and nothing else.
 *
 * The trajectory is named by the chain over its per-frame digests, which Python
 * computes. This file digests a list of hex strings and never a number, so the
 * identity of a run does not depend on how a language writes a float.
 */

import { Chord, resolveAction } from "./bindings.js";
import { computeDigest, Digest, HashBytes } from '../kernel/index.js';
import { P2PMeshHandoff } from './p2pEdge.js';
import { MeshDataChannel } from './p2pRtc.js';
import { P2PBootstrap, P2PMeshAbort, P2PMeshFinish, P2PMeshStart } from './p2pWire.js';
import { Renderer, SurfaceCommand } from './renderer.js';

const PYODIDE_VERSION = 'v0.26.2';

// The Python the browser runs after the shipped platform modules and the study
// bundle. It holds the driver on the Python side, so the JavaScript loop passes
// only plain values across the boundary and no live proxy is juggled per frame.
const DRIVER_GLUE = `
_mug_driver = None


def _mug_mesh_boot(config_json):
    global _mug_driver
    from mug.game.browser_mesh_driver import boot_mesh_driver

    _mug_driver = boot_mesh_driver(
        config_json, make_replica, globals().get("draw")
    )


def _mug_mesh_receive(remote, text):
    _mug_driver.receive(remote, text)


def _mug_mesh_tick(action):
    return _mug_driver.tick(int(action))


def _mug_mesh_ready():
    return _mug_driver.ready_to_finalize()


def _mug_mesh_finalize():
    _mug_driver.finalize()


def _mug_mesh_hashes():
    return _mug_driver.frame_hashes()


def _mug_mesh_frames():
    return _mug_driver.frame_count()


def _mug_mesh_payload():
    return _mug_driver.capture_payload_json()


def _mug_mesh_commands():
    return _mug_driver.commands()


def _mug_mesh_rollbacks():
    return _mug_driver.rollback_count()
`;

/** One platform module the browser runs verbatim. */
export interface MeshRuntimeModule {
  name: string;
  source: string;
}

/** The public manifest for one browser-executed peer-to-peer game channel. */
export interface MeshManifest {
  mode: 'peer';
  channel_key: string;
  source_bundle: string;
  requires: string[];
  action_bindings: { [key: string]: number };
  /** Chords: sequences of keys held together, each with the action it means. */
  action_chords?: readonly Chord[];
  default_action: number;
  fps: number;
  countdown_seconds: number;
  hooks: string[];
  max_steps: number;
  input_delay: number;
  snapshot_interval: number;
  redundancy: number;
  prelude_source: string;
  runtime_modules: MeshRuntimeModule[];
}

/** The booted mesh driver, as this file drives it. */
export interface MeshDriver {
  receive(remoteHandle: string, text: string): void;
  tick(action: number): string[];
  readyToFinalize(): boolean;
  finalize(): void;
  frameHashes(): string[];
  frameCount(): number;
  capturePayloadJson(): string;
  commands(): SurfaceCommand[] | null;
  rollbackCount(): number;
}

/** The ready Python runtime: it builds one driver for one room. */
export interface MeshRuntime {
  boot(runConfigJson: string): MeshDriver;
}

/** What one finished mesh episode produced. */
export interface MeshRunResult {
  trajectoryDigest: Digest;
  frameCount: number;
  submittedCapture: boolean;
  rollbackCount: number;
}

/** The manifest and the booted runtime one room plays with. */
export interface MeshSession {
  manifest: MeshManifest;
  runtime: MeshRuntime;
}

/** Everything the executor needs from the page. */
export interface MeshExecutorConfig {
  /**
   * Return the manifest and the booted runtime, awaited when a room starts.
   *
   * It is a callback rather than a value because the executor is built when the
   * client is, and the manifest arrives later over the socket. Waiting for it
   * here also means a browser whose runtime is still downloading joins its room
   * and holds the barrier, rather than failing out of it.
   */
  prepare: () => Promise<MeshSession>;
  pressed: Set<string>;
  hash: HashBytes;
  now: () => number;
  sleep: (delayMillis: number) => Promise<void>;
  renderer?: (() => Renderer | null) | undefined;
  onStatus?: ((text: string) => void) | undefined;
  onError?: ((message: string) => void) | undefined;
  onFinished?: ((result: MeshRunResult) => void) | undefined;
  /** How many frames the loop may run back to back to catch up after a stall. */
  maxCatchUpFrames?: number;
  /** How many frames past the step cap the barrier may take before giving up. */
  barrierGraceFrames?: number;
}

/**
 * Build the run configuration for one peer of one room.
 *
 * It is the exact shape `mug.game.browser_mesh.mesh_run_config` builds, from the
 * frames the client already holds. So no frame and no schema field has to carry
 * it, and the browser still names only public handles.
 */
export function meshRunConfig(
  manifest: MeshManifest,
  bootstrap: P2PBootstrap,
  start: P2PMeshStart,
): string {
  const handles = [bootstrap.local_peer_handle, ...bootstrap.peers.map((p) => p.peer_handle)];
  const frozen = [...new Set(handles)].sort();
  return JSON.stringify({
    local_actor_id: bootstrap.local_peer_handle,
    peer_actor_ids: frozen,
    channel_key: manifest.channel_key,
    room_handle: bootstrap.room_handle,
    negotiation_generation: bootstrap.negotiation_generation,
    seed: start.seed,
    input_delay: manifest.input_delay,
    snapshot_interval: manifest.snapshot_interval,
    default_action: manifest.default_action,
    max_steps: manifest.max_steps,
    redundancy: manifest.redundancy,
  });
}

function actionFor(manifest: MeshManifest, pressed: Set<string>): number {
  return resolveAction(
    pressed,
    manifest.action_bindings,
    manifest.default_action,
    manifest.action_chords ?? [],
  );
}

/** One peer's inbox: it holds messages until the driver exists to take them. */
class Inbox {
  private held: Array<[string, string]> = [];
  private driver: MeshDriver | null = null;

  accept(peerHandle: string, data: unknown): void {
    const text = typeof data === 'string' ? data : String(data);
    let parsed: unknown;
    try {
      parsed = JSON.parse(text);
    } catch {
      // A message that is not JSON is not a packet. Drop it: the codec would
      // refuse it, and refusing would end a room over one stray frame.
      return;
    }
    if (parsed === null || typeof parsed !== 'object' || Array.isArray(parsed)) {
      return;
    }
    // The channel also carries the transport's own validation ping and ack. They
    // belong to the handshake, not to the game.
    if ((parsed as { type?: unknown }).type === 'mug_mesh_validation') {
      return;
    }
    if (this.driver === null) {
      // The channels open before the start barrier, so a peer that started first
      // can speak before this peer has booted. Hold it rather than lose it.
      if (this.held.length < 4096) {
        this.held.push([peerHandle, text]);
      }
      return;
    }
    this.driver.receive(peerHandle, text);
  }

  attach(driver: MeshDriver): void {
    this.driver = driver;
    for (const [peer, text] of this.held.splice(0)) {
      driver.receive(peer, text);
    }
  }
}

/**
 * Build the executor that plays a mesh episode over the transport's handoff.
 *
 * It is a plain object over injected seams -- the runtime, the clock, the sleep,
 * the key set, the hasher, the renderer -- so a test drives a whole episode in
 * one process with no browser, no Pyodide, and no WebRTC.
 */
export function createMeshExecutor(config: MeshExecutorConfig): {
  onMeshReady(bootstrap: P2PBootstrap, handoff?: P2PMeshHandoff): void;
  onMeshStart(start: P2PMeshStart, handoff: P2PMeshHandoff): void;
  onMeshAbort(abort: P2PMeshAbort): void;
  onMeshFinish(finish: P2PMeshFinish): void;
  onConnectionLost(socketEpoch: number): void;
  finished: Promise<MeshRunResult>;
} {
  const inbox = new Inbox();
  let bound: ReadonlyMap<string, MeshDataChannel> | null = null;
  let running = false;
  // How many times this peer rolled back and replayed. A poor connection is felt as
  // correction, so the finish line says how much of it there was -- which is a fact
  // about the participant's run, and the only way anything outside the engine can
  // tell a mesh that corrected itself from one that never had to.
  let corrections = 0;
  let resolveRun: (result: MeshRunResult) => void;
  let rejectRun: (error: Error) => void;
  const finished = new Promise<MeshRunResult>((resolve, reject) => {
    resolveRun = resolve;
    rejectRun = reject;
  });
  // A room that aborts before it starts must not leave the promise pending; a
  // caller awaiting it would wait for a room that no longer exists.
  finished.catch(() => undefined);

  const status = (text: string): void => config.onStatus?.(text);

  function bind(handoff: P2PMeshHandoff): void {
    if (bound !== null) {
      return;
    }
    bound = handoff.channels;
    for (const [peerHandle, channel] of handoff.channels) {
      channel.onMessage((data) => inbox.accept(peerHandle, data));
    }
  }

  async function play(start: P2PMeshStart, handoff: P2PMeshHandoff): Promise<void> {
    const { pressed, hash, now, sleep } = config;
    bind(handoff);
    status('starting the peer game...');
    const { manifest, runtime } = await config.prepare();
    const driver = runtime.boot(meshRunConfig(manifest, handoff.bootstrap, start));
    inbox.attach(driver);

    const channels = [...handoff.channels.values()];
    const interval = manifest.fps > 0 ? 1000 / manifest.fps : 0;
    const catchUp = config.maxCatchUpFrames ?? 8;
    const grace = config.barrierGraceFrames ?? Math.max(120, manifest.max_steps);
    let due = now();

    for (let frame = 0; ; frame += 1) {
      if (frame > manifest.max_steps + grace) {
        throw new Error('the peer mesh never closed its episode barrier');
      }
      for (const text of driver.tick(actionFor(manifest, pressed))) {
        for (const channel of channels) {
          channel.send(text);
        }
      }
      const surface = config.renderer?.();
      if (surface) {
        const commands = driver.commands();
        if (commands !== null) {
          surface.draw({ commands });
        }
      }
      if (driver.readyToFinalize()) {
        break;
      }
      due += interval;
      const wait = due - now();
      if (wait > 0) {
        await sleep(wait);
        continue;
      }
      if (now() - due > catchUp * interval) {
        // The tab was hidden or the machine stalled. Run the frames the loop can
        // and drop the rest of the backlog rather than freeze the page catching
        // up: the peers predict this peer's input and roll back, which is what
        // the engine is for.
        due = now();
      }
      // Yield even when this frame is already due. A loop that never returned to
      // the event loop would starve the very thing it is waiting for: the data
      // channels deliver the peers' inputs, and nothing arrives while this frame
      // holds the thread. A study with an uncapped frame rate would otherwise run
      // its whole episode alone and then report that the barrier never closed.
      await sleep(0);
    }
    driver.finalize();

    const hashes = driver.frameHashes();
    const digest = await computeDigest(hashes, hash);
    const frameCount = driver.frameCount();
    await handoff.complete(digest, frameCount);
    let submitted = false;
    if (handoff.bootstrap.local_peer_handle === handoff.bootstrap.capture_owner_handle) {
      const payload = driver.capturePayloadJson();
      const payloadDigest: Digest = {
        algorithm: 'sha-256',
        hex: await hash(new TextEncoder().encode(payload)),
      };
      submitted = await handoff.submitCapture(digest, frameCount, payload, payloadDigest);
    }
    status('waiting for the other players...');
    const result: MeshRunResult = {
      trajectoryDigest: digest,
      frameCount,
      submittedCapture: submitted,
      rollbackCount: driver.rollbackCount(),
    };
    corrections = result.rollbackCount;
    config.onFinished?.(result);
    resolveRun(result);
  }

  function fail(error: Error): void {
    config.onError?.(error.message);
    rejectRun(error);
  }

  return {
    onMeshReady: (_bootstrap: P2PBootstrap, handoff?: P2PMeshHandoff): void => {
      // The channels are bound before this peer reports itself ready, so every
      // peer is listening before the server can release the start barrier.
      if (handoff !== undefined) {
        bind(handoff);
      }
      status('peer mesh ready');
    },
    onMeshStart: (start: P2PMeshStart, handoff: P2PMeshHandoff): void => {
      if (running) {
        return;
      }
      running = true;
      void play(start, handoff).catch((error: unknown) =>
        fail(error instanceof Error ? error : new Error(String(error))),
      );
    },
    onMeshAbort: (abort: P2PMeshAbort): void => {
      status('the peer game stopped: ' + abort.reason);
      rejectRun(new Error('the peer mesh aborted: ' + abort.reason));
    },
    onMeshFinish: (finish: P2PMeshFinish): void => {
      status(
        'the peer game finished (' +
          String(finish.frame_count) +
          ' frames, ' +
          String(corrections) +
          ' corrections)',
      );
    },
    onConnectionLost: (): void => {
      rejectRun(new Error('the connection to the server was lost'));
    },
    finished,
  };
}

// -- the Pyodide runtime -------------------------------------------------------

interface PyProxy {
  toJs(options?: { create_proxies?: boolean }): unknown;
}
interface PyodideInterface {
  loadPackage(name: string): Promise<void>;
  pyimport(name: string): { install(requirement: string): Promise<void> };
  runPythonAsync(code: string): Promise<unknown>;
  globals: { get(name: string): unknown };
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
 * Boot Pyodide and load the shipped runtime, the study bundle, and the glue.
 *
 * This is the slow part, so it runs while the participant is on the forms. It
 * matters more here than for a single-player browser game: the peers cross a
 * start barrier together, so a browser that booted late would hold up its whole
 * room.
 */
export async function preloadMeshRuntime(
  manifest: MeshManifest,
  options: { onStatus?: (text: string) => void } = {},
): Promise<MeshRuntime> {
  const onStatus = options.onStatus;
  onStatus?.('loading the python runtime...');
  const pyodide = await loadPyodideRuntime();
  if (manifest.requires.length > 0) {
    await pyodide.loadPackage('micropip');
    const micropip = pyodide.pyimport('micropip');
    for (const requirement of manifest.requires) {
      onStatus?.('installing ' + requirement + '...');
      await micropip.install(requirement);
    }
  }
  // The prelude supplies the few platform names the shipped modules import, then
  // each module runs under its own name, then the study's environment, then the
  // glue that binds them.
  await pyodide.runPythonAsync(manifest.prelude_source);
  const install = pyodide.globals.get('_mug_install_module') as (
    name: string,
    source: string,
  ) => unknown;
  for (const module of manifest.runtime_modules) {
    install(module.name, module.source);
  }
  await pyodide.runPythonAsync(manifest.source_bundle);
  await pyodide.runPythonAsync(DRIVER_GLUE);
  onStatus?.('the peer game is ready');

  const call = <T>(name: string): T => pyodide.globals.get(name) as T;
  return {
    boot(runConfigJson: string): MeshDriver {
      call<(config: string) => void>('_mug_mesh_boot')(runConfigJson);
      return {
        receive: call<(remote: string, text: string) => void>('_mug_mesh_receive'),
        tick: (action: number): string[] =>
          call<(action: number) => PyProxy>('_mug_mesh_tick')(action).toJs({
            create_proxies: false,
          }) as string[],
        readyToFinalize: call<() => boolean>('_mug_mesh_ready'),
        finalize: call<() => void>('_mug_mesh_finalize'),
        frameHashes: (): string[] =>
          call<() => PyProxy>('_mug_mesh_hashes')().toJs({
            create_proxies: false,
          }) as string[],
        frameCount: call<() => number>('_mug_mesh_frames'),
        capturePayloadJson: call<() => string>('_mug_mesh_payload'),
        commands: (): SurfaceCommand[] | null => {
          const value = call<() => PyProxy | null>('_mug_mesh_commands')();
          return value === null
            ? null
            : (value.toJs({ create_proxies: false }) as SurfaceCommand[]);
        },
        rollbackCount: call<() => number>('_mug_mesh_rollbacks'),
      };
    },
  };
}
