(() => {
  const choice = new URLSearchParams(location.search).get("platform");
  let platform = "android";

  if (choice === "mac" || choice === "android") {
    platform = choice;
  } else {
    const hint = navigator.userAgentData?.platform?.toLowerCase();
    const agent = navigator.userAgent;
    const appleMobile = /iPhone|iPad|iPod/i.test(agent) || navigator.maxTouchPoints > 1;
    if (hint !== "android" && !/Android/i.test(agent) && !appleMobile &&
        (hint === "macos" || /Macintosh/i.test(agent))) {
      platform = "mac";
    }
  }

  document.documentElement.dataset.platform = platform;
  document.addEventListener("DOMContentLoaded", () => {
    document.querySelector('[data-choice="' + platform + '"]')?.setAttribute("aria-current", "true");
  });
})();
