// The client shell. It opens the realtime socket, completes the handshake, and
// runs the participant flow: it renders each delivered activity, collects form
// answers, and submits a flow.advance command. When the flow reaches the game, it
// mounts a canvas, captures the keyboard, and draws the render packets the server
// pushes. The resume cursor lets a reconnect resume from the last seen position.

import { createRenderer } from "./renderer.js";
import { preloadBrowserGame, playBrowserEpisode } from "./browser_game.js";
import { renderMarkdown } from "./markdown.js";
import { debugIfServed } from "./debug.js";

const status = document.getElementById("status");
const app = document.getElementById("app");
let cursor = 0;
let socket = null;

// Game mode state: the active renderer, the pressed key set, and the canvas
// container the countdown overlays without shifting the layout.
let renderer = null;

// The game delivery the current activity mounted, held for the rounds after the
// first. A round loop sends one delivery and then an interval before each later
// round; without this the second round has no screen to draw on.
let playing = null;
let gameContainer = null;
const pressed = new Set();

// The actions of presses that have arrived and not yet been played, for a study
// whose input mode counts presses rather than reading what is held. It is filled
// on key down and drained one per frame by whichever loop is running.
const taps = [];

// How long the running game says a press lasts, and the manifest that said so.
// Only a browser-run game needs these here: in server execution the client sends
// what is held and the server counts the presses, because the bindings are the
// server's and a client is not asked to resolve them.
let inputScheme = "pressed_keys";
let browserManifest = null;

// The browser (Pyodide) runtime, preloaded eagerly while the participant is on
// the forms, so the game is ready the moment the flow reaches it.
let preloadPromise = null;

function report(text, ok) {
  status.textContent = text;
  // The mark beside the words is the state: green when the link holds, amber
  // when it does not. It is never the only signal, because the words say the
  // same thing.
  status.classList.toggle("state--weak", !ok);
}

// One element that every activity builds into, so a screen never has to know
// where it sits. It is cleared by whoever mounts the next activity.
function clear(host) {
  const at = host ?? app;
  // A pane's head says what the pane is and where the keys are going. It
  // belongs to the pane and not to the activity inside it, so it survives the
  // activity being drawn again.
  const head = at.querySelector(":scope > .pane__head");
  at.innerHTML = "";
  if (head) at.appendChild(head);
  return at;
}

// A labelled section key, and the numbered form of it that a judgement uses to
// say what to do first.
function sectionKey(text, step) {
  const key = document.createElement("div");
  key.className = step ? "key key--step" : "key";
  if (step) {
    const n = document.createElement("span");
    n.className = "key__n";
    n.textContent = String(step);
    key.appendChild(n);
  }
  key.append(text);
  return key;
}

// One turn of a conversation: a name with a mark, and a bubble under it. The
// two parties are on opposite sides, which is what makes a conversation
// readable without reading it. The screen never says whether the other party is
// a person or a model, so the mark carries no meaning beyond "not you".
function turn(author, name) {
  const one = document.createElement("div");
  one.className = author === "you" ? "turn turn--you" : "turn turn--them";
  one.dataset.author = author;
  const who = document.createElement("div");
  who.className = "turn__who";
  const mark = document.createElement("span");
  mark.className = "turn__mark";
  who.appendChild(mark);
  who.append(name);
  const bubble = document.createElement("div");
  bubble.className = "bubble";
  one.appendChild(who);
  one.appendChild(bubble);
  return one;
}

function button(label, kind) {
  const one = document.createElement("button");
  one.type = "button";
  one.className = kind ? `btn ${kind}` : "btn";
  one.textContent = label;
  return one;
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
  addresses: new Map(),

  image(name) {
    return this.images.get(name) ?? null;
  },

  // Where a declared picture is served. A page shows a picture by name and the
  // address is looked up here, so nothing a study writes becomes a request to
  // somewhere the study did not declare.
  url(name) {
    return this.addresses.get(name) ?? null;
  },

  // One frame of a sheet, by the name it was packed under. A name the sheet does
  // not hold answers null and the renderer draws the whole image, rather than
  // drawing some other sprite that happened to sit at an index.
  frame(name, packed) {
    const sheet = this.sheets.get(name);
    if (!sheet) return null;
    return sheet[packed] ?? null;
  },

  // One picture that fails to load does not fail the rest: the study loses that
  // drawing and the participant keeps their session.
  async load(manifest) {
    await Promise.all(
      Object.entries(manifest).map(async ([name, declared]) => {
        this.addresses.set(name, declared.url);
        if (declared.frames && Object.keys(declared.frames).length > 0) {
          this.sheets.set(name, declared.frames);
        }
        // A study may ship a file that is not a picture -- an exported network a
        // browser-run partner plays with. It is served the same way and it has an
        // address like everything else, but decoding it as an image would fail
        // once per load and say nothing, so it is not attempted.
        if (declared.media_type && !declared.media_type.startsWith("image/")) return;
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
  const sheet = document.createElement("div");
  sheet.className = "sheet";
  const panel = document.createElement("section");
  panel.className = "panel";
  const head = document.createElement("div");
  head.className = "panel__head";
  head.appendChild(sectionKey("A few questions"));
  const heading = document.createElement("h2");
  heading.className = "panel__ask";
  heading.textContent = spec.form_key;
  head.appendChild(heading);
  panel.appendChild(head);
  const form = document.createElement("form");
  panel.appendChild(form);
  sheet.appendChild(panel);

  for (const field of spec.fields) {
    // A choice or a scale is a group of radios, so it is a fieldset with a legend:
    // that is what tells a screen reader which question the options belong to.
    // A free-text field is one control, so its label is tied to it by id.
    if (field.kind === "choice" || field.kind === "likert") {
      const group = document.createElement("fieldset");
      group.className = "field";
      const legend = document.createElement("legend");
      legend.className = "field__label";
      legend.textContent = field.label;
      if (field.required) legend.appendChild(need("Needed"));
      group.appendChild(legend);
      if (field.kind === "likert") {
        // A scale is one row of cells with nothing chosen. A control that
        // starts in the middle sends the middle when nobody touches it, so the
        // study would record an answer that was never given.
        const cells = document.createElement("div");
        cells.className = "cells";
        for (let n = 1; n <= field.scale; n++) {
          addCell(cells, field.field_key, String(n), field.required);
        }
        group.appendChild(cells);
      } else {
        const choices = document.createElement("div");
        choices.className = "choices";
        for (const option of field.options) {
          addRadio(choices, field.field_key, option, field.required);
        }
        group.appendChild(choices);
      }
      form.appendChild(group);
    } else {
      const id = `field-${field.field_key}`;
      const wrap = document.createElement("div");
      wrap.className = "field";
      const label = document.createElement("label");
      label.className = "field__label";
      label.textContent = field.label;
      label.htmlFor = id;
      if (field.required) label.appendChild(need("Needed"));
      wrap.appendChild(label);
      const input = document.createElement("input");
      input.type = "text";
      input.name = field.field_key;
      input.id = id;
      if (field.required) input.required = true;
      wrap.appendChild(input);
      form.appendChild(wrap);
    }
  }

  const foot = document.createElement("div");
  foot.className = "panel__foot";
  const submit = document.createElement("button");
  submit.type = "submit";
  submit.className = "btn btn--primary";
  submit.textContent = "Continue";
  foot.appendChild(submit);
  form.appendChild(foot);

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
  clear().appendChild(sheet);
}

// A question that must be answered says so where it is asked, not in a message
// after the participant tries to go on.
function need(text) {
  const mark = document.createElement("span");
  mark.className = "field__need";
  mark.textContent = text;
  return mark;
}

function addRadio(parent, name, value, required) {
  // The label wraps the input, so clicking the text selects the option and a
  // screen reader reads the option's own name with it.
  const wrap = document.createElement("label");
  const input = document.createElement("input");
  input.type = "radio";
  input.name = name;
  input.value = value;
  if (required) input.required = true;
  wrap.appendChild(input);
  wrap.append(` ${value}`);
  parent.appendChild(wrap);
}

// One cell of a scale. The label wraps the input, so the whole cell is the hit
// area and a screen reader reads the number with it.
function addCell(parent, name, value, required) {
  const wrap = document.createElement("label");
  const input = document.createElement("input");
  input.type = "radio";
  input.name = name;
  input.value = value;
  if (required) input.required = true;
  wrap.appendChild(input);
  wrap.append(value);
  parent.appendChild(wrap);
}

function renderContent(delivery) {
  const sheet = document.createElement("div");
  sheet.className = "sheet";
  const page = document.createElement("div");
  page.dataset.testid = "content-page";
  page.className = "prose";
  // The page is not a landmark, so name the region for a screen reader and let a
  // keyboard reach it: long instructions must be scrollable without a mouse.
  page.tabIndex = 0;
  page.setAttribute("role", "region");
  page.setAttribute("aria-label", "Study instructions");
  renderMarkdown(page, delivery.content.body.text || "", assets);
  sheet.appendChild(page);
  const actions = document.createElement("div");
  actions.className = "actions";
  const next = button("Continue", "btn--primary");
  next.addEventListener("click", () => sendAdvance({}));
  actions.appendChild(next);
  sheet.appendChild(actions);
  clear().appendChild(sheet);
}

// --- comparison mode -----------------------------------------------------

// The mounted comparison screen. A comparison activity owns the socket the way a
// game does: the server sends the question and the blinded options, and the one
// answer goes back on the same socket rather than as a flow command.
let comparison = null;

function startComparison(delivery) {
  const sheet = clear();
  sheet.className = "scroll";
  const panel = document.createElement("section");
  panel.className = "panel";
  const head = document.createElement("div");
  head.className = "panel__head";
  head.appendChild(sectionKey("A comparison"));
  const heading = document.createElement("h2");
  heading.className = "panel__ask";
  heading.id = "comparison-ask";
  heading.textContent = delivery.ask || "Which was better?";
  head.appendChild(heading);
  panel.appendChild(head);
  const waiting = document.createElement("p");
  waiting.dataset.testid = "comparison-waiting";
  waiting.className = "block";
  waiting.textContent = "Loading what you are being asked about...";
  panel.appendChild(waiting);
  sheet.appendChild(panel);
  comparison = { panel, heading, waiting };
}

function renderComparisonOptions(message) {
  if (!comparison) startComparison(message);
  comparison.heading.textContent = message.ask;
  comparison.waiting.remove();
  const list = document.createElement("div");
  list.dataset.testid = "comparison-options";
  // The options are a group, and the question is its name: a screen reader then
  // announces what is being asked before it reads the first option.
  list.className = "pair";
  list.setAttribute("role", "radiogroup");
  list.setAttribute("aria-labelledby", comparison.heading.id);
  // The options arrive in the order the server committed to. Nothing here says
  // which condition an option is: the handle is opaque and the label is the
  // participant's own run. Both cells are one grid with one track rule, they
  // stretch together, and both badges are the same ink, so the layout carries
  // no signal either way.
  const letters = "ABCDEFGH";
  message.options.forEach((option, at) => {
    const cell = document.createElement("label");
    cell.className = "option option--pick";
    cell.dataset.handle = option.handle;
    const input = document.createElement("input");
    input.type = "radio";
    input.name = "comparison-choice";
    input.value = option.handle;
    cell.appendChild(input);

    const top = document.createElement("div");
    top.className = "option__head";
    const badge = document.createElement("span");
    badge.className = "badge badge--lg";
    badge.textContent = letters[at] ?? String(at + 1);
    top.appendChild(badge);
    const name = document.createElement("span");
    name.className = "option__name";
    // An option shows what it recorded: a run shows how long it went and what it
    // earned, a model output shows the text it produced. Neither says which
    // condition it was, which is the whole point of the blinding.
    const body = document.createElement("div");
    body.className = "option__text";
    if (typeof option.text === "string") {
      name.textContent = `Option ${badge.textContent}`;
      body.textContent = option.text;
    } else {
      const summary = option.summary || {};
      name.textContent = `Round ${option.played}`;
      body.textContent = `${summary.frames} frames, score ${summary.reward}`;
    }
    top.appendChild(name);
    cell.appendChild(top);
    cell.appendChild(body);

    const pick = document.createElement("div");
    pick.className = "option__pick";
    const dot = document.createElement("span");
    dot.className = "option__dot";
    dot.setAttribute("aria-hidden", "true");
    dot.textContent = "✓";
    pick.appendChild(dot);
    const word = document.createElement("span");
    word.textContent = "Choose this one";
    pick.appendChild(word);
    cell.appendChild(pick);

    input.addEventListener("change", () => {
      submit.disabled = false;
      submit.textContent = `Send: option ${badge.textContent}`;
    });
    list.appendChild(cell);
  });
  comparison.panel.appendChild(list);

  // One submit. The choice is made on the option, which is where the
  // participant is already looking; the button says which one it will send, so
  // nobody has to look back up the panel to check what they picked.
  const foot = document.createElement("div");
  foot.className = "panel__foot";
  const submit = button("Pick one above", "btn--primary");
  submit.dataset.testid = "comparison-submit";
  submit.disabled = true;
  submit.addEventListener("click", () => {
    const picked = list.querySelector("input:checked");
    if (picked) answerComparison(picked.value);
  });
  foot.appendChild(submit);
  comparison.panel.appendChild(foot);
  comparison.list = list;
  comparison.submit = submit;
}

function answerComparison(handle) {
  // The key is minted once per answer and reused on a retry, so a dropped receipt
  // costs the participant nothing: the server replays the first response.
  if (!comparison.key) comparison.key = idempotencyKey();
  for (const input of comparison.list.querySelectorAll("input")) {
    input.disabled = true;
  }
  if (comparison.submit) comparison.submit.disabled = true;
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
  for (const input of comparison.list.querySelectorAll("input")) {
    input.disabled = false;
  }
  if (comparison.submit) comparison.submit.disabled = false;
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

// How large a picture is when the study says nothing: what every game was drawn
// at before a study could say how large its own picture is.
const DRAWN_AT = [600, 400];

// How large the picture is, as the study said it, in pixels.
function sizeOf(size) {
  if (!Array.isArray(size) || size.length !== 2) return DRAWN_AT;
  const [wide, tall] = size;
  return wide > 0 && tall > 0 ? [wide, tall] : DRAWN_AT;
}

// The game on the screen now and how large it is drawn, so the picture is fitted
// again when the window changes size.
let fitting = null;

// Draw the picture at the size the study said, and **smaller** when there is not
// room for it. It is never drawn larger: a drawing is relative, so a kitchen of
// five squares by four put into somebody else's 600 by 400 is a picture larger
// than the game in it with every square stretched to a shape its sprites are not.
function fitCanvas() {
  if (fitting === null) return;
  const { canvas, container, body, size } = fitting;
  const style = getComputedStyle(body);
  const sides =
    parseFloat(style.paddingLeft || 0) + parseFloat(style.paddingRight || 0);
  // What the picture may fill. A pane is a box of its own and says how wide it is
  // and where it ends; a game that owns the whole screen is bounded by the
  // **window** instead, because the sheet it is drawn in is only as large as what
  // is in it -- so asking the sheet would be asking the picture how big the
  // picture is allowed to be, and it would keep whatever size it already had.
  const box = container.getBoundingClientRect();
  const room = panes
    ? Math.max(160, body.clientWidth - sides)
    : Math.max(160, window.innerWidth - box.left - sides);
  const floor = panes
    ? body.getBoundingClientRect().bottom - parseFloat(style.paddingBottom || 0)
    : window.innerHeight - 24;
  const tall = Math.max(120, floor - box.top);
  // One scale for both sides, so a picture that has to shrink keeps its shape.
  const part = Math.min(1, room / size[0], tall / size[1]);
  const wide = Math.round(size[0] * part);
  const high = Math.round(size[1] * part);
  container.style.width = `${wide}px`;
  canvas.style.width = `${wide}px`;
  canvas.style.height = `${high}px`;
  // The canvas holds real device pixels, so the picture is drawn at the size it is
  // shown at rather than blown up from a smaller one. It is capped, because past
  // two the pixels cost memory and nobody can see them.
  const density = Math.min(window.devicePixelRatio || 1, 2);
  if (renderer && renderer.resize) {
    renderer.resize(Math.round(wide * density), Math.round(high * density));
  }
}

function mountCanvas(caption, size) {
  const host = clear(gameHost());
  const body = document.createElement("div");
  // A game is not prose. The reading column is right for what is **written**
  // beside the picture and wrong for the picture: a canvas held to 44rem is a
  // postage stamp on a wide screen, and it was already being squashed to that
  // width with its height left where it was, so every square was distorted.
  body.className = panes ? "pane__body" : "sheet sheet--game";
  host.appendChild(body);
  // What the participant reads while they play is the study's to write. The
  // client used to ship one study's instructions to every study it ran.
  if (caption) {
    const legend = document.createElement("div");
    legend.dataset.testid = "game-caption";
    legend.className = "prose";
    legend.style.maxWidth = "600px";
    legend.style.margin = "0 0 0.75rem";
    renderMarkdown(legend, caption, assets);
    body.appendChild(legend);
    // A caption with pictures in it is one line tall until they arrive and two
    // afterwards, so the picture is fitted again as each one lands. Without this
    // the first round is fitted to a caption that has not finished being written.
    for (const picture of legend.querySelectorAll("img")) {
      picture.addEventListener("load", fitCanvas);
    }
  }
  const drawn = sizeOf(size);
  const canvas = document.createElement("canvas");
  canvas.width = drawn[0];
  canvas.height = drawn[1];
  canvas.className = "canvas";
  // The canvas takes focus, because in a composed activity the keyboard belongs
  // to whichever pane has it. Without this the participant could leave the
  // message box and have nowhere to go back to.
  canvas.tabIndex = 0;
  canvas.setAttribute("aria-label", "The game");
  // The container is the positioning context for the countdown overlay, so the
  // countdown sits on top of the canvas and never takes its own layout space.
  gameContainer = document.createElement("div");
  gameContainer.style.position = "relative";
  gameContainer.style.maxWidth = "100%";
  gameContainer.appendChild(canvas);
  body.appendChild(gameContainer);
  renderer = createRenderer(canvas, {
    assets,
    logical: { w: canvas.width, h: canvas.height },
  });
  fitting = { canvas, container: gameContainer, body, size: drawn };
  fitCanvas();
  window.addEventListener("resize", fitCanvas);
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
// A pane's head: what it is, and whether the keys are going to it. The badge is
// the answer beside the thing it is about, so a participant who presses a key
// and sees nothing move does not have to look elsewhere to find out why.
function paneHead(name, on, off) {
  const head = document.createElement("div");
  head.className = "pane__head";
  const label = document.createElement("span");
  label.className = "pane__name";
  label.textContent = name;
  const badge = document.createElement("span");
  badge.className = "pane__badge";
  badge.dataset.on = on;
  badge.dataset.off = off;
  badge.textContent = off;
  head.appendChild(label);
  head.appendChild(badge);
  return head;
}

function mountPanes(placement) {
  app.innerHTML = "";
  const frame = document.createElement("div");
  frame.dataset.testid = "composed";
  frame.dataset.placement = placement;
  frame.className = "panes";
  // Beside the canvas by default, and below it on a narrow screen, because a rail
  // squeezed to nothing is worse than a transcript underneath.
  const beside = placement === "beside" && window.innerWidth >= 760;
  if (!beside) frame.style.gridTemplateColumns = "minmax(0, 1fr)";

  const game = document.createElement("section");
  game.dataset.testid = "game-pane";
  game.dataset.pane = "game";
  game.className = "pane";
  game.setAttribute("aria-label", "The game");
  const chat = document.createElement("section");
  chat.dataset.testid = "chat-pane";
  chat.dataset.pane = "chat";
  chat.className = "pane";
  chat.setAttribute("aria-label", "The conversation");
  frame.appendChild(game);
  frame.appendChild(chat);

  // Which pane has the keyboard, said out loud. A participant whose arrow keys
  // stopped working needs to be able to see why, not guess. It is a badge in
  // each pane's head as well, so the answer is beside the thing it is about.
  const where = document.createElement("p");
  where.dataset.testid = "focus-hint";
  where.setAttribute("role", "status");
  where.setAttribute("aria-live", "polite");
  where.className = "hint";
  app.appendChild(frame);
  app.appendChild(where);

  game.appendChild(paneHead("The game", "Your keys play", "The game is paused"));
  chat.appendChild(paneHead("The conversation", "Your keys write here", "Not writing"));

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
  const input = panes.chat.querySelector("[name=message]");
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
    const mine = pane === held;
    pane.classList.toggle("pane--held", mine);
    const badge = pane.querySelector(".pane__badge");
    if (badge) badge.textContent = mine ? badge.dataset.on : badge.dataset.off;
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
  // The server holds the bindings and counts the presses, so nothing here has to.
  browserManifest = null;
  inputScheme = "pressed_keys";
  // One activity may run several rounds, and the server announces the activity
  // once: the rounds after the first arrive as frames alone. The rest between
  // them tears the canvas down, so what mounted it is kept to mount it again.
  playing = delivery;
  mountCanvas(delivery.caption, delivery.size);
  await countdown(delivery.countdown);
}

// Begin downloading Pyodide and the packages as soon as the study announces the
// bundle, so the download overlaps with the forms. The returned promise is what
// the game start awaits, so the participant cannot reach a blank canvas.
function startPreload(manifest) {
  if (preloadPromise) return;
  preloadPromise = preloadBrowserGame(manifest, {
    onStatus: (text) => report(text, true),
    assets,
  });
  preloadPromise.catch(() => report("failed to load the python runtime", false));
}

// Run the environment in the browser through Pyodide, then report the finished
// run over game.capture. The server validates and commits it under a fence. The
// game waits on the preload, so it never starts before the runtime is ready.
async function startBrowserGame(delivery) {
  inputMode = "browser";
  browserManifest = delivery.manifest;
  inputScheme = delivery.manifest.input_mode ?? "pressed_keys";
  taps.length = 0;
  mountCanvas(delivery.caption, delivery.size);
  try {
    startPreload(delivery.manifest);
    report("preparing the environment...", true);
    const runtime = await preloadPromise;
    await countdown(delivery.countdown);
    // Each slice is reported as it is played. A participant who shuts the tab
    // part-way through then leaves the frames they played rather than nothing,
    // which is what an episode held until the end always cost.
    await playBrowserEpisode(runtime, delivery.manifest, {
      renderer,
      pressed,
      taps,
      onStatus: (text) => report(text, true),
      onPart: (part) =>
        sendCommand("game.capture", {
          episode: part.boundary
            ? { transitions: part.transitions, boundary: part.boundary }
            : { transitions: part.transitions },
          actions: part.actions,
          partner_actions: part.partner_actions,
          first_frame: part.first_frame,
          final: part.final,
          generation: 1,
        }),
    });
  } catch (error) {
    report(`browser environment failed: ${error}`, false);
  }
}

function stopGame() {
  window.removeEventListener("keydown", onKeyDown);
  window.removeEventListener("keyup", onKeyUp);
  window.removeEventListener("resize", fitCanvas);
  fitting = null;
  pressed.clear();
  taps.length = 0;
  renderer = null;
}

// The screen between rounds of one game activity. It is participant-paced: the
// server holds the next round until this says to go on, because a rest that ends
// while someone is still reading is not a rest.
function renderInterval(message) {
  // Only the game pane is repainted. In a composed activity the conversation is
  // not paused by the screen between rounds: the room belongs to the activity, and
  // a rest from the game is not a rest from the person you are playing with.
  // The pane's own head -- what the pane is, and where the keys are going -- is
  // not the round's, so it is kept. `clear` is what keeps it; the rest screen was
  // the one place that emptied the pane by hand, and the badge never came back.
  clear(gameHost());
  // The rest owns everything it puts on the screen, in one element. It is removed
  // whole when the next round mounts, so a composed activity's conversation pane
  // is not swept up with it -- the rest is drawn beside the panes, not inside one.
  const rest = document.createElement("div");
  rest.dataset.testid = "between-rounds";
  const heading = document.createElement("h2");
  heading.textContent = `Round ${message.round} of ${message.of}`;
  rest.appendChild(heading);
  if (message.markdown) {
    const body = document.createElement("div");
    body.style.maxWidth = "44rem";
    body.style.textAlign = "left";
    body.style.margin = "0 auto";
    body.tabIndex = 0;
    body.setAttribute("role", "region");
    body.setAttribute("aria-label", "Between rounds");
    renderMarkdown(body, message.markdown, assets);
    rest.appendChild(body);
  }
  const next = document.createElement("button");
  next.textContent = "Continue";
  next.addEventListener("click", () => {
    socket.send(JSON.stringify({ type: "interval_done" }));
    // The next round is the same activity, so the server announces nothing more:
    // it steps and pushes frames. The screen those frames need is built here,
    // from the delivery that opened the activity. Without it a study of several
    // rounds played the first one and then showed this rest screen for the whole
    // of every round after it.
    startNextRound(rest);
  });
  rest.appendChild(next);
  app.appendChild(rest);
  next.focus();
}

// Mount the game screen again for the round the participant just asked for.
async function startNextRound(rest) {
  if (rest) rest.remove();
  if (!playing) return;
  if (playing.chat) await startComposed(playing, true);
  else if (playing.mode === "browser") await startBrowserGame(playing);
  else await startServerGame(playing);
}

function sendInput() {
  socket.send(JSON.stringify({ type: "input", keys: [...pressed] }));
}

function onKeyDown(event) {
  if (typing()) return;
  if (event.key === "ArrowLeft" || event.key === "ArrowRight") event.preventDefault();
  if (!pressed.has(event.key)) {
    // A press is counted when the key **arrives**, not while it is held. The
    // browser repeats key down events for a held key; those are not new presses
    // and a study counting presses must not read them as more.
    pressed.add(event.key);
    if (inputScheme === "single_keystroke" && taps.length < 8) {
      const action = tapAction(event.key);
      if (action !== null) taps.push(action);
    }
    if (inputMode === "server") sendInput();
  }
}

// What one press is worth, or null when the key is bound to nothing. This is the
// browser twin of `InputState._tap`, and the two must agree: a browser run is
// verified by re-executing it on the server.
//
// The press is the key that **arrived**, not the first key that happens to be
// down, so holding an arrow and then tapping the pick-up key is one move and one
// pick-up. A chord wins when the arrival completes one, which is what makes "up
// while left is held" the diagonal rather than the up.
function tapAction(arrived) {
  const manifest = browserManifest;
  if (!manifest) return null;
  const bindings = manifest.action_bindings;
  let bestSize = 0;
  let best = null;
  for (const chord of manifest.action_chords ?? []) {
    if (!chord.keys.every((key) => pressed.has(key))) continue;
    if (!chord.keys.includes(arrived)) continue;
    if (chord.keys.length > bestSize) {
      bestSize = chord.keys.length;
      best = chord.action;
    }
  }
  if (best !== null) return best;
  return arrived in bindings ? bindings[arrived] : null;
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
  const at = clear(host);

  // A standalone conversation owns the screen, so it scrolls the thread and
  // docks what the participant writes at the foot. Inside a pane the pane is
  // already the frame, so the same parts sit in it without a second one.
  const scroll = document.createElement("div");
  scroll.className = composed ? "pane__body" : "scroll";
  const thread = document.createElement("div");
  thread.className = composed ? "" : "thread";
  const scrollDown = () => {
    scroll.scrollTop = scroll.scrollHeight;
  };

  const tabs = document.createElement("div");
  tabs.setAttribute("role", "tablist");
  tabs.dataset.testid = "chat-channels";
  tabs.className = "channels";
  tabs.hidden = true;
  thread.appendChild(tabs);

  const transcript = document.createElement("div");
  transcript.setAttribute("role", "log");
  transcript.setAttribute("aria-label", "Conversation");
  transcript.dataset.testid = "chat-transcript";
  transcript.className = "log";
  thread.appendChild(transcript);
  scroll.appendChild(thread);
  at.appendChild(scroll);

  const dock = document.createElement("div");
  dock.className = composed ? "pane__foot" : "dock";
  const form = document.createElement("form");
  form.className = "composer";
  // The box grows to what is written and stops. A held size tells a participant
  // to write one line; an unbounded one pushes the conversation off the screen.
  const input = document.createElement("textarea");
  input.name = "message";
  input.rows = 1;
  input.autocomplete = "off";
  input.placeholder = "Write a message";
  input.setAttribute("aria-label", "Your message");
  const send = document.createElement("button");
  send.type = "submit";
  send.className = "send";
  send.disabled = true;
  send.setAttribute("aria-label", "Send");
  send.innerHTML =
    '<svg width="15" height="15" viewBox="0 0 16 16" fill="none" aria-hidden="true">' +
    '<path d="M8 13V3.5M8 3.5 3.8 7.7M8 3.5l4.2 4.2" stroke="currentColor" ' +
    'stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round"/></svg>';
  form.appendChild(input);
  form.appendChild(send);
  dock.appendChild(form);

  function grow() {
    input.style.height = "auto";
    input.style.height = `${Math.min(input.scrollHeight, 160)}px`;
    send.disabled = input.value.trim() === "";
  }
  input.addEventListener("input", grow);
  // Return sends and shift with return breaks the line, which is what a person
  // who has used any other message box expects.
  input.addEventListener("keydown", (event) => {
    if (event.key === "Enter" && !event.shiftKey) {
      event.preventDefault();
      form.requestSubmit();
    }
  });

  // Only a standalone conversation is ended by the participant. A composed
  // activity ends when its rounds end, so leaving the conversation early would
  // leave them playing a game they can no longer talk about.
  const leave = button("End the conversation", "btn--quiet btn--small");
  if (!composed) {
    const hint = document.createElement("p");
    hint.className = "hint";
    hint.textContent = "Return sends. Shift and return make a new line.";
    dock.appendChild(hint);
    const foot = document.createElement("div");
    foot.className = "hint";
    foot.appendChild(leave);
    dock.appendChild(foot);
  }
  at.appendChild(dock);
  grow();

  // One channel is shown at a time. A message that belongs to another channel is
  // held rather than dropped, so moving to it shows what was said there.
  const lines = new Map();
  let current = chatChannels[0] ?? null;
  // The placeholder that stands where a reply is going to be, or null when the
  // conversation is not waiting for one.
  let pending = null;

  function show(channel) {
    current = channel;
    transcript.innerHTML = "";
    for (const line of lines.get(channel) ?? []) transcript.appendChild(line);
    scrollDown();
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
      // One channel says nothing, so it is not drawn. A channel this
      // participant is not in never arrives, so it can not be drawn either.
      tabs.hidden = keys.length < 2;
      if (keys.length < 2) return;
      for (const key of keys) {
        const tab = document.createElement("button");
        tab.type = "button";
        tab.setAttribute("role", "tab");
        tab.dataset.channel = key;
        tab.textContent = key;
        tab.addEventListener("click", () => show(key));
        tabs.appendChild(tab);
      }
      show(current);
    },
    append(author, text, channel) {
      // The reply has arrived, so what stood in for it goes.
      if (author !== "you") this.waiting(false);
      const key = channel ?? current;
      const line = turn(author, author === "you" ? "You" : "Them");
      line.dataset.channel = key ?? "";
      line.querySelector(".bubble").append(text);
      const held = lines.get(key) ?? [];
      held.push(line);
      lines.set(key, held);
      if (key === current || current === null) {
        transcript.appendChild(line);
        scrollDown();
      }
    },
    // What the screen says between a message and its reply. A model on a local
    // runner takes seconds to answer, and a pane that shows nothing at all while
    // it thinks reads as a broken study rather than a slow one.
    waiting(on) {
      if (on) {
        if (pending) return;
        // It is the same bubble the words will arrive in, so nothing on the
        // screen moves when they do.
        pending = turn("them", "Them");
        pending.dataset.testid = "chat-waiting";
        const dots = document.createElement("span");
        dots.className = "dots";
        dots.setAttribute("role", "status");
        dots.setAttribute("aria-label", "Waiting for a reply");
        dots.innerHTML = "<span></span><span></span><span></span>";
        pending.querySelector(".bubble").appendChild(dots);
        transcript.appendChild(pending);
        scrollDown();
        return;
      }
      if (pending) pending.remove();
      pending = null;
    },
    // A reply that is never coming. The mount says so rather than leaving the
    // participant to work it out from an empty pane. It is not a bubble,
    // because nobody said it.
    notice(text) {
      this.waiting(false);
      const line = document.createElement("div");
      line.className = "notice";
      line.dataset.testid = "chat-notice";
      line.setAttribute("role", "status");
      const mark = document.createElement("b");
      mark.setAttribute("aria-hidden", "true");
      mark.textContent = "!";
      line.appendChild(mark);
      const words = document.createElement("span");
      words.textContent = text;
      line.appendChild(words);
      transcript.appendChild(line);
      scrollDown();
    },
    // Put something the conversation is asking at the end of the conversation,
    // where the last thing said is. A panel appended to the screen lands under
    // the message box, and then it reads as a question about something else.
    ask(panel) {
      scroll.appendChild(panel);
      scrollDown();
    },
    // Stop the participant writing, and say why. The box is left on the screen
    // rather than taken away: a box that vanishes leaves a hole where the thing
    // they were about to use was.
    hold(on, why) {
      input.disabled = Boolean(on);
      send.disabled = Boolean(on) || input.value.trim() === "";
      input.placeholder = on ? (why ?? "") : "Write a message";
    },
    close() {
      this.waiting(false);
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
    // Only a conversation that is the whole activity is owed a reply, so only it
    // says one is coming. Beside a game the other party is a **player**: it
    // answers when it is free and it is allowed to say nothing at all, so a
    // "typing" bubble raised by every message is a promise nobody made -- and one
    // the participant then watches for the rest of the round.
    if (!composed) chat.waiting(true);
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
  // The conversation goes on, so the participant may write again.
  if (chat) chat.hold(false);
}

function candidateAnswer(verdict, handle) {
  if (!candidates) return;
  const ratings = [];
  // An axis nobody answered sends nothing. The scales start with no mark, so a
  // value here means somebody put it there; a control parked in the middle used
  // to send the middle and record a judgement that was never given.
  for (const [key, control] of candidates.axes) {
    if (control.scope === "each") {
      for (const [option, cells] of control.each) {
        const picked = cells.querySelector("input:checked");
        if (picked) ratings.push({ axis: key, option, value: Number(picked.value) });
      }
      continue;
    }
    const picked = control.input?.querySelector("input:checked");
    if (!picked) continue;
    const value = Number(picked.value);
    if (value === 0) {
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

function candidateAxis(axis, order, panel, letters) {
  // One axis, drawn by what it asks for: a comparison between the two replies,
  // or one scale per reply. Either way the answer names a reply and never a
  // position.
  //
  // It is a row of cells with nothing chosen, not a slider. A slider has to
  // start somewhere, so a participant who never touches it still sends the
  // value it started on and the study records a judgement nobody gave.
  const block = document.createElement("fieldset");
  block.className = "axis";
  block.dataset.testid = "chat-axis";
  block.dataset.axis = axis.key;
  const legend = document.createElement("legend");
  legend.className = "axis__ask";
  legend.textContent = axis.ask;
  block.appendChild(legend);
  const each = new Map();
  const readout = document.createElement("div");
  readout.className = "readout";
  readout.setAttribute("role", "status");

  function cellRow(name, values, say) {
    const cells = document.createElement("div");
    cells.className = "cells";
    for (const [value, middle] of values) {
      const wrap = document.createElement("label");
      if (middle) {
        wrap.dataset.middle = "";
        wrap.append("=");
      }
      const one = document.createElement("input");
      one.type = "radio";
      one.name = name;
      one.value = String(value);
      one.dataset.axis = axis.key;
      one.setAttribute("aria-label", say(value));
      // The screen says back what was answered, in words. A mark on a row of
      // cells is never the only record of what somebody meant.
      one.addEventListener("change", () => {
        readout.textContent = `You said: ${say(value)}`;
        readout.classList.add("readout--set");
      });
      wrap.appendChild(one);
      cells.appendChild(wrap);
    }
    return cells;
  }

  if (axis.scope === "each") {
    const grid = document.createElement("div");
    grid.className = "each";
    order.forEach((handle, at) => {
      const letter = letters[at] ?? String(at + 1);
      const one = document.createElement("fieldset");
      one.className = "axis";
      one.style.margin = "0";
      const head = document.createElement("legend");
      head.className = "each__head";
      const badge = document.createElement("span");
      badge.className = "badge";
      badge.textContent = letter;
      head.appendChild(badge);
      const name = document.createElement("span");
      name.className = "each__name";
      name.textContent = `Reply ${letter}`;
      head.appendChild(name);
      one.appendChild(head);
      const values = [];
      for (let n = 1; n <= axis.points; n++) values.push([n, false]);
      const row = cellRow(
        `axis-${axis.key}-${handle}`,
        values,
        (n) => `Reply ${letter} is ${n} of ${axis.points}`,
      );
      // The cells carry their number, because an absolute scale is a number.
      row.querySelectorAll("label").forEach((wrap, n) => wrap.append(String(n + 1)));
      one.appendChild(row);
      one.appendChild(ends(axis.low ?? "Not at all", axis.high ?? "Exactly"));
      one.appendChild(readoutFor(one));
      grid.appendChild(one);
      each.set(handle, row);
    });
    block.appendChild(grid);
    panel.appendChild(block);
    return { input: null, scope: "each", each };
  }

  const first = letters[0] ?? "A";
  const second = letters[1] ?? "B";
  const values = [];
  for (let n = -axis.points; n <= axis.points; n++) values.push([n, n === 0]);
  const scale = document.createElement("div");
  scale.className = "scale";
  scale.appendChild(scaleEnd(first));
  const row = cellRow(`axis-${axis.key}`, values, (n) =>
    n === 0
      ? "they are the same"
      : `Reply ${n < 0 ? first : second} is ${Math.abs(n)} of ${axis.points} more`,
  );
  scale.appendChild(row);
  scale.appendChild(scaleEnd(second));
  block.appendChild(scale);
  block.appendChild(readout);
  panel.appendChild(block);
  return { input: row, scope: axis.scope ?? "pair", each };

  function readoutFor(host) {
    const one = document.createElement("div");
    one.className = "readout";
    one.setAttribute("role", "status");
    host.querySelectorAll("input").forEach((input) => {
      input.addEventListener("change", () => {
        one.textContent = `You said: ${input.getAttribute("aria-label")}`;
        one.classList.add("readout--set");
      });
    });
    return one;
  }
}

// The two ends of a comparison carry the same badges as the two replies, so
// which end is which is read and not remembered.
function scaleEnd(letter) {
  const end = document.createElement("span");
  end.className = "scale__end";
  const badge = document.createElement("span");
  badge.className = "badge";
  badge.textContent = letter;
  end.appendChild(badge);
  end.append("more");
  return end;
}

function ends(low, high) {
  const row = document.createElement("div");
  row.className = "ends";
  const left = document.createElement("span");
  left.textContent = low;
  const right = document.createElement("span");
  right.textContent = high;
  row.appendChild(left);
  row.appendChild(right);
  return row;
}

function renderCandidateReplies(message) {
  closeCandidateReplies();
  const panel = document.createElement("section");
  panel.dataset.testid = "chat-candidates";
  panel.className = "panel";
  const head = document.createElement("div");
  head.className = "panel__head";
  head.appendChild(sectionKey("A judgement"));
  const ask = document.createElement("h2");
  ask.className = "panel__ask";
  ask.id = "chat-candidates-ask";
  ask.textContent = message.ask;
  head.appendChild(ask);
  const note = document.createElement("div");
  note.className = "panel__note";
  note.textContent = "The conversation goes on from the one you choose.";
  head.appendChild(note);
  panel.appendChild(head);

  // The work runs 1 read and pick, 2 compare, then send. A participant should
  // never have to work out what to do first.
  const readBlock = document.createElement("div");
  readBlock.className = "block block--flush";
  const readHead = document.createElement("div");
  readHead.className = "block__head";
  readHead.appendChild(sectionKey("Read both, and pick the one you want", 1));
  readBlock.appendChild(readHead);

  const list = document.createElement("div");
  list.dataset.testid = "chat-candidate-options";
  // The two replies are one grid with one track rule, they stretch together,
  // and both badges are the same ink. The order is the server's, and the
  // answer names the handle rather than the side of the screen.
  list.className = "pair";
  list.setAttribute("role", "radiogroup");
  list.setAttribute("aria-labelledby", ask.id);
  const order = [];
  const letters = "ABCDEFGH";
  (message.options ?? []).forEach((option, at) => {
    order.push(option.handle);
    const letter = letters[at] ?? String(at + 1);
    const cell = document.createElement("label");
    cell.className = "option option--pick";
    cell.dataset.handle = option.handle;
    const input = document.createElement("input");
    input.type = "radio";
    input.name = "candidate-choice";
    input.value = option.handle;
    cell.appendChild(input);
    const top = document.createElement("div");
    top.className = "option__head";
    const badge = document.createElement("span");
    badge.className = "badge badge--lg";
    badge.textContent = letter;
    top.appendChild(badge);
    const name = document.createElement("span");
    name.className = "option__name";
    name.textContent = `Reply ${letter}`;
    top.appendChild(name);
    cell.appendChild(top);
    const body = document.createElement("div");
    body.className = "option__text";
    body.textContent = option.text;
    cell.appendChild(body);
    const pick = document.createElement("div");
    pick.className = "option__pick";
    const dot = document.createElement("span");
    dot.className = "option__dot";
    dot.setAttribute("aria-hidden", "true");
    dot.textContent = "✓";
    pick.appendChild(dot);
    const word = document.createElement("span");
    word.textContent = "Choose this reply";
    pick.appendChild(word);
    cell.appendChild(pick);
    input.addEventListener("change", () => {
      send.disabled = false;
      send.textContent = `Go on with Reply ${letter}`;
    });
    list.appendChild(cell);
  });
  readBlock.appendChild(list);
  panel.appendChild(readBlock);

  const axes = new Map();
  if ((message.axes ?? []).length) {
    const axisBlock = document.createElement("div");
    axisBlock.className = "block";
    const axisHead = document.createElement("div");
    axisHead.className = "block__head";
    axisHead.appendChild(sectionKey("How do they compare?", 2));
    axisBlock.appendChild(axisHead);
    for (const axis of message.axes ?? []) {
      axes.set(axis.key, candidateAxis(axis, order, axisBlock, letters));
    }
    panel.appendChild(axisBlock);
  }

  const foot = document.createElement("div");
  foot.className = "panel__foot";
  const send = button("Pick a reply above", "btn--primary");
  send.disabled = true;
  send.dataset.testid = "chat-candidate-send";
  send.addEventListener("click", () => {
    const picked = list.querySelector("input:checked");
    if (picked) candidateAnswer("choice", picked.value);
  });
  foot.appendChild(send);
  if (message.ties) {
    for (const [verdict, label] of [
      ["tie", "They are about the same"],
      ["both-bad", "Both are bad"],
    ]) {
      const one = button(label, "btn--small");
      one.dataset.verdict = verdict;
      // A tie still has to resolve to the reply the thread goes on with, and the
      // one they read first is the honest choice for it.
      one.addEventListener("click", () => candidateAnswer(verdict, order[0]));
      foot.appendChild(one);
    }
  }
  if (message.skippable) {
    const skip = button("Skip this one", "btn--quiet btn--small");
    skip.dataset.testid = "chat-candidate-skip";
    skip.style.marginLeft = "auto";
    skip.addEventListener("click", () => {
      socket.send(JSON.stringify({ type: "chat_candidate_skip" }));
      closeCandidateReplies();
    });
    foot.appendChild(skip);
  }
  panel.appendChild(foot);
  // The judgement is a turn in the conversation, so it goes at the end of the
  // conversation. Appending it to the screen put it *under* the message box,
  // which read as a question about something further down the page.
  if (chat) {
    chat.ask(panel);
    // Nothing can be written until a reply is chosen, because the next thing
    // the participant says follows from the one they pick. The box stays on
    // screen and says why, rather than going away and leaving a gap.
    chat.hold(true, "Choose a reply above to go on");
  } else {
    app.appendChild(panel);
  }
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
    // The activity is over, so the round it could still mount is over with it.
    playing = null;
    if (renderer) stopGame();
  }
  if (delivery.kind !== "comparison") comparison = null;
  if (delivery.kind === "form") renderForm(delivery);
  else if (delivery.kind === "comparison") startComparison(delivery);
  else if (delivery.kind === "content") renderContent(delivery);
  // A conversation is its own activity kind. The mode on a game is the older
  // spelling and still arrives, so both reach the same screen.
  else if (delivery.kind === "chat") startChat();
  else if (delivery.kind === "game" && delivery.mode === "chat") startChat();
  else if (delivery.kind === "game" && delivery.chat) startComposed(delivery);
  else if (delivery.kind === "game" && delivery.mode === "browser") startBrowserGame(delivery);
  else if (delivery.kind === "game") startServerGame(delivery);
  else if (delivery.kind === "complete") renderComplete(delivery);
}

// One activity that is a game and a conversation at once. The conversation is
// mounted first, so a message that arrives while the countdown is still running
// has somewhere to land.
// `again` is a later round of an activity already on the screen. The two panes are
// left standing and only the game is mounted again, because the conversation is the
// **activity's** and not the round's: what the pair have said to each other is still
// true in the next round, and the model they are talking to still remembers it.
// Building the panes again would replace the transcript with an empty one, so the
// participant would read "you can carry on the same conversation" on the rest screen
// and then watch it disappear.
async function startComposed(delivery, again = false) {
  if (!again || !panes) {
    const placement = delivery.chat.placement ?? "beside";
    startChat(mountPanes(placement).chat);
  }
  if (delivery.mode === "browser") {
    await startBrowserGame(delivery);
    return;
  }
  await startServerGame(delivery);
}

function renderComplete(delivery) {
  // The visit is finished; clear the resume token so a later visit starts fresh.
  localStorage.removeItem("mug_resume_token");
  const sheet = clear();
  sheet.className = "";
  const done = document.createElement("div");
  done.className = "sheet done";
  const heading = document.createElement("h1");
  heading.textContent = "All done. Thank you.";
  done.appendChild(heading);
  if (delivery.completion_code) {
    // The code is what the participant is paid on, so it is the largest thing
    // on the screen and it selects in one press.
    const note = document.createElement("p");
    note.className = "panel__note";
    note.textContent = "Copy this code before you close the page.";
    done.appendChild(note);
    const code = document.createElement("p");
    const value = document.createElement("span");
    value.className = "code";
    value.textContent = delivery.completion_code;
    code.appendChild(value);
    done.appendChild(code);
  }
  if (delivery.return_url) {
    const actions = document.createElement("div");
    actions.className = "actions";
    actions.style.justifyContent = "center";
    const link = document.createElement("a");
    link.className = "btn btn--primary";
    link.href = delivery.return_url;
    link.textContent = "Return to the study";
    actions.appendChild(link);
    done.appendChild(actions);
  }
  sheet.appendChild(done);
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
      // A frame that arrives with no canvas to draw it on is a fault, and it used
      // to be dropped without a word: every round after the first of a study with
      // `episodes=N` was pushed, dropped here, and never seen. It is reported now,
      // so the same fault cannot be silent twice.
      if (renderer) renderer.draw(message.packet);
      else report("a game frame arrived with no canvas to draw it on", false);
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
      if (chat) chat.waiting(true);
    } else if (message.type === "chat_notice") {
      // A reply that is not coming. Saying so is the difference between a study
      // that is slow and one the participant can tell is broken.
      if (chat) chat.notice(message.message ?? "The assistant could not reply.");
    } else if (message.type === "chat_candidates") {
      if (chat) chat.waiting(false);
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

// The debug drawer, when the server is in debug mode. It is asked for once and
// built beside everything else, so it survives a round ending, an activity
// changing, and a reconnection -- all of which repaint the study's own screen.
void debugIfServed(document.body);
