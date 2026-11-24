(() => {
  const hint = navigator.userAgentData?.platform?.toLowerCase();
  const agent = navigator.userAgent;
  const appleMobile = /iPhone|iPad|iPod/i.test(agent) || navigator.maxTouchPoints > 1;
  const mac = hint !== "android" && !/Android/i.test(agent) && !appleMobile &&
    (hint === "macos" || /Macintosh/i.test(agent));

  function platformFromUrl() {
    const choice = new URLSearchParams(location.search).get("platform");
    if (choice === "mac" || choice === "android") return choice;
    return mac ? "mac" : "android";
  }

  const page = document.documentElement;
  page.dataset.platform = platformFromUrl();
  document.addEventListener("DOMContentLoaded", () => {
    const links = document.querySelectorAll(".platform-switch [data-choice]");
    const status = document.getElementById("platform-status");

    function renderPlatform(platform) {
      const changed = page.dataset.platform !== platform;
      page.dataset.platform = platform;
      for (const link of links) {
        if (link.dataset.choice === platform) link.setAttribute("aria-current", "true");
        else link.removeAttribute("aria-current");
      }
      if (changed) {
        status.textContent = `${platform === "mac" ? "Mac" : "Android"} 설치 안내를 표시합니다.`;
        window.dispatchEvent(new Event("solasi:platformchange"));
      }
    }

    for (const link of links) {
      link.addEventListener("click", (event) => {
        if (event.button !== 0 || event.metaKey || event.ctrlKey || event.shiftKey || event.altKey) return;
        event.preventDefault();
        if (page.dataset.platform === link.dataset.choice) return;
        const url = new URL(location.href);
        url.searchParams.set("platform", link.dataset.choice);
        history.pushState(null, "", url);
        renderPlatform(link.dataset.choice);
      });
    }
    window.addEventListener("popstate", () => renderPlatform(platformFromUrl()));
    renderPlatform(page.dataset.platform);
  });
})();
