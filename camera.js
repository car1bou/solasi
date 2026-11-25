(() => {
  const film = document.querySelector(".film");
  if (!film || !window.DOMMatrix) return;

  const stage = film.querySelector(".film-stage");
  const world = film.querySelector(".film-world");
  const glass = film.querySelector(".film-glass");
  const motion = matchMedia("(prefers-reduced-motion: reduce)");
  const screen = [[957, 216], [1594, 271], [1563, 694], [912, 639]];
  const clamp = value => Math.max(0, Math.min(1, value));
  const ease = value => value * value * (3 - 2 * value);

  // Map the four corners of the 1600 × 1000 app capture onto a projected screen.
  function project([[x0, y0], [x1, y1], [x2, y2], [x3, y3]]) {
    const dx1 = x1 - x2, dx2 = x3 - x2;
    const dy1 = y1 - y2, dy2 = y3 - y2;
    const sx = x0 - x1 + x2 - x3, sy = y0 - y1 + y2 - y3;
    const det = dx1 * dy2 - dx2 * dy1;
    const g = (sx * dy2 - sy * dx2) / det;
    const h = (sy * dx1 - sx * dy1) / det;
    return new DOMMatrix([
      (x1 - x0 + g * x1) / 1600, (y1 - y0 + g * y1) / 1600, 0, g / 1600,
      (x3 - x0 + h * x3) / 1000, (y3 - y0 + h * y3) / 1000, 0, h / 1000,
      0, 0, 1, 0,
      x0, y0, 0, 1,
    ]);
  }

  const glassOnDesk = project(screen);
  const deskFromGlass = glassOnDesk.inverse();
  let poses, previous = -1, frame = 0;

  function compose() {
    const w = stage.clientWidth, h = stage.clientHeight;
    if (!w || !h) return;
    const portrait = w / h < 1.18;
    const scale = portrait ? Math.min(w / 815, h / 1310) : Math.max(w / 1817, h / 866) * 1.06;
    const subject = Math.min(w * .73, w * .97 - (1613 - 1253) * scale);
    const x = portrait ? w / 2 - 1253 * scale : Math.min(0, subject - 1253 * scale);
    const y = portrait ? h * .34 - 455 * scale : (h - 866 * scale) / 2;
    const opening = screen.map(([sx, sy]) => [x + sx * scale, y + sy * scale]);

    const bottom = Math.min(98, h * .13);
    const top = Math.min(76, h * .105);
    const closeWidth = portrait ? Math.min(w * 1.90, (h - top - bottom) * 1.6)
      : Math.min(w * .98, (h - top - bottom) * 1.6);
    const closeHeight = closeWidth / 1.6;
    const left = portrait ? -closeWidth * .071 : (w - closeWidth) / 2;
    const upper = top + (h - top - bottom - closeHeight) / 2;
    const landing = [[left, upper], [left + closeWidth, upper],
      [left + closeWidth, upper + closeHeight], [left, upper + closeHeight]];

    // Pass the near corner on a diagonal arc, then square up to the actual display.
    const span = portrait ? Math.min(w * 1.24, closeWidth * .91) : closeWidth * .96;
    const cx = w * (portrait ? .57 : .55), cy = h * (portrait ? .436 : .455);
    const bank = [[-.52, -.19], [.39, -.415], [.57, .237], [-.425, .349]]
      .map(([sx, sy]) => [cx + sx * span, cy + sy * span]);
    poses = { opening, bank, landing };
    previous = -1;
  }

  function paint() {
    frame = 0;
    if (!poses) return;
    const box = film.getBoundingClientRect();
    const progress = motion.matches ? 0 : clamp(-box.top / Math.max(1, box.height - stage.clientHeight));
    if (progress === previous) return;
    previous = progress;
    const t = ease(clamp(progress / .94));
    const arc = Math.sin(Math.PI * t);
    const { opening, bank, landing } = poses;
    const shot = opening.map((point, i) => point.map((from, axis) => {
      const to = landing[i][axis];
      return from + (to - from) * t + arc * (bank[i][axis] - (from + to) / 2);
    }));
    world.style.transform = project(shot).multiply(deskFromGlass).toString();
    const reveal = ease(clamp((progress - .49) / .39));
    stage.style.setProperty("--glass-light", String(.74 + .26 * reveal));
    stage.style.setProperty("--glass-opacity", String(.96 + .04 * reveal));
    stage.style.setProperty("--copy-opacity", String(1 - ease(clamp(progress / .25))));
    stage.style.setProperty("--credit-opacity", String(ease(clamp((progress - .77) / .16))));
    stage.style.setProperty("--desk-opacity", String(1 - ease(clamp((progress - .67) / .22))));
    stage.style.setProperty("--film-progress", String(progress));
  }

  function schedule() {
    if (!frame && !motion.matches) frame = requestAnimationFrame(paint);
  }

  function refresh() {
    film.classList.toggle("camera-ready", !motion.matches);
    compose();
    paint();
  }

  film.classList.add("camera-framed");
  glass.style.transform = glassOnDesk.toString();
  refresh();
  window.addEventListener("scroll", schedule, { passive: true });
  if (window.ResizeObserver) new ResizeObserver(refresh).observe(stage);
  else window.addEventListener("resize", refresh);
  motion.addEventListener("change", refresh);
})();
