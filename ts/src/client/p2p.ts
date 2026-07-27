/** Own one browser WebRTC mesh, its generation fence, and its teardown. */

import {
  P2PBootstrap,
  P2PSignal,
  P2PSignalAck,
  P2PSignalDelivery,
  SignalKind,
} from './p2pWire.js';
import { p2pSchema, signalPayloadJson } from './p2pOutbound.js';
import {
  MeshDataChannel,
  MeshPeerConnection,
  PeerConnectionFactory,
  RtcJsonObject,
  parseRtcSignalPayload,
} from './p2pRtc.js';
import {
  acceptValidationMessage,
  ChannelValidation,
  channelValidation,
  startChannelValidation,
} from './p2pValidation.js';

type JsonObject = RtcJsonObject;
export type MeshTimer = (handler: () => void, delayMillis: number) => unknown;

export interface PeerMeshConfig {
  bootstrap: P2PBootstrap;
  socketEpoch: number;
  createPeerConnection: PeerConnectionFactory;
  sendSignal(frame: { type: 'p2p_signal'; signal: P2PSignal }, socketEpoch: number): Promise<boolean>;
  nextRequestId(): string;
  setTimer: MeshTimer;
  clearTimer(handle: unknown): void;
  onFailure(error: Error): void;
}

interface PeerLeg {
  peerHandle: string;
  role: 'offerer' | 'answerer';
  connection: MeshPeerConnection;
  channel: MeshDataChannel | null;
  localDescriptionSent: boolean;
  remoteDescriptionSet: boolean;
  descriptionReceived: boolean;
  endOfCandidatesSent: boolean;
  pendingLocal: Array<{ kind: SignalKind; payload?: JsonObject }>;
  pendingRemote: Array<JsonObject | null>;
  validation: ChannelValidation;
  validated: boolean;
}

export class PeerMesh {
  private readonly legs = new Map<string, PeerLeg>();
  private readonly pendingRequests = new Set<string>();
  private readonly readyPromise: Promise<ReadonlyMap<string, MeshDataChannel>>;
  private resolveReady!: (channels: ReadonlyMap<string, MeshDataChannel>) => void;
  private rejectReady!: (error: Error) => void;
  private timeout: unknown = null;
  private started = false;
  private settled = false;
  private closed = false;

  constructor(private readonly config: PeerMeshConfig) {
    this.readyPromise = new Promise((resolve, reject) => {
      this.resolveReady = resolve;
      this.rejectReady = reject;
    });
  }

  /** Open and validate every server-assigned pairwise channel. */
  open(): Promise<ReadonlyMap<string, MeshDataChannel>> {
    if (this.started) {
      return this.readyPromise;
    }
    this.started = true;
    try {
      for (const peer of this.config.bootstrap.peers) {
        this.createLeg(peer.peer_handle, peer.role);
        if (this.closed) {
          return this.readyPromise;
        }
      }
      this.timeout = this.config.setTimer(
        () => this.fail(new Error('P2P mesh validation timed out')),
        this.config.bootstrap.validation_timeout_ms,
      );
      for (const leg of this.legs.values()) {
        if (leg.role === 'offerer') {
          void this.offer(leg).catch((error: unknown) => this.fail(asError(error)));
        }
      }
    } catch (error) {
      this.fail(asError(error));
    }
    return this.readyPromise;
  }

  /** Apply one authenticated server-stamped relay delivery. */
  async receiveSignal(signal: P2PSignalDelivery, socketEpoch: number): Promise<void> {
    if (!this.isCurrent(signal.room_handle, signal.negotiation_generation, socketEpoch)) {
      this.fail(new Error('stale P2P signal delivery'));
      return;
    }
    const leg = this.legs.get(signal.source_peer_handle);
    if (leg === undefined || this.closed) {
      this.fail(new Error('P2P signal came from an unknown peer'));
      return;
    }
    try {
      if (signal.signal_kind === 'offer') {
        await this.receiveOffer(leg, parseRtcSignalPayload(signal));
      } else if (signal.signal_kind === 'answer') {
        await this.receiveAnswer(leg, parseRtcSignalPayload(signal));
      } else if (signal.signal_kind === 'candidate') {
        await this.receiveCandidate(leg, parseRtcSignalPayload(signal));
      } else {
        await this.receiveCandidate(leg, null);
      }
    } catch (error) {
      this.fail(asError(error));
    }
  }

  /** Observe relay acceptance; a rejected signal invalidates the whole mesh. */
  receiveSignalAck(ack: P2PSignalAck, socketEpoch: number): void {
    if (socketEpoch !== this.config.socketEpoch || this.closed) {
      return;
    }
    if (!this.pendingRequests.delete(ack.request_id)) {
      return;
    }
    if (ack.status === 'rejected') {
      this.fail(new Error('P2P signal rejected: ' + ack.error_code));
    }
  }

  /** Close every partial or open leg. Safe to call more than once. */
  close(reason: Error = new Error('P2P mesh closed')): void {
    if (this.closed) {
      return;
    }
    const rejectPending = this.started && !this.settled;
    this.settled = true;
    this.closed = true;
    if (this.timeout !== null) {
      this.config.clearTimer(this.timeout);
      this.timeout = null;
    }
    for (const leg of this.legs.values()) {
      leg.channel?.close();
      leg.connection.close();
    }
    this.config.createPeerConnection.release?.();
    this.pendingRequests.clear();
    if (rejectPending) {
      this.rejectReady(reason);
    }
  }

  private createLeg(peerHandle: string, role: 'offerer' | 'answerer'): void {
    const connection = this.config.createPeerConnection(peerHandle, this.config.bootstrap);
    const leg: PeerLeg = {
      peerHandle,
      role,
      connection,
      channel: null,
      localDescriptionSent: false,
      remoteDescriptionSet: false,
      descriptionReceived: false,
      endOfCandidatesSent: false,
      pendingLocal: [],
      pendingRemote: [],
      validation: channelValidation(),
      validated: false,
    };
    this.legs.set(peerHandle, leg);
    connection.onIceCandidate((candidate) => this.localCandidate(leg, candidate));
    connection.onConnectionStateChange(() => this.connectionChanged(leg));
    connection.onDataChannel((channel) => {
      if (leg.role !== 'answerer') {
        this.fail(new Error('offerer received an unexpected data channel'));
      } else {
        this.bindChannel(leg, channel);
      }
    });
    this.connectionChanged(leg);
    if (role === 'offerer') {
      const channel = connection.createDataChannel(
        this.config.bootstrap.data_channel.label,
        { ordered: false, maxRetransmits: 0 },
      );
      this.bindChannel(leg, channel);
    }
  }

  private bindChannel(leg: PeerLeg, channel: MeshDataChannel): void {
    if (this.closed) {
      channel.close();
      return;
    }
    if (leg.channel !== null) {
      channel.close();
      this.fail(new Error('peer created more than one mesh data channel'));
      return;
    }
    if (
      channel.label !== this.config.bootstrap.data_channel.label ||
      channel.ordered !== false ||
      channel.maxRetransmits !== 0
    ) {
      channel.close();
      this.fail(new Error('peer created a non-conforming mesh data channel'));
      return;
    }
    leg.channel = channel;
    channel.onOpen(() => this.channelOpened(leg));
    channel.onMessage((data) => this.channelMessage(leg, data));
    channel.onClose(() => this.channelFailed(leg, 'closed'));
    channel.onError(() => this.channelFailed(leg, 'failed'));
    if (channel.readyState === 'open') {
      this.channelOpened(leg);
    } else if (channel.readyState === 'closed') {
      this.channelFailed(leg, 'closed');
    }
  }

  private async offer(leg: PeerLeg): Promise<void> {
    const description = await leg.connection.createOffer();
    await leg.connection.setLocalDescription(description);
    await this.send(leg, 'offer', description);
    leg.localDescriptionSent = true;
    await this.flushLocal(leg);
  }

  private async receiveOffer(leg: PeerLeg, description: JsonObject): Promise<void> {
    if (leg.role !== 'answerer' || leg.descriptionReceived) {
      throw new Error('unexpected P2P offer');
    }
    leg.descriptionReceived = true;
    await this.setRemote(leg, description);
    const answer = await leg.connection.createAnswer();
    await leg.connection.setLocalDescription(answer);
    await this.send(leg, 'answer', answer);
    leg.localDescriptionSent = true;
    await this.flushLocal(leg);
  }

  private async receiveAnswer(leg: PeerLeg, description: JsonObject): Promise<void> {
    if (leg.role !== 'offerer' || leg.descriptionReceived) {
      throw new Error('unexpected P2P answer');
    }
    leg.descriptionReceived = true;
    await this.setRemote(leg, description);
  }

  private async setRemote(leg: PeerLeg, description: JsonObject): Promise<void> {
    await leg.connection.setRemoteDescription(description);
    leg.remoteDescriptionSet = true;
    const pending = leg.pendingRemote.splice(0);
    for (const candidate of pending) {
      await leg.connection.addIceCandidate(candidate);
    }
  }

  private async receiveCandidate(leg: PeerLeg, candidate: JsonObject | null): Promise<void> {
    if (leg.remoteDescriptionSet) {
      await leg.connection.addIceCandidate(candidate);
    } else {
      if (leg.pendingRemote.length >= 64) {
        throw new Error('too many remote ICE candidates arrived before SDP');
      }
      leg.pendingRemote.push(candidate);
    }
  }

  private localCandidate(leg: PeerLeg, candidate: JsonObject | null): void {
    if (this.closed || (candidate === null && leg.endOfCandidatesSent)) {
      return;
    }
    const item = candidate === null
      ? { kind: 'end_of_candidates' as const }
      : { kind: 'candidate' as const, payload: candidate };
    if (candidate === null) {
      leg.endOfCandidatesSent = true;
    }
    if (!leg.localDescriptionSent) {
      if (leg.pendingLocal.length >= 64) {
        this.fail(new Error('local RTC emitted too many ICE candidates before SDP'));
        return;
      }
      leg.pendingLocal.push(item);
      return;
    }
    void this.send(leg, item.kind, item.payload).catch((error: unknown) =>
      this.fail(asError(error)),
    );
  }

  private async flushLocal(leg: PeerLeg): Promise<void> {
    const pending = leg.pendingLocal.splice(0);
    for (const item of pending) {
      await this.send(leg, item.kind, item.payload);
    }
  }

  private async send(leg: PeerLeg, kind: SignalKind, payload?: JsonObject): Promise<void> {
    if (this.closed) {
      throw new Error('P2P mesh is closed');
    }
    const requestId = this.config.nextRequestId();
    if (this.pendingRequests.size >= 256) {
      throw new Error('too many unacknowledged P2P signals');
    }
    const payloadJson = signalPayloadJson(kind, payload);
    const signal: P2PSignal = {
      schema: p2pSchema(this.config.bootstrap, 'mug.api-09.p2p-signal'),
      request_id: requestId,
      room_handle: this.config.bootstrap.room_handle,
      target_peer_handle: leg.peerHandle,
      negotiation_generation: this.config.bootstrap.negotiation_generation,
      signal_kind: kind,
      ...(payloadJson === undefined ? {} : { payload_json: payloadJson }),
    };
    this.pendingRequests.add(requestId);
    const sent = await this.config.sendSignal(
      { type: 'p2p_signal', signal },
      this.config.socketEpoch,
    );
    if (!sent) {
      this.pendingRequests.delete(requestId);
      throw new Error('stale socket refused a P2P signal');
    }
  }

  private channelOpened(leg: PeerLeg): void {
    if (this.closed || leg.channel === null) {
      return;
    }
    startChannelValidation(
      leg.validation,
      this.config.bootstrap.room_handle,
      this.config.bootstrap.negotiation_generation,
      this.config.nextRequestId(),
      (data) => leg.channel?.send(data),
    );
  }

  private channelMessage(leg: PeerLeg, data: unknown): void {
    if (this.closed) {
      return;
    }
    if (leg.validated) {
      return;
    }
    if (typeof data !== 'string') {
      this.fail(new Error('P2P channel validation requires text frames'));
      return;
    }
    const result = acceptValidationMessage(
      leg.validation,
      data,
      this.config.bootstrap.room_handle,
      this.config.bootstrap.negotiation_generation,
      (reply) => leg.channel?.send(reply),
    );
    if (result === 'exceeded') {
      this.fail(new Error('P2P channel validation traffic exceeded its bound'));
      return;
    }
    if (result === 'complete') {
      leg.validated = true;
      this.finishIfReady();
    }
  }

  private finishIfReady(): void {
    if (this.settled || [...this.legs.values()].some((leg) => !leg.validated)) {
      return;
    }
    const channels = new Map<string, MeshDataChannel>();
    for (const [peer, leg] of this.legs) {
      if (leg.channel === null || leg.channel.readyState !== 'open') {
        return;
      }
      channels.set(peer, leg.channel);
    }
    this.settled = true;
    if (this.timeout !== null) {
      this.config.clearTimer(this.timeout);
      this.timeout = null;
    }
    this.resolveReady(channels);
  }

  private connectionChanged(leg: PeerLeg): void {
    if (['closed', 'failed', 'disconnected'].includes(leg.connection.connectionState)) {
      this.fail(new Error('P2P connection ' + leg.connection.connectionState));
    }
  }

  private channelFailed(leg: PeerLeg, state: string): void {
    if (!this.closed) {
      this.fail(new Error('P2P channel to ' + leg.peerHandle + ' ' + state));
    }
  }

  private isCurrent(room: string, generation: number, epoch: number): boolean {
    return (
      room === this.config.bootstrap.room_handle &&
      generation === this.config.bootstrap.negotiation_generation &&
      epoch === this.config.socketEpoch
    );
  }

  private fail(error: Error): void {
    if (this.closed) {
      return;
    }
    this.close(error);
    this.config.onFailure(error);
  }
}

function asError(value: unknown): Error {
  return value instanceof Error ? value : new Error(String(value));
}
