(() => {
  const header = document.querySelector(".masthead");
  const desk = document.querySelector(".desk-surface");
  const stage = document.querySelector(".film-stage");
  const menu = header.querySelector(".fold-nav");
  const inlineNav = header.querySelector(".wide-nav");
  const narrowNav = matchMedia("(max-width: 58rem)");
  const footer = document.querySelector(".footer");
  const sections = Array.from(document.querySelectorAll("main > section"));
  const navLinks = header.querySelectorAll("a[href^='#']");
  const solutions = Array.from(document.querySelectorAll(".solution-list li"));
  const reduced = matchMedia("(prefers-reduced-motion: reduce)");
  const deskPointer = matchMedia("(hover: hover) and (pointer: fine) and (prefers-reduced-motion: no-preference)");
  // Side-light position and shadow depth as each chapter comes into view.
  const daylight = {
    home: [-.12, .31], preview: [-.12, .31], solutions: [.21, .08],
    process: [-.20, .72], work: [.22, .35], install: [-.06, .16]
  };
  let scheduled = false;
  let current = "";
  let highlighted;
  let lookFrame, lookX = 0, lookY = 0;

  function look(x, y) {
    lookX = Math.max(-1, Math.min(1, x));
    lookY = Math.max(-1, Math.min(1, y));
    if (lookFrame) return;
    lookFrame = requestAnimationFrame(() => {
      stage.style.setProperty("--look-x", lookX.toFixed(3));
      stage.style.setProperty("--look-y", lookY.toFixed(3));
      lookFrame = 0;
    });
  }
  document.addEventListener("pointermove", event => {
    if (deskPointer.matches && event.pointerType === "mouse") {
      look(event.clientX * 2 / innerWidth - 1, event.clientY * 2 / innerHeight - 1);
    }
  }, { passive: true });
  document.documentElement.addEventListener("pointerleave", () => look(0, 0));
  addEventListener("blur", () => look(0, 0));
  deskPointer.addEventListener("change", () => look(0, 0));

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
    const tops = sections.map(section => section.getBoundingClientRect().top);
    if (!reduced.matches) {
      const travel = Math.max(1, document.documentElement.scrollHeight - innerHeight);
      const progress = Math.max(0, Math.min(1, scrollY / travel));
      desk.style.setProperty("--desk-drift", ((.08 - .16 * progress) * innerHeight).toFixed(2) + "px");
      const index = Math.max(0, tops.filter(top => top < innerHeight).length - 1);
      const from = daylight[sections[Math.max(0, index - 1)].id];
      const to = daylight[sections[index].id];
      const part = Math.min(1, (innerHeight - tops[index]) / innerHeight);
      const mix = part * part * (3 - 2 * part);
      const light = from[0] + (to[0] - from[0]) * mix, shade = from[1] + (to[1] - from[1]) * mix;
      const foot = footer.getBoundingClientRect();
      const reveal = Math.max(0, Math.min(1, (innerHeight - foot.top) / Math.min(foot.height, innerHeight)));
      const close = reveal * reveal * (3 - 2 * reveal);
      desk.style.setProperty("--desk-light", ((light + (.24 - light) * close) * innerWidth).toFixed(2) + "px");
      desk.style.setProperty("--desk-shade", (shade + (.76 - shade) * close).toFixed(3));
    }
    const limit = header.offsetHeight + 2;
    const next = tops.findIndex(top => top > limit);
    const visible = (next < 0 ? sections[sections.length - 1] : sections[Math.max(0, next - 1)]).id;
    const active = visible === "preview" ? "home" : visible;
    highlightSolution();
    const compact = scrollY > limit;
    const folded = narrowNav.matches || menu.open || menu.contains(document.activeElement) || (compact && !inlineNav.contains(document.activeElement));
    header.classList.toggle("compact", compact);
    header.classList.toggle("folded", folded);
    inlineNav.toggleAttribute("inert", folded);
    menu.toggleAttribute("inert", !folded);
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
  document.addEventListener("visibilitychange", updateNavigation);
  reduced.addEventListener("change", schedule);
  document.addEventListener("toggle", schedule, true);
  header.addEventListener("focusout", schedule);
  updateNavigation();

  menu.querySelector("nav").addEventListener("click", event => {
    if (event.target.closest("a")) menu.open = false;
  });
  menu.addEventListener("focusout", event => {
    if (event.relatedTarget && !menu.contains(event.relatedTarget)) menu.open = false;
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
  if (document.documentElement.dataset.device === "mac") {
    document.querySelector(".film-copy p").textContent = "Apple Silicon Mac · macOS 27 이상";
    const lines = document.querySelectorAll("#heading > span");
    lines[0].textContent = "대본에서 한 문장을";
    lines[1].textContent = "다시 듣다.";
    document.querySelector(".film-description").textContent = "강의 녹음을 대본으로 옮기고, 문장을 골라 그 순간의 목소리를 다시 들으세요.";
    const example = document.querySelector(".result-example");
    example.src = "assets/mac-transcript.png?v=dark1";
    example.width = 1160;
    example.height = 792;
    example.alt = "Mac에서 기억과 학습 강의의 대본과 선택 구간 듣기 버튼을 함께 보여주는 화면";
    document.querySelector(".result-story p").textContent = "‘기억과 학습’ 수업에서 작업 기억을 어떻게 설명했는지 다시 들어 보세요. 강의 기록의 대본에서 해당 문장을 고르고 ‘선택 구간 듣기’를 누르면 그때의 설명을 원음으로 확인할 수 있습니다.";
    document.getElementById("transcript").open = true;
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
  const diagrams = document.querySelectorAll(".problem-visual, .course-map, .result-list");
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
