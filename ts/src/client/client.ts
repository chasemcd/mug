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
import { renderMarkdown } from './markdown.js';
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
  clearKeepingHead,
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

/**
 * How large a picture is when the study says nothing: what every game was drawn
 * at before a study could say how large its own picture is.
 */
const DRAWN_AT: readonly [number, number] = [600, 400];

/** How large the picture is, as the study said it, in pixels. */
function sizeOf(size?: readonly number[]): readonly [number, number] {
  if (!Array.isArray(size) || size.length !== 2) {
    return DRAWN_AT;
  }
  const [wide, tall] = size as [number, number];
  return wide > 0 && tall > 0 ? [wide, tall] : DRAWN_AT;
}

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
  p2p?: Omit<P2PEdgeConfig, 'newExecutor'> | undefined;
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

  // The game delivery the current activity mounted, held for the rounds after the
  // first. A round loop announces the activity once and then sends an interval
  // before each later round; without this the second round has no screen to draw
  // on, and every frame of it is dropped where the renderer is read.
  private playing: GameDelivery | null = null;
  private gameContainer: HTMLElement | null = null;
  // The game on the screen now and the shape it is drawn in, so the picture is
  // fitted again when the window changes size.
  private fitting: {
    canvas: HTMLCanvasElement;
    container: HTMLElement;
    body: HTMLElement;
    size: readonly [number, number];
  } | null = null;
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
        : new P2PEdge({ ...config.p2p, newExecutor: () => this.meshExecutor() });
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
        onRender: (packet) => {
          // A frame that arrives with no canvas to draw it on is a fault, and it
          // used to be dropped without a word: every round after the first of a
          // study with `episodes=N` was pushed, dropped here, and never seen.
          if (this.renderer) {
            this.renderer.draw(packet as unknown as RenderPacket);
          } else {
            this.report('a game frame arrived with no canvas to draw it on', false);
          }
        },
        onChat: (message) =>
          this.chat?.append(
            message.author === 'you' ? 'you' : 'them',
            message.text,
            message.channel,
          ),
        onChatPending: () => {
          this.report('waiting for a reply', true);
          this.chat?.waiting(true);
        },
        // A reply that is not coming. Saying so is the difference between a study
        // that is slow and one the participant can tell is broken.
        onChatNotice: (frame) =>
          this.chat?.notice(frame.message ?? 'The assistant could not reply.'),
        onChatCandidates: (frame) => {
          // One key per elicited turn, so a retry of the same judgement replays
          // rather than recording a second one (NS-10).
          this.candidateKey = idempotencyKey(this.config.env);
          this.chat?.waiting(false);
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
          renderInterval(
            this.gameHost(),
            frame,
            () => {
              this.session.sendIntervalDone();
              // The next round is the same activity, so nothing more is
              // announced: the server steps and pushes frames. The screen those
              // frames need is built here, from the delivery that opened the
              // activity.
              void this.startNextRound();
            },
            this.assets,
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
    if (delivery.kind !== 'game' && delivery.kind !== 'chat') {
      // The flow moved past the interactive activity, so the screen it mounted is
      // gone: the next activity rewrites the app element over it.
      this.chat = null;
      this.chatChannels = [];
      this.panes = null;
      // The activity is over, so the round it could still mount is over with it.
      this.playing = null;
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
      renderContent(
        this.config.app,
        delivery as ContentDelivery,
        (answers) => this.advance(answers),
        this.assets,
      );
    } else if (delivery.kind === 'game' && (delivery as GameDelivery).mode === 'browser') {
      void this.startBrowserGame(delivery as GameDelivery);
    } else if (delivery.kind === 'game' && (delivery as GameDelivery).mode === 'peer') {
      void this.startPeerGame(delivery as GameDelivery);
    } else if (delivery.kind === 'chat') {
      // A conversation is its own activity kind. The mode on a game is the older
      // spelling and still arrives, so both reach the same screen.
      this.startChat();
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

  private mountCanvas(caption?: string, size?: readonly number[]): void {
    const app = clearKeepingHead(this.gameHost());
    // What the participant reads while they play is the study's to write. The
    // client used to ship one study's instructions to every study it ran.
    if (caption !== undefined && caption !== '') {
      const legend = document.createElement('div');
      legend.dataset['testid'] = 'game-caption';
      legend.style.margin = '0 0 0.5rem';
      legend.style.maxWidth = '600px';
      legend.style.textAlign = 'left';
      renderMarkdown(legend, caption, this.assets);
      app.appendChild(legend);
      // A caption with pictures in it is one line tall until they arrive and two
      // afterwards, so the picture is fitted again as each one lands. Without
      // this the first round is fitted to a caption still being written.
      legend
        .querySelectorAll('img')
        .forEach((picture) => picture.addEventListener('load', this.onResize));
    }
    const drawn = sizeOf(size);
    const canvas = document.createElement('canvas');
    canvas.width = drawn[0];
    canvas.height = drawn[1];
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
    container.style.maxWidth = '100%';
    container.appendChild(canvas);
    app.appendChild(container);
    this.gameContainer = container;
    this.renderer = createRenderer(canvas, {
      assets: this.assets,
      logical: { w: canvas.width, h: canvas.height },
    });
    this.fitting = { canvas, container, body: app, size: drawn };
    this.fitCanvas();
    window.addEventListener('resize', this.onResize);
    this.panes?.useCanvas(canvas);
    this.config.keyTarget.addEventListener('keydown', this.onKeyDown);
    this.config.keyTarget.addEventListener('keyup', this.onKeyUp);
  }

  private readonly onResize = (): void => {
    this.fitCanvas();
  };

  /**
   * Draw the picture at the size the study said, and smaller when there is not
   * room for it.
   *
   * It is never drawn larger: a drawing is relative, so a kitchen of five squares
   * by four put into somebody else's 600 by 400 is a picture larger than the game
   * in it, with every square stretched to a shape its sprites are not.
   */
  private fitCanvas(): void {
    const fitting = this.fitting;
    if (fitting === null) {
      return;
    }
    const { canvas, container, body, size } = fitting;
    const style = getComputedStyle(body);
    const sides =
      parseFloat(style.paddingLeft || '0') + parseFloat(style.paddingRight || '0');
    // What the picture may fill. A pane is a box of its own and says how wide it
    // is and where it ends; a game that owns the whole screen is bounded by the
    // **window** instead, because the box it is drawn in is only as large as what
    // is in it -- so asking it would be asking the picture how big the picture is
    // allowed to be, and it would keep whatever size it already had.
    const box = container.getBoundingClientRect();
    const room =
      this.panes === null
        ? Math.max(160, window.innerWidth - box.left - sides)
        : Math.max(160, body.clientWidth - sides);
    const floor =
      this.panes === null
        ? window.innerHeight - 24
        : body.getBoundingClientRect().bottom -
          parseFloat(style.paddingBottom || '0');
    const tall = Math.max(120, floor - box.top);
    // One scale for both sides, so a picture that has to shrink keeps its shape.
    const part = Math.min(1, room / size[0], tall / size[1]);
    const wide = Math.round(size[0] * part);
    const high = Math.round(size[1] * part);
    container.style.width = `${wide}px`;
    canvas.style.width = `${wide}px`;
    canvas.style.height = `${high}px`;
    // The canvas holds real device pixels, so the picture is drawn at the size it
    // is shown at rather than blown up from a smaller one. It is capped, because
    // past two the pixels cost memory and nobody can see them.
    const density = Math.min(window.devicePixelRatio || 1, 2);
    this.renderer?.resize(
      Math.round(wide * density),
      Math.round(high * density),
    );
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
    this.playing = delivery;
    this.mountCanvas(delivery.caption, delivery.size);
    await this.countdown(delivery.countdown);
  }

  // Mount the game screen again for the round the participant just asked for.
  private async startNextRound(): Promise<void> {
    const playing = this.playing;
    if (!playing) {
      return;
    }
    if (playing.chat) {
      await this.startComposed(playing, true);
    } else if (playing.mode === 'browser') {
      await this.startBrowserGame(playing);
    } else {
      await this.startServerGame(playing);
    }
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
    this.mountCanvas(delivery.caption, delivery.size);
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
      // Each slice is reported as it is played, so a participant who shuts the
      // tab part-way through leaves the frames they played rather than nothing.
      await playBrowserEpisode(runtime, manifest, {
        renderer: this.renderer ?? undefined,
        pressed: this.pressed,
        hash: this.config.env.hash,
        onStatus: (text) => this.report(text, true),
        onPart: async (part) => {
          const episode = part.boundary
            ? { transitions: part.transitions, boundary: part.boundary }
            : { transitions: part.transitions };
          const payload = {
            episode,
            actions: part.actions,
            first_frame: part.first_frame,
            final: part.final,
            generation: 1,
          };
          await this.session.sendCommand('game.capture', payload as unknown as JsonValue);
        },
      });
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
  // `again` is a later round of an activity already on the screen. The two panes
  // are left standing and only the game is mounted again, because the conversation
  // is the **activity's** and not the round's: what the pair have said is still
  // true in the next round, and the model they are talking to still remembers it.
  // Building the panes again would replace the transcript with an empty one, so
  // the participant would read "you can carry on the same conversation" on the
  // rest screen and then watch it disappear.
  private async startComposed(
    delivery: GameDelivery,
    again = false,
  ): Promise<void> {
    if (!again || !this.panes) {
      const placement = delivery.chat?.placement ?? 'beside';
      this.panes = renderPanes(this.config.app, placement, () =>
        this.releaseKeys(),
      );
      this.startChat(this.panes.chat);
    }
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
    this.mountCanvas(delivery.caption, delivery.size);
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
    window.removeEventListener('resize', this.onResize);
    this.fitting = null;
    this.pressed.clear();
    this.renderer = null;
  }
}
