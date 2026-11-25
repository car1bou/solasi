(() => {
  const releases = "https://github.com/car1bou/solasi/releases/download/";
  const channels = {
    android: {
      tag: "android-updates", file: /^Solasi-Android-arm64-v([1-9][0-9]{0,9})\.apk$/,
      link: document.querySelector("#download-apk"), version: document.querySelector("#release-version"),
      label: "Android용 설치 파일", versionLabel: code => "v" + code + " 개발 프리뷰"
    },
    mac: {
      tag: "macos-updates", file: /^Solasi-macOS-arm64-([1-9][0-9]{0,9})\.zip$/,
      link: document.querySelector("#download-mac"), version: document.querySelector("#mac-release-version"),
      label: "Mac용 설치 파일", versionLabel: code => "빌드 " + code + " · 미리보기"
    }
  };
  const mac = document.documentElement.dataset.device === "mac";
  const android = /Android/i.test(navigator.userAgentData?.platform || navigator.userAgent);
  const platform = mac ? "mac" : android ? "android" : null;
  const hero = document.querySelector(".hero-install");
  if (platform) {
    const selected = channels[platform];
    hero.href = selected.link.href;
    hero.firstElementChild.textContent = selected.label;
    hero.setAttribute("aria-describedby", selected.link.getAttribute("aria-describedby"));
    const help = document.querySelector(".hero-help");
    help.href = "#" + platform;
    help.hidden = false;
    help.addEventListener("click", () => { document.querySelector(help.hash + " details").open = true; });
  }

  async function refresh(channel) {
    try {
      const response = await fetch("https://api.github.com/repos/car1bou/solasi/releases/tags/" + channel.tag, {credentials: "omit"});
      if (!response.ok) return;
      const release = await response.json();
      if (release.tag_name !== channel.tag || release.draft || !Array.isArray(release.assets)) return;
      let latest = Number(channel.version.dataset.code);
      for (const asset of release.assets) {
        const match = channel.file.exec(asset?.name);
        if (!match || asset.state !== "uploaded" || asset.browser_download_url !== releases + channel.tag + "/" + asset.name) continue;
        const code = Number(match[1]);
        if (code <= latest || code > 2100000000) continue;
        latest = code;
        channel.link.href = asset.browser_download_url;
        channel.version.textContent = channel.versionLabel(code);
        if (channel === channels[platform]) hero.href = channel.link.href;
      }
    } catch {
      // Both install links already point to a published build.
    }
  }
  for (const channel of Object.values(channels)) void refresh(channel);
})();
