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
  detail.width = hero.width;
  detail.height = hero.height;
  setImage(detail, hero.image, hero.alt);
  paper.style.setProperty("--app-w", hero.width);
  paper.style.setProperty("--app-h", hero.height);
  ["x", "y", "w", "h"].forEach((key, index) => paper.style.setProperty("--pdf-" + key, hero.crop[index]));

  if (page.tourTitle) setTitle("#process-heading", page.tourTitle);
  fill(".process-list > li", steps, (row, step) => {
    row.removeAttribute("data-separate-demo");
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
  one("#image-viewer img").src = gallery[0].image;
};

// The Mac walkthrough starts inside a lecture recording. Keep the two native
// captures in their recorded order so the first frame belongs to this device.
if (document.documentElement.dataset.device === "mac") {
  const list = document.querySelector(".process-list");
  const recordings = [...list.querySelectorAll('a[href*="process-transcript.mp4"], a[href*="process-replay.mp4"]')]
    .map(link => link.closest("li"));
  list.replaceChildren(...recordings);
  const [opening, conclusion] = document.querySelectorAll("#process-heading > span");
  opening.textContent = "강의 대본에서";
  conclusion.textContent = "다시 듣기까지.";
  recordings.forEach((row, index) => {
    row.querySelector(".step-number").textContent = String(index + 1).padStart(2, "0");
    const poster = row.querySelector(".step-screen img");
    poster.loading = index === 0 ? "eager" : "lazy";
  });
}
