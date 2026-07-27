/**
 * The realtime session: the websocket lifecycle and the resume protocol.
 *
 * It opens the socket, tracks the stream cursor, persists the signed resume
 * token, dispatches each incoming frame to the driver, and reconnects after a
 * drop -- carrying the last cursor and the stored token, so a reconnection
 * resumes the same visit where it stopped. It sends `flow.advance` and
 * `game.capture` commands and server-game input frames.
 *
 * Every environment dependency is injected: the socket factory, the key-value
 * store for the resume token, the reconnect scheduler, and the command minter's
 * clock, random source, and hasher. The browser passes real ones; a test passes
 * fakes and drives the whole protocol without a browser.
 */

import { JsonValue } from '../kernel/index.js';
import {
  isP2PInboundType,
  parseP2PInboundFrame,
  P2PInboundFrame,
  P2POutboundFrame,
} from './p2pWire.js';
import { AssetManifest } from './assets.js';
import { ConnectionQuality } from './quality.js';
import { buildCommand, WireEnv } from './wire.js';

const RESUME_TOKEN_KEY = 'mug_resume_token';

/** A minimal socket, so the real `WebSocket` and a test double share one shape. */
export interface Socket {
  send(data: string): void;
  close(): void;
  onMessage(handler: (data: string) => void): void;
  onOpen(handler: () => void): void;
  onClose(handler: () => void): void;
  onError(handler: () => void): void;
}

/** Open a socket to a fully built url. */
export type SocketFactory = (url: string) => Socket;

/** A small key-value store, so browser `localStorage` and a test map share a shape. */
export interface KeyValueStore {
  get(key: string): string | null;
  set(key: string, value: string): void;
  remove(key: string): void;
}

/** Run a callback after a delay (the reconnect backoff). */
export type Schedule = (callback: () => void, delayMillis: number) => void;

/** Where to reach the server and the launch ticket, if the entry link carried one. */
export interface Endpoint {
  /** The websocket origin, for example `ws://localhost:8000`. */
  wsBase: string;
  /** The launch ticket from the entry link, or null on an open study or a return. */
  ticket: string | null;
}

/** The handshake acknowledgement the server sends when the session opens. */
export interface HandshakeAck {
  type: 'handshake_ack';
  protocol_version: string;
  subject: string;
  resume_cursor: number;
  resume_token?: string;
  /** The deployment revision this connection is being served by, when gated. */
  deployment?: AcceptedDeployment;
  /** What the study asks this client to measure, when it declares a screen. */
  screening?: { sample_every_ms?: number };
  /** The pictures the study declared, each at the address of its own bytes. */
  assets?: AssetManifest;
}

/** The deployment revision a client states it accepted. */
export interface AcceptedDeployment {
  deployment_id: string;
  deployment_revision_id: string;
  revision_number: number;
}

/** A stream position on an accepted command. */
export interface StreamPosition {
  stream_id: string;
  sequence: number;
}

/** What the conversation is, for this participant: the channels they are in.
 *
 * A channel this participant is not in is absent from the list, because the
 * server never sends it. The screen can not hide what it was never told.
 */
export interface ChatRoomFrame {
  type: 'chat_room';
  channels: string[];
  seat: string;
}

/** One message the conversation carried, as the participant reads it. */
export interface ChatMessage {
  type: 'chat';
  message_id: string;
  author_actor_id: string;
  sequence: number;
  text: string;
  /** The channel the message belongs to, in a room that has more than one. */
  channel?: string;
  /** Set on a message restored after a reconnection: who wrote it. */
  author?: 'you' | 'them';
  /** True when this message is being redrawn rather than newly arriving. */
  restored?: boolean;
}

/** A model turn that was still running when this connection opened. */
export interface ChatPendingFrame {
  type: 'chat_pending';
  generation: number;
  prompt_message_id: string;
}

/** One axis a candidate elicitation asks about, beside "which one is better". */
export interface ChatAxisFrame {
  key: string;
  ask: string;
  /** `pair` is one answer over the two replies; `each` is one answer per reply. */
  scope: 'pair' | 'each';
  /** How far the scale goes: steps to each side for `pair`, positions for `each`. */
  points: number;
  low?: string | null;
  high?: string | null;
}

/** The candidate replies one turn is offering, in the order they are shown.
 *
 * Each reply is behind a blinded handle and nothing says which model wrote it,
 * because with two model seats the seat *is* the condition under test.
 */
export interface ChatCandidatesFrame {
  type: 'chat_candidates';
  assignment_id: string;
  prompt_message_id: string;
  channel: string;
  ask: string;
  ties: boolean;
  skippable: boolean;
  options: { handle: string; text: string }[];
  axes: ChatAxisFrame[];
}

/** The mount refused a choice: it named a reply the participant was not shown. */
export interface ChatCandidatesErrorFrame {
  type: 'chat_candidates_error';
  code: string;
  message: string;
}

/** The judgement was recorded, and the conversation goes on from the chosen reply. */
export interface ChatCandidatesAckFrame {
  type: 'chat_candidates_ack';
  response_id: string;
}

/** One axis answer: which reply it is about, and how much.
 *
 * `option` is a blinded handle and never a position, so a shuffled presentation
 * can not invert an axis. Leaving it unset is the midpoint that favours neither,
 * and the midpoint is the only answer whose value is zero.
 */
export interface ChatRating {
  axis: string;
  option?: string;
  value: number;
}

/** The options one comparison mount committed to, in the order it presents them. */
export interface ComparisonOptionsFrame {
  type: 'comparison';
  activity_key: string;
  ask: string;
  style: string;
  assignment_id: string;
  options: {
    handle: string;
    played?: number;
    summary?: { frames: number; reward: number };
    text?: string;
  }[];
}

/** The comparison mount refusing one answer, with the reason it gave. */
export interface ComparisonErrorFrame {
  type: 'comparison_error';
  code: string;
  message: string;
}

/** One between-rounds screen the game mount holds the next round for. */
export interface IntervalFrame {
  type: 'interval';
  markdown?: string;
  round: number;
  of: number;
}

/** The server's echo of one ping, carrying the client's own token back. */
export interface PongFrame {
  type: 'pong';
  token?: string;
}

/** What the study's screen decided about this connection, short of ending it. */
export interface ScreeningFrame {
  type: 'screening';
  action: string;
  reason?: string;
}

/** The durable acknowledgment that one comparison answer is recorded. */
export interface ComparisonAckFrame {
  type: 'comparison_ack';
  receipt_id: string;
}

/** The frames the driver reacts to. */
export interface SessionHandlers {
  onHandshake(ack: HandshakeAck): void;
  onDelivery(delivery: JsonValue): void;
  onRender(packet: JsonValue): void;
  onP2P(frame: P2PInboundFrame, socketEpoch: number): void;
  /** One message another author posted to the conversation the session is in. */
  onChat(message: ChatMessage): void;
  /** The blinded options of the comparison activity the session is at. */
  onComparisonOptions(frame: ComparisonOptionsFrame): void;
  /** The comparison mount refused one answer, so the participant may answer again. */
  onComparisonError(frame: ComparisonErrorFrame): void;
  /** One comparison answer is durably recorded. */
  onComparisonAck(frame: ComparisonAckFrame): void;
  /** The study's screen has something to say about this connection. */
  onScreening?(frame: ScreeningFrame): void;
  /** One round of a game activity ended and another is waiting to start. */
  onInterval?(frame: IntervalFrame): void;
  /** A model turn was already running when this connection opened. */
  onChatPending?(frame: ChatPendingFrame): void;
  /** The turn is asking the participant to choose between candidate replies. */
  onChatCandidates?(frame: ChatCandidatesFrame): void;
  onChatCandidatesError?(frame: ChatCandidatesErrorFrame): void;
  onChatCandidatesAck?(frame: ChatCandidatesAckFrame): void;
  /** The channels this participant is in, named by the mount that formed them. */
  onChatRoom?(frame: ChatRoomFrame): void;
  onError(message: string): void;
  onClose(socketEpoch: number): void;
}

/** Everything a session needs, injected. */
export interface SessionConfig {
  endpoint: Endpoint;
  connect: SocketFactory;
  store: KeyValueStore;
  schedule: Schedule;
  env: WireEnv;
  handlers: SessionHandlers;
  /** The reconnect backoff, in milliseconds. Defaults to one second. */
  reconnectMillis?: number;
}

interface AckFrame {
  type: 'ack';
  ack?: { stream_position?: StreamPosition; command_id?: string };
}

interface ErrorFrame {
  type: 'error';
  message?: string;
  // Which command was refused, so a state write can put back what it replaced.
  command_id?: string;
}

interface DeliveryFrame {
  type: 'delivery';
  delivery: JsonValue;
}

interface RenderFrame {
  type: 'render';
  packet: JsonValue;
}

type IncomingFrame =
  | HandshakeAck
  | AckFrame
  | ErrorFrame
  | DeliveryFrame
  | RenderFrame
  | ChatMessage
  | ComparisonOptionsFrame
  | ComparisonErrorFrame
  | ComparisonAckFrame
  | PongFrame
  | ScreeningFrame
  | IntervalFrame
  | ChatPendingFrame
  | ChatCandidatesFrame
  | ChatCandidatesErrorFrame
  | ChatCandidatesAckFrame
  | ChatRoomFrame;

/** The realtime session over one server. Call `start` to open the first socket. */
export class ParticipantSession {
  private socket: Socket | null = null;
  private cursor = 0;
  // What this participant carries between activities, as the server last
  // delivered it, and the writes not yet heard about so a refusal can be undone.
  private readonly carried = new Map<string, { value: JsonValue; revision: number }>();
  private readonly inFlightState = new Map<
    string,
    { namespace: string; value: JsonValue | null; revision: number }
  >();
  private socketEpoch = 0;
  private sendTail: Promise<void> = Promise.resolve();
  private stopped = false;
  private readonly quality: ConnectionQuality;

  constructor(private readonly config: SessionConfig) {
    this.quality = new ConnectionQuality(
      {
        now: config.env.now,
        randomBytes: config.env.randomBytes,
        schedule: config.schedule,
      },
      {
        ping: (token) => void this.send(JSON.stringify({ type: 'ping', token })),
        measurement: (samples) =>
          void this.send(JSON.stringify({ type: 'measurement', samples })),
      },
    );
  }

  /** Add time the page spent in the background, for the next measurement. */
  reportHidden(millis: number): void {
    this.quality.reportHidden(millis);
  }

  /** Open the socket and begin the session. */
  start(): void {
    if (this.stopped) {
      throw new Error('a stopped participant session cannot restart');
    }
    this.connect();
  }

  /** End the session and suppress its reconnect loop. Safe to call repeatedly. */
  stop(): void {
    if (this.stopped) {
      return;
    }
    this.stopped = true;
    this.quality.stop();
    this.socketEpoch += 1;
    const socket = this.socket;
    this.socket = null;
    socket?.close();
  }

  /** Send a command on a channel with a payload (for example `flow.advance`). */
  async sendCommand(channelKey: string, payload: JsonValue): Promise<string> {
    const frame = await buildCommand(this.config.env, channelKey, payload);
    await this.send(JSON.stringify(frame));
    return frame.command.command_id;
  }

  /**
   * Read one namespace of what this participant carries between activities.
   *
   * It is what the server last delivered, so a page reads it without asking for
   * it first. A namespace nobody has written yet reads as null.
   */
  readState(namespace: string): JsonValue | null {
    return this.carried.get(namespace)?.value ?? null;
  }

  /** Return the revision one namespace is held at, which a write must name. */
  stateRevision(namespace: string): number {
    return this.carried.get(namespace)?.revision ?? 0;
  }

  /**
   * Write one namespace against the revision that was read.
   *
   * The held revision moves forward at once, so a second write in the same
   * activity names what the first produced. A write the server refuses -- an
   * undeclared namespace, one the study keeps to itself, or a stale revision --
   * puts back what it replaced, so a page that lost a race is not left one
   * revision ahead and failing every write after it.
   */
  async writeState(namespace: string, value: JsonValue): Promise<void> {
    const held = this.carried.get(namespace);
    const revision = held?.revision ?? 0;
    this.carried.set(namespace, { value, revision: revision + 1 });
    const sent = await this.sendCommand('state.set', { namespace, value, revision });
    this.inFlightState.set(sent, {
      namespace,
      value: held?.value ?? null,
      revision,
    });
  }

  private rememberState(delivered: Record<string, JsonValue> | undefined): void {
    if (!delivered) return;
    for (const [namespace, value] of Object.entries(delivered)) {
      const held = this.carried.get(namespace);
      this.carried.set(namespace, { value, revision: held?.revision ?? 0 });
    }
  }

  private stateRefused(commandId: string | undefined): boolean {
    if (commandId === undefined) return false;
    const sent = this.inFlightState.get(commandId);
    if (!sent) return false;
    this.inFlightState.delete(commandId);
    this.carried.set(sent.namespace, {
      value: sent.value,
      revision: sent.revision,
    });
    return true;
  }

  /** Advance the flow with the collected form answers. */
  async sendAdvance(answers: JsonValue): Promise<void> {
    await this.sendCommand('flow.advance', { answers });
  }

  /** Send the pressed keys to the server stepping loop. */
  sendInput(keys: string[]): void {
    void this.send(JSON.stringify({ type: 'input', keys }));
  }

  /**
   * Post one message to the conversation the session is in.
   *
   * A chat frame is not a command: the mount that owns the socket for the chat
   * activity records the message itself, on the participant's behalf, and answers
   * with the reply. So there is no receipt to await here, exactly as an input
   * frame has none.
   */
  sendChat(text: string, channel?: string): void {
    const frame: Record<string, unknown> = { type: 'chat', text };
    if (channel !== undefined) {
      frame['channel'] = channel;
    }
    void this.send(JSON.stringify(frame));
  }

  /** Choose one of the candidate replies, and let the conversation go on from it.
   *
   * `choice` is the blinded handle of the reply the thread keeps. `verdict` says
   * what the participant meant by it: a tie or a both-bad verdict still names a
   * choice, because the conversation has to continue with one of them whatever
   * the judgement was.
   */
  sendChatCandidateChoice(
    choice: string,
    options: {
      verdict?: 'choice' | 'tie' | 'both-bad';
      ratings?: ChatRating[];
      responseTimeMs?: number | undefined;
      idempotencyKey?: string | undefined;
    } = {},
  ): void {
    const frame: Record<string, unknown> = {
      type: 'chat_candidate_choice',
      choice,
      verdict: options.verdict ?? 'choice',
    };
    if (options.ratings?.length) {
      frame['ratings'] = options.ratings;
    }
    if (options.responseTimeMs !== undefined) {
      frame['response_time_ms'] = Math.max(0, Math.round(options.responseTimeMs));
    }
    if (options.idempotencyKey !== undefined) {
      frame['idempotency_key'] = options.idempotencyKey;
    }
    void this.send(JSON.stringify(frame));
  }

  /** Pass on this turn's choice; the thread goes on with the reply shown first. */
  sendChatCandidateSkip(): void {
    void this.send(JSON.stringify({ type: 'chat_candidate_skip' }));
  }

  /** Go on to the next round of a game activity, after the interval screen. */
  sendIntervalDone(): void {
    void this.send(JSON.stringify({ type: 'interval_done' }));
  }

  /** Leave the conversation, so the flow moves on to the next activity. */
  sendChatEnd(): void {
    void this.send(JSON.stringify({ type: 'chat_end' }));
  }

  /**
   * Answer the comparison the session is at, naming the option by its handle.
   *
   * The key is the participant's own idempotency key and the caller keeps it for
   * the whole answer: a retry under the same key replays to the first receipt, so
   * a receipt lost to a dropped connection never costs a second recorded choice.
   */
  sendComparisonResponse(handle: string, idempotencyKey: string): void {
    void this.send(
      JSON.stringify({
        type: 'comparison_response',
        choice: handle,
        idempotency_key: idempotencyKey,
      }),
    );
  }

  /**
   * Send one ephemeral P2P control only on the socket that created its callback.
   *
   * `false` means a reconnect or stop fenced the caller before the send reached
   * the socket.
   */
  sendP2P(frame: P2POutboundFrame, socketEpoch: number): Promise<boolean> {
    return this.send(JSON.stringify(frame), socketEpoch);
  }

  /** Close only the current socket for a failed P2P attempt. */
  closeP2PSocket(socketEpoch: number): boolean {
    const socket = this.socket;
    if (socket === null || socketEpoch !== this.socketEpoch) {
      return false;
    }
    socket.close();
    return true;
  }

  /** Forget the stored resume token, so a later visit starts fresh. */
  clearResumeToken(): void {
    this.config.store.remove(RESUME_TOKEN_KEY);
  }

  private buildUrl(): string {
    const { endpoint, store } = this.config;
    const token = store.get(RESUME_TOKEN_KEY);
    const resume = token ? '&resume_token=' + encodeURIComponent(token) : '';
    const launch = endpoint.ticket
      ? '&ticket=' + encodeURIComponent(endpoint.ticket)
      : '';
    return endpoint.wsBase + '/ws?resume_from=' + this.cursor + resume + launch;
  }

  private connect(): void {
    if (this.stopped) {
      return;
    }
    const socket = this.config.connect(this.buildUrl());
    const epoch = this.socketEpoch + 1;
    this.socketEpoch = epoch;
    this.socket = socket;
    this.sendTail = Promise.resolve();
    socket.onMessage((data) => {
      if (this.isCurrent(socket, epoch)) {
        this.receive(data, socket, epoch);
      }
    });
    socket.onClose(() => {
      if (!this.isCurrent(socket, epoch)) {
        return;
      }
      this.socket = null;
      this.quality.stop();
      this.config.handlers.onClose(epoch);
      if (this.stopped) {
        return;
      }
      const delay = this.config.reconnectMillis ?? 1000;
      this.config.schedule(() => this.connect(), delay);
    });
    socket.onError(() => {
      if (this.isCurrent(socket, epoch)) {
        socket.close();
      }
    });
  }

  private receive(data: string, socket: Socket, epoch: number): void {
    let decoded: unknown;
    try {
      decoded = JSON.parse(data);
    } catch {
      this.rejectWire(socket, 'the server sent invalid JSON');
      return;
    }
    if (isP2PInboundType(decoded)) {
      try {
        this.config.handlers.onP2P(parseP2PInboundFrame(decoded), epoch);
      } catch (error) {
        this.rejectWire(socket, 'invalid P2P frame: ' + String(error));
      }
      return;
    }
    if (decoded === null || typeof decoded !== 'object' || Array.isArray(decoded)) {
      this.rejectWire(socket, 'the server sent a non-object frame');
      return;
    }
    const message = decoded as IncomingFrame;
    switch (message.type) {
      case 'handshake_ack': {
        this.cursor = message.resume_cursor ?? this.cursor;
        if (message.resume_token) {
          this.config.store.set(RESUME_TOKEN_KEY, message.resume_token);
        }
        // Pin the deployment revision this build accepted. A client made for a
        // revision the server no longer serves is refused rather than left to
        // run on against a study it was not built for.
        if (message.deployment) {
          void this.send(
            JSON.stringify({
              type: 'client_handshake',
              accepted_deployment: message.deployment,
            }),
          );
        }
        // A screening study says how often to measure; a study that declares no
        // screen says nothing, and this client then sends no sample at all.
        if (message.screening) {
          this.quality.start(message.screening.sample_every_ms ?? 10000);
        }
        this.config.handlers.onHandshake(message);
        break;
      }
      case 'pong':
        this.quality.onPong(message.token ?? '');
        break;
      case 'screening':
        this.config.handlers.onScreening?.(message);
        break;
      case 'interval':
        this.config.handlers.onInterval?.(message);
        break;
      case 'chat_pending':
        this.config.handlers.onChatPending?.(message);
        break;
      case 'chat_candidates':
        this.config.handlers.onChatCandidates?.(message);
        break;
      case 'chat_candidates_error':
        this.config.handlers.onChatCandidatesError?.(message);
        break;
      case 'chat_candidates_ack':
        this.config.handlers.onChatCandidatesAck?.(message);
        break;
      case 'chat_room':
        this.config.handlers.onChatRoom?.(message);
        break;
      case 'delivery':
        // What the participant carries travels with every step, so a page reads
        // it without asking for it first.
        this.rememberState(
          (message.delivery as { state?: Record<string, JsonValue> } | undefined)
            ?.state,
        );
        this.config.handlers.onDelivery(message.delivery);
        break;
      case 'render':
        this.config.handlers.onRender(message.packet);
        break;
      case 'chat':
        this.config.handlers.onChat(message);
        break;
      case 'comparison':
        this.config.handlers.onComparisonOptions(message);
        break;
      case 'comparison_error':
        this.config.handlers.onComparisonError(message);
        break;
      case 'comparison_ack':
        this.config.handlers.onComparisonAck(message);
        break;
      case 'ack': {
        const position = message.ack?.stream_position;
        if (position) {
          this.cursor = Math.max(this.cursor, position.sequence);
        }
        if (message.ack?.command_id) {
          this.inFlightState.delete(message.ack.command_id);
        }
        break;
      }
      case 'error':
        if (!this.stateRefused(message.command_id)) {
          this.config.handlers.onError(message.message ?? 'unknown error');
        }
        break;
      default:
        this.rejectWire(socket, 'the server sent an unknown frame');
    }
  }

  private send(data: string, expectedEpoch?: number): Promise<boolean> {
    const socket = this.socket;
    const epoch = this.socketEpoch;
    if (
      socket === null ||
      this.stopped ||
      (expectedEpoch !== undefined && expectedEpoch !== epoch)
    ) {
      return Promise.resolve(false);
    }
    const operation = this.sendTail.then(() => {
      if (
        !this.isCurrent(socket, epoch) ||
        (expectedEpoch !== undefined && expectedEpoch !== epoch)
      ) {
        return false;
      }
      socket.send(data);
      return true;
    });
    this.sendTail = operation.then(
      () => undefined,
      () => undefined,
    );
    return operation;
  }

  private isCurrent(socket: Socket, epoch: number): boolean {
    return !this.stopped && this.socket === socket && this.socketEpoch === epoch;
  }

  private rejectWire(socket: Socket, message: string): void {
    this.config.handlers.onError(message);
    socket.close();
  }
}
