/** Coordinate authenticated socket controls around one browser WebRTC mesh. */

import { Digest } from '../kernel/index.js';
import { PeerMesh } from './p2p.js';
import {
  captureSubmissionFrame,
  peerCompleteFrame,
  peerReadyFrame,
} from './p2pOutbound.js';
import { MeshDataChannel, PeerConnectionFactory } from './p2pRtc.js';
import {
  P2PBootstrap,
  P2PInboundFrame,
  P2PMeshAbort,
  P2PMeshFinish,
  P2PMeshStart,
  P2POutboundFrame,
  P2PSignalAck,
  P2PSignalDelivery,
} from './p2pWire.js';

export interface P2PControlPort {
  socketEpoch: number;
  send(frame: P2POutboundFrame): Promise<boolean>;
  close(): boolean;
}

export interface P2PMeshHandoff {
  bootstrap: P2PBootstrap;
  channels: ReadonlyMap<string, MeshDataChannel>;
  complete(trajectoryDigest: Digest, frameCount: number): Promise<boolean>;
  submitCapture(
    trajectoryDigest: Digest,
    frameCount: number,
    payloadJson: string,
    payloadDigest: Digest,
  ): Promise<boolean>;
}

export interface P2PExecutor {
  /**
   * Every channel is open and validated, and this peer is about to report itself
   * ready. The handoff is passed here as well as at the start, so an executor can
   * listen on the channels before the server releases the start barrier: a peer
   * that started first would otherwise speak to a peer that is not yet listening.
   */
  onMeshReady(bootstrap: P2PBootstrap, handoff: P2PMeshHandoff): void;
  onMeshStart(start: P2PMeshStart, handoff: P2PMeshHandoff): void;
  onMeshAbort(abort: P2PMeshAbort): void;
  onMeshFinish(finish: P2PMeshFinish): void;
  onConnectionLost(socketEpoch: number): void;
}

export interface P2PEdgeConfig {
  prepareConnections(bootstrap: P2PBootstrap): Promise<PeerConnectionFactory>;
  nextRequestId(): string;
  setTimer(handler: () => void, delayMillis: number): unknown;
  clearTimer(handle: unknown): void;
  /**
   * Build the executor for one room.
   *
   * One executor plays one episode: it binds that room's channels, runs its
   * frames, and settles one promise when the barrier closes. A study may hold
   * several game activities -- a practice round and then the real one -- and each
   * forms its own room over its own connections, so each gets its own executor.
   * An edge that reused one would bind the first room's channels forever and
   * ignore every start after the first.
   */
  newExecutor(): P2PExecutor;
  onError(message: string): void;
}

interface Attempt {
  bootstrap: P2PBootstrap;
  control: P2PControlPort;
  executor: P2PExecutor;
  mesh: PeerMesh | null;
  channels: ReadonlyMap<string, MeshDataChannel> | null;
  handoff: P2PMeshHandoff | null;
  pendingSignals: P2PSignalDelivery[];
  pendingAcks: P2PSignalAck[];
  started: boolean;
}

/** Own the current bootstrap attempt and fence every callback to its socket. */
export class P2PEdge {
  private attempt: Attempt | null = null;
  private stopped = false;

  constructor(private readonly config: P2PEdgeConfig) {}

  receive(frame: P2PInboundFrame, control: P2PControlPort): void {
    if (this.stopped) {
      return;
    }
    switch (frame.type) {
      case 'p2p_bootstrap':
        this.begin(frame.bootstrap, control);
        break;
      case 'p2p_signal_delivery':
        this.signal(frame.signal, control);
        break;
      case 'p2p_signal_ack':
        this.signalAck(frame.ack, control);
        break;
      case 'p2p_mesh_start':
        this.start(frame.start, control);
        break;
      case 'p2p_mesh_abort':
        this.abort(frame.abort, control);
        break;
      case 'p2p_mesh_finish':
        this.finish(frame.finish, control);
        break;
    }
  }

  disconnect(socketEpoch: number): void {
    const attempt = this.attempt;
    if (attempt === null || attempt.control.socketEpoch !== socketEpoch) {
      return;
    }
    attempt.mesh?.close();
    this.attempt = null;
    attempt.executor.onConnectionLost(socketEpoch);
  }

  stop(): void {
    if (this.stopped) {
      return;
    }
    this.stopped = true;
    this.attempt?.mesh?.close();
    this.attempt = null;
  }

  private begin(bootstrap: P2PBootstrap, control: P2PControlPort): void {
    this.attempt?.mesh?.close();
    const attempt: Attempt = {
      bootstrap,
      control,
      executor: this.config.newExecutor(),
      mesh: null,
      channels: null,
      handoff: null,
      pendingSignals: [],
      pendingAcks: [],
      started: false,
    };
    this.attempt = attempt;
    void this.prepare(attempt);
  }

  private async prepare(attempt: Attempt): Promise<void> {
    try {
      const factory = await this.config.prepareConnections(attempt.bootstrap);
      if (!this.isCurrent(attempt)) {
        factory.release?.();
        return;
      }
      const mesh = new PeerMesh({
        bootstrap: attempt.bootstrap,
        socketEpoch: attempt.control.socketEpoch,
        createPeerConnection: factory,
        sendSignal: (frame, epoch) =>
          epoch === attempt.control.socketEpoch
            ? attempt.control.send(frame)
            : Promise.resolve(false),
        nextRequestId: this.config.nextRequestId,
        setTimer: this.config.setTimer,
        clearTimer: this.config.clearTimer,
        onFailure: (error) => this.fail(attempt, error),
      });
      attempt.mesh = mesh;
      const opening = mesh.open();
      await this.drain(attempt);
      const channels = await opening;
      await this.ready(attempt, channels);
    } catch (error) {
      this.fail(attempt, asError(error));
    }
  }

  private async drain(attempt: Attempt): Promise<void> {
    if (attempt.mesh === null) {
      return;
    }
    for (const signal of attempt.pendingSignals.splice(0)) {
      await attempt.mesh.receiveSignal(signal, attempt.control.socketEpoch);
    }
    for (const ack of attempt.pendingAcks.splice(0)) {
      attempt.mesh.receiveSignalAck(ack, attempt.control.socketEpoch);
    }
  }

  private async ready(
    attempt: Attempt,
    channels: ReadonlyMap<string, MeshDataChannel>,
  ): Promise<void> {
    if (!this.isCurrent(attempt)) {
      attempt.mesh?.close();
      return;
    }
    attempt.channels = channels;
    const handoff = this.handoff(attempt, channels);
    attempt.handoff = handoff;
    // The executor takes the channels before this peer reports readiness, so by
    // the time any peer can start, every peer is already listening.
    attempt.executor.onMeshReady(attempt.bootstrap, handoff);
    const sent = await attempt.control.send(
      peerReadyFrame(attempt.bootstrap, [...channels.keys()]),
    );
    if (!sent || !this.isCurrent(attempt)) {
      this.fail(attempt, new Error('stale socket refused P2P readiness'));
      return;
    }
  }

  private handoff(
    attempt: Attempt,
    channels: ReadonlyMap<string, MeshDataChannel>,
  ): P2PMeshHandoff {
    return {
      bootstrap: attempt.bootstrap,
      channels,
      complete: (digest, frames) => {
        if (!attempt.started) {
          return Promise.reject(new Error('P2P mesh has not started'));
        }
        return this.sendCurrent(
          attempt,
          peerCompleteFrame(attempt.bootstrap, digest, frames),
        );
      },
      submitCapture: (digest, frames, payload, payloadDigest) => {
        if (!attempt.started) {
          return Promise.reject(new Error('P2P mesh has not started'));
        }
        if (
          attempt.bootstrap.local_peer_handle !==
          attempt.bootstrap.capture_owner_handle
        ) {
          return Promise.reject(new Error('only the capture owner may submit capture'));
        }
        return this.sendCurrent(
          attempt,
          captureSubmissionFrame(
            attempt.bootstrap, digest, frames, payload, payloadDigest,
          ),
        );
      },
    };
  }

  private signal(signal: P2PSignalDelivery, control: P2PControlPort): void {
    const attempt = this.currentFor(signal, control);
    if (attempt === null) {
      return;
    }
    if (attempt.mesh === null) {
      if (attempt.pendingSignals.length >= 64) {
        this.fail(attempt, new Error('too many P2P signals arrived before ICE setup'));
        return;
      }
      attempt.pendingSignals.push(signal);
    } else {
      void attempt.mesh.receiveSignal(signal, control.socketEpoch);
    }
  }

  private signalAck(ack: P2PSignalAck, control: P2PControlPort): void {
    const attempt = this.attempt;
    if (attempt === null || attempt.control.socketEpoch !== control.socketEpoch) {
      return;
    }
    if (attempt.mesh === null) {
      if (attempt.pendingAcks.length >= 64) {
        this.fail(attempt, new Error('too many P2P acknowledgments arrived before ICE setup'));
        return;
      }
      attempt.pendingAcks.push(ack);
    } else {
      attempt.mesh.receiveSignalAck(ack, control.socketEpoch);
    }
  }

  private start(start: P2PMeshStart, control: P2PControlPort): void {
    const attempt = this.currentFor(start, control);
    if (attempt === null || attempt.started) {
      return;
    }
    if (
      attempt.handoff === null ||
      start.capture_owner_handle !== attempt.bootstrap.capture_owner_handle
    ) {
      this.fail(attempt, new Error('P2P start arrived before validated readiness'));
      return;
    }
    attempt.started = true;
    attempt.executor.onMeshStart(start, attempt.handoff);
  }

  private abort(abort: P2PMeshAbort, control: P2PControlPort): void {
    const attempt = this.currentFor(abort, control);
    if (attempt === null) {
      return;
    }
    attempt.mesh?.close();
    this.attempt = null;
    attempt.executor.onMeshAbort(abort);
  }

  private finish(finish: P2PMeshFinish, control: P2PControlPort): void {
    const attempt = this.currentFor(finish, control);
    if (attempt === null || !attempt.started) {
      return;
    }
    attempt.mesh?.close();
    this.attempt = null;
    attempt.executor.onMeshFinish(finish);
  }

  private currentFor(
    boundary: { room_handle: string; negotiation_generation: number },
    control: P2PControlPort,
  ): Attempt | null {
    const attempt = this.attempt;
    if (
      attempt === null ||
      attempt.control.socketEpoch !== control.socketEpoch ||
      attempt.bootstrap.room_handle !== boundary.room_handle
    ) {
      return null;
    }
    if (
      attempt.bootstrap.negotiation_generation !==
      boundary.negotiation_generation
    ) {
      this.fail(attempt, new Error('stale P2P negotiation generation'));
      return null;
    }
    return attempt;
  }

  private sendCurrent(attempt: Attempt, frame: P2POutboundFrame): Promise<boolean> {
    return this.isCurrent(attempt)
      ? attempt.control.send(frame)
      : Promise.resolve(false);
  }

  private isCurrent(attempt: Attempt): boolean {
    return !this.stopped && this.attempt === attempt;
  }

  private fail(attempt: Attempt, error: Error): void {
    if (!this.isCurrent(attempt)) {
      return;
    }
    attempt.mesh?.close();
    this.attempt = null;
    attempt.control.close();
    attempt.executor.onConnectionLost(attempt.control.socketEpoch);
    this.config.onError(error.message);
  }
}

function asError(value: unknown): Error {
  return value instanceof Error ? value : new Error(String(value));
}
