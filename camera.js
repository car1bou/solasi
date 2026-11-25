(() => {
  const film = document.querySelector(".film");
  if (!film || !window.DOMMatrix) return;

  const stage = film.querySelector(".film-stage");
  const header = document.querySelector(".masthead");
  const world = film.querySelector(".film-world");
  const glass = film.querySelector(".film-glass");
  const intro = document.querySelector(".problem-heading");
  const paper = intro.querySelector(".lecture-page");
  const paperWindow = paper.querySelector(".lecture-window");
  const paperImage = paper.querySelector("img");
  const motion = matchMedia("(prefers-reduced-motion: reduce)");
  const narrow = matchMedia("(max-aspect-ratio: 9/10)");
  const desktopPhoto = { width: 3372, height: 1641, screen: [[1608.9, 459.28], [2595.98, 444.26], [2600.57, 1051.74], [1611.74, 1058.21]] };
  const mobilePhoto = { width: 1005, height: 2642, screen: [[108.17, 756.3], [894.75, 755.82], [894.95, 1266.72], [108.02, 1267.06]] };
  const clamp = value => Math.max(0, Math.min(1, value));
  const ease = value => value * value * (3 - 2 * value);

  // A 16:10 reference plane describes the glass on both photographed devices.
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

  let poses, pdf, deskFromGlass, appToGlass, previous = -1, previousPass = -1, frame = 0;

  function compose() {
    const w = stage.clientWidth, h = stage.clientHeight;
    if (!w || !h) return;
    const bounds = getComputedStyle(paper);
    pdf = ["x", "y", "w", "h"].map(key => Number(bounds.getPropertyValue("--pdf-" + key)));
    if (!pdf[2] || !pdf[3]) return;
    const portrait = narrow.matches;
    const photo = portrait ? mobilePhoto : desktopPhoto;
    const glassOnDesk = project(photo.screen);
    deskFromGlass = glassOnDesk.inverse();
    const appWidth = glass.naturalWidth || Number(glass.getAttribute("width"));
    const appHeight = glass.naturalHeight || Number(glass.getAttribute("height"));
    if (!(appWidth > 0 && appHeight > 0)) return;
    const fit = Math.min(1600 / appWidth, 1000 / appHeight);
    const insetX = (1600 - appWidth * fit) / 2;
    const insetY = (1000 - appHeight * fit) / 2;
    appToGlass = new DOMMatrix().translate(insetX, insetY).scale(fit);
    glass.style.setProperty("--capture-w", appWidth + "px");
    glass.style.setProperty("--capture-h", appHeight + "px");
    world.style.setProperty("--photo-w", photo.width + "px");
    world.style.setProperty("--photo-h", photo.height + "px");

    // Leave enough photographed wood around the frame for both the pointer and idle camera.
    const roomX = Math.min(portrait ? 27 : 48, w * (portrait ? .031 : .042));
    const roomY = Math.min(24, h * .034);
    const cover = Math.max((w + 2 * roomX) / photo.width, (h + 2 * roomY) / photo.height);
    // In the wide master the glass spans 988 pixels; the case and pen together stand 755 pixels tall.
    const scale = portrait ? cover : Math.max(cover, Math.min(w * .56 / 988, (h - header.offsetHeight * .55) * .86 / 755));
    const screenMiddle = glassOnDesk.transformPoint({ x: 800, y: 500 });
    const pan = (viewport, size, aim, subject, room) => {
      const margin = Math.min(room, (size * scale - viewport) / 2);
      return Math.min(-margin, Math.max(viewport + margin - size * scale, aim - subject * scale));
    };
    const horizontalAim = portrait ? w / 2 : Math.min(w * .655, w - scale * 530 - roomX);
    const x = pan(w, photo.width, horizontalAim, screenMiddle.x / screenMiddle.w, roomX);
    const y = pan(h, photo.height, portrait ? h * .40 : h * .47 + header.offsetHeight * .26,
      screenMiddle.y / screenMiddle.w, roomY);
    const opening = photo.screen.map(([sx, sy]) => [x + sx * scale, y + sy * scale]);

    // Cross the bezel. On a phone the left margin of the actual lecture page guides the framing.
    const endScale = Math.max((w + 4) / appWidth, (h + 4) / appHeight);
    const fullW = appWidth * endScale, fullH = appHeight * endScale;
    const centered = (w - fullW) / 2;
    const appLeft = Math.min(-2, Math.max(centered, w * .045 - pdf[0] * endScale));
    const appTop = (h - fullH) / 2;
    glass.style.setProperty("--front-x", appLeft + "px");
    glass.style.setProperty("--front-y", appTop + "px");
    glass.style.setProperty("--front-w", appWidth * endScale + "px");
    glass.style.setProperty("--front-h", appHeight * endScale + "px");
    const planeScale = endScale / fit;
    const left = appLeft - insetX * planeScale, upper = appTop - insetY * planeScale;
    const closeWidth = 1600 * planeScale, closeHeight = 1000 * planeScale;
    const landing = [[left, upper], [left + closeWidth, upper],
      [left + closeWidth, upper + closeHeight], [left, upper + closeHeight]];

    const openWidth = Math.hypot(opening[1][0] - opening[0][0], opening[1][1] - opening[0][1]);
    const focus = glassOnDesk.transformPoint({
      x: (w / 2 - left) / planeScale, y: (h / 2 - upper) / planeScale,
    });
    const aim = [x + scale * focus.x / focus.w, y + scale * focus.y / focus.w];
    const center = [w / 2, h / 2];
    const directions = (corners, origin, span) => corners.map(point =>
      point.map((value, axis) => (value - origin[axis]) / span));
    poses = { near: directions(opening, aim, openWidth), far: directions(landing, center, closeWidth),
      aim, center, openWidth, zoom: closeWidth / openWidth,
      front: { x: appLeft, y: appTop, w: fullW, h: fullH } };
    paper.style.setProperty("--flight-width", poses.front.w + "px");
    previous = previousPass = -1;
  }

  function passPage(t, travel, ready) {
    if (t === previousPass) return;
    previousPass = t;
    const height = stage.clientHeight;
    const passing = t > 0 && t < 1;
    const to = passing ? paper.getBoundingClientRect() : null;
    film.classList.toggle("passes-page", passing);
    paper.classList.toggle("in-flight", passing);
    const mix = ease(t);
    const arc = Math.sin(Math.PI * t) ** 2;
    const lead = .095 * (1 - mix) + (narrow.matches ? .22 : .07) * arc;
    intro.style.setProperty("--lede-lift", (ready ? -height * lead : 0).toFixed(2) + "px");
    intro.style.setProperty("--lede-ink", (ready ? .22 + .78 * ease(clamp((t - .12) / .55)) : 1).toFixed(3));
    if (!passing) {
      paperWindow.style.removeProperty("transform");
      paperWindow.style.removeProperty("clip-path");
      return;
    }

    // The same notebook pixels fill the viewport, then only its PDF travels into the heading.
    const from = poses.front;
    const [x, y, w, h] = pdf;
    const fx = from.w * x / glass.naturalWidth, fy = from.h * y / glass.naturalHeight;
    const scale = (to.width / (from.w * w / glass.naturalWidth)) ** mix;
    const left = (from.x + fx) * (1 - mix) + to.left * mix;
    const restingTop = to.top - (1 - t) * travel;
    const upper = (from.y + fy) * (1 - mix) + restingTop * mix
      - arc * Math.min(height * .11, 80) + travel * t ** 4 * (1 - t);
    paperWindow.style.transform = `translate3d(${left}px,${upper}px,0) rotate(${arc * -2}deg) scale(${scale}) translate(${-fx}px,${-fy}px)`;
    const trim = ease(clamp((t - .025) / .54)) * 100;
    const inset = [y / glass.naturalHeight, 1 - (x + w) / glass.naturalWidth,
      1 - (y + h) / glass.naturalHeight, x / glass.naturalWidth];
    paperWindow.style.clipPath = "inset(" + inset.map(edge => (edge * trim).toFixed(4) + "%").join(" ") + ")";
  }

  function paint() {
    frame = 0;
    if (!poses) return;
    const box = film.getBoundingClientRect();
    const captureReady = glass.naturalWidth > 0;
    const ready = captureReady && paperImage.naturalWidth > 0;
    const height = stage.clientHeight, travel = Math.max(1, height - header.offsetHeight - 12);
    const progress = motion.matches || !captureReady ? 0 : clamp(-box.top / Math.max(1, box.height - height));
    const pass = ready && !motion.matches ? clamp((height - box.bottom) / travel) : 0;
    if (progress !== previous || pass !== previousPass) {
      const immersion = ready ? ease(clamp((progress - .7) / .29)) * (1 - ease(clamp((pass - .06) / .30))) : 0;
      header.style.setProperty("--into-app", (-101 * immersion).toFixed(2) + "%");
    }
    passPage(pass, travel, ready);
    if (progress === previous) return;
    previous = progress;
    const t = progress * (1 + progress * (1 - progress));
    const level = ease(clamp(t / .88));
    const { near, far, aim, center, openWidth, zoom } = poses;
    const span = openWidth * zoom ** t;
    const shot = near.map((point, i) => point.map((from, axis) =>
      aim[axis] + (center[axis] - aim[axis]) * level + span * (from + (far[i][axis] - from) * level)));
    const view = project(shot);
    world.style.transform = view.multiply(deskFromGlass).toString();
    stage.classList.toggle("has-capture", captureReady);
    // At rest, let the browser downsample text like a regular image without a 3D texture.
    const front = t === 1 && captureReady;
    glass.classList.toggle("is-front", front);
    // Prefilter small, tilted screens before projection so fine strokes survive minification.
    const screenPixels = span * window.devicePixelRatio;
    const small = captureReady && !front && screenPixels < glass.naturalWidth * .30;
    const sampleWidth = small ? 2 ** Math.ceil(Math.log2(screenPixels)) : glass.naturalWidth;
    glass.style.width = small ? sampleWidth + "px" : "";
    glass.style.height = small ? sampleWidth * glass.naturalHeight / glass.naturalWidth + "px" : "";
    const texture = view.multiply(appToGlass);
    glass.style.transform = front ? "none" : (small ? texture.scale(glass.naturalWidth / sampleWidth) : texture).toString();
    stage.style.setProperty("--screen-mix", String(captureReady ? .8 + .2 * ease(clamp(progress / .24)) : 0));
    const crosshair = view.transformPoint({ x: 800, y: 500 });
    stage.style.setProperty("--axis-x", crosshair.x / crosshair.w + "px");
    stage.style.setProperty("--axis-y", crosshair.y / crosshair.w + "px");
    stage.style.setProperty("--axis-hole-x", (span * .56 + 32) + "px");
    stage.style.setProperty("--axis-hole-y", (span * .49 + 20) + "px");
    const reveal = ease(clamp((progress - .49) / .39));
    stage.style.setProperty("--glass-light", String(.88 + .12 * reveal));
    stage.style.setProperty("--copy-opacity", String(1 - ease(clamp(progress / .25))));
    stage.style.setProperty("--opening-link-visibility", progress >= .24 ? "hidden" : "visible");
    const room = 1 - ease(clamp(progress / .76));
    stage.style.setProperty("--room-presence", room.toFixed(4));
    stage.classList.toggle("inside-screen", room === 0);
    stage.style.setProperty("--desk-opacity", front ? "0" : "1");
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
  window.addEventListener("load", refresh, { once: true });
  glass.addEventListener("load", refresh, { once: true });
  paperImage.addEventListener("load", refresh, { once: true });
  if (paperImage.complete && !paperImage.naturalWidth) intro.classList.add("page-missing");
  paperImage.addEventListener("error", () => intro.classList.add("page-missing"), { once: true });
  window.addEventListener("scroll", schedule, { passive: true });
  if (window.ResizeObserver) new ResizeObserver(refresh).observe(stage);
  else window.addEventListener("resize", refresh);
  motion.addEventListener("change", refresh);
  narrow.addEventListener("change", refresh);
})();
