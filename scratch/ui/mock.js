// Controls for the mock-ups only. None of this is platform behaviour: it lets
// one page show the light and the dark reading, and the two readings of a
// thread, without opening four files.

const root = document.documentElement;

function setTheme(name) {
  root.dataset.theme = name;
  localStorage.setItem("mug_mock_theme", name);
  for (const button of document.querySelectorAll("[data-theme-pick]")) {
    button.setAttribute("aria-pressed", String(button.dataset.themePick === name));
  }
}

function setThread(name) {
  root.dataset.thread = name;
  localStorage.setItem("mug_mock_thread", name);
  for (const button of document.querySelectorAll("[data-thread-pick]")) {
    button.setAttribute("aria-pressed", String(button.dataset.threadPick === name));
  }
}

setTheme(localStorage.getItem("mug_mock_theme") || "light");
setThread(localStorage.getItem("mug_mock_thread") || "flat");

document.addEventListener("click", (event) => {
  const theme = event.target.closest("[data-theme-pick]");
  if (theme) setTheme(theme.dataset.themePick);
  const thread = event.target.closest("[data-thread-pick]");
  if (thread) setThread(thread.dataset.threadPick);
});

// The composer grows with what is typed, and stops. A box that grows without a
// bound pushes the conversation off the screen.
for (const area of document.querySelectorAll(".composer textarea")) {
  const grow = () => {
    area.style.height = "auto";
    area.style.height = `${Math.min(area.scrollHeight, 176)}px`;
    const send = area.closest(".composer").querySelector(".composer__send");
    if (send) send.disabled = area.value.trim() === "";
  };
  area.addEventListener("input", grow);
  grow();
}
