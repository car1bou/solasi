(() => {
  const film = document.querySelector(".film");
  const stage = document.querySelector(".film-stage");
  const play = document.querySelector(".film-play");
  const label = play.querySelector(".play-label");
  const seek = document.querySelector(".film-seek");
  const time = document.querySelector(".film-time span");
  const nav = document.querySelector(".masthead");
  const navLinks = Array.from(nav.querySelectorAll("nav a"));
  const scenes = Array.from(document.querySelectorAll("[data-scene-surface]"));
  const duration = 8000;
  let distance = 0;
  let sceneOffsets = [];
  let currentSection = "";
  let progress = 0;
  let running = false;
  let started = 0;
  let playbackFrame = 0;
  let scrollFrame = 0;

  function measure() {
    distance = Math.max(0, film.offsetHeight - stage.offsetHeight);
    sceneOffsets = scenes.map(scene => scene.getBoundingClientRect().top + scrollY - nav.offsetHeight - 2);
    render();
  }

  function render() {
    scrollFrame = 0;
    progress = distance ? Math.min(1, Math.max(0, scrollY / distance)) : 0;
    const value = Math.round(progress * 1000);
    const seconds = Math.floor(value * duration / 1000000);
    seek.value = value;
    seek.style.setProperty("--elapsed", value / 10 + "%");
    seek.setAttribute("aria-valuetext", seconds + "초, 전체 8초");
    time.textContent = "0:0" + seconds;
    label.textContent = running ? "일시정지" : value >= 1000 ? "다시 재생" : value ? "이어 재생" : "인트로 재생";

    const upcoming = sceneOffsets.findIndex(top => top > scrollY);
    const section = upcoming < 0 ? scenes[scenes.length - 1] : scenes[upcoming - 1];
    const sectionID = section?.id || "home";
    if (sectionID === currentSection) return;
    currentSection = sectionID;
    document.documentElement.dataset.surface = section?.dataset.sceneSurface || "hero";
    for (const link of navLinks) {
      if (link.hash === "#" + (sectionID === "transcript" ? "notes" : sectionID)) link.setAttribute("aria-current", "location");
      else link.removeAttribute("aria-current");
    }
  }

  function pause() {
    if (!running) return;
    running = false;
    cancelAnimationFrame(playbackFrame);
    play.removeAttribute("data-playing");
    render();
  }

  function moveTo(fraction) {
    window.scrollTo({ top: distance * fraction, behavior: "instant" });
  }

  function playFrame(now) {
    const fraction = Math.min(1, (now - started) / duration);
    moveTo(fraction);
    if (fraction >= 1 || !distance) pause();
    else playbackFrame = requestAnimationFrame(playFrame);
  }

  play.addEventListener("click", () => {
    if (running) return pause();
    if (!distance) return;
    running = true;
    play.setAttribute("data-playing", "");
    started = performance.now() - (progress >= .9995 ? 0 : progress) * duration;
    playFrame(performance.now());
    render();
  });
  seek.addEventListener("input", () => {
    const fraction = seek.valueAsNumber / 1000;
    pause();
    moveTo(fraction);
    render();
  });
  for (const event of ["wheel", "touchstart", "pointerdown"]) {
    window.addEventListener(event, e => {
      if (event === "wheel" || !play.contains(e.target)) pause();
    }, { passive: true });
  }
  window.addEventListener("keydown", event => {
    if (["ArrowDown", "ArrowUp", "PageDown", "PageUp", "Home", "End", "Escape", "Tab"].includes(event.key) ||
        (event.key === " " && event.target !== play)) pause();
  });
  document.addEventListener("visibilitychange", () => { if (document.hidden) pause(); });
  window.addEventListener("hashchange", pause);
  window.addEventListener("pagehide", pause);
  matchMedia("(prefers-reduced-motion: reduce)").addEventListener("change", pause);
  window.addEventListener("scroll", () => { if (!scrollFrame) scrollFrame = requestAnimationFrame(render); }, { passive: true });
  const observer = new ResizeObserver(measure);
  for (const el of [film, stage, nav, ...scenes]) observer.observe(el);
  measure();

  const platform = new URLSearchParams(location.search).get("platform");
  if (!location.hash || location.hash === "#preview") {
    const chapter = platform === "mac" ? "transcript" : platform === "android" ? "notes" : null;
    if (chapter) document.getElementById(chapter).scrollIntoView({ behavior: "instant" });
  }

  const viewer = document.getElementById("image-viewer");
  if (typeof viewer.showModal !== "function") return;
  const viewerImage = viewer.querySelector("img");
  const viewerLabel = document.getElementById("viewer-label");
  for (const link of document.querySelectorAll(".enlarge")) {
    link.addEventListener("click", event => {
      if (event.button !== 0 || event.metaKey || event.ctrlKey || event.altKey || event.shiftKey) return;
      event.preventDefault();
      const figure = link.closest("figure");
      viewerLabel.textContent = figure.querySelector("figcaption span").textContent;
      viewerImage.alt = figure.querySelector("img").alt;
      viewerImage.src = link.href;
      viewer.showModal();
    });
  }
})();
