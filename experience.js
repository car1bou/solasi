(() => {
  const header = document.querySelector(".masthead");
  const desk = document.querySelector(".desk-surface");
  const stage = document.querySelector(".film-stage");
  const menu = header.querySelector(".fold-nav");
  const inlineNav = header.querySelector(".wide-nav");
  const narrowNav = matchMedia("(max-width: 58rem)");
  const footer = document.querySelector(".footer");
  const viewer = document.getElementById("image-viewer");
  const sections = Array.from(document.querySelectorAll("main > section"));
  const navLinks = header.querySelectorAll("a[href^='#']");
  const solutions = Array.from(document.querySelectorAll(".solution-list li"));
  const reduced = matchMedia("(prefers-reduced-motion: reduce)");
  const deskPointer = matchMedia("(hover: hover) and (pointer: fine) and (prefers-reduced-motion: no-preference)");
  // Side-light position and shadow depth as each chapter comes into view.
  const daylight = {
    home: [-.12, .31], process: [-.12, .31], preview: [-.15, .49],
    solutions: [.21, .08], results: [-.20, .72], work: [.22, .35], install: [-.06, .16]
  };
  let scheduled = false;
  let current = "";
  let highlighted, layout;
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

  // Document positions stay fixed while scrolling. Measure again when content or the viewport resizes.
  function measure(y) {
    const foot = footer.getBoundingClientRect();
    const tops = sections.map(section => section.getBoundingClientRect().top + y);
    const headerHeight = header.offsetHeight;
    const travel = Math.max(1, document.documentElement.scrollHeight - innerHeight);
    const chapters = Array.from(document.querySelectorAll(".is-player .chapter-stop"),
      stop => stop.getBoundingClientRect().top + y - headerHeight);
    const chapterStops = [0, ...chapters, tops[2] - headerHeight];
    return {
      tops, travel, chapterStops, stops: [...chapterStops, ...tops.slice(3).map(top => top - headerHeight), Math.min(foot.top + y, travel), travel],
      rowBounds: solutions.map(row => {
        const rect = row.getBoundingClientRect();
        return [rect.top + y, rect.bottom + y];
      }),
      foot: foot.top + y, footHeight: foot.height, header: headerHeight
    };
  }

  function highlightSolution(y) {
    const center = y + (innerHeight + layout.header) / 2;
    const index = reduced.matches ? -1 : layout.rowBounds.findIndex(([top, bottom]) => top <= center && bottom > center);
    const row = solutions[index];
    if (row === highlighted) return;
    highlighted?.classList.remove("is-current");
    row?.classList.add("is-current");
    highlighted = row;
  }

  function updateNavigation() {
    scheduled = false;
    const y = scrollY;
    if (!layout) layout = measure(y);
    const { tops, travel } = layout;
    const viewEnd = y + innerHeight;
    if (!reduced.matches) {
      const progress = Math.max(0, Math.min(1, y / travel));
      desk.style.setProperty("--desk-drift", ((.08 - .16 * progress) * innerHeight).toFixed(2) + "px");
      const index = Math.max(0, tops.filter(top => top < viewEnd).length - 1);
      const from = daylight[sections[Math.max(0, index - 1)].id];
      const to = daylight[sections[index].id];
      const part = Math.min(1, (viewEnd - tops[index]) / innerHeight);
      const mix = part * part * (3 - 2 * part);
      const light = from[0] + (to[0] - from[0]) * mix, shade = from[1] + (to[1] - from[1]) * mix;
      const reveal = Math.max(0, Math.min(1, (viewEnd - layout.foot) / Math.min(layout.footHeight, innerHeight)));
      const close = reveal * reveal * (3 - 2 * reveal);
      desk.style.setProperty("--desk-light", ((light + (.24 - light) * close) * innerWidth).toFixed(2) + "px");
      desk.style.setProperty("--desk-shade", (shade + (.76 - shade) * close).toFixed(3));
    }
    const limit = y + layout.header + 2;
    const next = tops.findIndex(top => top > limit);
    const visible = (next < 0 ? sections[sections.length - 1] : sections[Math.max(0, next - 1)]).id;
    const active = visible === "solutions" || visible === "results" ? "preview" : visible;
    highlightSolution(y);
    const compact = tops[1] <= limit;
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
  function invalidateLayout() {
    layout = null;
    schedule();
  }
  if (window.ResizeObserver) {
    const sizes = new ResizeObserver(invalidateLayout);
    for (const element of [header, footer, ...sections, ...solutions]) sizes.observe(element);
  }
  addEventListener("scroll", schedule, { passive: true });
  addEventListener("resize", invalidateLayout);
  addEventListener("load", invalidateLayout, { once: true });
  document.addEventListener("visibilitychange", invalidateLayout);
  reduced.addEventListener("change", invalidateLayout);
  document.addEventListener("toggle", invalidateLayout, true);
  header.addEventListener("focusout", schedule);
  updateNavigation();

  // Decide after the entire gesture settles so a flick's small trailing deltas never pull it back.
  const quietTime = 220;
  const smallDistance = () => Math.min(180, Math.max(120, innerHeight * .22));
  let gesture, timer, snapFrame = 0, wheelTime = -Infinity, touch, lastScrollY = scrollY;
  function cancelSnap() {
    clearTimeout(timer);
    cancelAnimationFrame(snapFrame);
    snapFrame = 0;
    gesture = null;
  }
  function resetInput() {
    cancelSnap();
    touch = null;
    wheelTime = -Infinity;
  }
  function settle() {
    if (!gesture) return;
    const { start, delta } = gesture;
    const direction = Math.sign(delta);
    cancelSnap();
    const y = scrollY;
    const travel = Math.abs(y - start);
    if (Math.abs(delta) < 5 || travel < 2 || travel > smallDistance() || reduced.matches || viewer.open || menu.open) return;
    if (!layout) layout = measure(y);
    const chapter = layout.chapterStops.findIndex(stop => Math.abs(stop - start) <= 4);
    let target = chapter < 0 ? undefined : layout.chapterStops[chapter + direction];
    if (target === undefined) {
      let nearest = Math.min(100, innerHeight * .14);
      for (const stop of layout.stops) {
        const gap = Math.abs(stop - y);
        if ((stop - start) * direction > 2 && gap <= nearest) {
          target = stop;
          nearest = gap;
        }
      }
    }
    if (target === undefined || Math.abs(target - y) <= 1) return;
    // Native smooth scrolling can swallow a new wheel gesture while it is still animating.
    const startTime = performance.now();
    const duration = Math.min(380, 140 + Math.abs(target - y) * .34);
    function align(now) {
      const t = Math.min(1, Math.max(0, (now - startTime) / duration));
      scrollTo({top: target - (target - y) * (1 - t) ** 3, behavior: "instant"});
      snapFrame = t < 1 ? requestAnimationFrame(align) : 0;
    }
    snapFrame = requestAnimationFrame(align);
  }
  function waitForRest() {
    if (!gesture) return;
    if (Math.abs(scrollY - gesture.start) > smallDistance()) return cancelSnap();
    if (touch) return;
    clearTimeout(timer);
    timer = setTimeout(settle, quietTime);
  }
  addEventListener("wheel", event => {
    if (snapFrame) cancelSnap();
    if (reduced.matches || viewer.open || menu.open || event.defaultPrevented || event.ctrlKey ||
        event.metaKey || event.shiftKey || Math.abs(event.deltaX) >= Math.abs(event.deltaY)) return resetInput();
    const unit = event.deltaMode === 1 ? 16 : event.deltaMode === 2 ? innerHeight : 1;
    const delta = event.deltaY * unit;
    if (event.timeStamp - wheelTime > quietTime) {
      cancelSnap();
      // A passive wheel listener can run after compositing but before the scroll event.
      const y = scrollY;
      const start = Math.abs(lastScrollY - y) <= Math.abs(delta) + 2 ? lastScrollY : y;
      gesture = {start, delta: 0, distance: 0};
    }
    wheelTime = event.timeStamp;
    if (!gesture) return;
    gesture.delta += delta;
    gesture.distance += Math.abs(delta);
    if (gesture.distance > smallDistance()) cancelSnap();
    else waitForRest();
  }, {passive: true});
  addEventListener("touchstart", event => {
    resetInput();
    if (event.touches.length !== 1 || reduced.matches || viewer.open || menu.open) return;
    const finger = event.touches[0];
    touch = {x: finger.clientX, y: finger.clientY, time: event.timeStamp};
    gesture = {start: scrollY, delta: 0, distance: 0};
  }, {passive: true});
  addEventListener("touchend", event => {
    if (!touch || !gesture) return resetInput();
    const finger = event.changedTouches[0];
    const dy = touch.y - finger.clientY;
    const distance = Math.abs(dy);
    const speed = distance / Math.max(1, event.timeStamp - touch.time);
    if (distance < 5 || distance > smallDistance() || speed > .65 || Math.abs(touch.x - finger.clientX) >= distance) return resetInput();
    gesture.delta = dy;
    touch = null;
    waitForRest();
  }, {passive: true});
  addEventListener("scroll", () => {
    lastScrollY = scrollY;
    waitForRest();
  }, {passive: true});
  for (const name of ["touchcancel", "pointerdown", "keydown", "hashchange", "resize", "blur", "pagehide"]) {
    addEventListener(name, resetInput, {passive: true});
  }

  reduced.addEventListener("change", resetInput);

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
  openLinkedScreen(true);
  addEventListener("hashchange", () => openLinkedScreen(false));

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
  const diagrams = document.querySelectorAll(".problem-visual, .course-map");
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
