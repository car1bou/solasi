(() => {
  const header = document.querySelector(".masthead");
  const menu = header.querySelector(".fold-nav");
  const sections = Array.from(document.querySelectorAll("main > section"));
  const navLinks = header.querySelectorAll("a[href^='#']");
  let scheduled = false;
  let current = "";

  function updateNavigation() {
    scheduled = false;
    const limit = header.offsetHeight + 2;
    const next = sections.findIndex(section => section.getBoundingClientRect().top > limit);
    const visible = (next < 0 ? sections[sections.length - 1] : sections[Math.max(0, next - 1)]).id;
    const active = visible === "preview" ? "home" : visible;
    header.classList.toggle("compact", scrollY > limit);
    if (active === current) return;
    current = active;
    for (const link of navLinks) {
      if (link.hash === "#" + active && !link.classList.contains("brand")) link.setAttribute("aria-current", "location");
      else link.removeAttribute("aria-current");
    }
  }
  function schedule() {
    if (!scheduled) { scheduled = true; requestAnimationFrame(updateNavigation); }
  }
  addEventListener("scroll", schedule, { passive: true });
  addEventListener("resize", schedule);
  document.addEventListener("toggle", schedule, true);
  updateNavigation();

  menu.querySelector("nav").addEventListener("click", event => {
    if (event.target.closest("a")) menu.open = false;
  });
  document.addEventListener("click", event => { if (menu.open && !menu.contains(event.target)) menu.open = false; });
  document.addEventListener("keydown", event => {
    if (event.key === "Escape" && menu.open) {
      menu.open = false;
      menu.querySelector("summary").focus();
    }
  });

  function openLinkedScreen(initial) {
    const hash = location.hash.slice(1);
    const platform = new URLSearchParams(location.search).get("platform");
    const legacy = initial && (!hash || hash === "preview") && (platform === "mac" || platform === "android");
    const id = legacy ? (platform === "mac" ? "transcript" : "notes") : hash;
    const screen = document.getElementById(id);
    if (!screen?.matches("details[name='work']")) return;
    screen.open = true;
    screen.scrollIntoView({ behavior: "instant", block: "start" });
  }
  openLinkedScreen(true);
  addEventListener("hashchange", () => openLinkedScreen(false));

  const viewer = document.getElementById("image-viewer");
  if (typeof viewer.showModal !== "function") return;
  for (const link of document.querySelectorAll(".enlarge")) {
    link.addEventListener("click", event => {
      if (event.button !== 0 || event.metaKey || event.ctrlKey || event.altKey || event.shiftKey) return;
      event.preventDefault();
      const figure = link.closest("figure");
      document.getElementById("viewer-label").textContent = figure.querySelector("figcaption span").textContent;
      const image = viewer.querySelector("img");
      image.src = link.href;
      image.alt = figure.querySelector("img").alt;
      viewer.showModal();
    });
  }
})();
