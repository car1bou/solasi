(() => {
  const sample = document.getElementById("preview");
  const controls = sample.querySelector(".sample-controls");
  const buttons = controls.querySelectorAll("button[data-mode-choice]");
  const initialPlatform = new URLSearchParams(location.search).get("platform");

  function showMode(mode) {
    sample.dataset.mode = mode;
    for (const button of buttons) {
      button.setAttribute("aria-pressed", String(button.dataset.modeChoice === mode));
    }
  }

  if (initialPlatform === "mac") showMode("transcript");
  for (const button of buttons) {
    button.addEventListener("click", () => showMode(button.dataset.modeChoice));
  }
  controls.hidden = false;

  const previewLink = document.querySelector(".preview-link");
  const installLink = document.querySelector(".install-link");
  const install = document.getElementById("install");
  let frame = 0;
  let current;

  function updateNavigation() {
    frame = 0;
    const atEnd = window.scrollY + window.innerHeight >= document.documentElement.scrollHeight - 2;
    const atInstall = install.getBoundingClientRect().top <= 128;
    const next = window.scrollY > 0 && (atInstall || atEnd) ? installLink : previewLink;
    if (next === current) return;
    current?.removeAttribute("aria-current");
    next.setAttribute("aria-current", "location");
    current = next;
  }

  function queueNavigation() {
    if (!frame) frame = requestAnimationFrame(updateNavigation);
  }

  window.addEventListener("scroll", queueNavigation, { passive: true });
  window.addEventListener("resize", queueNavigation);
  updateNavigation();
})();
