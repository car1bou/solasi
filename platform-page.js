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
  for (const image of [one(".film-glass"), paper.querySelector("img")]) {
    image.width = hero.width;
    image.height = hero.height;
    setImage(image, hero.image, image.classList.contains("film-glass") ? "" : hero.alt);
  }
  paper.style.setProperty("--app-w", hero.width);
  paper.style.setProperty("--app-h", hero.height);
  ["x", "y", "w", "h"].forEach((key, index) => paper.style.setProperty("--pdf-" + key, hero.crop[index]));

  if (page.tourTitle) setTitle("#process-heading", page.tourTitle);
  one(".course-glass").src = steps[0].image;
  fill(".process-list > li", steps, (row, step) => {
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
