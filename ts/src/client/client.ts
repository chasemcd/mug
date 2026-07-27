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
import { P2PEdge, P2PEdgeConfig, P2PExecutor } from './p2pEdge.js';
import {
  MeshManifest,
  MeshRuntime,
  MeshSession,
  createMeshExecutor,
  preloadMeshRuntime,
} from './p2pGame.js';
import { AssetManifest, DecodeAsset, LoadedAssets } from './assets.js';
import { RenderPacket, Renderer, createRenderer } from './renderer.js';
import {
  Endpoint,
  KeyValueStore,
  ParticipantSession,
  Schedule,
  SocketFactory,
} from './session.js';
import { WireEnv, idempotencyKey } from './wire.js';
import {
  BrowserManifest,
  playBrowserEpisode,
  preloadBrowserGame,
  BrowserRuntime,
} from './browserGame.js';
import {
  ChatScreen,
  ComparisonDelivery,
  ComparisonScreen,
  Delivery,
  FormDelivery,
  ContentDelivery,
  GameDelivery,
  Panes,
  CompleteDelivery,
  renderChat,
  renderPanes,
  renderComparison,
  renderComplete,
  renderInterval,
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
  /**
   * Mount the authenticated browser mesh edge when this deployment offers P2P.
   *
   * The transport is configured here; the executor is not. The client builds
   * that itself, because playing the game is the client's job and the transport
   * only hands it open channels.
   */
  p2p?: Omit<P2PEdgeConfig, 'executor'> | undefined;
  /**
   * Turn one declared asset into something a canvas can draw.
   *
   * The browser passes a decoder over `fetch`; a client with none loads no
   * pictures, which is right for a study that declares none.
   */
  decodeAsset?: DecodeAsset | undefined;
}

function sleep(millis: number): Promise<void> {
  return new Promise((resolve) => setTimeout(resolve, millis));
}

export class ParticipantClient {
  private readonly session: ParticipantSession;
  private readonly p2pEdge: P2PEdge | null;
  private renderer: Renderer | null = null;
  private gameContainer: HTMLElement | null = null;
  private readonly pressed = new Set<string>();
  // The two panes of a composed activity, or null when the activity is one screen.
  private panes: Panes | null = null;
  private inputMode: 'server' | 'browser' = 'server';
  private preloadPromise: Promise<BrowserRuntime> | null = null;
  private meshManifest: MeshManifest | null = null;
  private meshPreload: Promise<MeshRuntime> | null = null;
  private chat: ChatScreen | null = null;
  // The channels this participant is in. A channel they are not in never reaches
  // the client, so this is the whole of what their screen can show.
  private chatChannels: string[] = [];
  private chatSeat: string | undefined = undefined;
  // The idempotency key of the elicitation on screen, minted when it arrives.
  private candidateKey: string | undefined = undefined;
  private comparison: ComparisonScreen | null = null;
  // The key of the answer in flight. It is minted once and kept, so a retry under
  // it replays rather than records a second choice.
  private comparisonKey: string | null = null;

  // True while the participant is typing, so the game does not also read the keys:
  // the arrow keys move the caret, and steering with them at the same time is how a
  // message ends up written into the environment.
  private typing(): boolean {
    const active = document.activeElement;
    return (
      active !== null &&
      (active.tagName === 'INPUT' || active.tagName === 'TEXTAREA')
    );
  }

  // Let go of every held key when the keyboard leaves the game. Without this, a key
  // held as the participant clicks the message box stays down for the rest of the
  // conversation, and the car drives itself while they type.
  private releaseKeys(): void {
    if (this.pressed.size === 0) {
      return;
    }
    this.pressed.clear();
    if (this.inputMode === 'server') {
      this.session.sendInput([...this.pressed]);
    }
  }

  private readonly onKeyDown = (event: KeyboardEvent): void => {
    if (this.typing()) {
      return;
    }
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
    if (this.typing()) {
      return;
    }
    if (this.pressed.delete(event.key) && this.inputMode === 'server') {
      this.session.sendInput([...this.pressed]);
    }
  };

  private readonly assets = new LoadedAssets();

  constructor(private readonly config: ClientConfig) {
    this.p2pEdge =
      config.p2p === undefined
        ? null
        : new P2PEdge({ ...config.p2p, executor: this.meshExecutor() });
    this.session = new ParticipantSession({
      endpoint: config.endpoint,
      connect: config.connect,
      store: config.store,
      schedule: config.schedule,
      env: config.env,
      handlers: {
        onHandshake: (ack) => {
          // The declared pictures load while the participant is on the forms, so
          // the first frame that draws one is not the frame that fetches it.
          if (ack.assets !== undefined && this.config.decodeAsset !== undefined) {
            void this.assets.load(ack.assets, this.config.decodeAsset);
          }
          this.report('connected -- protocol ' + ack.protocol_version, true);
        },
        onDelivery: (delivery) => this.render(delivery as unknown as Delivery),
        onRender: (packet) => this.renderer?.draw(packet as unknown as RenderPacket),
        onChat: (message) =>
          this.chat?.append(
            message.author === 'you' ? 'you' : 'them',
            message.text,
            message.channel,
          ),
        onChatPending: () => this.report('waiting for a reply', true),
        onChatCandidates: (frame) => {
          // One key per elicited turn, so a retry of the same judgement replays
          // rather than recording a second one (NS-10).
          this.candidateKey = idempotencyKey(this.config.env);
          this.chat?.elicit(frame);
        },
        onChatCandidatesError: (frame) => this.report('error: ' + frame.message, false),
        onChatCandidatesAck: () => this.chat?.settled(),
        onChatRoom: (frame) => {
          this.chatChannels = frame.channels;
          this.chatSeat = frame.seat;
          this.chat?.channels(frame.channels, frame.seat);
        },
        onComparisonOptions: (frame) => this.comparison?.present(frame),
        onComparisonError: (frame) => {
          this.comparison?.reopen();
          this.comparisonKey = null;
          this.report('error: ' + frame.message, false);
        },
        onComparisonAck: () => {
          this.comparison?.close();
          this.comparisonKey = null;
        },
        onP2P: (frame, socketEpoch) => {
          if (this.p2pEdge === null) {
            this.report('error: P2P bootstrap reached a client without a mesh edge', false);
            return;
          }
          this.p2pEdge.receive(frame, {
            socketEpoch,
            send: (outbound) => this.session.sendP2P(outbound, socketEpoch),
            close: () => this.session.closeP2PSocket(socketEpoch),
          });
        },
        onScreening: (frame) =>
          this.report(frame.reason ?? 'your connection is struggling', false),
        onInterval: (frame) => {
          this.stopGame();
          // Only the game pane is repainted, so a composed activity's
          // conversation goes on while the participant reads the screen.
          renderInterval(this.gameHost(), frame, () =>
            this.session.sendIntervalDone(),
          );
        },
        onError: (message) => this.report('error: ' + message, false),
        onClose: (socketEpoch) => {
          this.p2pEdge?.disconnect(socketEpoch);
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

  /** Add time the page spent in the background, for the next measurement. */
  reportHidden(millis: number): void {
    this.session.reportHidden(millis);
  }

  /** Stop the client and every reconnect attempt. */
  stop(): void {
    this.p2pEdge?.stop();
    this.stopGame();
    this.session.stop();
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
    if (delivery.kind !== 'game') {
      // The flow moved past the interactive activity, so the screen it mounted is
      // gone: the next activity rewrites the app element over it.
      this.chat = null;
      this.chatChannels = [];
      this.panes = null;
      if (this.renderer) {
        this.stopGame();
      }
    }
    if (delivery.kind !== 'comparison') {
      this.comparison = null;
    }
    if (delivery.kind === 'form') {
      renderForm(this.config.app, delivery as FormDelivery, (answers) => this.advance(answers));
    } else if (delivery.kind === 'content') {
      renderContent(this.config.app, delivery as ContentDelivery, (answers) =>
        this.advance(answers),
      );
    } else if (delivery.kind === 'game' && (delivery as GameDelivery).mode === 'browser') {
      void this.startBrowserGame(delivery as GameDelivery);
    } else if (delivery.kind === 'game' && (delivery as GameDelivery).mode === 'peer') {
      void this.startPeerGame(delivery as GameDelivery);
    } else if (delivery.kind === 'game' && (delivery as GameDelivery).mode === 'chat') {
      this.startChat();
    } else if (delivery.kind === 'game' && (delivery as GameDelivery).chat) {
      void this.startComposed(delivery as GameDelivery);
    } else if (delivery.kind === 'game') {
      void this.startServerGame(delivery as GameDelivery);
    } else if (delivery.kind === 'comparison') {
      this.startComparison(delivery as ComparisonDelivery);
    } else if (delivery.kind === 'complete') {
      this.renderComplete(delivery as CompleteDelivery);
    }
  }

  // A comparison activity owns the socket the way a game does: the question comes
  // with the delivery, the blinded options follow on the socket, and the answer
  // goes back the same way rather than as a flow command.
  private startComparison(delivery: ComparisonDelivery): void {
    this.comparisonKey = null;
    this.comparison = renderComparison(this.config.app, delivery, (handle) => {
      this.comparisonKey ??= idempotencyKey(this.config.env);
      this.session.sendComparisonResponse(handle, this.comparisonKey);
    });
  }

  private renderComplete(delivery: CompleteDelivery): void {
    // The visit is finished; clear the resume token so a later visit starts fresh.
    this.session.clearResumeToken();
    renderComplete(this.config.app, delivery);
  }

  // --- game mode -----------------------------------------------------------

  // Where a game mounts its canvas: its own pane in a composed activity, and the
  // whole screen otherwise.
  private gameHost(): HTMLElement {
    return this.panes ? this.panes.game : this.config.app;
  }

  private mountCanvas(): void {
    const app = this.gameHost();
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
    canvas.style.maxWidth = '100%';
    // The canvas takes focus, because in a composed activity the keyboard belongs
    // to whichever pane has it. Without this the participant could leave the
    // message box and have nowhere to go back to.
    canvas.tabIndex = 0;
    canvas.setAttribute('aria-label', 'The game');
    // The container is the positioning context for the countdown overlay, so the
    // countdown sits on top of the canvas and never takes its own layout space.
    const container = document.createElement('div');
    container.style.position = 'relative';
    container.style.width = '600px';
    container.style.maxWidth = '100%';
    container.appendChild(canvas);
    app.appendChild(container);
    this.gameContainer = container;
    this.renderer = createRenderer(canvas, { assets: this.assets });
    this.panes?.useCanvas(canvas);
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
  private startPreload(manifest: BrowserManifest | MeshManifest): void {
    if (manifest.mode === 'peer') {
      this.startMeshPreload(manifest);
      return;
    }
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
    if (!manifest || manifest.mode !== 'browser') {
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

  // --- the conversation ----------------------------------------------------

  // A chat activity owns the socket the way a game does, but the participant
  // writes rather than plays: the screen posts each message and shows the reply
  // the mount sends back. Ending the conversation is what advances the flow.
  private startChat(host?: HTMLElement): void {
    this.chat = renderChat(
      host ?? this.config.app,
      {
        onSend: (text, channel) => this.session.sendChat(text, channel),
        onEnd: () => this.session.sendChatEnd(),
        onChoose: (handle, verdict, ratings, responseTimeMs) =>
          this.session.sendChatCandidateChoice(handle, {
            verdict,
            ratings,
            responseTimeMs,
            idempotencyKey: this.candidateKey,
          }),
        onSkip: () => this.session.sendChatCandidateSkip(),
      },
      host !== undefined,
    );
    if (this.chatChannels.length > 0) {
      this.chat.channels(this.chatChannels, this.chatSeat);
    }
  }

  // One activity that is a game and a conversation at once. The conversation is
  // mounted first, so a message that arrives while the countdown is still running
  // has somewhere to land.
  private async startComposed(delivery: GameDelivery): Promise<void> {
    const placement = delivery.chat?.placement ?? 'beside';
    this.panes = renderPanes(this.config.app, placement, () => this.releaseKeys());
    this.startChat(this.panes.chat);
    if (delivery.mode === 'browser') {
      await this.startBrowserGame(delivery);
      return;
    }
    await this.startServerGame(delivery);
  }

  // --- the browser peer-to-peer game ---------------------------------------

  // The runtime boots while the participant is on the forms. It matters more here
  // than for a single-player browser game: the peers cross a start barrier
  // together, so a browser that booted late would hold up its whole room.
  private startMeshPreload(manifest: MeshManifest): void {
    this.meshManifest = manifest;
    if (this.meshPreload) {
      return;
    }
    this.meshPreload = preloadMeshRuntime(manifest, {
      onStatus: (text) => this.report(text, true),
    });
    this.meshPreload.catch(() => this.report('failed to load the peer runtime', false));
  }

  // The mesh is driven by the transport, not by the flow: this only prepares the
  // canvas and the keys, and the executor plays when the room starts.
  private async startPeerGame(delivery: GameDelivery): Promise<void> {
    this.inputMode = 'browser';
    this.mountCanvas();
    const manifest = delivery.manifest;
    if (manifest && manifest.mode === 'peer') {
      this.startMeshPreload(manifest);
    }
    this.report('waiting for another player...', true);
    await this.countdown(delivery.countdown);
  }

  private meshExecutor(): P2PExecutor {
    return createMeshExecutor({
      prepare: (): Promise<MeshSession> => this.meshSession(),
      pressed: this.pressed,
      hash: this.config.env.hash,
      now: () => Date.now(),
      sleep,
      renderer: () => this.renderer,
      onStatus: (text) => this.report(text, true),
      onError: (message) => this.report('peer game failed: ' + message, false),
    });
  }

  private async meshSession(): Promise<MeshSession> {
    const manifest = this.meshManifest;
    if (manifest === null || this.meshPreload === null) {
      throw new Error('the peer game has no manifest');
    }
    return { manifest, runtime: await this.meshPreload };
  }

  private stopGame(): void {
    this.config.keyTarget.removeEventListener('keydown', this.onKeyDown);
    this.config.keyTarget.removeEventListener('keyup', this.onKeyUp);
    this.pressed.clear();
    this.renderer = null;
  }
}
