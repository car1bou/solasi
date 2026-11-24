const channel = "https://api.github.com/repos/car1bou/solasi/releases/tags/android-updates";
const downloads = "https://github.com/car1bou/solasi/releases/download/android-updates/";
const download = document.getElementById("download-apk");
const version = document.getElementById("release-version");

async function refreshRelease() {
  try {
    const response = await fetch(channel, { credentials: "omit" });
    if (!response.ok) return;
    const release = await response.json();
    if (release.tag_name !== "android-updates" || release.draft || !Array.isArray(release.assets)) return;

    let latest = Number(version.dataset.code);
    for (const asset of release.assets) {
      const match = /^Solasi-Android-arm64-v([1-9][0-9]{0,9})\.apk$/.exec(asset?.name);
      if (!match || asset.state !== "uploaded" || asset.browser_download_url !== downloads + asset.name) continue;
      const code = Number(match[1]);
      if (code <= latest || code > 2100000000) continue;
      latest = code;
      download.href = asset.browser_download_url;
      version.textContent = "v" + code + " 개발 프리뷰";
    }
  } catch {
    // The published APK link remains available when the release lookup fails.
  }
}

if (document.documentElement.dataset.platform === "android") void refreshRelease();
else window.addEventListener("solasi:platformchange", refreshRelease, { once: true });
