/**
 * The participant client: the driver that ties the session, the activity
 * rendering, and the game together.
 *
 * It opens the realtime session, reports each delivered activity, collects form
 * answers and submits `flow.advance`, and, when the flow reaches the game, mounts
 * a canvas, captures the keyboard, and either draws the server's render packets
 * (server mode) or runs the environment in the browser through Pyodide and
 * reports the run over `game.capture` (browser mode). It reproduces the reference
 * JavaScript client, built on the kernel twin and the injected session.
 */

import { JsonValue } from '../kernel/index.js';
import { RenderPacket, Renderer, createRenderer } from './renderer.js';
import {
  Endpoint,
  KeyValueStore,
  ParticipantSession,
  Schedule,
  SocketFactory,
} from './session.js';
import { WireEnv } from './wire.js';
import {
  BrowserManifest,
  playBrowserEpisode,
  preloadBrowserGame,
  BrowserRuntime,
} from './browserGame.js';
import {
  Delivery,
  FormDelivery,
  ContentDelivery,
  GameDelivery,
  CompleteDelivery,
  renderComplete,
  renderContent,
  renderForm,
} from './ui.js';

/** A target for keyboard listeners; the browser `window` satisfies it. */
export interface KeyTarget {
  addEventListener(type: 'keydown' | 'keyup', handler: (event: KeyboardEvent) => void): void;
  removeEventListener(type: 'keydown' | 'keyup', handler: (event: KeyboardEvent) => void): void;
}

/** Everything the client needs, injected. */
export interface ClientConfig {
  app: HTMLElement;
  status: HTMLElement;
  keyTarget: KeyTarget;
  endpoint: Endpoint;
  connect: SocketFactory;
  store: KeyValueStore;
  schedule: Schedule;
  env: WireEnv;
}

function sleep(millis: number): Promise<void> {
  return new Promise((resolve) => setTimeout(resolve, millis));
}

export class ParticipantClient {
  private readonly session: ParticipantSession;
  private renderer: Renderer | null = null;
  private gameContainer: HTMLElement | null = null;
  private readonly pressed = new Set<string>();
  private inputMode: 'server' | 'browser' = 'server';
  private preloadPromise: Promise<BrowserRuntime> | null = null;

  private readonly onKeyDown = (event: KeyboardEvent): void => {
    if (event.key === 'ArrowLeft' || event.key === 'ArrowRight') {
      event.preventDefault();
    }
    if (!this.pressed.has(event.key)) {
      this.pressed.add(event.key);
      if (this.inputMode === 'server') {
        this.session.sendInput([...this.pressed]);
      }
    }
  };

  private readonly onKeyUp = (event: KeyboardEvent): void => {
    if (this.pressed.delete(event.key) && this.inputMode === 'server') {
      this.session.sendInput([...this.pressed]);
    }
  };

  constructor(private readonly config: ClientConfig) {
    this.session = new ParticipantSession({
      endpoint: config.endpoint,
      connect: config.connect,
      store: config.store,
      schedule: config.schedule,
      env: config.env,
      handlers: {
        onHandshake: (ack) => this.report('connected -- protocol ' + ack.protocol_version, true),
        onDelivery: (delivery) => this.render(delivery as unknown as Delivery),
        onRender: (packet) => this.renderer?.draw(packet as unknown as RenderPacket),
        onError: (message) => this.report('error: ' + message, false),
        onClose: () => {
          if (this.renderer) {
            this.stopGame();
          }
          this.report('disconnected -- retrying', false);
        },
      },
    });
  }

  /** Open the socket and run the flow. */
  start(): void {
    this.session.start();
  }

  private report(text: string, ok: boolean): void {
    this.config.status.textContent = text;
    this.config.status.classList.toggle('ok', ok);
  }

  private advance(answers: JsonValue): void {
    void this.session.sendAdvance(answers);
  }

  // --- delivery dispatch ---------------------------------------------------

  private render(delivery: Delivery): void {
    // A preload announcement starts the background download; it does not change
    // the visible activity, so the form stays on screen while packages arrive.
    if (delivery.kind === 'preload') {
      this.startPreload(delivery.manifest);
      return;
    }
    if (delivery.kind !== 'game' && this.renderer) {
      this.stopGame();
    }
    if (delivery.kind === 'form') {
      renderForm(this.config.app, delivery as FormDelivery, (answers) => this.advance(answers));
    } else if (delivery.kind === 'content') {
      renderContent(this.config.app, delivery as ContentDelivery, (answers) =>
        this.advance(answers),
      );
    } else if (delivery.kind === 'game' && (delivery as GameDelivery).mode === 'browser') {
      void this.startBrowserGame(delivery as GameDelivery);
    } else if (delivery.kind === 'game') {
      void this.startServerGame(delivery as GameDelivery);
    } else if (delivery.kind === 'complete') {
      this.renderComplete(delivery as CompleteDelivery);
    }
  }

  private renderComplete(delivery: CompleteDelivery): void {
    // The visit is finished; clear the resume token so a later visit starts fresh.
    this.session.clearResumeToken();
    renderComplete(this.config.app, delivery);
  }

  // --- game mode -----------------------------------------------------------

  private mountCanvas(): void {
    const app = this.config.app;
    app.innerHTML = '';
    const heading = document.createElement('p');
    heading.textContent = 'Use the left and right arrow keys to reach the flag.';
    app.appendChild(heading);
    const canvas = document.createElement('canvas');
    canvas.width = 600;
    canvas.height = 400;
    canvas.style.background = '#dfe7f5';
    canvas.style.border = '1px solid #333';
    canvas.style.display = 'block';
    // The container is the positioning context for the countdown overlay, so the
    // countdown sits on top of the canvas and never takes its own layout space.
    const container = document.createElement('div');
    container.style.position = 'relative';
    container.style.width = '600px';
    container.appendChild(canvas);
    app.appendChild(container);
    this.gameContainer = container;
    this.renderer = createRenderer(canvas);
    this.config.keyTarget.addEventListener('keydown', this.onKeyDown);
    this.config.keyTarget.addEventListener('keyup', this.onKeyUp);
  }

  // A pre-roll countdown after the participant continues, so the episode does not
  // start while they are still settling in. The server holds its stepping loop for
  // the same duration, so the count matches when the environment begins.
  private async countdown(seconds: number | undefined): Promise<void> {
    if (!seconds || seconds <= 0) {
      return;
    }
    const banner = document.createElement('div');
    Object.assign(banner.style, {
      position: 'absolute',
      inset: '0',
      display: 'flex',
      alignItems: 'center',
      justifyContent: 'center',
      fontSize: '3rem',
      fontWeight: 'bold',
      color: '#101010',
      backdropFilter: 'blur(6px)',
      webkitBackdropFilter: 'blur(6px)',
      pointerEvents: 'none',
    });
    (this.gameContainer ?? this.config.app).appendChild(banner);
    for (let n = seconds; n > 0; n--) {
      banner.textContent = String(n);
      await sleep(1000);
    }
    banner.remove();
  }

  private async startServerGame(delivery: GameDelivery): Promise<void> {
    this.inputMode = 'server';
    this.mountCanvas();
    await this.countdown(delivery.countdown);
  }

  // Begin downloading Pyodide and the packages as soon as the study announces the
  // bundle, so the download overlaps with the forms. The returned promise is what
  // the game start awaits, so the participant cannot reach a blank canvas.
  private startPreload(manifest: BrowserManifest): void {
    if (this.preloadPromise) {
      return;
    }
    this.preloadPromise = preloadBrowserGame(manifest, {
      onStatus: (text) => this.report(text, true),
    });
    this.preloadPromise.catch(() => this.report('failed to load the python runtime', false));
  }

  // Run the environment in the browser through Pyodide, then report the finished
  // run over `game.capture`. The server validates and commits it under a fence.
  private async startBrowserGame(delivery: GameDelivery): Promise<void> {
    this.inputMode = 'browser';
    this.mountCanvas();
    const manifest = delivery.manifest;
    if (!manifest) {
      this.report('the browser game is missing its manifest', false);
      return;
    }
    try {
      this.startPreload(manifest);
      this.report('preparing the environment...', true);
      const runtime = await this.preloadPromise!;
      await this.countdown(delivery.countdown);
      const run = await playBrowserEpisode(runtime, manifest, {
        renderer: this.renderer ?? undefined,
        pressed: this.pressed,
        hash: this.config.env.hash,
        onStatus: (text) => this.report(text, true),
      });
      // The action sequence rides alongside the episode, so the server can
      // re-execute the run under the same inputs and verify the state hashes.
      const episode = { transitions: run.transitions, boundary: run.boundary };
      const payload = { episode, actions: run.actions, generation: 1 };
      void this.session.sendCommand('game.capture', payload as unknown as JsonValue);
    } catch (error) {
      this.report('browser environment failed: ' + String(error), false);
    }
  }

  private stopGame(): void {
    this.config.keyTarget.removeEventListener('keydown', this.onKeyDown);
    this.config.keyTarget.removeEventListener('keyup', this.onKeyUp);
    this.pressed.clear();
    this.renderer = null;
  }
}
