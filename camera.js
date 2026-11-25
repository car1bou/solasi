(() => {
  const film = document.querySelector(".film");
  if (!film) return;

  const stage = film.querySelector(".film-stage");
  const header = document.querySelector(".masthead");
  const world = film.querySelector(".film-world");
  const wood = world.querySelector(".wood-field");
  const glass = film.querySelector(".film-glass");
  const intro = document.querySelector(".problem-heading");
  const paper = intro.querySelector(".lecture-page");
  const paperImage = paper.querySelector("img");
  const motion = matchMedia("(prefers-reduced-motion: reduce)");
  const narrow = matchMedia("(max-aspect-ratio: 9/10)");
  const mac = document.documentElement.dataset.device === "mac";
  // The Mac display starts just below its photographed camera notch.
  const desktopPhoto = mac
    ? {file: "macbook-studio.webp", width: 1254, height: 1254, screen: [[484.5,330],[1105,330],[1103.3,701.5],[485.8,702.6]], body: [431,305,1169,929]}
    : {file: "tablet-studio-wide.webp", width: 3372, height: 1641, screen: [[1608.9,459.28],[2595.98,444.26],[2600.57,1051.74],[1611.74,1058.21]]};
  const mobilePhoto = mac
    ? {file: "macbook-studio-tall.webp", width: 1024, height: 1536, screen: [[185.5,261],[839.4,261],[837.4,648.5],[186.2,648.5]], body: [128,234,907,887]}
    : {file: "tablet-studio-tall.webp", width: 1005, height: 2642, screen: [[108.17,756.3],[894.75,755.82],[894.95,1266.72],[108.02,1267.06]]};
  const plate = world.querySelector(".film-photo");
  const portraitSource = document.createElement("source");
  portraitSource.media = narrow.media;
  portraitSource.width = mobilePhoto.width;
  portraitSource.height = mobilePhoto.height;
  portraitSource.srcset = "assets/" + mobilePhoto.file;
  plate.before(portraitSource);
  plate.width = desktopPhoto.width;
  plate.height = desktopPhoto.height;
  plate.src = "assets/" + desktopPhoto.file;
  const capture = mac ? "assets/mac-transcript.png?v=dark1" : "assets/tablet-notebook.png?v=dark1";
  for (const image of [glass, paperImage]) {
    image.width = mac ? 1160 : 2560;
    image.height = mac ? 792 : 1600;
    image.src = capture;
  }
  if (mac) {
    paperImage.alt = "Mac에서 기억과 학습 강의의 대본을 열어 작업 기억에 관한 문장을 확인하는 화면";
    for (const [key, value] of Object.entries({x: 228, y: 53, w: 902, h: 441})) {
      paper.style.setProperty("--pdf-" + key, value);
    }
    paper.style.setProperty("--app-w", glass.width);
    paper.style.setProperty("--app-h", glass.height);
  }
  if (!window.DOMMatrix) return;
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

  let poses, deskFromGlass, appToGlass, previous = -1, previousCover = -1, frame = 0;

  function compose() {
    const w = stage.clientWidth, h = stage.clientHeight;
    if (!w || !h) return;
    const pageLeft = Number(getComputedStyle(paper).getPropertyValue("--pdf-x"));
    const portrait = narrow.matches;
    const photo = portrait ? mobilePhoto : desktopPhoto;
    const glassOnDesk = project(photo.screen);
    deskFromGlass = glassOnDesk.inverse();
    const appWidth = glass.naturalWidth || Number(glass.getAttribute("width"));
    const appHeight = glass.naturalHeight || Number(glass.getAttribute("height"));
    if (!(appWidth > 0 && appHeight > 0)) return;
    // Fill the Mac glass with the window's top 16:10 crop. The lower margin is outside the display.
    const fit = mac ? 1600 / appWidth : Math.min(1600 / appWidth, 1000 / appHeight);
    const insetX = (1600 - appWidth * fit) / 2;
    const insetY = mac ? 0 : (1000 - appHeight * fit) / 2;
    const shownHeight = Math.min(appHeight, 1000 / fit);
    if (mac) glass.style.clipPath = `inset(0 0 ${100 * (1 - shownHeight / appHeight)}% 0)`;
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
    let scale = portrait ? cover : Math.max(cover, Math.min(w * .56 / 988, (h - header.offsetHeight * .55) * .86 / 755));
    const screenMiddle = glassOnDesk.transformPoint({ x: 800, y: 500 });
    let subjectX = screenMiddle.x / screenMiddle.w, subjectY = screenMiddle.y / screenMiddle.w;
    if (mac) {
      const [left, top, right, bottom] = photo.body;
      subjectX = (left + right) / 2; subjectY = (top + bottom) / 2;
      // Keep the keyboard in shot, even in a panoramic window or a narrow Split View.
      const limit = Math.min(w * (portrait ? .94 : .65) / (right - left),
        (h - header.offsetHeight * .55) * (portrait ? .50 : .89) / (bottom - top));
      scale = Math.min(Math.max(cover, w * (portrait ? .91 : .57) / (right - left)), limit);
    }
    const pan = (viewport, size, aim, subject, room) => {
      if (mac && size * scale < viewport + 2 * room) return aim - subject * scale;
      const margin = Math.min(room, (size * scale - viewport) / 2);
      return Math.min(-margin, Math.max(viewport + margin - size * scale, aim - subject * scale));
    };
    const horizontalAim = portrait ? w / 2 : mac ? w * .68 : Math.min(w * .655, w - scale * 530 - roomX);
    const verticalAim = mac ? (portrait ? h*.35 : h*.50 + header.offsetHeight*.25) : (portrait ? h*.40 : h*.47 + header.offsetHeight*.26);
    const panorama = mac && photo.width * scale < w + 2 * roomX;
    const x = panorama ? w + roomX - photo.width * scale : pan(w, photo.width, horizontalAim, subjectX, roomX);
    const y = pan(h, photo.height, verticalAim, subjectY, roomY);
    if (mac) {
      const silhouette = `url("assets/${portrait ? "macbook-tall-mask.svg" : "macbook-mask.svg"}")`;
      wood.style.maskImage = panorama ? silhouette + ",linear-gradient(90deg,transparent,#000 10%)" : silhouette;
      wood.style.maskComposite = "intersect";
      // Bookmatch the empty left edge of the same photograph for extra-wide windows.
      const wing = panorama ? Math.max(0, (x + roomX) / scale) : 0;
      world.style.setProperty("--wood-wing", wing + "px");
      world.style.setProperty("--wing-photo", `url("assets/${photo.file}")`);
      world.style.setProperty("--wing-size", Math.max(photo.width, wing / .30) + "px");
      world.style.maskImage = y > -roomY || y + photo.height * scale < h + roomY
        ? "linear-gradient(transparent,#000 9%,#000 93%,transparent)" : "none";
    }
    const opening = photo.screen.map(([sx, sy]) => [x + sx * scale, y + sy * scale]);
    // Anchor the moving light to this crop even when the page opens mid-zoom.
    world.dataset.woodView = [-x / (photo.width * scale), -y / (photo.height * scale),
      w / (photo.width * scale), h / (photo.height * scale)].join(" ");

    // Cross the bezel. On a phone the left margin of the actual lecture page guides the framing.
    const endScale = Math.max((w + 4) / appWidth, (h + 4) / shownHeight);
    const fullW = appWidth * endScale, fullH = appHeight * endScale;
    const centered = (w - fullW) / 2;
    const appLeft = Math.min(-2, Math.max(centered, w * .045 - pageLeft * endScale));
    const appTop = (h - shownHeight * endScale) / 2;
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
      aim, center, openWidth, zoom: closeWidth / openWidth };
    previous = previousCover = -1;
  }

  function paint() {
    frame = 0;
    if (!poses) return;
    const box = film.getBoundingClientRect();
    const height = stage.clientHeight;
    const captureReady = glass.naturalWidth > 0;
    const moving = captureReady && !motion.matches;
    const scroll = moving ? clamp(-box.top / Math.max(1, box.height - height)) : 0;
    // Hold the photograph for the first scroll beat, then settle inside the app before the page turns.
    const progress = clamp((scroll - .13) / .75);
    const cover = moving ? Math.min(height, Math.max(0, height - box.bottom)) : 0;
    if (cover !== previousCover) {
      stage.classList.toggle("revealing-chapter", cover > 0 && cover < height);
      stage.style.setProperty("--cover-y", cover + "px");
      stage.style.setProperty("--cover-feather", Math.min(height * .12, cover * .75, 96) + "px");
    }
    if (progress === previous && cover === previousCover) return;
    previousCover = cover;
    const immersion = ease(clamp((progress - .30) / .36)) * (1 - ease(clamp((cover / height - .18) / .44)));
    header.style.setProperty("--into-app", (-101 * immersion).toFixed(2) + "%");
    if (progress === previous) return;
    previous = progress;
    const t = ease(progress);
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
    stage.style.setProperty("--axis-hole-x", (span * (mac ? .70 : .56) + 32) + "px");
    stage.style.setProperty("--axis-hole-y", (span * (mac ? .80 : .49) + 20) + "px");
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
    film.classList.toggle("camera-ready", !motion.matches && !(glass.complete && !glass.naturalWidth));
    compose();
    paint();
  }

  film.classList.add("camera-framed");
  refresh();
  window.addEventListener("load", refresh, { once: true });
  glass.addEventListener("load", refresh, { once: true });
  glass.addEventListener("error", refresh, { once: true });
  if (paperImage.complete && !paperImage.naturalWidth) intro.classList.add("page-missing");
  paperImage.addEventListener("error", () => intro.classList.add("page-missing"), { once: true });
  window.addEventListener("scroll", schedule, { passive: true });
  if (window.ResizeObserver) new ResizeObserver(refresh).observe(stage);
  else window.addEventListener("resize", refresh);
  motion.addEventListener("change", refresh);
  narrow.addEventListener("change", refresh);
})();
