(() => {
  const runway = document.querySelector(".process-run");
  const stage = runway.querySelector(".process-list");
  const steps = [...stage.children];
  const clips = steps.map(step => step.querySelector("video"));
  const figures = steps.map(step => step.querySelector(".step-film"));
  const reduced = matchMedia("(prefers-reduced-motion: reduce)");
  const ruler = document.createElement("div");
  ruler.className = "process-ruler";
  ruler.setAttribute("aria-hidden", "true");
  let current = -1, watching = false, frame = 0;
  let paused = Boolean(navigator.connection?.saveData);
  let pointerX = null, spacing = 0, lastWidth = 0, lastRuler = "";
  const clamp = n => Math.max(0, Math.min(1, n));
  const fade = n => { const t = clamp(n); return t * t * (3 - 2 * t); };

  function play(i) {
    const clip = clips[i];
    if (!clip.hasAttribute("src")) clip.src = figures[i].querySelector("a").href;
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
      clip.classList.add("is-showing");
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

  function drawRuler(position) {
    const width = document.documentElement.clientWidth;
    if (width !== lastWidth) {
      lastWidth = width;
      spacing = Math.max(28, Math.min(67, width * .035));
      ruler.replaceChildren();
      for (let i = -1; i <= Math.ceil(width / spacing) + 1; i++) {
        const tick = document.createElement("i");
        tick.style.setProperty("--tick-left", i * spacing + "px");
        tick.style.setProperty("--tick-delay", -(i + 2) * .43 + "s");
        ruler.append(tick);
      }
      lastRuler = "";
    }
    const key = position.toFixed(4) + "/" + pointerX;
    if (key === lastRuler) return;
    lastRuler = key;
    const chapter = Math.floor(position);
    const sweep = chapter + fade((position - chapter - .10) / .80);
    const shift = -(sweep * width * .72 % spacing);
    const peak = width * (.455 + .065 * Math.sin(sweep * 1.7));
    ruler.style.setProperty("--ruler-x", shift + "px");
    Array.from(ruler.children).forEach((tick, i) => {
      const x = (i - 1) * spacing + shift;
      const height = Math.exp(-Math.abs(x - peak) / (width * .18));
      const nearby = pointerX === null ? 0 : Math.exp(-(((x - pointerX) / Math.max(45, width * .06)) ** 2));
      tick.style.setProperty("--tick-height", Math.min(1, .04 + .96 * height + .16 * nearby).toFixed(3));
      tick.style.setProperty("--tick-light", Math.min(.9, .11 + .54 * height + .30 * nearby).toFixed(3));
      tick.style.setProperty("--tick-width", Math.abs(x - peak) < spacing / 2 ? "2px" : "1px");
    });
  }

  function sync() {
    frame = 0;
    if (reduced.matches) return;
    const top = parseFloat(getComputedStyle(stage).top) || 0;
    const rect = runway.getBoundingClientRect();
    const travel = Math.max(1, runway.offsetHeight - stage.offsetHeight);
    const position = clamp((top - rect.top) / travel) * steps.length;
    const index = Math.min(steps.length - 1, Math.floor(position));
    const phase = position - index;
    // Settle on a complete composition even when the visitor stops exactly at a chapter boundary.
    const demo = phase >= .44 ? 1 : 0;
    const card = 1 - demo;
    const changed = current !== index;
    if (changed) {
      if (current >= 0) {
        clips[current].pause();
        steps[current].removeAttribute("aria-current");
        steps[current].inert = true;
      }
      current = index;
      steps[index].inert = false;
      steps[index].setAttribute("aria-current", "step");
      steps[index].append(ruler);
      if (steps[index + 1]) steps[index + 1].querySelector("img").loading = "eager";
    }
    // Keep the outgoing row's state while its fade finishes.
    steps[index].style.setProperty("--card-opacity", card);
    steps[index].style.setProperty("--demo-opacity", demo);
    runway.style.setProperty("--card-opacity", card);
    runway.style.setProperty("--demo-opacity", demo);
    const inView = rect.top <= innerHeight && rect.bottom > top;
    if (inView && card > 0) drawRuler(position);
    const visible = demo > .12 && rect.top <= top + 1 && rect.bottom >= top + stage.offsetHeight * .48;
    figures[index].inert = !visible;
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
    ruler.remove();
    runway.classList.toggle("is-player", !reduced.matches);
    runway.style.setProperty("--steps", steps.length);
    steps.forEach((step, i) => {
      step.removeAttribute("aria-current");
      step.inert = figures[i].inert = !reduced.matches;
      buttons[i].hidden = reduced.matches;
    });
    sync();
  }

  configure();
  runway.addEventListener("pointermove", event => {
    if (event.pointerType === "mouse") { pointerX = event.clientX; schedule(); }
  }, {passive: true});
  runway.addEventListener("pointerleave", () => { pointerX = null; schedule(); });
  window.addEventListener("scroll", schedule, {passive: true});
  window.addEventListener("resize", schedule);
  window.addEventListener("load", schedule, {once: true});
  document.addEventListener("visibilitychange", sync);
  reduced.addEventListener("change", configure);
})();
