// For the mock-ups only. It makes the screens answer, so the design can be
// judged by using it rather than by looking at it.

// The message box grows with what is written, and stops. Only the message box:
// a box on a form is the size the form asked for, and shrinking it to one line
// tells a participant to write one line.
for (const area of document.querySelectorAll(".composer textarea")) {
  const grow = () => {
    area.style.height = "auto";
    area.style.height = `${Math.min(area.scrollHeight, 160)}px`;
    const send = area.closest("form")?.querySelector(".send");
    if (send) send.disabled = area.value.trim() === "";
  };
  area.addEventListener("input", grow);
  grow();
}

// A scale says back what was said, in words. Each cell carries the sentence it
// means, so the screen never asks somebody to remember what the third mark from
// the left was for.
function sayBack(input) {
  const axis = input.closest(".axis");
  const readout = axis?.querySelector(".readout");
  if (!readout) return;
  const said = input.closest("label")?.dataset.say;
  readout.innerHTML = said ? `You said: <b>${said}</b>` : "";
  readout.classList.toggle("readout--set", Boolean(said));
}

// How much of a judgement is answered. It counts groups of radios, so an axis
// that asks about each option on its own counts as the two questions it is.
function countAnswers(root) {
  const groups = new Map();
  for (const input of root.querySelectorAll(".cells input[type=radio]")) {
    groups.set(input.name, groups.get(input.name) || input.checked);
  }
  const total = groups.size;
  const done = [...groups.values()].filter(Boolean).length;
  const badge = root.querySelector("[data-count]");
  if (!badge) return;
  badge.textContent =
    done === total ? `All ${total} answered` : `${done} of ${total} answered`;
  badge.classList.toggle("answered--all", done === total && total > 0);
}

// Choosing an option is done on the option. The submit says which one it is
// going to send, so a participant never has to look back up the panel to check
// what they picked.
function readChoice(panel) {
  const submit = panel.querySelector("[data-submit]");
  if (!submit) return;
  const picked = panel.querySelector(".option--pick input:checked");
  submit.disabled = !picked;
  if (!picked) {
    submit.textContent = submit.dataset.empty;
    return;
  }
  const named =
    picked.closest(".option").querySelector(".badge")?.textContent.trim() ?? "";
  submit.textContent = submit.dataset.ready.replace("{}", named);
}

document.addEventListener("change", (event) => {
  const input = event.target;
  if (!input.matches?.("input[type=radio]")) return;
  const panel = input.closest(".panel");
  if (input.matches(".cells input")) {
    sayBack(input);
    if (panel) countAnswers(panel);
  }
  if (panel) readChoice(panel);
});

document.addEventListener("click", (event) => {
  // Which pane the keys go to.
  const hold = event.target.closest("[data-hold]");
  if (hold) {
    const which = hold.dataset.hold;
    for (const button of document.querySelectorAll("[data-hold]")) {
      button.setAttribute("aria-pressed", String(button.dataset.hold === which));
    }
    for (const pane of document.querySelectorAll("[data-pane]")) {
      const held = pane.dataset.pane === which;
      pane.classList.toggle("pane--held", held);
      const badge = pane.querySelector(".pane__badge");
      if (badge) badge.textContent = held ? badge.dataset.on : badge.dataset.off;
    }
  }

  // One screen of the study at a time.
  const screen = event.target.closest("[data-screen]");
  if (screen) {
    for (const button of document.querySelectorAll("[data-screen]")) {
      button.setAttribute("aria-pressed", String(button === screen));
    }
    for (const panel of document.querySelectorAll("[data-panel]")) {
      panel.hidden = panel.dataset.panel !== screen.dataset.screen;
    }
  }
});

for (const panel of document.querySelectorAll(".panel")) {
  countAnswers(panel);
  readChoice(panel);
}
