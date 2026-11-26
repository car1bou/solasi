(() => {
  const film = document.querySelector(".film");
  if (!film) return;

  const stage = film.querySelector(".film-stage");
  const header = document.querySelector(".masthead");
  const world = film.querySelector(".film-world");
  const backdrop = document.querySelector(".opening-plate");
  const heroCopy = film.querySelector(".film-copy");
  const sourceLink = film.querySelector(".film-source");
  const heroDescription = film.querySelector(".film-description");
  const glass = film.querySelector(".film-glass");
  const plane = film.querySelector(".glass-plane");
  const axes = film.querySelector(".field-axes");
  const lesson = document.getElementById("process");
  const list = lesson.querySelector(".process-list");
  const chapterTitle = lesson.querySelector(".process-heading");
  const seat = list.querySelector(".step-screen");
  const firstCopy = list.querySelector(".step-copy");
  const intro = document.querySelector(".problem-heading");
  const paper = intro.querySelector(".lecture-page");
  const paperImage = paper.querySelector("img");
  const motion = matchMedia("(prefers-reduced-motion: reduce)");
  const narrow = matchMedia("(max-aspect-ratio: 9/10)");
  const device = document.documentElement.dataset.device;
  const scenes = {
    tablet: [
      {file: "tablet-studio-wide.webp", width: 3372, height: 1641, screen: [[1608.9,459.28],[2595.98,444.26],[2600.57,1051.74],[1611.74,1058.21]], body: [1569,403,2642,1182]},
      {file: "tablet-studio-tall.webp", width: 1005, height: 2642, screen: [[108.17,756.3],[894.75,755.82],[894.95,1266.72],[108.02,1267.06]], body: [72,720,930,1371]}
    ],
    ipad: [
      {file: "ipad-studio-wide.webp", width: 1254, height: 1254, screen: [[421,353],[1145,353],[1145,868],[421,868]], body: [398,331,1167,956]},
      {file: "ipad-studio-tall.webp", width: 1024, height: 1536, screen: [[121,365],[904,365],[904,924],[121,924]], body: [96,341,928,1019]}
    ],
    mac: [
      {file: "macbook-studio.webp", width: 1254, height: 1254, screen: [[484.5,330],[1105,330],[1103.3,701.5],[485.8,702.6]], body: [431,305,1169,929]},
      {file: "macbook-studio-tall.webp", width: 1024, height: 1536, screen: [[185.5,261],[839.4,261],[837.4,648.5],[186.2,648.5]], body: [128,234,907,887]}
    ],
    windows: [
      {file: "windows-desktop-wide.webp", width: 1536, height: 1024, screen: [[507.5,156.5],[1276,156.5],[1275.5,560.5],[507.5,560.5]], body: [501,149,1494,889]},
      {file: "windows-desktop-tall.webp", width: 1024, height: 1536, screen: [[75,207.5],[786.5,207.5],[785.5,592],[77,592.5]], body: [69,201,977,897]}
    ]
  };
  const [desktopPhoto, mobilePhoto] = scenes[device] || scenes.tablet;
  const planeHeight = device === "ipad" ? 1200 : device === "windows" ? 900 : 1000;
  plane.style.height = planeHeight + "px";
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
  glass.src = seat.querySelector("img").src;
  if (!paperImage.hasAttribute("src")) {
    const mac = device === "mac";
    paperImage.width = mac ? 1280 : 2560;
    paperImage.height = mac ? 800 : 1600;
    paperImage.src = mac ? "assets/mac-transcript.png?v=se1" : "assets/tablet-notebook.png?v=se1";
    if (mac) paperImage.alt = "Mac에서 소프트웨어 공학 개요의 대본을 열어 설계 문서와 테스트 결과에 대한 설명을 읽는 화면";
  }
  if (!window.DOMMatrix) return;
  const clamp = value => Math.max(0, Math.min(1, value));
  const ease = value => value * value * (3 - 2 * value);

  // Project the app canvas onto the four measured corners of the photographed display.
  function project([[x0, y0], [x1, y1], [x2, y2], [x3, y3]]) {
    const dx1 = x1 - x2, dx2 = x3 - x2;
    const dy1 = y1 - y2, dy2 = y3 - y2;
    const sx = x0 - x1 + x2 - x3, sy = y0 - y1 + y2 - y3;
    const det = dx1 * dy2 - dx2 * dy1;
    const g = (sx * dy2 - sy * dx2) / det;
    const h = (sy * dx1 - sx * dy1) / det;
    return new DOMMatrix([
      (x1 - x0 + g * x1) / 1600, (y1 - y0 + g * y1) / 1600, 0, g / 1600,
      (x3 - x0 + h * x3) / planeHeight, (y3 - y0 + h * y3) / planeHeight, 0, h / planeHeight,
      0, 0, 1, 0,
      x0, y0, 0, 1,
    ]);
  }

  let loadedPhoto, opening, landing, deskFromGlass, copyHeadroom, origin = 0, travel = 1, previous = -1, frame = 0;

  function compose() {
    const w = stage.clientWidth, h = stage.clientHeight;
    if (!w || !h) return;
    const portrait = narrow.matches;
    const photo = loadedPhoto || (portrait ? mobilePhoto : desktopPhoto);
    // The two front-on monitor photos have slightly wide LCDs. Calibrate the whole desk
    // to the native display ratio so the app and bezel keep the same four corners.
    const [tl, tr, , bl] = photo.screen;
    const heightCorrection = device === "windows"
      ? (tr[0] - tl[0]) / (bl[1] - tl[1]) * (planeHeight / 1600) : 1;
    const photoHeight = photo.height * heightCorrection;
    const glassOnDesk = project(photo.screen);
    deskFromGlass = glassOnDesk.inverse();
    world.style.setProperty("--photo-w", photo.width + "px");
    world.style.setProperty("--photo-h", photo.height + "px");

    // Leave photographed wood around the device as it blends into the shared desktop.
    const roomX = Math.min(portrait ? 27 : 48, w * (portrait ? .031 : .042));
    const roomY = Math.min(24, h * .034);
    const cover = Math.max((w + 2 * roomX) / photo.width, (h + 2 * roomY) / photoHeight);
    // The bounds include the full case and accessories. Reserve actual text and navigation
    // space before fitting the photograph.
    const [left, rawTop, right, rawBottom] = photo.body;
    const bodyTop = rawTop * heightCorrection, bottom = rawBottom * heightCorrection;
    const gap = Math.max(12, Math.min(24, w * .022));
    const safeLeft = portrait ? gap : heroCopy.offsetLeft + heroCopy.offsetWidth + gap;
    const safeRight = w - gap;
    const safeTop = header.offsetHeight + gap;
    const footerTop = Math.min(sourceLink.offsetTop, heroDescription.offsetTop);
    const safeBottom = (portrait ? heroCopy.offsetTop : footerTop) - gap;
    const bodyWidth = right - left, bodyHeight = bottom - bodyTop;
    const fit = Math.min(Math.max(1, safeRight - safeLeft) / bodyWidth,
      Math.max(1, safeBottom - safeTop) / bodyHeight);
    const ideal = w * (portrait ? .91 : .57) / bodyWidth;
    const scale = Math.min(Math.max(cover, ideal), fit);
    const between = (value, min, max) => Math.max(min, Math.min(max, value));
    const aimX = portrait ? w / 2 : w * .68;
    const aimY = portrait ? h * .37 : (safeTop + safeBottom) / 2;
    const panorama = photo.width * scale < w + 2 * roomX;
    const pan = (viewport, size, aim, center, room) => {
      const desired = aim - center * scale;
      return size * scale < viewport + 2 * room ? desired
        : between(desired, viewport + room - size * scale, -room);
    };
    const overscan = device === "windows" ? Math.min(roomX, 8) : roomX;
    const x = between(panorama ? w + overscan - photo.width * scale
      : pan(w, photo.width, aimX, (left + right) / 2, roomX),
      safeLeft - left * scale, safeRight - right * scale);
    const y = between(pan(h, photoHeight, aimY, (bodyTop + bottom) / 2, roomY),
      safeTop - bodyTop * scale, safeBottom - bottom * scale);

    const mask = {mac: "macbook", ipad: "ipad", windows: "windows-desktop"}[device];
    const tallPlate = photo === mobilePhoto;
    const maskFile = mask ? mask + (tallPlate ? "-tall" : "") : "walnut-" + (tallPlate ? "tall" : "wide");
    const silhouette = `url("assets/${maskFile}-mask.svg")`;
    world.style.setProperty("--wood-mask", silhouette);
    backdrop.style.setProperty("--wood-mask", silhouette);
    backdrop.style.width = photo.width + "px";
    backdrop.style.height = photo.height + "px";
    const photograph = `url("assets/${photo.file}")`;
    backdrop.style.backgroundImage = photograph;
    // A responsive picture can go blank while the other orientation downloads.
    world.style.backgroundImage = loadedPhoto && !plate.naturalWidth ? photograph : "";
    opening = photo.screen.map(([sx, sy]) => [x + sx * scale, y + sy * heightCorrection * scale]);

    const target = seat.getBoundingClientRect();
    const stickyTop = parseFloat(getComputedStyle(list).top) || 0;
    origin = film.getBoundingClientRect().top + scrollY;
    travel = Math.max(1, film.offsetHeight - h - stickyTop);
    const top = target.top + stickyTop - list.getBoundingClientRect().top;
    const headingHeight = chapterTitle.lastElementChild.getBoundingClientRect().bottom - chapterTitle.getBoundingClientRect().top;
    copyHeadroom = Math.max(1, firstCopy.offsetTop - headingHeight - 6);
    landing = [[target.left, top], [target.right, top],
      [target.right, top + target.height], [target.left, top + target.height]];
    previous = -1;
  }

  function paint() {
    frame = 0;
    if (!landing) return;
    const moving = film.classList.contains("camera-ready");
    const offset = scrollY - origin;
    const scroll = moving ? clamp(offset / travel) : 0;
    if (scroll === previous) return;
    previous = scroll;
    const t = ease(scroll);
    const docked = moving && offset >= travel - .75;
    const shot = opening.map((corner, i) => corner.map((n, axis) =>
      n + (landing[i][axis] - n) * t));
    const view = project(shot);
    const room = 1 - ease(clamp((scroll - .12) / .77));
    if (room > 0) {
      world.style.transform = backdrop.style.transform = view.multiply(deskFromGlass).toString();
    }
    backdrop.hidden = !moving || room === 0;
    backdrop.style.opacity = room;
    plane.style.transform = view.toString();
    const copy = 1 - ease(clamp((scroll - .12) / .32));
    stage.style.setProperty("--copy-opacity", copy);
    stage.style.setProperty("--opening-link-visibility", copy > .05 ? "visible" : "hidden");
    stage.style.setProperty("--room-presence", room);
    lesson.style.setProperty("--lesson-exposure", moving ? 1 - room : 1);
    header.style.setProperty("--header-fill", ease(clamp((scroll - .58) / .42)));
    const chapter = ease(clamp((scroll - .51) / .44));
    film.classList.toggle("docked", docked);
    lesson.style.setProperty("--lesson-copy", moving ? chapter : 1);
    // Keep the whole label above the moving LCD until it reaches the first player.
    const lift = Math.min(0, Math.min(shot[0][1], shot[1][1]) - landing[0][1]);
    firstCopy.style.translate = moving && !docked ? `0 ${lift}px` : "";
    firstCopy.style.opacity = moving && !docked ? chapter * ease(clamp(1 + lift / copyHeadroom)) : "";
    const approach = moving && offset < travel ? "0 " + (offset - travel) + "px" : "";
    list.style.translate = chapterTitle.style.translate = approach;
    const span = Math.hypot(shot[1][0] - shot[0][0], shot[1][1] - shot[0][1]);
    // Fit the undistorted recording into the photographed LCD and then into the player.
    const height = Math.hypot(shot[3][0] - shot[0][0], shot[3][1] - shot[0][1]);
    if (glass.naturalWidth && height && span) {
      const fit = (glass.naturalWidth / glass.naturalHeight) / (span / height);
      glass.parentElement.style.transform = `scale(${Math.min(1, fit)}, ${Math.min(1, 1 / fit)})`;
    }
    if (!copy) return;
    const center = view.transformPoint({ x: 800, y: planeHeight / 2 });
    axes.style.setProperty("--axis-x", center.x / center.w + "px");
    axes.style.setProperty("--axis-y", center.y / center.w + "px");
    axes.style.setProperty("--axis-hole-x", (span * (device === "windows" || device === "mac" ? .70 : .56) + 32) + "px");
    axes.style.setProperty("--axis-hole-y", (span * (device === "windows" || device === "mac" ? .80 : .49) + 20) + "px");
  }

  function schedule() {
    if (!frame && !motion.matches && !(previous === 1 && scrollY >= origin + travel)) frame = requestAnimationFrame(paint);
  }

  function refresh() {
    if (plate.naturalWidth && plate.currentSrc) {
      loadedPhoto = plate.currentSrc.endsWith("/" + mobilePhoto.file) ? mobilePhoto : desktopPhoto;
    }
    const captured = glass.naturalWidth > 0;
    stage.classList.toggle("has-capture", captured);
    stage.style.setProperty("--screen-mix", captured ? 1 : 0);
    film.classList.toggle("camera-ready", !motion.matches && captured && Boolean(loadedPhoto));
    compose();
    paint();
  }

  film.classList.add("camera-framed");
  refresh();
  window.addEventListener("load", refresh, { once: true });
  for (const image of [glass, plate]) {
    image.addEventListener("load", refresh);
    image.addEventListener("error", refresh);
  }
  if (paperImage.complete && !paperImage.naturalWidth) intro.classList.add("page-missing");
  paperImage.addEventListener("error", () => intro.classList.add("page-missing"), { once: true });
  window.addEventListener("scroll", schedule, { passive: true });
  if (window.ResizeObserver) {
    const sizes = new ResizeObserver(refresh);
    sizes.observe(film);
    sizes.observe(header);
    sizes.observe(stage);
    sizes.observe(seat);
    sizes.observe(heroCopy);
    sizes.observe(list);
  } else window.addEventListener("resize", refresh);
  motion.addEventListener("change", refresh);
  narrow.addEventListener("change", refresh);
})();
