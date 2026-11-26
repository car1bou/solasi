(() => {
  const runway = document.querySelector(".process-run");
  const film = document.querySelector(".film");
  const display = film.querySelector(".film-display");
  const stage = runway.querySelector(".process-list");
  const steps = [...stage.children];
  const clips = steps.map(step => step.querySelector("video"));
  const devices = steps.map(step => step.querySelector("figcaption > span").textContent.trim());
  const separate = steps.map((step, i) => step.dataset.separateDemo ||
    (i > 0 && devices[i] !== devices[i - 1] ? devices[i] + " 시연" : ""));
  const links = steps.map(step => step.querySelector(".step-film a"));
  const controls = runway.querySelector(".process-controls");
  const previous = controls.querySelector(".step-prev");
  const next = controls.querySelector(".step-next");
  const counter = controls.querySelector("output");
  const toggle = document.createElement("button");
  toggle.type = "button";
  counter.after(toggle);
  const heldFrame = document.createElement("canvas");
  const reduced = matchMedia("(prefers-reduced-motion: reduce)");
  let current = 0, seated = false, visible = false, frame = 0;
  let paused = Boolean(navigator.connection?.saveData);

  function updateControls() {
    const clip = clips[current];
    previous.disabled = current === 0;
    next.disabled = current === steps.length - 1;
    const separateDemo = separate[current + 1];
    next.textContent = separateDemo ? separateDemo + " →" : "다음 →";
    next.setAttribute("aria-label", separateDemo ? "다음 단계: " + separateDemo : "다음 단계");
    counter.setAttribute("aria-live", paused ? "polite" : "off");
    counter.textContent = (current + 1) + " / " + steps.length;
    toggle.textContent = clip.ended ? "다시 보기" : clip.paused ? "재생" : "일시 정지";
    toggle.disabled = Boolean(clip.error);
  }

  function play() {
    const clip = clips[current];
    if (!clip.hasAttribute("src")) clip.src = links[current].href;
    clip.play().catch(updateControls);
  }

  function select(index) {
    const old = clips[current];
    old.pause();
    if (old.readyState >= 1) old.currentTime = 0;
    old.classList.remove("is-showing");
    current = index;
    steps.forEach((step, i) => {
      step.inert = i !== index;
      if (i === index) step.setAttribute("aria-current", "step");
      else step.removeAttribute("aria-current");
    });
    if (steps[index + 1]) steps[index + 1].querySelector("img").loading = "eager";
    updateControls();
    if (visible && !paused) play();
  }

  previous.onclick = () => select(current - 1);
  next.onclick = () => select(current + 1);
  toggle.onclick = () => {
    const clip = clips[current];
    paused = !clip.paused;
    if (paused) clip.pause();
    else play();
  };

  clips.forEach((clip, i) => {
    clip.addEventListener("playing", () => {
      if (i !== current || !visible) { clip.pause(); return; }
      clip.classList.add("is-showing");
      updateControls();
    });
    clip.addEventListener("pause", updateControls);
    clip.addEventListener("error", updateControls);
    clip.addEventListener("ended", () => {
      if (i === current && visible && !paused && i + 1 < steps.length && !separate[i + 1] &&
          !steps[i].contains(document.activeElement)) select(i + 1);
      else updateControls();
    });
  });

  // Scrolling back carries the frame the visitor last saw onto the physical display.
  function keepFrame() {
    const clip = clips[current];
    const source = clip.readyState >= 2 && clip.classList.contains("is-showing")
      ? clip : steps[current].querySelector("img");
    const width = source.videoWidth || source.naturalWidth;
    if (!width) return;
    heldFrame.width = width;
    heldFrame.height = source.videoHeight || source.naturalHeight;
    heldFrame.getContext("2d").drawImage(source, 0, 0);
    if (!heldFrame.parentElement) display.append(heldFrame);
  }

  function sync() {
    frame = 0;
    if (reduced.matches) return;
    const top = parseFloat(getComputedStyle(stage).top) || 0;
    const rect = runway.getBoundingClientRect();
    const docked = !film.classList.contains("camera-ready") || rect.top <= top + 1;
    if (seated && !docked) keepFrame();
    seated = docked;
    const threshold = Math.min(stage.offsetHeight, innerHeight) * .48;
    const watching = docked && !document.hidden && rect.top <= innerHeight - threshold && rect.bottom >= top + threshold;
    if (watching === visible) return;
    visible = watching;
    const clip = clips[current];
    if (!visible) clip.pause();
    else if (!paused && !clip.ended) play();
  }

  function schedule() {
    if (!frame) frame = requestAnimationFrame(sync);
  }

  function configure() {
    visible = seated = false;
    clips[current].pause();
    heldFrame.remove();
    runway.classList.toggle("is-player", !reduced.matches);
    controls.hidden = reduced.matches;
    if (reduced.matches) {
      steps.forEach(step => { step.inert = false; step.removeAttribute("aria-current"); });
    } else {
      select(0);
      sync();
    }
  }

  configure();
  window.addEventListener("scroll", schedule, {passive: true});
  window.addEventListener("resize", schedule);
  window.addEventListener("load", schedule, {once: true});
  document.addEventListener("visibilitychange", sync);
  reduced.addEventListener("change", configure);
})();
