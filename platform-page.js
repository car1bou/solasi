// Apply the platform's product screens before the scroll camera and video player measure them.
window.renderPlatformPage = function (page) {
  const one = selector => document.querySelector(selector);
  const fill = (selector, items, render) => {
    document.querySelectorAll(selector).forEach((node, index) => render(node, items[index]));
  };
  const setTitle = (selector, lines) => fill(selector + " > span", lines, (span, line) => {
    span.textContent = line;
  });
  const setCopy = (node, item) => {
    node.querySelector("h3").textContent = item.title;
    node.querySelector("p").textContent = item.description;
  };
  const setImage = (image, src, alt) => {
    image.width = page.hero.width;
    image.height = page.hero.height;
    image.alt = alt || "";
    image.src = src;
  };

  const { name, hero, steps, result, gallery } = page;
  document.title = "Solasi | " + name;
  one(".film-copy > p").textContent = hero.eyebrow;
  setTitle("#heading", hero.title);
  one(".film-description").textContent = hero.description;
  const paper = one(".lecture-page");
  const detail = paper.querySelector("img");
  setImage(detail, hero.image, hero.alt);

  if (page.tourTitle) setTitle("#process-heading", page.tourTitle);
  fill(".process-list > li", steps, (row, step) => {
    row.dataset.recordedOn = document.documentElement.dataset.platform;
    setCopy(row, step);
    setImage(row.querySelector(".step-screen img"), step.image, step.alt);
    row.querySelector("figcaption > span").textContent = step.caption || page.demoCaption || name;
    const link = row.querySelector(".step-film a");
    link.href = step.video;
    link.setAttribute("aria-label", step.title + " 시연 영상 크게 보기");
  });

  fill(".solution-list > li", page.features, (row, feature) => {
    setCopy(row, feature);
    row.querySelector(".solution-code").textContent = feature.tag;
  });
  if (page.map) fill(".course-map > span", page.map, (span, label) => { span.textContent = label; });
  one(".result-story p").textContent = result.description;
  setImage(one(".result-example"), result.image, result.alt);
  fill(".result-list > li", result.items, setCopy);
  fill(".work-index > details", page.details, (detail, item) => {
    detail.querySelector("summary").textContent = item.title;
    detail.querySelector("p").textContent = item.description;
  });
  fill(".work-gallery > figure", gallery, (figure, item) => {
    setImage(figure.querySelector("img"), item.image, item.alt);
    figure.querySelector("figcaption > span").textContent = item.caption;
    figure.querySelector(".enlarge").href = item.image;
  });
  setImage(one("#image-viewer img"), gallery[0].image, gallery[0].alt);
};

// The default tour spans tablet and Mac. Device-specific tours stay on their own platform.
const tourPlatform = document.documentElement.dataset.platform;
if (tourPlatform === "mac" || tourPlatform === "android") {
  const list = document.querySelector(".process-list");
  const recordings = [...list.querySelectorAll(`[data-recorded-on="${tourPlatform}"]`)];
  const [opening, conclusion] = document.querySelectorAll("#process-heading > span");
  if (tourPlatform === "mac") {
    opening.textContent = "강의 기록에서";
    conclusion.textContent = "다시 듣기까지.";
    // The native recording continues from the open lecture directly into its transcript.
    const macOpening = [
      {
        title: "강의 기록 열기",
        description: "홈의 최근 기록에서 ‘소프트웨어 공학 개요’ 강의를 엽니다.",
        alt: "Mac용 Solasi 홈에 표시된 최근 강의 기록",
        asset: "mac-step-record",
      },
      {
        title: "대본 열기",
        description: "강의 기록에서 대본 탭을 눌러 녹음한 내용을 문장별로 확인합니다.",
        alt: "Mac용 Solasi의 ‘소프트웨어 공학 개요’ 강의 기록과 대본 탭",
        asset: "mac-step-transcript",
      },
    ];
    recordings.splice(1, 0, recordings[0].cloneNode(true));
    macOpening.forEach(({ title, description, alt, asset }, index) => {
      const row = recordings[index];
      row.querySelector("h3").textContent = title;
      row.querySelector("p").textContent = description;
      const image = row.querySelector(".step-screen img");
      image.alt = alt;
      image.src = `assets/${asset}.webp?v=se1`;
      const link = row.querySelector(".step-film a");
      link.href = `assets/${asset}.mp4?v=se1`;
      link.setAttribute("aria-label", title + " 시연 영상 크게 보기");
    });
  } else {
    opening.textContent = "과목 만들기부터";
    conclusion.textContent = "PDF 필기까지.";
    document.title = "Solasi | Android 태블릿";
    document.querySelector(".film-copy > p").textContent = "Android 태블릿";
    const [first, second] = document.querySelectorAll("#heading > span");
    first.textContent = "강의 자료에";
    second.textContent = "바로 필기하세요.";
    document.querySelector(".film-description").textContent = "과목을 만들고 강의 PDF를 펼치세요. 중요한 문장에 형광펜을 긋고 자료 옆에 필기를 남길 수 있습니다.";
  }
  list.replaceChildren(...recordings);
  recordings.forEach((row, index) => {
    row.querySelector(".step-number").textContent = String(index + 1).padStart(2, "0");
    row.querySelector(".step-screen img").loading = index === 0 ? "eager" : "lazy";
  });
}
