(() => {
  const film = document.querySelector(".film");
  if (!film || !window.DOMMatrix) return;

  const stage = film.querySelector(".film-stage");
  const world = film.querySelector(".film-world");
  const glass = film.querySelector(".film-glass");
  const motion = matchMedia("(prefers-reduced-motion: reduce)");
  const narrow = matchMedia("(max-aspect-ratio: 59/50)");
  const desktopPhoto = { width: 1672, height: 941, screen: [[693.3, 360], [989.1, 387], [970.7, 575.4], [671.5, 547.8]] };
  const mobilePhoto = { width: 852, height: 1846, screen: [[327.4, 640.9], [541.1, 658], [528.4, 799.1], [312.3, 782.1]] };
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

  let poses, deskFromGlass, previous = -1, frame = 0;

  function compose() {
    const w = stage.clientWidth, h = stage.clientHeight;
    if (!w || !h) return;
    const portrait = narrow.matches;
    const photo = portrait ? mobilePhoto : desktopPhoto;
    const glassOnDesk = project(photo.screen);
    deskFromGlass = glassOnDesk.inverse();
    glass.style.transform = glassOnDesk.toString();
    world.style.setProperty("--photo-w", photo.width + "px");
    world.style.setProperty("--photo-h", photo.height + "px");

    // Overscan leaves room for the opening bank to keep the tabletop edge off camera.
    const scale = 1.20 * Math.max(w / photo.width, h / photo.height);
    const screenMiddle = glassOnDesk.transformPoint({ x: 800, y: 500 });
    const pan = (viewport, size, aim, subject) =>
      Math.min(0, Math.max(viewport - size * scale, aim - subject * scale));
    const x = pan(w, photo.width, w / 2, screenMiddle.x / screenMiddle.w);
    const y = pan(h, photo.height, h * (portrait ? .40 : .50), screenMiddle.y / screenMiddle.w);
    const opening = photo.screen.map(([sx, sy]) => [x + sx * scale, y + sy * scale]);

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
    poses = { opening, bank, landing, bankStrength: Math.min(1, (2.4 * h / w) ** 3) };
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
    const arc = Math.sin(Math.PI * t) * poses.bankStrength;
    const { opening, bank, landing } = poses;
    const shot = opening.map((point, i) => point.map((from, axis) => {
      const to = landing[i][axis];
      return from + (to - from) * t + arc * (bank[i][axis] - (from + to) / 2);
    }));
    const view = project(shot);
    world.style.transform = view.multiply(deskFromGlass).toString();
    const center = view.transformPoint({ x: 800, y: 500 });
    stage.style.setProperty("--axis-x", center.x / center.w + "px");
    stage.style.setProperty("--axis-y", center.y / center.w + "px");
    const reveal = ease(clamp((progress - .49) / .39));
    stage.style.setProperty("--glass-light", String(.74 + .26 * reveal));
    stage.style.setProperty("--copy-opacity", String(1 - ease(clamp(progress / .25))));
    stage.style.setProperty("--opening-link-visibility", progress >= .24 ? "hidden" : "visible");
    stage.style.setProperty("--desk-opacity", String(1 - ease(clamp((progress - .67) / .22))));
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
  refresh();
  window.addEventListener("scroll", schedule, { passive: true });
  if (window.ResizeObserver) new ResizeObserver(refresh).observe(stage);
  else window.addEventListener("resize", refresh);
  motion.addEventListener("change", refresh);
  narrow.addEventListener("change", refresh);
})();
