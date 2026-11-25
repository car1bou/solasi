(() => {
  const header = document.querySelector(".masthead");
  const menu = header.querySelector(".fold-nav");
  const sections = Array.from(document.querySelectorAll("main > section"));
  const navLinks = header.querySelectorAll("a[href^='#']");
  const solutions = Array.from(document.querySelectorAll(".solution-list li"));
  const reduced = matchMedia("(prefers-reduced-motion: reduce)");
  const pointerLight = matchMedia("(hover: hover) and (pointer: fine) and (prefers-reduced-motion: no-preference)");
  let scheduled = false;
  let current = "";
  let highlighted;
  let litField, lightFrame, pointerX;

  document.addEventListener("pointermove", event => {
    if (!pointerLight.matches || event.pointerType !== "mouse") return;
    const field = event.target.closest?.(".field");
    if (field !== litField) {
      litField?.style.removeProperty("--light-follow");
      litField = field;
    }
    pointerX = event.clientX;
    if (!litField || lightFrame) return;
    lightFrame = requestAnimationFrame(() => {
      litField?.style.setProperty("--light-follow", ((pointerX - innerWidth / 2) * .016).toFixed(1) + "px");
      lightFrame = 0;
    });
  }, { passive: true });

  if ("IntersectionObserver" in window) {
    const arrivals = new IntersectionObserver(entries => {
      for (const entry of entries) {
        if (!entry.isIntersecting) continue;
        entry.target.classList.add("has-arrived");
        arrivals.unobserve(entry.target);
      }
    });
    document.querySelectorAll(".field .motion-title").forEach(title => arrivals.observe(title));
  }

  function highlightSolution() {
    const center = (innerHeight + header.offsetHeight) / 2;
    const row = reduced.matches ? undefined : solutions.find(item => {
      const rect = item.getBoundingClientRect();
      return rect.top <= center && rect.bottom > center;
    });
    if (row === highlighted) return;
    highlighted?.classList.remove("is-current");
    row?.classList.add("is-current");
    highlighted = row;
  }

  function updateNavigation() {
    scheduled = false;
    const limit = header.offsetHeight + 2;
    const next = sections.findIndex(section => section.getBoundingClientRect().top > limit);
    const visible = (next < 0 ? sections[sections.length - 1] : sections[Math.max(0, next - 1)]).id;
    const active = visible === "preview" ? "home" : visible;
    highlightSolution();
    header.classList.toggle("compact", scrollY > limit);
    if (active === current) return;
    current = active;
    for (const link of navLinks) {
      if (link.hash === "#" + active && !link.classList.contains("brand")) link.setAttribute("aria-current", "location");
      else link.removeAttribute("aria-current");
    }
  }
  function schedule() {
    if (!scheduled) { scheduled = true; requestAnimationFrame(updateNavigation); }
  }
  addEventListener("scroll", schedule, { passive: true });
  addEventListener("resize", schedule);
  reduced.addEventListener("change", schedule);
  document.addEventListener("toggle", schedule, true);
  updateNavigation();

  menu.querySelector("nav").addEventListener("click", event => {
    if (event.target.closest("a")) menu.open = false;
  });
  document.addEventListener("click", event => { if (menu.open && !menu.contains(event.target)) menu.open = false; });
  document.addEventListener("keydown", event => {
    if (event.key === "Escape" && menu.open) {
      menu.open = false;
      menu.querySelector("summary").focus();
    }
  });

  function openLinkedScreen(initial) {
    const hash = location.hash.slice(1);
    const platform = new URLSearchParams(location.search).get("platform");
    const legacy = initial && (!hash || hash === "preview") && (platform === "mac" || platform === "android");
    const id = legacy ? (platform === "mac" ? "transcript" : "notes") : hash;
    const screen = document.getElementById(id);
    if (!screen?.matches("details[name='work']")) return;
    screen.open = true;
    screen.scrollIntoView({ behavior: "instant", block: "start" });
  }
  openLinkedScreen(true);
  addEventListener("hashchange", () => openLinkedScreen(false));

  const viewer = document.getElementById("image-viewer");
  if (typeof viewer.showModal !== "function") return;
  for (const link of document.querySelectorAll(".enlarge")) {
    link.addEventListener("click", event => {
      if (event.button !== 0 || event.metaKey || event.ctrlKey || event.altKey || event.shiftKey) return;
      event.preventDefault();
      const figure = link.closest("figure");
      document.getElementById("viewer-label").textContent = figure.querySelector("figcaption span").textContent;
      const image = viewer.querySelector("img");
      image.src = link.href;
      image.alt = figure.querySelector("img").alt;
      viewer.showModal();
    });
  }
})();

(() => {
  const root = document.documentElement;
  if (CSS.supports("view-timeline: --diagram block") && CSS.supports("animation-range: cover 10% cover 60%")) {
    root.classList.add("diagram-motion");
    return;
  }
  if (!window.IntersectionObserver) return;

  const reduced = matchMedia("(prefers-reduced-motion: reduce)");
  const diagrams = document.querySelectorAll(".problem-visual, .course-map, .field, .result-list");
  const visible = new Set();
  let frame = 0;
  function paint() {
    frame = 0;
    for (const diagram of visible) {
      const {top, height} = diagram.getBoundingClientRect();
      diagram.style.setProperty("--diagram-position", (innerHeight - top) / (innerHeight + height));
    }
  }
  function schedule() {
    if (!frame && visible.size) frame = requestAnimationFrame(paint);
  }
  const observer = new IntersectionObserver(entries => {
    for (const entry of entries) {
      if (entry.isIntersecting) visible.add(entry.target);
      else visible.delete(entry.target);
    }
    schedule();
  });
  function configure() {
    observer.disconnect();
    visible.clear();
    cancelAnimationFrame(frame);
    frame = 0;
    if (!reduced.matches) diagrams.forEach(diagram => observer.observe(diagram));
  }
  root.classList.add("diagram-motion", "diagram-manual");
  addEventListener("scroll", schedule, {passive:true});
  addEventListener("resize", schedule);
  reduced.addEventListener("change", configure);
  configure();
})();
