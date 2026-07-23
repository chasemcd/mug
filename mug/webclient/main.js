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
}

function sendAdvance(answers) {
  sendCommand("flow.advance", { answers });
}

// --- form and content rendering ------------------------------------------

function renderForm(delivery) {
  const spec = delivery.form;
  app.innerHTML = "";
  const form = document.createElement("form");
  const heading = document.createElement("h2");
  heading.textContent = spec.form_key;
  form.appendChild(heading);

  for (const field of spec.fields) {
    const label = document.createElement("label");
    label.textContent = field.label;
    label.style.display = "block";
    label.style.margin = "0.75rem 0 0.25rem";
    form.appendChild(label);

    if (field.kind === "choice") {
      for (const option of field.options) addRadio(form, field.field_key, option);
    } else if (field.kind === "likert") {
      for (let n = 1; n <= field.scale; n++) addRadio(form, field.field_key, String(n));
    } else {
      const input = document.createElement("input");
      input.type = "text";
      input.name = field.field_key;
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

function addRadio(form, name, value) {
  const wrap = document.createElement("label");
  wrap.style.marginRight = "1rem";
  const input = document.createElement("input");
  input.type = "radio";
  input.name = name;
  input.value = value;
  wrap.appendChild(input);
  wrap.append(` ${value}`);
  form.appendChild(wrap);
}

function renderContent(delivery) {
  app.innerHTML = "";
  const pre = document.createElement("pre");
  pre.textContent = delivery.content.body.text || "";
  pre.style.whiteSpace = "pre-wrap";
  app.appendChild(pre);
  const next = document.createElement("button");
  next.textContent = "Continue";
  next.addEventListener("click", () => sendAdvance({}));
  app.appendChild(next);
}

// --- game mode -----------------------------------------------------------

// The input mode: "server" sends key frames to the server loop; "browser" keeps
// the pressed keys local for the in-browser stepping loop.
let inputMode = "server";

function mountCanvas() {
  app.innerHTML = "";
  const heading = document.createElement("p");
  heading.textContent = "Use the left and right arrow keys to reach the flag.";
  app.appendChild(heading);
  const canvas = document.createElement("canvas");
  canvas.width = 600;
  canvas.height = 400;
  canvas.style.background = "#dfe7f5";
  canvas.style.border = "1px solid #333";
  canvas.style.display = "block";
  // The container is the positioning context for the countdown overlay, so the
  // countdown sits on top of the canvas and never takes its own layout space.
  gameContainer = document.createElement("div");
  gameContainer.style.position = "relative";
  gameContainer.style.width = "600px";
  gameContainer.appendChild(canvas);
  app.appendChild(gameContainer);
  renderer = createRenderer(canvas);
  window.addEventListener("keydown", onKeyDown);
  window.addEventListener("keyup", onKeyUp);
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

function sendInput() {
  socket.send(JSON.stringify({ type: "input", keys: [...pressed] }));
}

function onKeyDown(event) {
  if (event.key === "ArrowLeft" || event.key === "ArrowRight") event.preventDefault();
  if (!pressed.has(event.key)) {
    pressed.add(event.key);
    if (inputMode === "server") sendInput();
  }
}

function onKeyUp(event) {
  if (pressed.delete(event.key) && inputMode === "server") sendInput();
}

// --- delivery dispatch ---------------------------------------------------

function render(delivery) {
  // A preload announcement starts the background download; it does not change
  // the visible activity, so the form stays on screen while packages arrive.
  if (delivery.kind === "preload") {
    startPreload(delivery.manifest);
    return;
  }
  if (delivery.kind !== "game" && renderer) stopGame();
  if (delivery.kind === "form") renderForm(delivery);
  else if (delivery.kind === "content") renderContent(delivery);
  else if (delivery.kind === "game" && delivery.mode === "browser") startBrowserGame(delivery);
  else if (delivery.kind === "game") startServerGame(delivery);
  else if (delivery.kind === "complete") renderComplete(delivery);
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
      report(`connected -- protocol ${message.protocol_version}`, true);
    } else if (message.type === "delivery") {
      render(message.delivery);
    } else if (message.type === "render") {
      if (renderer) renderer.draw(message.packet);
    } else if (message.type === "ack" && message.ack?.stream_position) {
      cursor = Math.max(cursor, message.ack.stream_position.sequence);
    } else if (message.type === "error") {
      report(`error: ${message.message}`, false);
    }
  });

  socket.addEventListener("close", () => {
    if (renderer) stopGame();
    report("disconnected -- retrying", false);
    setTimeout(connect, 1000);
  });
  socket.addEventListener("error", () => socket.close());
}

connect();
