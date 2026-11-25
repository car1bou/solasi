(() => {
  const runway = document.querySelector(".process-run");
  if (!runway) return;
  const stage = runway.querySelector(".process-list");
  const steps = [...stage.children];
  const clips = steps.map(step => step.querySelector("video"));
  const originals = steps.map(step => step.querySelector(".step-film a"));
  const reduced = matchMedia("(prefers-reduced-motion: reduce)");
  let scheduled = false;
  let current = -1;
  let lastProgress = -1;
  let inView = false;
  let activeClip;
  let held = false;
  const toggle = document.createElement("button");
  toggle.type = "button";
  toggle.hidden = true;
  toggle.className = "step-toggle";

  function updateControl() {
    toggle.hidden = !activeClip?.classList.contains("is-showing");
    if (!toggle.hidden) {
      toggle.textContent = activeClip.ended ? "다시 보기" : activeClip.paused ? "이어서 보기" : "일시 정지";
    }
  }

  function playClip(clip) {
    clip.play().catch(() => {
      if (clip === activeClip && clip.paused) clip.classList.remove("is-showing");
      updateControl();
    });
  }

  toggle.addEventListener("click", () => {
    if (!activeClip) return;
    held = !activeClip.paused;
    if (held) activeClip.pause();
    else playClip(activeClip);
  });

  clips.forEach(clip => {
    clip.addEventListener("playing", () => {
      if (clip === activeClip) {
        clip.classList.add("is-showing");
        updateControl();
      }
    });
    clip.addEventListener("pause", updateControl);
    clip.addEventListener("ended", updateControl);
    clip.addEventListener("error", () => { clip.classList.remove("is-showing"); updateControl(); });
  });

  function syncPlayback() {
    const next = inView && !document.hidden && !reduced.matches && !navigator.connection?.saveData
      ? clips[current] : undefined;
    if (next === activeClip) return;
    activeClip?.pause();
    activeClip = next;
    updateControl();
    if (!next) return;
    if (!next.hasAttribute("src")) next.src = originals[current].href;
    if (!held) playClip(next);
  }

  function showStep() {
    scheduled = false;
    if (reduced.matches) return;
    const top = parseFloat(getComputedStyle(stage).top);
    const rect = runway.getBoundingClientRect();
    const travel = Math.max(1, rect.height - stage.offsetHeight);
    const threshold = Math.min(stage.offsetHeight, innerHeight) * .48;
    inView = rect.top <= innerHeight - threshold && rect.bottom >= top + threshold;
    const progress = Math.max(0, Math.min(1, (top - rect.top) / travel));
    if (progress === lastProgress) { syncPlayback(); return; }
    lastProgress = progress;
    stage.style.setProperty("--ruler-x", (-progress * stage.clientWidth * .84).toFixed(2) + "px");

    // Keep each step still for reading, then roll its lines through the same slots.
    const position = Math.max(0, Math.min(steps.length - 1, progress * steps.length - .5));
    const first = Math.floor(position);
    const mix = Math.max(0, Math.min(1, (position - first - .22) / .56));
    const eased = mix * mix * (3 - 2 * mix);
    steps.forEach((step, i) => {
      const offset = Math.max(-1, Math.min(1, i - first - eased));
      const visible = Math.abs(offset) < 1;
      step.toggleAttribute("data-in-frame", visible);
      step.toggleAttribute("data-wiping", visible && offset > 0);
      if (visible) step.style.setProperty("--step-shift", (offset * 100).toFixed(2) + "%");
    });
    const index = first + Number(mix >= .5);
    if (index !== current) {
      steps[current]?.removeAttribute("aria-current");
      if (originals[current]) originals[current].inert = true;
      current = index;
      held = false;
      steps[current].setAttribute("aria-current", "step");
      originals[current].inert = false;
      originals[current].before(toggle);
      if (clips[current].readyState >= 1) clips[current].currentTime = 0;
    }
    syncPlayback();
  }

  function requestStep() {
    if (!scheduled && !reduced.matches) {
      scheduled = true;
      requestAnimationFrame(showStep);
    }
  }

  function configure() {
    runway.classList.toggle("is-scrubbed", !reduced.matches);
    originals.forEach(link => { link.inert = !reduced.matches; });
    steps[current]?.removeAttribute("aria-current");
    current = -1;
    if (reduced.matches) {
      syncPlayback();
    } else {
      lastProgress = -1;
      showStep();
    }
  }

  configure();
  document.addEventListener("visibilitychange", syncPlayback);
  window.addEventListener("scroll", requestStep, { passive: true });
  window.addEventListener("resize", () => {
    lastProgress = -1;
    requestStep();
  });
  reduced.addEventListener("change", configure);
})();
