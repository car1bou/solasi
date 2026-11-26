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
  const platform = document.documentElement.dataset.platform;
  const selectedCard = document.getElementById(platform)?.closest(".install-options article");
  const name = selectedCard?.querySelector("h3").textContent;
  const shortName = platform === "android" ? "Android" : name;
  let hero = document.querySelector(".hero-install");
  const help = document.querySelector(".hero-help");

  function showHero() {
    const download = selectedCard.querySelector(".device-download");
    const action = download.disabled ? "배포 안내" : "설치 안내";
    const actionLabel = shortName + " " + action;
    document.querySelector(".fold-nav a[href='#install']").textContent = actionLabel;
    const topLink = document.querySelector(".masthead .install-link");
    topLink.firstChild.textContent = action + " ";
    topLink.setAttribute("aria-label", actionLabel);
    document.querySelector(".footer .install-link").firstChild.textContent = actionLabel + " ";
    const fileLink = document.querySelector(".install-heading .field-link");
    fileLink.href = "#" + platform;
    fileLink.firstChild.textContent = shortName + (download.disabled ? " 배포 상태 " : " 설치 파일 ");
    help.hidden = false;
    help.href = "#" + platform;
    help.textContent = shortName + (download.disabled ? " 배포 안내" : " 설치 방법");
    if (download.disabled) {
      const pending = download.cloneNode(true);
      pending.removeAttribute("id");
      pending.className = "hero-install";
      hero.replaceWith(pending);
      hero = pending;
    } else {
      hero.href = download.href;
      hero.firstElementChild.textContent = channels[platform].label;
      hero.setAttribute("aria-describedby", download.getAttribute("aria-describedby"));
    }
  }

  if (selectedCard) {
    const linkedCard = document.getElementById(location.hash.slice(1))?.closest(".install-options article");
    selectedCard.parentElement.replaceChildren(selectedCard);
    if (linkedCard && linkedCard !== selectedCard) location.replace("#" + platform);
    document.querySelector("#install-heading span").textContent = name + "에서";
    const recordCopy = {
      android: "강의 자료와 필기는 이 태블릿에 저장됩니다.",
      ipad: "강의 자료와 필기는 이 iPad에 저장됩니다.",
      mac: "수업 기록은 이 Mac에 저장됩니다. 외부 AI를 선택하면 질문과 관련 자료가 해당 서비스로 전송됩니다.",
      windows: "수업 기록은 이 PC에 저장됩니다. 외부 AI를 선택하면 질문과 관련 자료가 해당 서비스로 전송됩니다."
    };
    document.querySelector(".install-heading p").textContent = recordCopy[platform];
    const pageLink = selectedCard.querySelector(".platform-heading a");
    pageLink.href = "?device=overview#devices";
    pageLink.removeAttribute("aria-label");
    pageLink.textContent = "다른 기기 설치 보기";
    showHero();
    help.addEventListener("click", () => {
      const guide = selectedCard.querySelector("details");
      if (guide && !selectedCard.querySelector(".device-download").disabled) guide.open = true;
    });
  }

  function markPending(channel) {
    const pending = document.createElement("button");
    pending.type = "button";
    pending.disabled = true;
    pending.className = channel.link.className;
    pending.id = channel.link.id;
    pending.textContent = channel.label + " 준비 중";
    channel.link.replaceWith(pending);
    channel.version.textContent = "";
    if (channel === channels[platform]) showHero();
  }

  async function refresh(channel) {
    try {
      const response = await fetch("https://api.github.com/repos/car1bou/solasi/releases/tags/" + channel.tag, {credentials: "omit"});
      if (response.status === 404) { markPending(channel); return; }
      if (!response.ok) return;
      const release = await response.json();
      if (release.tag_name !== channel.tag || !Array.isArray(release.assets)) return;
      if (release.draft) { markPending(channel); return; }
      let latest = 0;
      for (const asset of release.assets) {
        const match = channel.file.exec(asset?.name);
        if (!match || asset.state !== "uploaded" || !(asset.size > 0) || asset.browser_download_url !== releases + channel.tag + "/" + asset.name) continue;
        const code = Number(match[1]);
        if (code <= latest || code > 2100000000) continue;
        latest = code;
        channel.link.href = asset.browser_download_url;
      }
      if (!latest) { markPending(channel); return; }
      channel.version.textContent = channel.versionLabel(latest);
      if (channel === channels[platform]) hero.href = channel.link.href;
    } catch {
      // A failed network check preserves the published download embedded in the page.
    }
  }
  for (const channel of Object.values(channels)) {
    if (channel.link.isConnected) void refresh(channel);
  }
})();
