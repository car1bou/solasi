(() => {
  const film = document.querySelector(".film");
  if (!film) return;

  const stage = film.querySelector(".film-stage");
  const header = document.querySelector(".masthead");
  const world = film.querySelector(".film-world");
  const wood = world.querySelector(".wood-field");
  const heroCopy = film.querySelector(".film-copy");
  const sourceLink = film.querySelector(".film-source");
  const heroDescription = film.querySelector(".film-description");
  const glass = film.querySelector(".film-glass");
  const plane = film.querySelector(".glass-plane");
  const lesson = document.getElementById("process");
  const list = lesson.querySelector(".process-list");
  const seat = list.querySelector(".step-screen");
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
  const planeHeight = device === "ipad" ? 1200 : 1000;
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
    const capture = mac ? "assets/mac-transcript.png?v=dark1" : "assets/tablet-notebook.png?v=dark1";
    paperImage.width = mac ? 1160 : 2560;
    paperImage.height = mac ? 792 : 1600;
    paperImage.src = capture;
    if (mac) {
      paperImage.alt = "Mac에서 기억과 학습 강의의 대본을 열어 작업 기억에 관한 문장을 확인하는 화면";
      for (const [key, value] of Object.entries({x: 228, y: 53, w: 902, h: 441})) {
        paper.style.setProperty("--pdf-" + key, value);
      }
      paper.style.setProperty("--app-w", paperImage.width);
      paper.style.setProperty("--app-h", paperImage.height);
    }
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

  let opening, landing, copyBounds, deskFromGlass, previous = -1, frame = 0;

  function compose() {
    const w = stage.clientWidth, h = stage.clientHeight;
    if (!w || !h) return;
    const portrait = narrow.matches;
    const photo = portrait ? mobilePhoto : desktopPhoto;
    const glassOnDesk = project(photo.screen);
    deskFromGlass = glassOnDesk.inverse();
    world.style.setProperty("--photo-w", photo.width + "px");
    world.style.setProperty("--photo-h", photo.height + "px");

    // Leave enough photographed wood around the frame for both the pointer and idle camera.
    const roomX = Math.min(portrait ? 27 : 48, w * (portrait ? .031 : .042));
    const roomY = Math.min(24, h * .034);
    const cover = Math.max((w + 2 * roomX) / photo.width, (h + 2 * roomY) / photo.height);
    // The bounds include the full case and accessories. Reserve actual text and navigation
    // space before fitting the photograph, including room for pointer-driven camera drift.
    const [left, bodyTop, right, bottom] = photo.body;
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
    const y = between(pan(h, photo.height, aimY, (bodyTop + bottom) / 2, roomY),
      safeTop - bodyTop * scale, safeBottom - bottom * scale);

    world.classList.toggle("wide-desk", panorama);
    const mask = {mac: "macbook", ipad: "ipad", windows: "windows-desktop"}[device];
    const maskFile = mask ? mask + (portrait ? "-tall" : "") : "walnut-" + (portrait ? "tall" : "wide");
    const silhouette = `url("assets/${maskFile}-mask.svg")`;
    wood.style.maskImage = panorama ? silhouette + ",linear-gradient(90deg,transparent,#000 10%)" : silhouette;
    wood.style.maskComposite = "intersect";
    // Bookmatch the empty left edge of the same photograph for extra-wide windows.
    const wing = panorama ? Math.max(0, (x + roomX) / scale) : 0;
    world.style.setProperty("--wood-wing", wing + "px");
    world.style.setProperty("--wing-photo", `url("assets/${photo.file}")`);
    world.style.setProperty("--wing-size", Math.max(photo.width, wing / .30) + "px");
    world.style.maskImage = y > -roomY || y + photo.height * scale < h + roomY
      ? "linear-gradient(transparent,#000 9%,#000 93%,transparent)" : "none";
    opening = photo.screen.map(([sx, sy]) => [x + sx * scale, y + sy * scale]);
    // Anchor the moving light to this crop even when the page opens mid-zoom.
    world.dataset.woodView = [-x / (photo.width * scale), -y / (photo.height * scale),
      w / (photo.width * scale), h / (photo.height * scale)].join(" ");

    // The active caption can wrap to a different height after a manual chapter change.
    const step = list.querySelector('[aria-current="step"]') || list.firstElementChild;
    const target = step.querySelector(".step-screen").getBoundingClientRect();
    const stickyTop = parseFloat(getComputedStyle(list).top) || 0;
    const listOffset = stickyTop - list.getBoundingClientRect().top;
    const top = target.top + listOffset;
    const copyRect = step.querySelector(".step-copy").getBoundingClientRect();
    copyBounds = [copyRect.left, copyRect.top + listOffset, copyRect.right, copyRect.bottom + listOffset];
    landing = [[target.left, top], [target.right, top],
      [target.right, top + target.height], [target.left, top + target.height]];
    previous = -1;
  }

  function paint() {
    frame = 0;
    if (!landing) return;
    const moving = film.classList.contains("camera-ready");
    const stickyTop = parseFloat(getComputedStyle(list).top) || 0;
    const travel = Math.max(1, film.offsetHeight - stage.clientHeight - stickyTop);
    const offset = -film.getBoundingClientRect().top;
    const scroll = moving ? clamp(offset / travel) : 0;
    if (scroll === previous) return;
    previous = scroll;
    const t = ease(clamp((scroll - .19) / .81));
    const docked = moving && offset >= travel - .75;
    const shot = opening.map((corner, i) => corner.map((n, axis) =>
      n + (landing[i][axis] - n) * t));
    const view = project(shot);
    world.style.transform = view.multiply(deskFromGlass).toString();
    plane.style.transform = view.toString();
    stage.classList.toggle("has-capture", glass.naturalWidth > 0);
    const copy = 1 - ease(clamp((scroll - .12) / .32));
    const room = 1 - ease(clamp((scroll - .14) / .50));
    stage.style.setProperty("--copy-opacity", copy);
    stage.style.setProperty("--opening-link-visibility", copy > .05 ? "visible" : "hidden");
    stage.style.setProperty("--room-presence", room);
    stage.style.setProperty("--desk-opacity", room);
    header.style.setProperty("--header-fill", ease(clamp((scroll - .58) / .42)));
    stage.style.setProperty("--screen-mix", glass.naturalWidth ? 1 : 0);
    stage.classList.toggle("inside-screen", room === 0);
    stage.classList.toggle("dissolving-desk", room < 1);
    film.classList.toggle("docked", docked);
    const arrival = moving ? ease(clamp((scroll - .42) / .48)) : 1;
    lesson.style.setProperty("--lesson-copy", arrival);
    // On stacked layouts the screen passes the text before settling beneath it.
    const gap = Math.max(Math.min(...shot.map(p => p[0])) - copyBounds[2],
      copyBounds[0] - Math.max(...shot.map(p => p[0])),
      Math.min(...shot.map(p => p[1])) - copyBounds[3],
      copyBounds[1] - Math.max(...shot.map(p => p[1])));
    lesson.style.setProperty("--step-copy", arrival * ease(clamp(gap / 12)));
    lesson.style.setProperty("--approach-y", moving ? -Math.max(0, travel - offset) + "px" : "0px");
    const center = view.transformPoint({ x: 800, y: planeHeight / 2 });
    const span = Math.hypot(shot[1][0] - shot[0][0], shot[1][1] - shot[0][1]);
    // Fit the undistorted recording into the photographed LCD and then into the player.
    const height = Math.hypot(shot[3][0] - shot[0][0], shot[3][1] - shot[0][1]);
    if (glass.naturalWidth && height && span) {
      const fit = (glass.naturalWidth / glass.naturalHeight) / (span / height);
      glass.parentElement.style.transform = `scale(${Math.min(1, fit)}, ${Math.min(1, 1 / fit)})`;
    }
    stage.style.setProperty("--axis-x", center.x / center.w + "px");
    stage.style.setProperty("--axis-y", center.y / center.w + "px");
    stage.style.setProperty("--axis-hole-x", (span * (device === "windows" || device === "mac" ? .70 : .56) + 32) + "px");
    stage.style.setProperty("--axis-hole-y", (span * (device === "windows" || device === "mac" ? .80 : .49) + 20) + "px");
  }

  function schedule() {
    if (!frame && !motion.matches) frame = requestAnimationFrame(paint);
  }

  function refresh() {
    film.classList.toggle("camera-ready", !motion.matches && glass.naturalWidth > 0 && plate.naturalWidth > 0);
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
    sizes.observe(stage);
    sizes.observe(seat);
    sizes.observe(heroCopy);
    sizes.observe(list);
  } else window.addEventListener("resize", refresh);
  list.addEventListener("stepchange", refresh);
  motion.addEventListener("change", refresh);
  narrow.addEventListener("change", refresh);
})();
