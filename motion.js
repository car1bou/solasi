(() => {
  const preview = document.getElementById("preview");
  const ripple = preview.querySelector(".preview-ripple");
  const reduceMotion = matchMedia("(prefers-reduced-motion: reduce)");
  let pointer = null;
  let frame = 0;
  let pulse;

  function draw() {
    frame = 0;
    if (reduceMotion.matches) return;
    const bounds = preview.getBoundingClientRect();
    const height = window.innerHeight;
    const range = document.documentElement.scrollHeight - height;
    const progress = Math.max(0, Math.min(1, window.scrollY / Math.max(1, range)));
    const drift = Math.max(-1, Math.min(1, (height - 2 * bounds.top - bounds.height) / (height + bounds.height)));
    const x = pointer ? pointer.clientX - bounds.left : -1;
    const y = pointer ? pointer.clientY - bounds.top : -1;
    const pointing = x >= 0 && x <= bounds.width && y >= 0 && y <= bounds.height;

    document.body.style.setProperty("--ambient-x", `${-progress * 170}px`);
    document.body.style.setProperty("--ambient-y", `${progress * height * 0.5}px`);
    preview.style.setProperty("--paper-x", `${drift * Math.min(42, bounds.width * 0.045)}px`);
    preview.style.setProperty("--paper-y", `${drift * Math.min(96, bounds.height * 0.11)}px`);
    preview.toggleAttribute("data-pointing", pointing);
    if (pointing) {
      preview.style.setProperty("--light-x", `${x}px`);
      preview.style.setProperty("--light-y", `${y}px`);
    }
  }

  function queueDraw() {
    if (!frame && !reduceMotion.matches) frame = requestAnimationFrame(draw);
  }

  window.addEventListener("scroll", queueDraw, { passive: true });
  window.addEventListener("resize", queueDraw);
  window.addEventListener("solasi:platformchange", queueDraw);
  preview.addEventListener("pointermove", (event) => {
    if (event.pointerType === "touch" || reduceMotion.matches) return;
    pointer = { clientX: event.clientX, clientY: event.clientY };
    queueDraw();
  });
  preview.addEventListener("pointerleave", () => {
    pointer = null;
    queueDraw();
  });

  preview.addEventListener("click", (event) => {
    if (reduceMotion.matches || !ripple.animate) return;
    const bounds = preview.getBoundingClientRect();
    const target = event.detail ? null : event.target.getBoundingClientRect();
    ripple.style.left = `${(target ? target.left + target.width / 2 : event.clientX) - bounds.left}px`;
    ripple.style.top = `${(target ? target.top + target.height / 2 : event.clientY) - bounds.top}px`;
    pulse?.cancel();
    pulse = ripple.animate([
      { transform: "translate(-50%, -50%) scale(.18)", opacity: .9 },
      { transform: "translate(-50%, -50%) scale(1.7)", opacity: 0 },
    ], { duration: 760, easing: "cubic-bezier(.16, 1, .3, 1)" });
  });

  reduceMotion.addEventListener("change", () => {
    pointer = null;
    pulse?.cancel();
    preview.removeAttribute("data-pointing");
    queueDraw();
  });
  queueDraw();
})();
