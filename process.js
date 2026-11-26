(() => {
  const runway = document.querySelector(".process-run");
  const stage = runway.querySelector(".process-list");
  const steps = [...stage.children];
  const clips = steps.map(step => step.querySelector("video"));
  const figures = steps.map(step => step.querySelector(".step-film"));
  const posters = figures.map(figure => figure.querySelector("img"));
  const decoded = new Set();
  const heldFrame = document.createElement("canvas");
  heldFrame.className = "held-frame";
  heldFrame.setAttribute("aria-hidden", "true");
  const returnFrame = document.createElement("canvas");
  const deviceScreen = document.querySelector(".film-display");
  const reduced = matchMedia("(prefers-reduced-motion: reduce)");
  const ruler = document.createElement("canvas");
  const ink = ruler.getContext("2d");
  ruler.className = "process-ruler";
  ruler.setAttribute("aria-hidden", "true");
  let current = -1, watching = false, seated = false, frame = 0;
  let paused = Boolean(navigator.connection?.saveData);
  let pointerX = null, lastPointer = null, lastSweep = -1;
  let width, height, top, runwayStart, runwayHeight, stageHeight, spacing, density, gradient;
  const clamp = n => Math.max(0, Math.min(1, n));
  const fade = n => { const t = clamp(n); return t * t * (3 - 2 * t); };

  // Carry the last visible app frame across a slow load or back onto the photographed device.
  function copyFrame(i, target) {
    const screen = posters[i].parentElement;
    const clip = clips[i];
    const source = heldFrame.parentElement === screen ? heldFrame
      : clip.readyState >= 2 && clip.classList.contains("is-showing") ? clip : posters[i];
    if (source === target) return true;
    const width = source === heldFrame ? source.width : source.videoWidth || source.naturalWidth;
    if (!width) return false;
    target.width = width;
    target.height = source === heldFrame ? source.height : source.videoHeight || source.naturalHeight;
    target.getContext("2d").drawImage(source, 0, 0);
    return true;
  }

  posters.forEach((poster, i) => {
    const ready = () => {
      decoded.add(poster);
      if (i === current) heldFrame.remove();
    };
    const decode = () => poster.decode().then(ready, () => { if (poster.naturalWidth) ready(); });
    if (poster.complete && poster.naturalWidth) decode();
    else poster.addEventListener("load", decode, {once: true});
  });

  function prepare(i) {
    const clip = clips[i];
    if (!clip || clip.hasAttribute("src")) return;
    clip.preload = "auto";
    clip.src = figures[i].querySelector("a").href;
  }

  function showClip(i) {
    if (i !== current || !watching) return;
    clips[i].classList.add("is-showing");
    heldFrame.remove();
  }

  function play(i) {
    prepare(i);
    const clip = clips[i];
    // Arm before play so a long, still opening can hand off on its first presented frame.
    if (!clip.classList.contains("is-showing")) clip.requestVideoFrameCallback?.(() => showClip(i));
    clip.play().catch(() => updateButton(i));
  }

  function updateButton(i) {
    const clip = clips[i];
    buttons[i].textContent = clip.ended ? "다시 보기" : clip.paused ? "재생" : "일시 정지";
  }

  const buttons = clips.map((clip, i) => {
    const button = document.createElement("button");
    button.type = "button";
    button.className = "step-play";
    button.textContent = "재생";
    figures[i].querySelector("a").before(button);
    button.onclick = () => {
      paused = !clip.paused;
      if (paused) clip.pause();
      else play(i);
    };
    clip.addEventListener("playing", () => {
      if (i !== current || !watching) { clip.pause(); return; }
      if (!clip.requestVideoFrameCallback) showClip(i);
      updateButton(i);
    });
    clip.addEventListener("pause", () => updateButton(i));
    clip.addEventListener("ended", () => updateButton(i));
    clip.addEventListener("error", () => {
      clip.classList.remove("is-showing");
      button.disabled = true;
    });
    return button;
  });

  function measure() {
    if (reduced.matches) return;
    top = parseFloat(getComputedStyle(stage).top) || 0;
    runwayStart = runway.getBoundingClientRect().top + scrollY;
    runwayHeight = runway.offsetHeight;
    stageHeight = stage.offsetHeight;
    height = innerHeight;
    const viewportWidth = document.documentElement.clientWidth;
    const pixelRatio = Math.min(2, window.devicePixelRatio || 1);
    if (ink && (viewportWidth !== width || pixelRatio !== density)) {
      width = viewportWidth;
      density = pixelRatio;
      spacing = Math.max(28, Math.min(67, width * .035));
      ruler.width = Math.round(width * density);
      ruler.height = Math.round(64 * density);
      gradient = ink.createLinearGradient(0, 1, 0, 0);
      gradient.addColorStop(0, "#f7e5cc");
      gradient.addColorStop(.51, "#ebc6a7");
      gradient.addColorStop(1, "rgba(214,163,127,.18)");
      lastSweep = -1;
    }
    if (frame) cancelAnimationFrame(frame);
    sync();
  }

  function drawRuler(position) {
    if (!ink || !width) return;
    const chapter = Math.floor(position);
    const sweep = chapter + fade((position - chapter - .10) / .80);
    if (sweep === lastSweep && pointerX === lastPointer) return;
    lastSweep = sweep;
    lastPointer = pointerX;
    const shift = -(sweep * width * .72 % spacing);
    const peak = width * (.455 + .065 * Math.sin(sweep * 1.7));
    ink.resetTransform();
    ink.clearRect(0, 0, ruler.width, ruler.height);
    ink.fillStyle = gradient;
    for (let x = shift; x <= width + spacing; x += spacing) {
      const wave = Math.exp(-Math.abs(x - peak) / (width * .18));
      const nearby = pointerX === null ? 0 : Math.exp(-(((x - pointerX) / Math.max(45, width * .06)) ** 2));
      const bar = ruler.height * Math.min(1, .04 + .96 * wave + .16 * nearby);
      ink.globalAlpha = Math.min(.9, .11 + .54 * wave + .30 * nearby);
      ink.setTransform(density, 0, 0, -bar, x * density, ruler.height);
      ink.fillRect(0, 0, Math.abs(x - peak) < spacing / 2 ? 2 : 1, 1);
    }
  }

  function sync() {
    frame = 0;
    if (reduced.matches) return;
    const runwayTop = runwayStart - scrollY;
    const runwayBottom = runwayTop + runwayHeight;
    const travel = Math.max(1, runwayHeight - stageHeight);
    const position = clamp((top - runwayTop) / travel) * steps.length;
    const index = Math.min(steps.length - 1, Math.floor(position));
    const docked = runwayTop <= top + 1;
    if (seated && !docked && copyFrame(0, returnFrame)) deviceScreen.append(returnFrame);
    seated = docked;
    const changed = current !== index;
    if (changed) {
      posters[index].loading = "eager";
      if (current >= 0) {
        if (!decoded.has(posters[index]) && !clips[index].classList.contains("is-showing") && copyFrame(current, heldFrame)) {
          posters[index].parentElement.append(heldFrame);
        } else heldFrame.remove();
        clips[current].pause();
        steps[current].removeAttribute("aria-current");
        steps[current].inert = true;
      }
      current = index;
      steps[index].inert = false;
      steps[index].setAttribute("aria-current", "step");
      steps[index].append(ruler);
      if (!navigator.connection?.saveData) {
        prepare(index);
        prepare(index + 1);
        if (posters[index + 1]) posters[index + 1].loading = "eager";
      }
    }
    const inView = runwayTop <= height && runwayBottom > top;
    if (inView) drawRuler(position);
    const visible = docked && runwayBottom >= top + stageHeight * .48;
    if (figures[index].inert !== !visible) figures[index].inert = !visible;
    const shouldPlay = visible && !document.hidden;
    if (changed || shouldPlay !== watching) {
      watching = shouldPlay;
      if (!watching) clips[index].pause();
      else if (!paused && !clips[index].ended) play(index);
    }
  }

  function schedule() {
    if (!reduced.matches && !frame) frame = requestAnimationFrame(sync);
  }

  function configure() {
    if (current >= 0) clips[current].pause();
    current = -1;
    watching = false;
    seated = false;
    heldFrame.remove();
    returnFrame.remove();
    ruler.remove();
    runway.classList.toggle("is-player", !reduced.matches);
    runway.style.setProperty("--steps", steps.length);
    steps.forEach((step, i) => {
      step.removeAttribute("aria-current");
      step.inert = figures[i].inert = !reduced.matches;
      buttons[i].hidden = reduced.matches;
    });
    measure();
  }

  // The pinned screens overlap. Place their snap positions on the scrolling runway.
  steps.forEach((_, i) => {
    const stop = document.createElement("span");
    stop.className = "chapter-stop";
    stop.setAttribute("aria-hidden", "true");
    stop.style.setProperty("--chapter-index", i);
    runway.append(stop);
  });
  configure();
  runway.addEventListener("pointermove", event => {
    if (event.pointerType === "mouse") { pointerX = event.clientX; schedule(); }
  }, {passive: true});
  runway.addEventListener("pointerleave", () => { pointerX = null; schedule(); });
  window.addEventListener("scroll", schedule, {passive: true});
  if (window.ResizeObserver) {
    const sizes = new ResizeObserver(measure);
    [runway, stage, document.querySelector(".film"), document.querySelector(".masthead")].forEach(el => sizes.observe(el));
  }
  window.addEventListener("resize", measure);
  window.addEventListener("load", measure, {once: true});
  document.addEventListener("visibilitychange", sync);
  reduced.addEventListener("change", configure);
})();
