/** Browser-free conformance for the authenticated WebRTC edge. */

/// <reference types="node" />

import { strict as assert } from 'assert';
import { createHash } from 'crypto';

import { Digest, HashBytes } from '../src/kernel/index.js';
import { PeerMesh } from '../src/client/p2p.js';
import {
  P2PControlPort,
  P2PEdge,
  P2PExecutor,
  P2PMeshHandoff,
} from '../src/client/p2pEdge.js';
import {
  captureSubmissionFrame,
  peerCompleteFrame,
  peerReadyFrame,
} from '../src/client/p2pOutbound.js';
import {
  fetchBrowserPeerConnectionFactory,
  PeerConnectionFactory,
} from '../src/client/p2pRtc.js';
import {
  parseP2PInboundFrame,
  P2PBootstrap,
  P2PInboundFrame,
  P2PMeshAbort,
  P2PMeshFinish,
  P2PMeshStart,
  P2POutboundFrame,
  P2PSignalDelivery,
} from '../src/client/p2pWire.js';
import {
  acceptValidationMessage,
  channelValidation,
} from '../src/client/p2pValidation.js';
import {
  createMeshExecutor,
  MeshDriver,
  MeshManifest,
  MeshRuntime,
} from '../src/client/p2pGame.js';
import {
  bootstrap,
  FakeRtcNetwork,
  ManualTimers,
  publicHandle,
} from './p2p_fakes.js';

const DIGEST: Digest = {
  algorithm: 'sha-256',
  hex: 'ec6d3f0019480421a8cdc9ce8db2f2e88f2398e0daf0c7773ced3841ba435029',
};
const nodeSha256: HashBytes = async (bytes) =>
  createHash('sha256').update(Buffer.from(bytes)).digest('hex');

let requestSequence = 1;

function nextRequestId(): string {
  const suffix = requestSequence.toString(16).padStart(12, '0');
  requestSequence += 1;
  return 'request_019b6000-0000-7000-8000-' + suffix;
}

function timers(): {
  setTimer: (handler: () => void, delay: number) => unknown;
  clearTimer: (handle: unknown) => void;
} {
  return {
    setTimer: (handler, delay) => setTimeout(handler, delay),
    clearTimer: (handle) => clearTimeout(handle as ReturnType<typeof setTimeout>),
  };
}

function makeMesh(
  local: string,
  members: readonly string[],
  network: FakeRtcNetwork,
  failures: Error[] = [],
  epoch = 1,
): PeerMesh {
  return new PeerMesh({
    bootstrap: bootstrap(local, members),
    socketEpoch: epoch,
    createPeerConnection: network.factory(local),
    sendSignal: (frame, currentEpoch) => network.relay(local, frame, currentEpoch),
    nextRequestId,
    ...timers(),
    onFailure: (error) => failures.push(error),
  });
}

async function turn(): Promise<void> {
  await new Promise<void>((resolve) => setTimeout(resolve, 0));
}

function signalDelivery(
  source: string,
  kind: P2PSignalDelivery['signal_kind'],
  payload?: object,
  generation = 1,
): P2PSignalDelivery {
  return {
    schema: {
      name: 'mug.api-09.p2p-signal-delivery',
      version: 0,
      digest: DIGEST,
    },
    room_handle: publicHandle('R'),
    source_peer_handle: source,
    negotiation_generation: generation,
    signal_kind: kind,
    ...(payload === undefined ? {} : { payload_json: JSON.stringify(payload) }),
  };
}

function testStrictWireParser(): void {
  const valid = { type: 'p2p_bootstrap', bootstrap: bootstrap(
    publicHandle('B'), [publicHandle('B'), publicHandle('C')],
  ) };
  assert.equal(parseP2PInboundFrame(valid).type, 'p2p_bootstrap');

  for (const field of ['name', 'version', 'digest'] as const) {
    const bad = JSON.parse(JSON.stringify(valid)) as typeof valid;
    if (field === 'name') bad.bootstrap.schema.name = 'mug.api-09.p2p-signal';
    if (field === 'version') bad.bootstrap.schema.version = 1;
    if (field === 'digest') bad.bootstrap.schema.digest.hex = '0'.repeat(64);
    assert.throws(() => parseP2PInboundFrame(bad), /schema/);
  }
  const stale = JSON.parse(JSON.stringify(valid)) as typeof valid;
  stale.bootstrap.validation_timeout_ms = 999;
  assert.throws(() => parseP2PInboundFrame(stale), /validation_timeout/);
  const invalidHandle = JSON.parse(JSON.stringify(valid)) as typeof valid;
  invalidHandle.bootstrap.room_handle = 'actor_private';
  assert.throws(() => parseP2PInboundFrame(invalidHandle), /public handle/);
  const extra = { ...valid, sender: 'actor_private' };
  assert.throws(() => parseP2PInboundFrame(extra), /unexpected/);
}

function testSignalAndBoundaryParserFailures(): void {
  const candidate = {
    type: 'p2p_signal_delivery',
    signal: signalDelivery(publicHandle('C'), 'candidate', {
      candidate: 'x'.repeat(4_097),
    }),
  };
  assert.throws(() => parseP2PInboundFrame(candidate), /4096/);
  const start = {
    type: 'p2p_mesh_start',
    start: meshStart(0),
  };
  assert.throws(() => parseP2PInboundFrame(start), /start_sequence/);
  assert.throws(
    () => parseP2PInboundFrame({ type: 'p2p_future_frame', value: {} }),
    /unknown/,
  );
}

async function testTwoPeerOrderingAndValidation(): Promise<void> {
  const members = [publicHandle('B'), publicHandle('C')];
  const network = new FakeRtcNetwork(true);
  const first = makeMesh(members[0]!, members, network);
  const second = makeMesh(members[1]!, members, network);
  network.register(members[0]!, first, 1);
  network.register(members[1]!, second, 1);
  let firstReady = false;
  const firstOpen = first.open().then((channels) => {
    firstReady = true;
    return channels;
  });
  const secondOpen = second.open();
  await turn();
  assert.equal(firstReady, false, 'an open RTC channel is not yet application-valid');
  network.releaseValidation();
  const [firstChannels, secondChannels] = await Promise.all([firstOpen, secondOpen]);
  assert.equal(firstChannels.size, 1);
  assert.equal(secondChannels.size, 1);

  for (const source of members) {
    const kinds = network.sent
      .filter((item) => item.source === source)
      .map((item) => item.signal.signal_kind);
    const description = source === members[0] ? 'offer' : 'answer';
    assert.ok(kinds.indexOf(description) < kinds.indexOf('candidate'));
    assert.ok(kinds.indexOf('candidate') < kinds.indexOf('end_of_candidates'));
  }
  for (const item of network.sent) {
    assert.equal('sender' in item.signal, false);
    assert.equal('source_peer_handle' in item.signal, false);
  }
}

async function testThreePeerFullMesh(): Promise<void> {
  const members = [publicHandle('B'), publicHandle('C'), publicHandle('D')];
  const network = new FakeRtcNetwork();
  const meshes = members.map((local) => makeMesh(local, members, network));
  meshes.forEach((mesh, index) => network.register(members[index]!, mesh, 1));
  const channels = await Promise.all(meshes.map((mesh) => mesh.open()));
  assert.deepEqual(channels.map((item) => item.size), [2, 2, 2]);
  assert.equal(network.pairs.size, 3);
  for (const pair of network.pairs.values()) {
    for (const connection of pair.allConnections()) {
      if (connection.channelOptions !== null) {
        assert.deepEqual(connection.channelOptions, {
          ordered: false,
          maxRetransmits: 0,
        });
      }
    }
  }
}

async function testRemoteCandidateBuffering(): Promise<void> {
  const members = [publicHandle('B'), publicHandle('C')];
  const network = new FakeRtcNetwork();
  const pair = network.pair(members[0]!, members[1]!);
  pair.connection(members[0]!).createDataChannel(
    'mug-mesh-data', { ordered: false, maxRetransmits: 0 },
  );
  const localConnection = pair.connection(members[1]!);
  const manual = new ManualTimers();
  const mesh = new PeerMesh({
    bootstrap: bootstrap(members[1]!, members),
    socketEpoch: 4,
    createPeerConnection: () => localConnection,
    sendSignal: async () => true,
    nextRequestId,
    setTimer: manual.set,
    clearTimer: manual.clear,
    onFailure: () => {},
  });
  const opening = mesh.open();
  void opening.catch(() => {});
  await mesh.receiveSignal(signalDelivery(
    members[0]!, 'candidate', { candidate: 'early' },
  ), 4);
  await mesh.receiveSignal(signalDelivery(
    members[0]!, 'offer', { type: 'offer', sdp: 'v=0' },
  ), 4);
  assert.ok(
    localConnection.operations.indexOf('set_remote_description') <
    localConnection.operations.indexOf('add_candidate'),
  );
  mesh.close();
  await assert.rejects(opening, /closed/);
}

async function testFailureTimeoutAndStaleEpoch(): Promise<void> {
  const members = [publicHandle('B'), publicHandle('C')];
  const network = new FakeRtcNetwork(true);
  const failures: Error[] = [];
  const first = makeMesh(members[0]!, members, network, failures);
  const second = makeMesh(members[1]!, members, network);
  network.register(members[0]!, first, 1);
  network.register(members[1]!, second, 1);
  const firstOpen = first.open();
  void second.open().catch(() => {});
  await turn();
  network.pair(members[0]!, members[1]!).fail(members[0]!);
  await assert.rejects(firstOpen, /failed/);
  assert.equal(failures.length, 1);
  second.close();

  // Each later case needs its own network: the case above failed that pair, and
  // a mesh over an already-failed connection rejects before its timer can fire.
  const manual = new ManualTimers();
  const timeoutMesh = meshWithManualTimer(members, new FakeRtcNetwork(), manual, 8);
  const timed = timeoutMesh.open();
  manual.fire();
  await assert.rejects(timed, /timed out/);

  const staleMesh = meshWithManualTimer(
    members, new FakeRtcNetwork(), new ManualTimers(), 9,
  );
  const stale = staleMesh.open();
  await staleMesh.receiveSignal(signalDelivery(
    members[1]!, 'candidate', { candidate: 'old' },
  ), 8);
  await assert.rejects(stale, /stale/);
}

function meshWithManualTimer(
  members: readonly string[],
  network: FakeRtcNetwork,
  manual: ManualTimers,
  epoch: number,
): PeerMesh {
  return new PeerMesh({
    bootstrap: bootstrap(members[0]!, members),
    socketEpoch: epoch,
    createPeerConnection: network.factory(members[0]!),
    sendSignal: async () => true,
    nextRequestId,
    setTimer: manual.set,
    clearTimer: manual.clear,
    onFailure: () => {},
  });
}

function testValidationAndOutboundBounds(): void {
  const state = channelValidation();
  assert.equal(
    acceptValidationMessage(
      state, 'x'.repeat(1_025), publicHandle('R'), 1, () => {},
    ),
    'exceeded',
  );
  const mesh = bootstrap(
    publicHandle('B'), [publicHandle('B'), publicHandle('C')],
  );
  assert.deepEqual(
    peerReadyFrame(mesh, [publicHandle('C')]).type,
    'p2p_peer_ready',
  );
  assert.equal(peerCompleteFrame(mesh, DIGEST, 3).type, 'p2p_peer_complete');
  assert.equal(
    captureSubmissionFrame(mesh, DIGEST, 3, '{}', DIGEST).type,
    'p2p_capture_submission',
  );
  assert.throws(
    () => captureSubmissionFrame(mesh, DIGEST, 3, 'x'.repeat(1_048_577), DIGEST),
    /1048576/,
  );
}

async function testIceGrantRedemption(): Promise<void> {
  const mesh = bootstrap(
    publicHandle('B'), [publicHandle('B'), publicHandle('C')],
  );
  let request: { endpoint: string; init: { body: string; credentials: string } } | null = null;
  await fetchBrowserPeerConnectionFactory(mesh, async (endpoint, init) => {
    request = { endpoint, init };
    return {
      ok: true,
      status: 200,
      headers: { get: () => 'private, no-store' },
      json: async () => ({
        iceServers: [{
          urls: ['turn:turn.example.test'],
          username: 'short-lived',
          credential: 'secret',
        }],
        iceTransportPolicy: 'relay',
      }),
    };
  });
  assert.equal(request!.endpoint, '/api/p2p/ice');
  assert.equal(request!.init.credentials, 'same-origin');
  const body = JSON.parse(request!.init.body) as Record<string, unknown>;
  assert.equal(
    (body.schema as { name: string }).name,
    'mug.api-09.p2p-ice-grant-request',
  );
  await assert.rejects(
    fetchBrowserPeerConnectionFactory(mesh, async () => ({
      ok: true,
      status: 200,
      headers: { get: () => null },
      json: async () => ({ iceServers: [], iceTransportPolicy: 'all' }),
    })),
    /no-store/,
  );
}

function meshStart(sequence = 1): P2PMeshStart {
  return {
    schema: { name: 'mug.api-09.p2p-mesh-start', version: 0, digest: DIGEST },
    room_handle: publicHandle('R'),
    negotiation_generation: 1,
    seed: 7,
    start_sequence: sequence,
    capture_owner_handle: publicHandle('B'),
  };
}

function meshAbort(): P2PMeshAbort {
  return {
    schema: { name: 'mug.api-09.p2p-mesh-abort', version: 0, digest: DIGEST },
    room_handle: publicHandle('R'),
    negotiation_generation: 1,
    reason: 'peer_disconnected',
    disposition: 'repool',
  };
}

function meshFinish(): P2PMeshFinish {
  return {
    schema: { name: 'mug.api-09.p2p-mesh-finish', version: 0, digest: DIGEST },
    room_handle: publicHandle('R'),
    negotiation_generation: 1,
    trajectory_digest: DIGEST,
    frame_count: 3,
    capture_receipt: publicHandle('F'),
  };
}

interface EdgeProbe {
  ready: number;
  starts: number;
  aborts: number;
  finishes: number;
  lost: number;
  handoff: P2PMeshHandoff | null;
  readyHandoff: P2PMeshHandoff | null;
}

function executor(probe: EdgeProbe): P2PExecutor {
  return {
    onMeshReady: (_bootstrap, handoff) => {
      probe.ready += 1;
      probe.readyHandoff = handoff;
    },
    onMeshStart: (_start, handoff) => {
      probe.starts += 1;
      probe.handoff = handoff;
    },
    onMeshAbort: () => { probe.aborts += 1; },
    onMeshFinish: () => { probe.finishes += 1; },
    onConnectionLost: () => { probe.lost += 1; },
  };
}

function emptyProbe(): EdgeProbe {
  return {
    ready: 0, starts: 0, aborts: 0, finishes: 0, lost: 0,
    handoff: null, readyHandoff: null,
  };
}

async function testCoordinatorLifecycle(): Promise<void> {
  const members = [publicHandle('B'), publicHandle('C')];
  const network = new FakeRtcNetwork();
  const probes = [emptyProbe(), emptyProbe()];
  const outbound: P2POutboundFrame[][] = [[], []];
  let edges: P2PEdge[] = [];
  let ports: P2PControlPort[] = [];
  edges = members.map((local, index) => new P2PEdge({
    prepareConnections: async () => network.factory(local),
    nextRequestId,
    ...timers(),
    executor: executor(probes[index]!),
    onError: (message) => { throw new Error(message); },
  }));
  ports = members.map((_local, index) => edgePort(index, members, edges, outbound));
  edges.forEach((edge, index) => edge.receive({
    type: 'p2p_bootstrap',
    bootstrap: bootstrap(members[index]!, members),
  }, ports[index]!));
  await eventually(() => probes.every((probe) => probe.ready === 1));
  // The channels reach the executor at readiness, so every peer is listening
  // before the server can release the start barrier. What stays fenced is the
  // authority to report: the room has not started, so nothing may be claimed.
  assert.ok(probes[0]!.readyHandoff !== null, 'the channels reach the executor');
  assert.equal(probes[0]!.handoff, null, 'no room has started yet');
  await assert.rejects(
    probes[0]!.readyHandoff!.complete(DIGEST, 3),
    /has not started/,
  );
  edges.forEach((edge, index) => edge.receive(
    { type: 'p2p_mesh_start', start: meshStart() },
    ports[index]!,
  ));
  assert.ok(probes.every((probe) => probe.handoff !== null));
  await probes[0]!.handoff!.complete(DIGEST, 3);
  await probes[0]!.handoff!.submitCapture(DIGEST, 3, '{}', DIGEST);
  await assert.rejects(
    probes[1]!.handoff!.submitCapture(DIGEST, 3, '{}', DIGEST),
    /capture owner/,
  );
  edges[0]!.receive({ type: 'p2p_mesh_finish', finish: meshFinish() }, ports[0]!);
  edges[1]!.receive({ type: 'p2p_mesh_abort', abort: meshAbort() }, ports[1]!);
  assert.equal(probes[0]!.finishes, 1);
  assert.equal(probes[1]!.aborts, 1);
  assert.ok(outbound[0]!.some((frame) => frame.type === 'p2p_capture_submission'));
}

function edgePort(
  index: number,
  members: readonly string[],
  edges: readonly P2PEdge[],
  outbound: P2POutboundFrame[][],
): P2PControlPort {
  return {
    socketEpoch: 1,
    close: () => true,
    send: async (frame) => {
      outbound[index]!.push(frame);
      if (frame.type === 'p2p_signal') {
        const target = frame.signal.target_peer_handle === members[0] ? 0 : 1;
        edges[target]!.receive({
          type: 'p2p_signal_delivery',
          signal: signalDelivery(
            members[index]!, frame.signal.signal_kind,
            frame.signal.payload_json === undefined
              ? undefined
              : JSON.parse(frame.signal.payload_json) as object,
          ),
        }, edgePort(target, members, edges, outbound));
      }
      return true;
    },
  };
}

async function eventually(condition: () => boolean): Promise<void> {
  for (let attempt = 0; attempt < 100; attempt += 1) {
    if (condition()) return;
    await turn();
  }
  throw new Error('condition did not become true');
}


// -- the mesh executor ---------------------------------------------------------

// A stand-in for the Pyodide runtime. The rollback engine is Python and is proven
// there; what this scenario proves is the executor around it -- that every packet
// a driver emits reaches every peer's driver over the real channels, that the
// barrier ends the loop, and that the reported claim is derived from what the
// driver produced. So the fake driver is deliberately trivial.
function fakeRuntime(frames: number): MeshRuntime {
  return {
    boot(configJson: string): MeshDriver {
      const config = JSON.parse(configJson) as {
        local_actor_id: string;
        peer_actor_ids: string[];
        seed: number;
      };
      const heard: string[] = [];
      let frame = 0;
      return {
        receive: (remote, text) => { heard.push(remote + '|' + text); },
        tick: (action) => {
          frame += 1;
          return [JSON.stringify({
            kind: 'input',
            sender: config.local_actor_id,
            current_frame: frame,
            inputs: [[frame, action]],
          })];
        },
        readyToFinalize: () => frame >= frames && heard.length >= frames,
        finalize: () => {},
        frameHashes: () => Array.from(
          { length: frames },
          (_unused, index) => String(index).padStart(64, '0'),
        ),
        frameCount: () => frames,
        capturePayloadJson: () => JSON.stringify({ frames, seed: config.seed }),
        commands: () => null,
        rollbackCount: () => 0,
      };
    },
  };
}

function meshManifest(): MeshManifest {
  return {
    mode: 'peer',
    channel_key: 'conformance',
    source_bundle: '',
    requires: [],
    action_bindings: { ArrowUp: 1 },
    default_action: 0,
    fps: 0,
    countdown_seconds: 0,
    hooks: [],
    max_steps: 16,
    input_delay: 2,
    snapshot_interval: 5,
    redundancy: 10,
    prelude_source: '',
    runtime_modules: [],
  };
}

async function testMeshExecutorPlaysAnEpisode(): Promise<void> {
  const frames = 6;
  const members = [publicHandle('B'), publicHandle('C')];
  const network = new FakeRtcNetwork();
  const outbound: P2POutboundFrame[][] = [[], []];
  const runtime = fakeRuntime(frames);
  const executors = members.map(() => createMeshExecutor({
    prepare: async () => ({ manifest: meshManifest(), runtime }),
    pressed: new Set<string>(['ArrowUp']),
    hash: nodeSha256,
    // A clock that never advances is the hard case, not a convenience: every
    // frame is already due, so a loop that only yielded when it had time to wait
    // would never return to the event loop, no channel message would arrive, and
    // the barrier would never close. Pinning the clock makes that a failure here
    // rather than an intermittent one in a participant's browser.
    now: () => 0,
    sleep: () => new Promise((resolve) => setTimeout(resolve, 0)),
  }));
  const edges = members.map((local, index) => new P2PEdge({
    prepareConnections: async () => network.factory(local),
    nextRequestId,
    ...timers(),
    executor: executors[index]!,
    onError: (message) => { throw new Error(message); },
  }));
  const ports = members.map((_local, index) =>
    edgePort(index, members, edges, outbound));

  edges.forEach((edge, index) => edge.receive({
    type: 'p2p_bootstrap',
    bootstrap: bootstrap(members[index]!, members),
  }, ports[index]!));
  await eventually(() => outbound.every(
    (frames_) => frames_.some((frame) => frame.type === 'p2p_peer_ready'),
  ));
  edges.forEach((edge, index) => edge.receive(
    { type: 'p2p_mesh_start', start: meshStart() },
    ports[index]!,
  ));

  const results = await Promise.all(executors.map((one) => one.finished));

  // Both peers derived the identical trajectory identity from the same frames.
  assert.equal(results[0]!.trajectoryDigest.hex, results[1]!.trajectoryDigest.hex);
  assert.equal(results[0]!.frameCount, frames);
  // Every peer claims the run; only the designated owner submits the payload.
  assert.equal(
    outbound.filter((sent) =>
      sent.some((frame) => frame.type === 'p2p_peer_complete')).length,
    2,
  );
  assert.equal(
    outbound.filter((sent) =>
      sent.some((frame) => frame.type === 'p2p_capture_submission')).length,
    1,
  );
  assert.equal(
    results.filter((result) => result.submittedCapture).length,
    1,
  );
}

async function main(): Promise<void> {
  testStrictWireParser();
  testSignalAndBoundaryParserFailures();
  await testTwoPeerOrderingAndValidation();
  await testThreePeerFullMesh();
  await testRemoteCandidateBuffering();
  await testFailureTimeoutAndStaleEpoch();
  testValidationAndOutboundBounds();
  await testIceGrantRedemption();
  await testCoordinatorLifecycle();
  await testMeshExecutorPlaysAnEpisode();
  console.log('browser P2P conformance: 10 scenario(s) OK');
}

main().catch((error) => {
  console.error(error);
  process.exitCode = 1;
});
