(() => {
  const runway = document.querySelector(".process-run");
  if (!runway) return;
  const stage = runway.querySelector(".process-list");
  const steps = [...stage.children];
  const reduced = matchMedia("(prefers-reduced-motion: reduce)");
  let scheduled = false;
  let current = -1;
  let lastProgress = -1;

  function showStep() {
    scheduled = false;
    if (reduced.matches) return;
    const top = parseFloat(getComputedStyle(stage).top);
    const travel = Math.max(1, runway.offsetHeight - stage.offsetHeight);
    const progress = Math.max(0, Math.min(1, (top - runway.getBoundingClientRect().top) / travel));
    if (progress === lastProgress) return;
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
      if (visible) step.style.setProperty("--step-shift", (offset * 100).toFixed(2) + "%");
    });
    const index = first + Number(mix >= .5);
    if (index === current) return;
    steps[current]?.removeAttribute("aria-current");
    steps[index].setAttribute("aria-current", "step");
    current = index;
  }

  function requestStep() {
    if (!scheduled && !reduced.matches) {
      scheduled = true;
      requestAnimationFrame(showStep);
    }
  }

  function configure() {
    runway.classList.toggle("is-scrubbed", !reduced.matches);
    if (reduced.matches) {
      steps[current]?.removeAttribute("aria-current");
      current = -1;
    } else {
      lastProgress = -1;
      showStep();
    }
  }

  configure();
  window.addEventListener("scroll", requestStep, { passive: true });
  window.addEventListener("resize", () => {
    lastProgress = -1;
    requestStep();
  });
  reduced.addEventListener("change", configure);
})();
