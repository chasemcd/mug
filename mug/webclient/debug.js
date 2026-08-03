// The debug drawer: what the run is saying about itself, on the screen it is on.
//
// A study that runs a model partner is opaque in exactly the place a researcher
// needs to see: the seat was asked something, something came back, and an action
// was or was not read out of it. None of that reaches a participant's screen, and
// it should not -- so this is built only when the server says it is in debug mode,
// and a server that is not says nothing and answers nothing.
//
// **It shares nothing with the participant's transport.** The notes are polled
// over plain HTTP. A debugging aid that can break the run it is watching is worse
// than no debugging aid, so nothing here touches the websocket, the frame
// protocol, or the canvas.
//
// It draws **over** the study rather than beside it. The picture a participant
// plays is sized by the study; a panel that took part of the width would resize
// the game to make room for a debugging aid, which is the wrong way round.
//
// These modules use ASD-STE100 Simplified Technical English.

// How often the drawer asks what has happened. Twice a second is under what a
// person reads as a delay, and it is one small request: the answer holds only the
// notes written since the last one.
const EVERY = 500;

// How many notes the drawer keeps on the screen. Past this the oldest are dropped,
// so a study left running for an hour does not build a page the browser cannot
// scroll.
const KEEP = 400;

// The fields that are long enough to want their own box: a prompt, a reply, a
// carried thought. Everything else reads on one line.
const LONG = new Set(["payload", "output", "reply", "prompt", "thought", "text"]);

// The families a reader filters by. "everything" is not a family; it is the
// absence of a filter, which is the state the drawer opens in.
const FAMILIES = ["model", "agent", "round", "chat"];

// What a fault looks like. These are coloured apart, because the whole reason to
// open this panel is usually that one of them happened.
const BAD = new Set([
  "model.error",
  "model.raised",
  "agent.unreadable",
  "agent.fallback",
  "round.failed",
]);

// Turn one note's field into the text a person reads. A value that is not already
// text is rendered as the JSON it is, because a field like `payload` is a shape.
function readable(value) {
  if (value === null || value === undefined) return "-";
  if (typeof value === "string") return value;
  return JSON.stringify(value, null, 2);
}

// The prompt out of a model payload, when the payload is the shape every provider
// reads. A study that sends its own shape gets the whole payload instead, which
// is the honest answer: the client must not pretend to understand it.
function prompt(payload) {
  const messages = payload && payload.messages;
  if (!Array.isArray(messages)) return null;
  return messages
    .map((one) => `${one.role ?? "?"}: ${one.content ?? ""}`)
    .join("\n\n");
}

function el(tag, className, text) {
  const made = document.createElement(tag);
  if (className) made.className = className;
  if (text !== undefined) made.textContent = text;
  return made;
}

// Build the drawer and start reading. `host` is where it is put (the document
// body); nothing else on the page is touched.
export function startDebug(host) {
  const drawer = el("aside", "debug");
  drawer.dataset.testid = "debug-panel";
  drawer.dataset.open = "false";
  drawer.setAttribute("aria-label", "What the run is doing");

  const toggle = el("button", "debug__toggle", "debug `");
  toggle.dataset.testid = "debug-toggle";
  toggle.type = "button";
  toggle.setAttribute("aria-expanded", "false");

  const head = el("div", "debug__head");
  const line = el("p", "debug__status", "reading...");
  line.dataset.testid = "debug-status";
  const kinds = el("div", "debug__kinds");
  head.appendChild(line);
  head.appendChild(kinds);

  const list = el("div", "debug__notes");
  list.dataset.testid = "debug-notes";
  drawer.appendChild(head);
  drawer.appendChild(list);
  host.appendChild(toggle);
  host.appendChild(drawer);

  // Which families are shown. Empty means every one of them, so the drawer opens
  // showing everything and a reader narrows from there.
  const showing = new Set();
  for (const family of FAMILIES) {
    const button = el("button", "debug__kind", family);
    button.type = "button";
    button.dataset.family = family;
    button.setAttribute("aria-pressed", "false");
    button.addEventListener("click", () => {
      if (showing.has(family)) showing.delete(family);
      else showing.add(family);
      button.setAttribute("aria-pressed", String(showing.has(family)));
      for (const note of list.children) {
        note.hidden = !shown(note.dataset.family);
      }
    });
    kinds.appendChild(button);
  }

  function shown(family) {
    return showing.size === 0 || showing.has(family);
  }

  function open(on) {
    drawer.dataset.open = String(on);
    toggle.setAttribute("aria-expanded", String(on));
  }

  toggle.addEventListener("click", () => open(drawer.dataset.open !== "true"));
  // The backtick is the key, because it is the one key on the board that no
  // study binds to a move. A key a game reads would make the drawer cost the
  // participant a step every time it was opened.
  window.addEventListener("keydown", (event) => {
    if (event.key !== "`") return;
    event.preventDefault();
    open(drawer.dataset.open !== "true");
  });

  function draw(note) {
    const family = note.kind.split(".")[0];
    const row = el("div", "debug__note");
    row.dataset.family = family;
    row.dataset.kind = note.kind;
    if (BAD.has(note.kind)) row.dataset.bad = "true";
    row.hidden = !shown(family);

    const top = el("p", "debug__field");
    top.appendChild(el("span", "debug__when", `${note.at.slice(11, 23)} `));
    top.appendChild(el("span", "debug__what", note.kind));
    if (note.subject) {
      top.appendChild(el("span", "debug__who", ` ${note.subject}`));
    }
    row.appendChild(top);

    for (const [name, value] of Object.entries(note.fields ?? {})) {
      if (value === null && name !== "text") continue;
      const words =
        name === "payload" ? (prompt(value) ?? readable(value)) : readable(value);
      if (LONG.has(name) || words.length > 80) {
        row.appendChild(el("p", "debug__name", name));
        row.appendChild(el("pre", "debug__long", words));
      } else {
        const field = el("p", "debug__field");
        field.appendChild(el("span", "debug__name", `${name} `));
        field.appendChild(document.createTextNode(words));
        row.appendChild(field);
      }
    }
    list.appendChild(row);
  }

  let seen = 0;
  let missed = false;

  async function read() {
    let answer;
    try {
      const got = await fetch(`/_debug/notes?since=${seen}`, {
        cache: "no-store",
      });
      if (!got.ok) throw new Error(String(got.status));
      answer = await got.json();
    } catch (error) {
      line.textContent = `not reading -- ${error.message}`;
      return;
    }
    // A reader that has fallen behind the ring is told, rather than left to read
    // the gap as a run that went quiet.
    if (seen > 0 && answer.first_held > seen + 1 && !missed) {
      missed = true;
      list.appendChild(
        el("p", "debug__gap", "-- some notes were dropped (the panel fell behind)"),
      );
    }
    const bottom =
      list.scrollHeight - list.scrollTop - list.clientHeight < 40;
    for (const note of answer.notes ?? []) {
      draw(note);
      seen = Math.max(seen, note.sequence);
    }
    while (list.children.length > KEEP) list.removeChild(list.firstChild);
    // Follow the tail only when the reader is already at it. Somebody scrolled up
    // reading a prompt must not be dragged back down by the next note.
    if (bottom) list.scrollTop = list.scrollHeight;
    line.textContent =
      `${answer.written} notes | ${answer.open_sessions}/` +
      `${answer.max_sessions} sessions`;
  }

  void read();
  const timer = setInterval(read, EVERY);
  return {
    open,
    stop() {
      clearInterval(timer);
    },
  };
}

// Ask the server whether it is watching, and build the drawer when it is. A
// server that is not in debug mode has no such path, so the answer is a 404 and
// nothing is built -- which is the whole gate: a participant's client cannot show
// what the server does not serve.
export async function debugIfServed(host) {
  try {
    const got = await fetch("/_debug", { cache: "no-store" });
    if (!got.ok) return null;
  } catch {
    return null;
  }
  return startDebug(host);
}
