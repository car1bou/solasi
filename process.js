(() => {
  const runway = document.querySelector(".process-run");
  if (!runway) return;
  const stage = runway.querySelector(".process-list");
  const steps = [...stage.children];
  const reduced = matchMedia("(prefers-reduced-motion: reduce)");
  let scheduled = false;
  let current = -1;

  function showStep() {
    scheduled = false;
    if (reduced.matches) return;
    const top = parseFloat(getComputedStyle(stage).top);
    const travel = Math.max(1, runway.offsetHeight - stage.offsetHeight);
    const progress = (top - runway.getBoundingClientRect().top) / travel;
    const index = Math.max(0, Math.min(steps.length - 1, Math.floor(progress * steps.length)));
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
      showStep();
    }
  }

  configure();
  window.addEventListener("scroll", requestStep, { passive: true });
  window.addEventListener("resize", requestStep);
  reduced.addEventListener("change", configure);
})();
