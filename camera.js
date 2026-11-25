(() => {
  const film = document.querySelector(".film");
  if (!film) return;

  const stage = film.querySelector(".film-stage");
  const header = document.querySelector(".masthead");
  const world = film.querySelector(".film-world");
  const wood = world.querySelector(".wood-field");
  const glass = film.querySelector(".film-glass");
  const plane = film.querySelector(".glass-plane");
  const lesson = document.getElementById("process");
  const list = lesson.querySelector(".process-list");
  const seat = list.querySelector(".step-screen");
  const openingStill = plane.querySelector(".course-glass");
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

  let opening, landing, deskFromGlass, previous = -1, frame = 0;

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
    opening = photo.screen.map(([sx, sy]) => [x + sx * scale, y + sy * scale]);
    // Anchor the moving light to this crop even when the page opens mid-zoom.
    world.dataset.woodView = [-x / (photo.width * scale), -y / (photo.height * scale),
      w / (photo.width * scale), h / (photo.height * scale)].join(" ");

    // Measure the first real video in its pinned position, even on a deep link or after rotation.
    const target = seat.getBoundingClientRect();
    const stickyTop = parseFloat(getComputedStyle(list).top) || 0;
    const top = target.top - list.getBoundingClientRect().top + stickyTop;
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
    const t = ease(clamp((scroll - .12) / .87));
    const docked = moving && offset >= travel - .75;
    const shot = opening.map((corner, i) => corner.map((n, axis) =>
      n + (landing[i][axis] - n) * t));
    const view = project(shot);
    world.style.transform = view.multiply(deskFromGlass).toString();
    plane.style.transform = view.toString();
    stage.classList.toggle("has-capture", glass.naturalWidth > 0);
    const copy = 1 - ease(clamp((scroll - .12) / .32));
    const room = 1 - ease(clamp((scroll - .25) / .57));
    stage.style.setProperty("--copy-opacity", copy);
    stage.style.setProperty("--opening-link-visibility", copy > .05 ? "visible" : "hidden");
    stage.style.setProperty("--room-presence", room);
    stage.style.setProperty("--desk-opacity", room);
    stage.style.setProperty("--screen-mix", glass.naturalWidth ? .94 + .06 * t : 0);
    const course = ease(clamp((scroll - .44) / .39));
    plane.style.setProperty("--course-edge", (-6 + 112 * course) + "%");
    stage.classList.toggle("inside-screen", room === 0);
    stage.classList.toggle("dissolving-desk", room < 1);
    film.classList.toggle("docked", docked);
    lesson.style.setProperty("--lesson-copy", moving ? ease(clamp((scroll - .42) / .48)) : 1);
    lesson.style.setProperty("--lesson-controls", scroll > .50 ? "visible" : "hidden");
    lesson.style.setProperty("--approach-y", moving ? -Math.max(0, travel - offset) + "px" : "0px");
    const center = view.transformPoint({ x: 800, y: 500 });
    const span = Math.hypot(shot[1][0] - shot[0][0], shot[1][1] - shot[0][1]);
    stage.style.setProperty("--axis-x", center.x / center.w + "px");
    stage.style.setProperty("--axis-y", center.y / center.w + "px");
    stage.style.setProperty("--axis-hole-x", (span * (mac ? .70 : .56) + 32) + "px");
    stage.style.setProperty("--axis-hole-y", (span * (mac ? .80 : .49) + 20) + "px");
  }

  function schedule() {
    if (!frame && !motion.matches) frame = requestAnimationFrame(paint);
  }

  function refresh() {
    film.classList.toggle("camera-ready", !motion.matches && glass.naturalWidth > 0 && openingStill.naturalWidth > 0 && plate.naturalWidth > 0);
    compose();
    paint();
  }

  film.classList.add("camera-framed");
  refresh();
  window.addEventListener("load", refresh, { once: true });
  for (const image of [glass, openingStill, plate]) {
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
    sizes.observe(list);
  } else window.addEventListener("resize", refresh);
  motion.addEventListener("change", refresh);
  narrow.addEventListener("change", refresh);
})();
