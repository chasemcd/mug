/** In-process RTC fakes for the browser P2P conformance runner. */

import { PeerMesh } from '../src/client/p2p.js';
import {
  MeshDataChannel,
  MeshPeerConnection,
  PeerConnectionFactory,
  RtcJsonObject,
} from '../src/client/p2pRtc.js';
import { P2PBootstrap, P2PSignal } from '../src/client/p2pWire.js';

type Handler = () => void;

export function publicHandle(letter: string): string {
  return 'handle_' + letter.repeat(21) + 'A';
}

const BUNDLE_DIGEST = {
  algorithm: 'sha-256' as const,
  hex: 'ec6d3f0019480421a8cdc9ce8db2f2e88f2398e0daf0c7773ced3841ba435029',
};

export function bootstrap(local: string, members: readonly string[]): P2PBootstrap {
  const peers = members
    .filter((peer) => peer !== local)
    .map((peer) => ({
      peer_handle: peer,
      role: local < peer ? 'offerer' as const : 'answerer' as const,
    }));
  return {
    schema: {
      name: 'mug.api-09.p2p-mesh-bootstrap',
      version: 0,
      digest: BUNDLE_DIGEST,
    },
    room_handle: publicHandle('R'),
    negotiation_generation: 1,
    local_peer_handle: local,
    capture_owner_handle: members[0]!,
    peers,
    data_channel: { label: 'mug-mesh-data', ordered: false, max_retransmits: 0 },
    validation_timeout_ms: 1_000,
    ice_grant_handle: publicHandle('I'),
    ice_endpoint: '/api/p2p/ice',
    ice_expires_at: '2026-08-02T12:10:00.000000Z',
  };
}

export class FakeDataChannel implements MeshDataChannel {
  readyState = 'connecting';
  readonly sent: string[] = [];
  private other: FakeDataChannel | null = null;
  private readonly openHandlers: Handler[] = [];
  private readonly messageHandlers: Array<(data: unknown) => void> = [];
  private readonly closeHandlers: Handler[] = [];
  private readonly errorHandlers: Handler[] = [];

  constructor(
    readonly label: string,
    readonly ordered: boolean,
    readonly maxRetransmits: number | null,
    private readonly transmit: (delivery: () => void) => void,
  ) {}

  pair(other: FakeDataChannel): void {
    this.other = other;
  }

  send(data: string): void {
    if (this.readyState !== 'open' || this.other === null) {
      throw new Error('fake data channel is not open');
    }
    this.sent.push(data);
    const other = this.other;
    this.transmit(() => {
      for (const handler of other.messageHandlers) {
        handler(data);
      }
    });
  }

  close(): void {
    if (this.readyState === 'closed') {
      return;
    }
    this.readyState = 'closed';
    for (const handler of this.closeHandlers) {
      handler();
    }
  }

  onOpen(handler: Handler): void {
    this.openHandlers.push(handler);
  }

  onMessage(handler: (data: unknown) => void): void {
    this.messageHandlers.push(handler);
  }

  onClose(handler: Handler): void {
    this.closeHandlers.push(handler);
  }

  onError(handler: Handler): void {
    this.errorHandlers.push(handler);
  }

  markOpen(): void {
    this.readyState = 'open';
  }

  emitOpen(): void {
    for (const handler of this.openHandlers) {
      handler();
    }
  }

  fail(): void {
    for (const handler of this.errorHandlers) {
      handler();
    }
  }
}

export class FakeConnection implements MeshPeerConnection {
  connectionState = 'new';
  localDescription: RtcJsonObject | null = null;
  remoteDescription: RtcJsonObject | null = null;
  readonly remoteCandidates: Array<RtcJsonObject | null> = [];
  readonly operations: string[] = [];
  channelOptions: { ordered: false; maxRetransmits: 0 } | null = null;
  channel: FakeDataChannel | null = null;
  closeCalls = 0;
  private iceHandler: ((candidate: RtcJsonObject | null) => void) | null = null;
  private dataHandler: ((channel: MeshDataChannel) => void) | null = null;
  private stateHandler: Handler | null = null;

  constructor(readonly local: string, private readonly pair: FakePair) {}

  createDataChannel(
    label: string,
    options: { ordered: false; maxRetransmits: 0 },
  ): MeshDataChannel {
    this.channelOptions = options;
    return this.pair.createChannels(this, label, options);
  }

  async createOffer(): Promise<RtcJsonObject> {
    this.operations.push('create_offer');
    return { type: 'offer', sdp: 'offer:' + this.local };
  }

  async createAnswer(): Promise<RtcJsonObject> {
    this.operations.push('create_answer');
    return { type: 'answer', sdp: 'answer:' + this.local };
  }

  async setLocalDescription(description: RtcJsonObject): Promise<void> {
    this.operations.push('set_local_description');
    this.localDescription = description;
    this.iceHandler?.({ candidate: 'ice:' + this.local });
    this.iceHandler?.(null);
  }

  async setRemoteDescription(description: RtcJsonObject): Promise<void> {
    this.operations.push('set_remote_description');
    this.remoteDescription = description;
    this.pair.remoteDescriptionSet(this, description);
  }

  async addIceCandidate(candidate: RtcJsonObject | null): Promise<void> {
    if (this.remoteDescription === null) {
      throw new Error('ICE applied before the remote description');
    }
    this.operations.push(candidate === null ? 'add_end' : 'add_candidate');
    this.remoteCandidates.push(candidate);
    this.pair.maybeOpen();
  }

  close(): void {
    this.closeCalls += 1;
    if (this.connectionState === 'closed') {
      return;
    }
    this.connectionState = 'closed';
    this.channel?.close();
  }

  onIceCandidate(handler: (candidate: RtcJsonObject | null) => void): void {
    this.iceHandler = handler;
  }

  onDataChannel(handler: (channel: MeshDataChannel) => void): void {
    this.dataHandler = handler;
  }

  onConnectionStateChange(handler: Handler): void {
    this.stateHandler = handler;
  }

  receiveChannel(): void {
    if (this.channel === null) {
      throw new Error('answerer has no remote data channel');
    }
    this.dataHandler?.(this.channel);
  }

  connected(): void {
    this.connectionState = 'connected';
    this.stateHandler?.();
  }

  fail(): void {
    this.connectionState = 'failed';
    this.stateHandler?.();
  }
}

export class FakePair {
  private readonly connections = new Map<string, FakeConnection>();
  private channels: [FakeDataChannel, FakeDataChannel] | null = null;
  private opened = false;

  constructor(
    readonly first: string,
    readonly second: string,
    private readonly transmit: (delivery: () => void) => void,
  ) {}

  connection(local: string): FakeConnection {
    let connection = this.connections.get(local);
    if (connection === undefined) {
      connection = new FakeConnection(local, this);
      this.connections.set(local, connection);
      if (this.channels !== null) {
        connection.channel = local === this.first ? this.channels[0] : this.channels[1];
      }
    }
    return connection;
  }

  createChannels(
    owner: FakeConnection,
    label: string,
    options: { ordered: false; maxRetransmits: 0 },
  ): FakeDataChannel {
    if (this.channels !== null) {
      throw new Error('pair created two data channels');
    }
    const first = new FakeDataChannel(
      label, options.ordered, options.maxRetransmits, this.transmit,
    );
    const second = new FakeDataChannel(
      label, options.ordered, options.maxRetransmits, this.transmit,
    );
    first.pair(second);
    second.pair(first);
    this.channels = owner.local === this.first ? [first, second] : [second, first];
    for (const [local, connection] of this.connections) {
      connection.channel = local === this.first ? this.channels[0] : this.channels[1];
    }
    return owner.channel!;
  }

  remoteDescriptionSet(connection: FakeConnection, description: RtcJsonObject): void {
    if (description.type === 'offer') {
      connection.receiveChannel();
    }
    this.maybeOpen();
  }

  maybeOpen(): void {
    const first = this.connections.get(this.first);
    const second = this.connections.get(this.second);
    if (
      this.opened ||
      first?.remoteDescription === null ||
      second?.remoteDescription === null ||
      !first?.remoteCandidates.some((item) => item !== null) ||
      !second?.remoteCandidates.some((item) => item !== null) ||
      this.channels === null
    ) {
      return;
    }
    this.opened = true;
    first.connected();
    second.connected();
    this.channels[0].markOpen();
    this.channels[1].markOpen();
    this.channels[0].emitOpen();
    this.channels[1].emitOpen();
  }

  fail(local: string): void {
    this.connections.get(local)?.fail();
  }

  allConnections(): FakeConnection[] {
    return [...this.connections.values()];
  }
}

export class FakeRtcNetwork {
  readonly sent: Array<{ source: string; signal: P2PSignal }> = [];
  readonly pairs = new Map<string, FakePair>();
  private readonly meshes = new Map<string, { mesh: PeerMesh; epoch: number }>();
  private readonly heldMessages: Array<() => void> = [];

  constructor(readonly holdValidation = false) {}

  factory(local: string): PeerConnectionFactory {
    return (remote) => this.pair(local, remote).connection(local);
  }

  register(local: string, mesh: PeerMesh, epoch: number): void {
    this.meshes.set(local, { mesh, epoch });
  }

  async relay(
    source: string,
    frame: { type: 'p2p_signal'; signal: P2PSignal },
    epoch: number,
  ): Promise<boolean> {
    const current = this.meshes.get(source);
    if (current === undefined || current.epoch !== epoch) {
      return false;
    }
    this.sent.push({ source, signal: frame.signal });
    const target = this.meshes.get(frame.signal.target_peer_handle);
    if (target === undefined) {
      throw new Error('fake relay target is absent');
    }
    await target.mesh.receiveSignal({
      schema: {
        name: 'mug.api-09.p2p-signal-delivery',
        version: 0,
        digest: frame.signal.schema.digest,
      },
      room_handle: frame.signal.room_handle,
      source_peer_handle: source,
      negotiation_generation: frame.signal.negotiation_generation,
      signal_kind: frame.signal.signal_kind,
      ...(frame.signal.payload_json === undefined
        ? {}
        : { payload_json: frame.signal.payload_json }),
    }, target.epoch);
    current.mesh.receiveSignalAck({
      schema: {
        name: 'mug.api-09.p2p-signal-ack',
        version: 0,
        digest: frame.signal.schema.digest,
      },
      request_id: frame.signal.request_id,
      status: 'queued',
    }, epoch);
    return true;
  }

  releaseValidation(): void {
    while (this.heldMessages.length > 0) {
      this.heldMessages.shift()!();
    }
  }

  pair(first: string, second: string): FakePair {
    const members = [first, second].sort();
    const key = members.join(':');
    let pair = this.pairs.get(key);
    if (pair === undefined) {
      pair = new FakePair(members[0]!, members[1]!, (delivery) => {
        if (this.holdValidation) {
          this.heldMessages.push(delivery);
        } else {
          delivery();
        }
      });
      this.pairs.set(key, pair);
    }
    return pair;
  }
}

export class ManualTimers {
  private readonly callbacks: Handler[] = [];

  set = (handler: Handler): unknown => {
    this.callbacks.push(handler);
    return handler;
  };

  clear = (handle: unknown): void => {
    const index = this.callbacks.indexOf(handle as Handler);
    if (index >= 0) {
      this.callbacks.splice(index, 1);
    }
  };

  fire(): void {
    for (const callback of this.callbacks.splice(0)) {
      callback();
    }
  }
}
