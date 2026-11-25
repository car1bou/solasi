(() => {
  const find = selector => document.querySelector(selector);
  const reduced = matchMedia("(prefers-reduced-motion: reduce)");
  const compact = matchMedia("(max-width: 47.99rem)");
  const root = document.documentElement;
  const bound = n => Math.max(0, Math.min(1, n));
  const mix = (a, b, t) => a + (b - a) * t;
  const ease = t => t * t * (3 - 2 * t);

  function dock(header, src, kind) {
    const image = new Image();
    image.alt = "";
    image.setAttribute("aria-hidden", "true");
    image.className = "chapter-dock chapter-" + kind;
    image.loading = "lazy";
    image.src = src;
    if (kind === "mark") find(header).prepend(image);
    else find(header).append(image);
    return image;
  }

  document.querySelectorAll(".work-still figcaption > span").forEach(label => {
    const mark = new Image(26, 26);
    mark.src = "assets/solasi-icon.png";
    mark.alt = "";
    mark.className = "chapter-origin-mark";
    label.prepend(mark);
  });
  dock(".work-heading", "assets/mac-transcript.png?v=dark1", "screen");
  const routes = [
    [".process-list li:last-child .step-screen", find(".lecture-window")],
    [".week-sketch span:last-child", find(".course-map b")],
    [".solution-list li:last-child .solution-code", find(".result-example")],
    [".chapter-origin-mark", dock(".install-heading", "assets/solasi-icon.png", "mark")],
  ];
  const carrier = document.createElement("div");
  carrier.className = "chapter-carrier";
  carrier.setAttribute("aria-hidden", "true");
  carrier.hidden = true;
  document.body.append(carrier);
  let source, destination, stopCapture, frame = 0;

  function followVideo(video, surface) {
    const canvas = document.createElement("canvas");
    const context = canvas.getContext("2d");
    if (!context) return;
    function paint() {
      if (video.readyState < 2 || !video.classList.contains("is-showing")) return;
      const w = Math.min(1000, video.videoWidth);
      if (canvas.width !== w) {
        canvas.width = w;
        canvas.height = Math.round(w * video.videoHeight / video.videoWidth);
      }
      context.drawImage(video, 0, 0, canvas.width, canvas.height);
      if (surface.firstChild !== canvas) surface.replaceChildren(canvas);
    }
    paint();
    if (video.requestVideoFrameCallback) {
      let callback;
      function next() { paint(); callback = video.requestVideoFrameCallback(next); }
      callback = video.requestVideoFrameCallback(next);
      stopCapture = () => video.cancelVideoFrameCallback(callback);
    } else {
      video.addEventListener("timeupdate", paint);
      stopCapture = () => video.removeEventListener("timeupdate", paint);
    }
  }

  function face(element) {
    const surface = document.createElement("div");
    surface.className = "chapter-face";
    const image = element.matches("img") ? element : element.querySelector("img");
    if (image) {
      const still = image.cloneNode(false);
      still.className = "";
      still.alt = "";
      still.loading = "eager";
      if (element.classList.contains("lecture-window")) {
        // The next chapter shows a detail from the capture; land on the same crop.
        const frame = element.getBoundingClientRect(), crop = image.getBoundingClientRect();
        still.style.position = "absolute";
        still.style.width = 100 * crop.width / frame.width + "%";
        still.style.height = 100 * crop.height / frame.height + "%";
        still.style.left = 100 * (crop.left - frame.left) / frame.width + "%";
        still.style.top = 100 * (crop.top - frame.top) / frame.height + "%";
      }
      surface.append(still);
      const video = element.querySelector("video");
      if (video) followVideo(video, surface);
    } else {
      const style = getComputedStyle(element);
      surface.classList.add("is-label");
      surface.textContent = element.textContent;
      surface.style.background = style.backgroundImage === "none" ? style.backgroundColor : style.backgroundImage;
      surface.style.color = style.color;
      surface.style.fontSize = style.fontSize;
      surface.style.fontWeight = style.fontWeight;
      surface.style.borderStyle = style.borderStyle;
      surface.style.borderColor = style.borderColor;
      surface.style.borderWidth = style.borderWidth;
      surface.style.padding = style.padding;
      if (element.parentElement.classList.contains("week-sketch")) surface.style.justifyItems = "start";
    }
    return surface;
  }

  function release() {
    stopCapture?.();
    stopCapture = null;
    source?.classList.remove("chapter-in-transit");
    destination?.classList.remove("chapter-in-transit");
    source = destination = null;
    carrier.hidden = true;
  }

  function render() {
    frame = 0;
    if (reduced.matches) return;
    const height = innerHeight, width = document.documentElement.clientWidth;
    for (const [selector, target] of routes) {
      const origin = selector === ".chapter-origin-mark"
        ? [...document.querySelectorAll(selector)].find(mark => mark.offsetWidth)
        : find(selector);
      if (!origin) continue;
      if (origin.classList.contains("step-screen") && !origin.closest("li").hasAttribute("aria-current")) continue;
      const from = origin.getBoundingClientRect(), to = target.getBoundingClientRect();
      if (!from.width || !to.width) continue;
      const start = from.top + from.height / 2, end = to.top + to.height / 2;
      const distance = end - start - height * .13;
      const progress = distance > 0 ? (height * .42 - start) / distance : 0;
      if (progress <= 0 || progress >= 1) continue;
      if (target !== destination || origin !== source) {
        release();
        source = origin;
        destination = target;
        carrier.replaceChildren(face(source));
        if (!source.classList.contains("chapter-origin-mark")) carrier.append(face(destination));
        source.classList.add("chapter-in-transit");
        destination.classList.add("chapter-in-transit");
        carrier.hidden = false;
      }

      const t = ease(progress);
      const arc = Math.sin(Math.PI * progress) ** 2;
      // On narrow screens the travelling material stays beside the heading until it docks.
      const lane = compact.matches ? ease(bound(progress / .35)) * ease(bound((1 - progress) / .16)) : arc;
      const rawWidth = mix(from.width, to.width, t);
      const w = mix(rawWidth, Math.min(rawWidth, width * (compact.matches ? .19 : .23)), lane);
      const h = mix(from.height, to.height, t) * (w / rawWidth);
      let x = mix(from.left + from.width / 2, to.left + to.width / 2, t);
      if (compact.matches) {
        const edge = destination.classList.contains("chapter-mark") ? 46 : 20;
        x = mix(x, width - w / 2 - edge, lane);
      }
      let y = mix(start, end, t) - arc * Math.min(38, height * .035);
      if (compact.matches && destination.classList.contains("chapter-mark")) {
        const belowIndex = origin.closest(".work-grid").getBoundingClientRect().bottom + h / 2 + 12;
        y = mix(y, Math.max(y, belowIndex), ease(bound((progress - .18) / .3)));
      }
      carrier.style.width = w.toFixed(2) + "px";
      carrier.style.height = h.toFixed(2) + "px";
      carrier.style.transform = "translate3d(" + (x - w / 2).toFixed(2) + "px," + (y - h / 2).toFixed(2) + "px,0)";
      carrier.style.borderRadius = destination.classList.contains("chapter-mark") ? "22%" : "1.2%";
      if (carrier.children.length === 2) {
        const cut = 100 * ease(bound((t - .25) / .5));
        carrier.firstChild.style.clipPath = "inset(0 0 0 " + cut.toFixed(2) + "%)";
        carrier.lastChild.style.clipPath = "inset(0 " + (100 - cut).toFixed(2) + "% 0 0)";
      }
      return;
    }
    if (source) release();
  }

  function schedule() { if (!reduced.matches && !frame) frame = requestAnimationFrame(render); }
  function configure() {
    release();
    root.classList.toggle("chapter-joined", !reduced.matches);
    schedule();
  }
  addEventListener("scroll", schedule, {passive:true});
  addEventListener("resize", schedule);
  document.addEventListener("toggle", schedule, true);
  if (window.ResizeObserver) {
    const sizes = new ResizeObserver(schedule);
    document.querySelectorAll(".work-index details").forEach(item => sizes.observe(item));
  }
  reduced.addEventListener("change", configure);
  configure();
})();
