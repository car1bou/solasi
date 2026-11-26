// Apply the platform's product screens before the scroll camera and video player measure them.
window.renderPlatformPage = function (page) {
  const one = selector => document.querySelector(selector);
  const fill = (selector, items, render) => {
    const slots = document.querySelectorAll(selector);
    items.forEach((item, index) => render(slots[index], item));
  };
  const setImage = (image, src, alt) => {
    image.width = page.hero.width;
    image.height = page.hero.height;
    image.alt = alt || "";
    image.src = src;
  };

  const { name, hero, steps, gallery } = page;
  document.title = "Solasi | " + name;
  one(".film-copy > p").textContent = hero.eyebrow;
  const paper = one(".lecture-page");
  const detail = paper.querySelector("img");
  setImage(detail, hero.image, hero.alt);

  // The five chapters live in the HTML. Replace only recordings supplied by this platform.
  fill(".process-list > li", steps, (row, step) => {
    row.dataset.recordedOn = document.documentElement.dataset.platform;
    row.querySelector(".step-copy p").textContent = step.description;
    setImage(row.querySelector(".step-screen img"), step.image, step.alt);
    row.querySelector("figcaption > span").textContent = step.caption || page.demoCaption || name;
    const link = row.querySelector(".step-film a");
    link.href = step.video;
  });

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

if (document.documentElement.dataset.platform === "android") {
  const ink = document.querySelector('.process-list [data-step="ink"]');
  ink.querySelector(".step-film a").href = "assets/android-step-star.mp4";
  ink.querySelector(".step-copy p").textContent = "‘필기만’으로 자료를 넓게 펼치고, 빨간 펜으로 ‘소프트웨어의 정의’ 옆에 별표를 그립니다.";
  document.title = "Solasi | Android 태블릿";
  document.querySelector(".film-copy > p").textContent = "Android 태블릿";
}
