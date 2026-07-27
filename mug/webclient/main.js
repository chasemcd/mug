// The client shell. It opens the realtime socket, completes the handshake, and
// runs the participant flow: it renders each delivered activity, collects form
// answers, and submits a flow.advance command. When the flow reaches the game, it
// mounts a canvas, captures the keyboard, and draws the render packets the server
// pushes. The resume cursor lets a reconnect resume from the last seen position.

import { createRenderer } from "./renderer.js";
import { preloadBrowserGame, playBrowserEpisode } from "./browser_game.js";

const status = document.getElementById("status");
const app = document.getElementById("app");
let cursor = 0;
let socket = null;

// Game mode state: the active renderer, the pressed key set, and the canvas
// container the countdown overlays without shifting the layout.
let renderer = null;
let gameContainer = null;
const pressed = new Set();

// The browser (Pyodide) runtime, preloaded eagerly while the participant is on
// the forms, so the game is ready the moment the flow reaches it.
let preloadPromise = null;

function report(text, ok) {
  status.textContent = text;
  status.classList.toggle("ok", Boolean(ok));
}

// The status line changes without the participant asking, so it is announced
// politely rather than silently: connection loss is something they must be told.
status.setAttribute("role", "status");
status.setAttribute("aria-live", "polite");

// --- realtime command envelope helpers -----------------------------------

function uuid7() {
  const bytes = crypto.getRandomValues(new Uint8Array(16));
  const ms = Date.now();
  for (let i = 0; i < 6; i++) {
    bytes[5 - i] = (ms / 2 ** (8 * i)) & 0xff;
  }
  bytes[6] = 0x70 | (bytes[6] & 0x0f);
  bytes[8] = 0x80 | (bytes[8] & 0x3f);
  const hex = [...bytes].map((b) => b.toString(16).padStart(2, "0")).join("");
  return `${hex.slice(0, 8)}-${hex.slice(8, 12)}-${hex.slice(12, 16)}-${hex.slice(16, 20)}-${hex.slice(20)}`;
}

function base64url(bytes) {
  let binary = "";
  for (const b of bytes) binary += String.fromCharCode(b);
  return btoa(binary).replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/, "");
}

function idempotencyKey() {
  return `idem_${base64url(crypto.getRandomValues(new Uint8Array(16)))}`;
}

function instant() {
  // The wire instant carries six fractional digits; pad the millisecond stamp.
  return new Date().toISOString().replace("Z", "000Z");
}

const A_DIGEST = { algorithm: "sha-256", hex: "a".repeat(64) };

function sendCommand(channelKey, payload) {
  const command = {
    command_id: `command_${uuid7()}`,
    channel_key: channelKey,
    intent_schema: { name: "mug.demo.intent", version: 0, digest: A_DIGEST },
    payload_digest: A_DIGEST,
    idempotency_key: idempotencyKey(),
    submitted_at: instant(),
  };
  socket.send(JSON.stringify({ type: "command", command, payload }));
  return command.command_id;
}

function sendAdvance(answers) {
  sendCommand("flow.advance", { answers });
}

// --- what the participant carries between activities ----------------------

// The namespaces the study declared this participant may read, as the server last
// delivered them, with the revision each was at. A page reads them through
// `window.mug.state` rather than through a global blob, which is the whole point:
// one namespace is versioned on its own, so two open tabs cannot silently
// overwrite each other.
const carried = new Map();

// The state writes this client has sent and not yet heard about, by command id, so
// a refusal can put back what the optimistic bump replaced.
const inFlight = new Map();

function rememberState(delivered) {
  if (!delivered) return;
  for (const [namespace, value] of Object.entries(delivered)) {
    const held = carried.get(namespace);
    carried.set(namespace, { value, revision: held ? held.revision : 0 });
  }
}

// The page bridge. It is deliberately small: read what this participant carries,
// and write one namespace against the revision that was read. A write the server
// refuses -- an undeclared namespace, one the study keeps to itself, or a stale
// revision -- comes back as an error frame and leaves what is held untouched.
window.mug = {
  state: {
    get(namespace) {
      const held = carried.get(namespace);
      return held ? held.value : null;
    },
    revision(namespace) {
      const held = carried.get(namespace);
      return held ? held.revision : 0;
    },
    set(namespace, value) {
      const held = carried.get(namespace);
      const revision = held ? held.revision : 0;
      // Held forward so a second write in the same activity names the revision
      // the first one produced, rather than the one it replaced.
      carried.set(namespace, { value, revision: revision + 1 });
      const sent = sendCommand("state.set", { namespace, value, revision });
      inFlight.set(sent, { namespace, value: held ? held.value : null, revision });
    },
  },
};

// A refused write is rolled back to what was held before it, so a page that lost a
// race is not left one revision ahead of the server and failing every write after.
function stateRefused(commandId) {
  const sent = inFlight.get(commandId);
  if (!sent) return false;
  inFlight.delete(commandId);
  carried.set(sent.namespace, { value: sent.value, revision: sent.revision });
  return true;
}

// --- declared assets ------------------------------------------------------

// The pictures the study declared, loaded by digest and handed to the renderer by
// name. An environment draws `image_name: "ball"`; nothing in it knows a path or a
// URL. A name nobody declared answers null, and the renderer then draws nothing
// rather than a placeholder that would hide a missing sprite from everyone.
const assets = {
  images: new Map(),
  sheets: new Map(),

  image(name) {
    return this.images.get(name) ?? null;
  },

  frame(name, index) {
    const sheet = this.sheets.get(name);
    if (!sheet || index < 0 || index >= sheet.length) return null;
    return sheet[index];
  },

  // One picture that fails to load does not fail the rest: the study loses that
  // drawing and the participant keeps their session.
  async load(manifest) {
    await Promise.all(
      Object.entries(manifest).map(async ([name, declared]) => {
        if (declared.frames && declared.frames.length > 0) {
          this.sheets.set(name, declared.frames);
        }
        try {
          const response = await fetch(declared.url);
          if (!response.ok) return;
          const blob = await response.blob();
          this.images.set(name, await createImageBitmap(blob));
        } catch {
          // Nothing to draw under this name, which the renderer handles.
        }
      }),
    );
  },
};

// --- connection quality --------------------------------------------------

// The samples a screening study asks for. The client measures and reports; the
// server alone compares them to the study's bounds and decides what they cost.
// Nothing here knows the bound, so nothing here can decide it has passed.
const quality = {
  timer: null,
  pending: new Map(),
  rtt: null,
  hiddenSince: null,
  hidden: 0,

  // Time the page has spent in the background. The tab a participant switched
  // away from is not a tab they are playing in, and a study is entitled to say so.
  watchVisibility() {
    document.addEventListener("visibilitychange", () => {
      if (document.visibilityState === "hidden") {
        this.hiddenSince = performance.now();
      } else if (this.hiddenSince !== null) {
        this.hidden = Math.round(performance.now() - this.hiddenSince);
        this.hiddenSince = null;
      }
    });
  },

  // One round trip, measured against the server's own echo. The token is opaque
  // and carries nothing: it exists to match a reply to the ping that asked for it.
  ping() {
    if (!socket || socket.readyState !== WebSocket.OPEN) return;
    const token = uuid7();
    this.pending.set(token, performance.now());
    socket.send(JSON.stringify({ type: "ping", token }));
  },

  onPong(token) {
    const sentAt = this.pending.get(token);
    if (sentAt === undefined) return;
    this.pending.delete(token);
    this.rtt = Math.round((performance.now() - sentAt) * 1000);
    this.send();
  },

  samples() {
    const found = {};
    if (this.rtt !== null) found.rtt = this.rtt;
    found.hidden = this.hidden * 1000;
    return found;
  },

  send() {
    if (!socket || socket.readyState !== WebSocket.OPEN) return;
    if (this.rtt === null) return;
    socket.send(
      JSON.stringify({ type: "measurement", samples: this.samples() }),
    );
    this.hidden = 0;
  },

  // A study that declares no screen never calls this, so a client that is not
  // being screened sends no frame at all.
  start(everyMs) {
    this.stop();
    this.ping();
    this.timer = setInterval(() => this.ping(), Math.max(1000, everyMs));
  },

  stop() {
    if (this.timer !== null) clearInterval(this.timer);
    this.timer = null;
    this.pending.clear();
  },
};

quality.watchVisibility();

// --- form and content rendering ------------------------------------------

function renderForm(delivery) {
  const spec = delivery.form;
  app.innerHTML = "";
  const form = document.createElement("form");
  const heading = document.createElement("h2");
  heading.textContent = spec.form_key;
  form.appendChild(heading);

  for (const field of spec.fields) {
    // A choice or a scale is a group of radios, so it is a fieldset with a legend:
    // that is what tells a screen reader which question the options belong to.
    // A free-text field is one control, so its label is tied to it by id.
    if (field.kind === "choice" || field.kind === "likert") {
      const group = document.createElement("fieldset");
      group.style.border = "none";
      group.style.margin = "0.75rem 0 0.25rem";
      group.style.padding = "0";
      const legend = document.createElement("legend");
      legend.textContent = field.label;
      group.appendChild(legend);
      const values =
        field.kind === "choice"
          ? field.options
          : Array.from({ length: field.scale }, (_, n) => String(n + 1));
      for (const option of values) addRadio(group, field.field_key, option, field.required);
      form.appendChild(group);
    } else {
      const id = `field-${field.field_key}`;
      const label = document.createElement("label");
      label.textContent = field.label;
      label.htmlFor = id;
      label.style.display = "block";
      label.style.margin = "0.75rem 0 0.25rem";
      form.appendChild(label);
      const input = document.createElement("input");
      input.type = "text";
      input.name = field.field_key;
      input.id = id;
      if (field.required) input.required = true;
      form.appendChild(input);
    }
  }

  const submit = document.createElement("button");
  submit.type = "submit";
  submit.textContent = "Continue";
  submit.style.display = "block";
  submit.style.marginTop = "1rem";
  form.appendChild(submit);

  form.addEventListener("submit", (event) => {
    event.preventDefault();
    const answers = {};
    for (const field of spec.fields) {
      const value = new FormData(form).get(field.field_key);
      if (value === null || value === "") continue;
      answers[field.field_key] = field.kind === "likert" ? Number(value) : value;
    }
    sendAdvance(answers);
  });
  app.appendChild(form);
}

function addRadio(parent, name, value, required) {
  // The label wraps the input, so clicking the text selects the option and a
  // screen reader reads the option's own name with it.
  const wrap = document.createElement("label");
  wrap.style.marginRight = "1rem";
  const input = document.createElement("input");
  input.type = "radio";
  input.name = name;
  input.value = value;
  if (required) input.required = true;
  wrap.appendChild(input);
  wrap.append(` ${value}`);
  parent.appendChild(wrap);
}

function renderContent(delivery) {
  app.innerHTML = "";
  const pre = document.createElement("pre");
  pre.textContent = delivery.content.body.text || "";
  pre.style.whiteSpace = "pre-wrap";
  // A <pre> is not a landmark, so name the region for a screen reader and let a
  // keyboard reach it: long instructions must be scrollable without a mouse.
  pre.tabIndex = 0;
  pre.setAttribute("role", "region");
  pre.setAttribute("aria-label", "Study instructions");
  app.appendChild(pre);
  const next = document.createElement("button");
  next.textContent = "Continue";
  next.addEventListener("click", () => sendAdvance({}));
  app.appendChild(next);
}

// --- comparison mode -----------------------------------------------------

// The mounted comparison screen. A comparison activity owns the socket the way a
// game does: the server sends the question and the blinded options, and the one
// answer goes back on the same socket rather than as a flow command.
let comparison = null;

function startComparison(delivery) {
  app.innerHTML = "";
  const heading = document.createElement("h2");
  heading.textContent = delivery.ask || "Which was better?";
  app.appendChild(heading);
  const waiting = document.createElement("p");
  waiting.dataset.testid = "comparison-waiting";
  waiting.textContent = "Loading what you are being asked about...";
  app.appendChild(waiting);
  comparison = { heading, waiting };
}

function renderComparisonOptions(message) {
  if (!comparison) startComparison(message);
  comparison.heading.textContent = message.ask;
  comparison.waiting.remove();
  const list = document.createElement("div");
  list.dataset.testid = "comparison-options";
  // The options are a group, and the question is its name: a screen reader then
  // announces what is being asked before it reads the first option.
  const askId = "comparison-ask";
  comparison.heading.id = askId;
  list.setAttribute("role", "group");
  list.setAttribute("aria-labelledby", askId);
  // The options arrive in the order the server committed to. Nothing here says
  // which condition an option is: the handle is opaque and the label is the
  // participant's own run, so the button order carries no signal either way.
  for (const option of message.options) {
    const button = document.createElement("button");
    button.type = "button";
    button.dataset.handle = option.handle;
    button.style.display = "block";
    button.style.margin = "0.5rem 0";
    // An option shows what it recorded: a run shows how long it went and what it
    // earned, a model output shows the text it produced. Neither says which
    // condition it was, which is the whole point of the blinding.
    if (typeof option.text === "string") {
      button.textContent = option.text;
      button.style.whiteSpace = "pre-wrap";
      button.style.textAlign = "left";
      button.style.maxWidth = "40rem";
    } else {
      const summary = option.summary || {};
      button.textContent =
        `Round ${option.played} -- ${summary.frames} frames, score ${summary.reward}`;
    }
    button.addEventListener("click", () => answerComparison(option.handle));
    list.appendChild(button);
  }
  app.appendChild(list);
  comparison.list = list;
}

function answerComparison(handle) {
  // The key is minted once per answer and reused on a retry, so a dropped receipt
  // costs the participant nothing: the server replays the first response.
  if (!comparison.key) comparison.key = idempotencyKey();
  for (const button of comparison.list.querySelectorAll("button")) {
    button.disabled = true;
  }
  socket.send(
    JSON.stringify({
      type: "comparison_response",
      choice: handle,
      idempotency_key: comparison.key,
    }),
  );
}

function reportComparisonError(message) {
  if (!comparison || !comparison.list) return;
  for (const button of comparison.list.querySelectorAll("button")) {
    button.disabled = false;
  }
  report(`error: ${message.message}`, false);
}

// --- game mode -----------------------------------------------------------

// The input mode: "server" sends key frames to the server loop; "browser" keeps
// the pressed keys local for the in-browser stepping loop.
let inputMode = "server";

// The two panes of a composed activity, or null when the activity is one screen.
// It holds the game pane, the chat pane, and the ordered focus stops Tab cycles.
let panes = null;

// Where a game mounts its canvas: its own pane in a composed activity, and the
// whole screen otherwise.
function gameHost() {
  return panes ? panes.game : app;
}

function mountCanvas() {
  const host = gameHost();
  host.innerHTML = "";
  const heading = document.createElement("p");
  heading.textContent = "Use the left and right arrow keys to reach the flag.";
  host.appendChild(heading);
  const canvas = document.createElement("canvas");
  canvas.width = 600;
  canvas.height = 400;
  canvas.style.background = "#dfe7f5";
  canvas.style.border = "1px solid #333";
  canvas.style.display = "block";
  canvas.style.maxWidth = "100%";
  // The canvas takes focus, because in a composed activity the keyboard belongs
  // to whichever pane has it. Without this the participant could leave the
  // message box and have nowhere to go back to.
  canvas.tabIndex = 0;
  canvas.setAttribute("aria-label", "The game");
  // The container is the positioning context for the countdown overlay, so the
  // countdown sits on top of the canvas and never takes its own layout space.
  gameContainer = document.createElement("div");
  gameContainer.style.position = "relative";
  gameContainer.style.width = "600px";
  gameContainer.style.maxWidth = "100%";
  gameContainer.appendChild(canvas);
  host.appendChild(gameContainer);
  renderer = createRenderer(canvas, { assets });
  if (panes) {
    panes.canvas = canvas;
    refocusStops();
    canvas.focus();
  }
  window.addEventListener("keydown", onKeyDown);
  window.addEventListener("keyup", onKeyUp);
}

// --- the composed activity: a game and a conversation, side by side ------

// Mount the two panes of a composed activity. The game keeps its own pane and the
// conversation keeps its own, so a round ending repaints one and leaves the other
// alone -- which is what lets the conversation stay usable in an intermission.
function mountPanes(placement) {
  app.innerHTML = "";
  const frame = document.createElement("div");
  frame.dataset.testid = "composed";
  frame.dataset.placement = placement;
  frame.style.display = "flex";
  frame.style.gap = "1rem";
  frame.style.alignItems = "flex-start";
  // Beside the canvas by default, and below it on a narrow screen, because a rail
  // squeezed to nothing is worse than a transcript underneath.
  const beside = placement === "beside" && window.innerWidth >= 760;
  frame.style.flexDirection = beside ? "row" : "column";

  const game = document.createElement("div");
  game.dataset.testid = "game-pane";
  game.style.flex = "0 1 auto";
  const chat = document.createElement("div");
  chat.dataset.testid = "chat-pane";
  chat.style.flex = beside ? "1 1 18rem" : "1 1 auto";
  chat.style.minWidth = "0";
  chat.style.width = beside ? "auto" : "100%";
  frame.appendChild(game);
  frame.appendChild(chat);

  // Which pane has the keyboard, said out loud. A participant whose arrow keys
  // stopped working needs to be able to see why, not guess.
  const where = document.createElement("p");
  where.dataset.testid = "focus-hint";
  where.setAttribute("role", "status");
  where.setAttribute("aria-live", "polite");
  where.style.margin = "0.5rem 0 0";
  where.style.fontSize = "0.85rem";
  app.appendChild(frame);
  app.appendChild(where);

  panes = { frame, game, chat, where, canvas: null, stops: [] };
  frame.addEventListener("keydown", onPaneKey);
  frame.addEventListener("focusin", showFocus);
  return panes;
}

// The stops Tab moves between: the canvas, the message box, and the channel tabs.
// Cycling rather than a two-way toggle is what keeps the channel tabs reachable at
// all -- a private channel that needs a mouse is not usable by keyboard.
function refocusStops() {
  if (!panes) return;
  const input = panes.chat.querySelector("input[name=message]");
  const tabs = panes.chat.querySelector("[role=tablist] button");
  panes.stops = [panes.canvas, input, tabs].filter(Boolean);
}

function onPaneKey(event) {
  if (!panes) return;
  if (event.key === "Escape") {
    // The fast way back to the game from anywhere in the conversation.
    event.preventDefault();
    if (panes.canvas) panes.canvas.focus();
    return;
  }
  if (event.key !== "Tab") return;
  refocusStops();
  if (panes.stops.length < 2) return;
  event.preventDefault();
  const at = panes.stops.indexOf(document.activeElement);
  const step = event.shiftKey ? -1 : 1;
  const next = (at + step + panes.stops.length) % panes.stops.length;
  panes.stops[next].focus();
}

function showFocus() {
  if (!panes) return;
  const inGame = panes.game.contains(document.activeElement);
  const held = inGame ? panes.game : panes.chat;
  for (const pane of [panes.game, panes.chat]) {
    pane.style.outline = pane === held ? "2px solid #2b6cb0" : "2px solid transparent";
    pane.style.outlineOffset = "4px";
  }
  panes.where.textContent = inGame
    ? "The game has the keyboard. Press Tab to write a message."
    : "The conversation has the keyboard. Press Tab or Escape to play.";
  if (!inGame) releaseKeys();
}

// Let go of every held key when the keyboard leaves the game. Without this, a key
// held as the participant clicks the message box stays down for the rest of the
// conversation, and the car drives itself while they type.
function releaseKeys() {
  if (!pressed.size) return;
  pressed.clear();
  if (inputMode === "server") sendInput();
}

// True while the participant is typing, so the game does not also read the keys:
// the arrow keys move the caret, and steering with them at the same time is how a
// message ends up written into the environment.
function typing() {
  const active = document.activeElement;
  return !!active && (active.tagName === "INPUT" || active.tagName === "TEXTAREA");
}

function sleep(ms) {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

// A pre-roll countdown after the participant continues, so the episode does not
// start while they are still settling in. The server holds its stepping loop for
// the same duration, so the count matches when the environment begins.
async function countdown(seconds) {
  if (!seconds || seconds <= 0) return;
  // An absolute overlay that blurs the canvas behind it and shows the count. It
  // takes no layout space, so when it is removed the numbers and the blur simply
  // vanish and the game begins -- no trailing "Go" and no layout shift.
  const banner = document.createElement("div");
  Object.assign(banner.style, {
    position: "absolute",
    inset: "0",
    display: "flex",
    alignItems: "center",
    justifyContent: "center",
    fontSize: "3rem",
    fontWeight: "bold",
    color: "#101010",
    backdropFilter: "blur(6px)",
    webkitBackdropFilter: "blur(6px)",
    pointerEvents: "none",
  });
  (gameContainer ?? app).appendChild(banner);
  for (let n = seconds; n > 0; n--) {
    banner.textContent = `${n}`;
    await sleep(1000);
  }
  banner.remove();
}

async function startServerGame(delivery) {
  inputMode = "server";
  mountCanvas();
  await countdown(delivery.countdown);
}

// Begin downloading Pyodide and the packages as soon as the study announces the
// bundle, so the download overlaps with the forms. The returned promise is what
// the game start awaits, so the participant cannot reach a blank canvas.
function startPreload(manifest) {
  if (preloadPromise) return;
  preloadPromise = preloadBrowserGame(manifest, {
    onStatus: (text) => report(text, true),
  });
  preloadPromise.catch(() => report("failed to load the python runtime", false));
}

// Run the environment in the browser through Pyodide, then report the finished
// run over game.capture. The server validates and commits it under a fence. The
// game waits on the preload, so it never starts before the runtime is ready.
async function startBrowserGame(delivery) {
  inputMode = "browser";
  mountCanvas();
  try {
    startPreload(delivery.manifest);
    report("preparing the environment...", true);
    const runtime = await preloadPromise;
    await countdown(delivery.countdown);
    const run = await playBrowserEpisode(runtime, delivery.manifest, {
      renderer,
      pressed,
      onStatus: (text) => report(text, true),
    });
    // The action sequence rides alongside the episode, so the server can
    // re-execute the run under the same inputs and verify the state hashes.
    const episode = { transitions: run.transitions, boundary: run.boundary };
    sendCommand("game.capture", {
      episode,
      actions: run.actions,
      generation: 1,
    });
  } catch (error) {
    report(`browser environment failed: ${error}`, false);
  }
}

function stopGame() {
  window.removeEventListener("keydown", onKeyDown);
  window.removeEventListener("keyup", onKeyUp);
  pressed.clear();
  renderer = null;
}

// The screen between rounds of one game activity. It is participant-paced: the
// server holds the next round until this says to go on, because a rest that ends
// while someone is still reading is not a rest.
function renderInterval(message) {
  // Only the game pane is repainted. In a composed activity the conversation is
  // not paused by the screen between rounds: the room belongs to the activity, and
  // a rest from the game is not a rest from the person you are playing with.
  const host = gameHost();
  host.innerHTML = "";
  const heading = document.createElement("h2");
  heading.textContent = `Round ${message.round} of ${message.of}`;
  app.appendChild(heading);
  if (message.markdown) {
    const body = document.createElement("pre");
    body.textContent = message.markdown;
    body.style.whiteSpace = "pre-wrap";
    body.tabIndex = 0;
    body.setAttribute("role", "region");
    body.setAttribute("aria-label", "Between rounds");
    app.appendChild(body);
  }
  const next = document.createElement("button");
  next.textContent = "Continue";
  next.addEventListener("click", () => {
    socket.send(JSON.stringify({ type: "interval_done" }));
  });
  app.appendChild(next);
  next.focus();
}

function sendInput() {
  socket.send(JSON.stringify({ type: "input", keys: [...pressed] }));
}

function onKeyDown(event) {
  if (typing()) return;
  if (event.key === "ArrowLeft" || event.key === "ArrowRight") event.preventDefault();
  if (!pressed.has(event.key)) {
    pressed.add(event.key);
    if (inputMode === "server") sendInput();
  }
}

function onKeyUp(event) {
  if (typing()) return;
  if (pressed.delete(event.key) && inputMode === "server") sendInput();
}

// --- the conversation ----------------------------------------------------

// The mounted chat screen: it holds the transcript element while the activity
// runs, and it is null the rest of the time.
let chat = null;

// The channels this participant is in, as the mount named them. A conversation
// with one channel says nothing, so this stays empty and the screen shows one
// transcript. A channel this participant is not in never appears here, because
// the server never sends it: the screen can not hide what it was never told.
let chatChannels = [];

// A chat activity owns the socket the way a game does, but the participant
// writes rather than plays. The participant's own message is added here when
// they send it, because the mount does not echo it: it records the message and
// answers with the reply. The two authors are labelled "You" and "Them" -- the
// screen never says whether the other party is a person or a model, because only
// the study knows, and only the study may say.
function startChat(host) {
  // A conversation that is the whole activity owns the screen; one that sits
  // beside a game owns its pane, and the game keeps the other.
  const composed = Boolean(host);
  const at = host ?? app;
  at.innerHTML = "";
  const tabs = document.createElement("div");
  tabs.setAttribute("role", "tablist");
  tabs.dataset.testid = "chat-channels";
  tabs.style.margin = "0 0 0.5rem";
  at.appendChild(tabs);

  const transcript = document.createElement("div");
  transcript.setAttribute("role", "log");
  transcript.dataset.testid = "chat-transcript";
  transcript.style.margin = "0 0 1rem";
  // The rail keeps its size before anything is said. A transcript that
  // collapses to nothing reads as a broken pane rather than an empty one.
  transcript.style.minHeight = "8rem";
  transcript.style.maxHeight = "20rem";
  transcript.style.overflowY = "auto";
  at.appendChild(transcript);

  const form = document.createElement("form");
  const input = document.createElement("input");
  input.type = "text";
  input.name = "message";
  input.autocomplete = "off";
  input.setAttribute("aria-label", "Your message");
  input.style.width = "70%";
  const send = document.createElement("button");
  send.type = "submit";
  send.textContent = "Send";
  form.appendChild(input);
  form.appendChild(send);
  at.appendChild(form);

  // Only a standalone conversation is ended by the participant. A composed
  // activity ends when its rounds end, so leaving the conversation early would
  // leave them playing a game they can no longer talk about.
  const leave = document.createElement("button");
  leave.type = "button";
  leave.textContent = "End the conversation";
  leave.style.marginTop = "1rem";
  if (!composed) at.appendChild(leave);

  // One channel is shown at a time. A message that belongs to another channel is
  // held rather than dropped, so moving to it shows what was said there.
  const lines = new Map();
  let current = chatChannels[0] ?? null;

  function show(channel) {
    current = channel;
    transcript.innerHTML = "";
    for (const line of lines.get(channel) ?? []) transcript.appendChild(line);
    transcript.scrollTop = transcript.scrollHeight;
    for (const tab of tabs.children) {
      tab.setAttribute("aria-selected", String(tab.dataset.channel === channel));
    }
  }

  chat = {
    channels(keys, seat) {
      chatChannels = keys;
      current = keys[0] ?? null;
      tabs.innerHTML = "";
      tabs.dataset.seat = seat ?? "";
      if (keys.length < 2) return;
      for (const key of keys) {
        const tab = document.createElement("button");
        tab.type = "button";
        tab.setAttribute("role", "tab");
        tab.dataset.channel = key;
        tab.textContent = key;
        tab.style.marginRight = "0.5rem";
        tab.addEventListener("click", () => show(key));
        tabs.appendChild(tab);
      }
      show(current);
    },
    append(author, text, channel) {
      const key = channel ?? current;
      const line = document.createElement("p");
      line.dataset.author = author;
      line.dataset.channel = key ?? "";
      line.style.margin = "0.25rem 0";
      const who = document.createElement("strong");
      who.textContent = author === "you" ? "You: " : "Them: ";
      line.appendChild(who);
      line.append(text);
      const held = lines.get(key) ?? [];
      held.push(line);
      lines.set(key, held);
      if (key === current || current === null) {
        transcript.appendChild(line);
        transcript.scrollTop = transcript.scrollHeight;
      }
    },
    close() {
      input.disabled = true;
      send.disabled = true;
      leave.disabled = true;
    },
  };
  if (chatChannels.length) chat.channels(chatChannels, tabs.dataset.seat);

  form.addEventListener("submit", (event) => {
    event.preventDefault();
    const text = input.value.trim();
    if (!text) return;
    input.value = "";
    chat.append("you", text, current);
    const frame = { type: "chat", text };
    if (current !== null) frame.channel = current;
    socket.send(JSON.stringify(frame));
  });
  leave.addEventListener("click", () => {
    chat.close();
    socket.send(JSON.stringify({ type: "chat_end" }));
  });
}

// --- the choice between candidate replies --------------------------------

// The open elicitation, or null when the conversation is not asking. Only the
// blinded handles are held: which reply came from which seat is exactly what the
// screen must not be able to say.
let candidates = null;

function closeCandidateReplies() {
  if (candidates) candidates.panel.remove();
  candidates = null;
}

function candidateAnswer(verdict, handle) {
  if (!candidates) return;
  const ratings = [];
  for (const [key, control] of candidates.axes) {
    const value = Number(control.input.value);
    if (control.scope === "each") {
      for (const [option, each] of control.each) {
        ratings.push({ axis: key, option, value: Number(each.value) });
      }
    } else if (value === 0) {
      ratings.push({ axis: key, value: 0 });
    } else {
      const side = value < 0 ? candidates.order[0] : candidates.order[1];
      ratings.push({ axis: key, option: side, value: Math.abs(value) });
    }
  }
  socket.send(
    JSON.stringify({
      type: "chat_candidate_choice",
      choice: handle,
      verdict,
      ratings,
      response_time_ms: Math.max(0, Math.round(performance.now() - candidates.shown)),
      idempotency_key: candidates.key,
    }),
  );
}

function candidateAxis(axis, order, panel) {
  // One axis, drawn by what it asks for: a slider between the two replies, or one
  // scale per reply. Either way the answer names a reply and never a position.
  const block = document.createElement("div");
  block.dataset.testid = "chat-axis";
  block.dataset.axis = axis.key;
  block.style.margin = "0.5rem 0";
  const label = document.createElement("label");
  label.textContent = axis.ask;
  label.htmlFor = "axis-" + axis.key;
  block.appendChild(label);
  const each = new Map();
  let input = document.createElement("input");
  if (axis.scope === "each") {
    for (const handle of order) {
      const one = document.createElement("input");
      one.type = "range";
      one.min = "1";
      one.max = String(axis.points);
      one.value = String(Math.ceil(axis.points / 2));
      one.id = "axis-" + axis.key + "-" + handle;
      one.dataset.option = handle;
      one.setAttribute("aria-label", axis.ask);
      block.appendChild(one);
      each.set(handle, one);
    }
  } else {
    input.type = "range";
    input.min = String(-axis.points);
    input.max = String(axis.points);
    input.value = "0";
    input.step = "1";
    input.id = "axis-" + axis.key;
    input.setAttribute("aria-label", axis.ask);
    if (axis.low) input.setAttribute("aria-valuetext", axis.low);
    block.appendChild(input);
  }
  panel.appendChild(block);
  return { input, scope: axis.scope ?? "pair", each };
}

function renderCandidateReplies(message) {
  closeCandidateReplies();
  const panel = document.createElement("section");
  panel.dataset.testid = "chat-candidates";
  const ask = document.createElement("h3");
  ask.id = "chat-candidates-ask";
  ask.textContent = message.ask;
  panel.appendChild(ask);
  const list = document.createElement("ul");
  list.dataset.testid = "chat-candidate-options";
  list.setAttribute("aria-labelledby", ask.id);
  const order = [];
  for (const option of message.options ?? []) {
    order.push(option.handle);
    const item = document.createElement("li");
    const button = document.createElement("button");
    button.type = "button";
    button.dataset.handle = option.handle;
    button.textContent = option.text;
    button.addEventListener("click", () => candidateAnswer("choice", option.handle));
    item.appendChild(button);
    list.appendChild(item);
  }
  panel.appendChild(list);
  const axes = new Map();
  for (const axis of message.axes ?? []) {
    axes.set(axis.key, candidateAxis(axis, order, panel));
  }
  if (message.ties) {
    for (const [verdict, label] of [
      ["tie", "They are about the same"],
      ["both-bad", "Both are bad"],
    ]) {
      const button = document.createElement("button");
      button.type = "button";
      button.dataset.verdict = verdict;
      button.textContent = label;
      // A tie still has to resolve to the reply the thread goes on with, and the
      // one they read first is the honest choice for it.
      button.addEventListener("click", () => candidateAnswer(verdict, order[0]));
      panel.appendChild(button);
    }
  }
  if (message.skippable) {
    const skip = document.createElement("button");
    skip.type = "button";
    skip.dataset.testid = "chat-candidate-skip";
    skip.textContent = "Skip";
    skip.addEventListener("click", () => {
      socket.send(JSON.stringify({ type: "chat_candidate_skip" }));
      closeCandidateReplies();
    });
    panel.appendChild(skip);
  }
  app.appendChild(panel);
  candidates = {
    panel,
    order,
    axes,
    key: idempotencyKey(),
    shown: performance.now(),
  };
}

// --- delivery dispatch ---------------------------------------------------

function render(delivery) {
  // A preload announcement starts the background download; it does not change
  // the visible activity, so the form stays on screen while packages arrive.
  if (delivery.kind === "preload") {
    startPreload(delivery.manifest);
    return;
  }
  // What the participant carries travels with every step, so a page reads it
  // without asking for it first.
  rememberState(delivery.state);
  if (delivery.kind !== "game") {
    // The flow moved past the interactive activity, so the screen it mounted is
    // gone: the next activity rewrites the app element over it.
    chat = null;
    chatChannels = [];
    panes = null;
    if (renderer) stopGame();
  }
  if (delivery.kind !== "comparison") comparison = null;
  if (delivery.kind === "form") renderForm(delivery);
  else if (delivery.kind === "comparison") startComparison(delivery);
  else if (delivery.kind === "content") renderContent(delivery);
  else if (delivery.kind === "game" && delivery.mode === "chat") startChat();
  else if (delivery.kind === "game" && delivery.chat) startComposed(delivery);
  else if (delivery.kind === "game" && delivery.mode === "browser") startBrowserGame(delivery);
  else if (delivery.kind === "game") startServerGame(delivery);
  else if (delivery.kind === "complete") renderComplete(delivery);
}

// One activity that is a game and a conversation at once. The conversation is
// mounted first, so a message that arrives while the countdown is still running
// has somewhere to land.
async function startComposed(delivery) {
  const placement = delivery.chat.placement ?? "beside";
  const mounted = mountPanes(placement);
  startChat(mounted.chat);
  if (delivery.mode === "browser") {
    await startBrowserGame(delivery);
    return;
  }
  await startServerGame(delivery);
}

function renderComplete(delivery) {
  // The visit is finished; clear the resume token so a later visit starts fresh.
  localStorage.removeItem("mug_resume_token");
  app.innerHTML = "<h2>All done. Thank you.</h2>";
  if (delivery.completion_code) {
    const code = document.createElement("p");
    code.textContent = `Completion code: ${delivery.completion_code}`;
    app.appendChild(code);
  }
  if (delivery.return_url) {
    const link = document.createElement("a");
    link.href = delivery.return_url;
    link.textContent = "Return to the study";
    app.appendChild(link);
  }
}

// --- connection ----------------------------------------------------------

function connect() {
  const scheme = location.protocol === "https:" ? "wss" : "ws";
  // Present the stored resume token, so a reconnection resumes the same visit
  // where it stopped rather than starting a fresh one.
  const token = localStorage.getItem("mug_resume_token");
  const resume = token ? `&resume_token=${encodeURIComponent(token)}` : "";
  // Present the launch ticket from the entry link on first entry, so the server
  // enrolls the participant. A return uses the stored token instead of a ticket.
  const ticket = new URLSearchParams(location.search).get("ticket");
  const launch = ticket ? `&ticket=${encodeURIComponent(ticket)}` : "";
  socket = new WebSocket(
    `${scheme}://${location.host}/ws?resume_from=${cursor}${resume}${launch}`,
  );

  socket.addEventListener("message", (event) => {
    const message = JSON.parse(event.data);
    if (message.type === "handshake_ack") {
      cursor = message.resume_cursor ?? cursor;
      if (message.resume_token) {
        localStorage.setItem("mug_resume_token", message.resume_token);
      }
      // Pin the deployment revision this client accepted. A build made for a
      // revision the server no longer serves is refused here rather than running
      // on quietly against a study it was not built for.
      if (message.deployment) {
        socket.send(
          JSON.stringify({
            type: "client_handshake",
            accepted_deployment: message.deployment,
          }),
        );
      }
      // The declared pictures load while the participant is on the forms, so the
      // first frame that draws one is not the frame that fetches it.
      if (message.assets) {
        void assets.load(message.assets);
      }
      // A screening study says how often to measure. One is taken at once, so
      // entry is decided on this connection rather than a minute into it.
      if (message.screening) {
        quality.start(message.screening.sample_every_ms ?? 10000);
      }
      report(`connected -- protocol ${message.protocol_version}`, true);
    } else if (message.type === "pong") {
      quality.onPong(message.token);
    } else if (message.type === "screening") {
      report(message.reason ?? "your connection is struggling", false);
    } else if (message.type === "delivery") {
      render(message.delivery);
    } else if (message.type === "render") {
      if (renderer) renderer.draw(message.packet);
    } else if (message.type === "interval") {
      stopGame();
      renderInterval(message);
    } else if (message.type === "chat_room") {
      // What the conversation is, for this participant. A channel they are not in
      // is not in this list, so their screen never learns that it exists.
      chatChannels = message.channels ?? [];
      if (chat) chat.channels(chatChannels, message.seat);
    } else if (message.type === "chat") {
      // A restored message names its own author, because a conversation redrawn
      // after a refresh has to read the way it did before it.
      if (chat) {
        chat.append(
          message.author === "you" ? "you" : "them",
          message.text,
          message.channel,
        );
      }
    } else if (message.type === "chat_pending") {
      report("waiting for a reply", true);
    } else if (message.type === "chat_candidates") {
      renderCandidateReplies(message);
    } else if (message.type === "chat_candidates_error") {
      report(message.message ?? "that reply was not one of the ones shown", true);
    } else if (message.type === "chat_candidates_ack") {
      closeCandidateReplies();
    } else if (message.type === "comparison") {
      renderComparisonOptions(message);
    } else if (message.type === "comparison_error") {
      reportComparisonError(message);
    } else if (message.type === "comparison_ack") {
      if (comparison && comparison.list) comparison.list.remove();
    } else if (message.type === "ack" && message.ack?.stream_position) {
      cursor = Math.max(cursor, message.ack.stream_position.sequence);
      inFlight.delete(message.ack.command_id);
    } else if (message.type === "error") {
      // A refused state write puts back what it optimistically replaced, so the
      // page is not left one revision ahead of the server for the rest of the
      // activity. Everything else is reported as it always was.
      if (!stateRefused(message.command_id)) {
        report(`error: ${message.message}`, false);
      }
    }
  });

  socket.addEventListener("close", () => {
    quality.stop();
    if (renderer) stopGame();
    report("disconnected -- retrying", false);
    setTimeout(connect, 1000);
  });
  socket.addEventListener("error", () => socket.close());
}

connect();
