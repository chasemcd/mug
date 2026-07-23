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
}

/** A stream position on an accepted command. */
export interface StreamPosition {
  stream_id: string;
  sequence: number;
}

/** The frames the driver reacts to. */
export interface SessionHandlers {
  onHandshake(ack: HandshakeAck): void;
  onDelivery(delivery: JsonValue): void;
  onRender(packet: JsonValue): void;
  onError(message: string): void;
  onClose(): void;
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
  ack?: { stream_position?: StreamPosition };
}

interface ErrorFrame {
  type: 'error';
  message?: string;
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
  | RenderFrame;

/** The realtime session over one server. Call `start` to open the first socket. */
export class ParticipantSession {
  private socket: Socket | null = null;
  private cursor = 0;

  constructor(private readonly config: SessionConfig) {}

  /** Open the socket and begin the session. */
  start(): void {
    this.connect();
  }

  /** Send a command on a channel with a payload (for example `flow.advance`). */
  async sendCommand(channelKey: string, payload: JsonValue): Promise<void> {
    const frame = await buildCommand(this.config.env, channelKey, payload);
    this.socket?.send(JSON.stringify(frame));
  }

  /** Advance the flow with the collected form answers. */
  async sendAdvance(answers: JsonValue): Promise<void> {
    await this.sendCommand('flow.advance', { answers });
  }

  /** Send the pressed keys to the server stepping loop. */
  sendInput(keys: string[]): void {
    this.socket?.send(JSON.stringify({ type: 'input', keys }));
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
    const socket = this.config.connect(this.buildUrl());
    this.socket = socket;
    socket.onMessage((data) => this.receive(data));
    socket.onClose(() => {
      this.config.handlers.onClose();
      const delay = this.config.reconnectMillis ?? 1000;
      this.config.schedule(() => this.connect(), delay);
    });
    socket.onError(() => socket.close());
  }

  private receive(data: string): void {
    const message = JSON.parse(data) as IncomingFrame;
    switch (message.type) {
      case 'handshake_ack': {
        this.cursor = message.resume_cursor ?? this.cursor;
        if (message.resume_token) {
          this.config.store.set(RESUME_TOKEN_KEY, message.resume_token);
        }
        this.config.handlers.onHandshake(message);
        break;
      }
      case 'delivery':
        this.config.handlers.onDelivery(message.delivery);
        break;
      case 'render':
        this.config.handlers.onRender(message.packet);
        break;
      case 'ack': {
        const position = message.ack?.stream_position;
        if (position) {
          this.cursor = Math.max(this.cursor, position.sequence);
        }
        break;
      }
      case 'error':
        this.config.handlers.onError(message.message ?? 'unknown error');
        break;
      default:
        break;
    }
  }
}
