(() => {
  const root = document.documentElement;
  const hero = document.querySelector(".hero");
  const preview = document.getElementById("preview");
  const transcript = document.getElementById("transcript");
  const install = document.getElementById("install");
  const masthead = document.querySelector(".masthead");
  const previewLink = document.querySelector(".preview-link");
  const installLink = document.querySelector(".install-link");
  const scenes = document.querySelectorAll(".chapter-media");
  const reduced = matchMedia("(prefers-reduced-motion: reduce)");
  let callback = 0;
  let activeLink;

  function updateScene() {
    callback = 0;
    const cutoff = masthead.offsetHeight + 2;
    const previewTop = preview.getBoundingClientRect().top;
    const atEnd = window.scrollY > 0 && window.scrollY + window.innerHeight >= root.scrollHeight - 2;
    const inInstall = install.getBoundingClientRect().top <= cutoff || atEnd;
    const surface = inInstall ? "install" : transcript.getBoundingClientRect().top <= cutoff ? "dark" :
      previewTop <= cutoff ? "paper" : "hero";
    if (root.dataset.surface !== surface) root.dataset.surface = surface;
    const nextLink = inInstall ? installLink : surface !== "hero" ? previewLink : null;
    if (nextLink !== activeLink) {
      activeLink?.removeAttribute("aria-current");
      nextLink?.setAttribute("aria-current", "location");
      activeLink = nextLink;
    }

    if (reduced.matches) return;
    const viewHeight = window.innerHeight;
    const heroBox = hero.getBoundingClientRect();
    const drift = Math.min(heroBox.height, Math.max(0, -heroBox.top)) * .23;
    hero.style.setProperty("--hero-drift", `${drift}px`);

    for (const scene of scenes) {
      const top = scene.parentElement.getBoundingClientRect().top;
      const progress = Math.min(1, Math.max(0, (viewHeight - top) / (viewHeight * .72)));
      scene.style.setProperty("--scene-shift", `${(1 - progress) * 34}px`);
      scene.style.setProperty("--scene-scale", String(.95 + progress * .05));
      scene.style.setProperty("--scene-crop", `${(1 - progress) * 4}%`);
    }
  }

  function schedule() {
    if (!callback) callback = requestAnimationFrame(updateScene);
  }

  window.addEventListener("scroll", schedule, { passive: true });
  window.addEventListener("resize", schedule);
  reduced.addEventListener("change", schedule);
  const platform = new URLSearchParams(location.search).get("platform");
  if (!location.hash || location.hash === "#preview") {
    if (platform === "mac") transcript.scrollIntoView({ behavior: "instant" });
    if (platform === "android") document.getElementById("notes").scrollIntoView({ behavior: "instant" });
  }
  updateScene();

  const viewer = document.getElementById("image-viewer");
  if (typeof viewer.showModal !== "function") return;
  const viewerImage = viewer.querySelector("img");
  const label = viewer.querySelector("#viewer-label");

  for (const link of document.querySelectorAll(".enlarge")) {
    link.addEventListener("click", (event) => {
      if (event.button !== 0 || event.metaKey || event.ctrlKey || event.altKey || event.shiftKey) return;
      event.preventDefault();
      const figure = link.closest("figure");
      const source = figure.querySelector("img");
      label.textContent = figure.querySelector("figcaption span").textContent;
      viewerImage.alt = source.alt;
      viewerImage.src = link.href;
      viewer.showModal();
    });
  }
})();
