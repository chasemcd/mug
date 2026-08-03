// For the mock-ups only. The box grows with what is written, and stops.
for (const area of document.querySelectorAll("textarea")) {
  const grow = () => {
    area.style.height = "auto";
    area.style.height = `${Math.min(area.scrollHeight, 160)}px`;
    const act = area.closest("form")?.querySelector("button[type=submit]");
    if (act) act.disabled = area.value.trim() === "";
  };
  area.addEventListener("input", grow);
  grow();
}
