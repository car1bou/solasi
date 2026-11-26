(() => {
  const platform = document.documentElement.dataset.platform;
  const name = {android: "Android 태블릿", ipad: "iPad", mac: "Mac", windows: "Windows"}[platform];
  if (!name) return;

  const one = selector => document.querySelector(selector);
  function heading(selector, first, second) {
    const lines = one(selector).querySelectorAll("span");
    lines[0].textContent = first;
    lines[1].textContent = second;
  }
  function screen(figure, file, width, height, alt, caption) {
    const img = figure.querySelector("img");
    img.width = width;
    img.height = height;
    img.alt = alt;
    img.src = "assets/" + file;
    figure.querySelector(".enlarge").href = img.src;
    figure.querySelector("figcaption span").textContent = caption;
  }

  heading("#work-heading", name + " 화면을", "가까이에서.");
  one('.fold-nav a[href="#work"]').textContent = name + " 앱 화면";

  if (platform === "mac" || platform === "windows") {
    one(".solution-head .section-label").textContent = name + "의 복습 기능";
    if (platform === "windows") {
      one(".result-story .section-label").textContent = "소프트웨어 공학 · Windows 복습 예시";
      heading("#results-heading", "대본에서 고른 문장,", "원음으로 다시 듣기.");
      one(".result-story p:last-child").textContent = "소프트웨어의 정의를 복습하다가 개발 산출물에 대한 설명을 다시 듣고 싶다면, 강의 대본에서 그 문장을 고릅니다. ‘선택 구간 듣기’를 누르면 해당 구간의 녹음이 재생됩니다.";
      screen(one("#results figure"), "windows-replay.webp?v=se1", 1600, 900, "강의 대본에서 개발 산출물을 설명하는 문장을 선택하고 해당 구간을 재생하는 화면", "Windows 화면 예시 · 대본과 구간 재생");
    }
    return;
  }

  const android = platform === "android";
  const description = name + "에서 강의 PDF에 필기하고, 같은 쪽에 남긴 메모를 다시 읽으세요.";
  one(".film-description").textContent = description;
  one('meta[name="description"]').content = description;
  one(".footer-brand p").textContent = "강의 PDF에 필기하고 쪽마다 메모를 남기는 학습 앱.";
  heading("#process-heading", "수업 준비부터", "필기 복습까지.");
  const caption = name + " 화면 예시";
  const width = android ? 1280 : 1536;
  const height = android ? 800 : 1152;
  const chapters = [
    ["memo", "쪽 메모 쓰기",
      android ? "‘필기만’에서 돌아와 16쪽 메모에 ‘설계 문서와 테스트 결과도 소프트웨어 산출물이다.’라고 적습니다." : "16쪽 메모에 ‘테스트 결과도 산출물에 포함될까?’라는 질문을 적습니다."],
    ["review", "저장한 메모 다시 보기",
      android ? "자료 목록에서 강의 PDF를 다시 엽니다. 16쪽의 별표 옆에 저장한 메모가 남아 있습니다." : "메모를 접었다가 다시 펼쳐, 표시해 둔 정의와 그 옆에 남긴 질문을 함께 봅니다."]
  ];
  const rows = one(".process-list").children;
  chapters.forEach(([file, title, copy], i) => {
    const row = rows[i + 3];
    row.dataset.recordedOn = platform;
    row.querySelector("h3").textContent = title;
    row.querySelector(".step-copy p").textContent = copy;
    const poster = row.querySelector(".step-screen img");
    poster.width = width;
    poster.height = height;
    poster.alt = caption + " · " + title;
    poster.src = android ? "assets/android-step-" + file + ".webp" : "assets/ipad-start-" + file + ".webp";
    row.querySelector("figcaption span").textContent = caption;
    const link = row.querySelector(".step-film a");
    link.href = (android ? "assets/android-step-" : "assets/ipad-") + file + ".mp4";
    link.setAttribute("aria-label", title + " 시연 영상 크게 보기");
  });

  one('.fold-nav a[href="#solutions"]').textContent = "필기와 메모";
  one('.fold-nav a[href="#results"]').textContent = "필기 복습 예시";
  const problems = document.querySelectorAll(".problem-copy");
  problems[1].querySelector("h3").textContent = "질문은 그 쪽에 남겨 둡니다.";
  problems[1].querySelector("p").textContent = "수업 중 궁금한 점은 PDF 옆의 쪽 메모에 적습니다. 나중에 자료를 다시 펼치면 무엇을 보며 적었는지 바로 알 수 있습니다.";
  const diagram = one(".sound-sketch");
  diagram.className = "problem-visual file-sketch";
  diagram.querySelector(".sound-line").remove();
  ["16쪽", "소프트웨어의 정의", "쪽 메모"].forEach((item, i) => { diagram.children[i].textContent = item; });
  problems[2].querySelector("p").textContent = "소프트웨어 공학 과목을 열면 지난주에 보던 PDF와 필기를 다시 펼칠 수 있습니다. 다음 주 자료도 같은 과목에 모아 둡니다.";
  one('.problem-list a[href="#solutions"]').firstChild.textContent = "필기와 메모 보기 ";

  one(".solution-head .section-label").textContent = name + "의 필기와 메모";
  heading("#solutions-heading", "강의 PDF를", "내 노트로.");
  ["자료", "필기", "메모", "복습"].forEach((item, i) => { one(".course-map").querySelectorAll("span")[i].textContent = item; });
  const features = [
    ["과목에 강의 자료 모으기", "수업에 쓸 PDF를 과목에 추가합니다. 다음 시간에도 과목의 자료 목록에서 열 수 있습니다.", "과목"],
    ["필기할 쪽 넓게 펼치기", "원하는 쪽으로 이동해 ‘필기만’을 누르세요. 자료와 필기 도구가 남아 작은 글씨와 그림을 넓게 볼 수 있습니다.", "필기만"],
    ["자료 위에 표시하기", "중요한 정의에는 형광펜을 긋고, 그림 옆에는 펜으로 설명을 덧붙입니다.", "손글씨"],
    ["쪽에 질문 남기기", "메모 칸에 질문이나 수업 중 들은 예를 적습니다. 쪽을 다시 열면 원래 자료와 함께 읽을 수 있습니다.", "쪽 메모"],
    android
      ? ["메모에 쓴 낱말 찾기", "과목 검색에 기억나는 단어를 입력해 관련 페이지 메모를 찾습니다.", "단어 검색"]
      : ["저장한 필기 다시 보기", "과목에서 PDF를 다시 열고 표시했던 쪽을 펼칩니다. 밑줄과 메모를 함께 보며 지난 수업을 되짚습니다.", "복습"]
  ];
  document.querySelectorAll(".solution-list li").forEach((row, i) => {
    const [title, copy, tag] = features[i];
    row.querySelector("h3").textContent = title;
    row.querySelector("p").textContent = copy;
    row.querySelector(".solution-code").textContent = tag;
  });
  one(".result-story .section-label").textContent = "소프트웨어 공학 · " + name + " 복습 예시";
  heading("#results-heading", "16쪽을 다시 펴면,", "그때의 메모도 함께.");
  const memo = android ? "설계 문서와 테스트 결과도 소프트웨어 산출물이다." : "테스트 결과도 산출물에 포함될까?";
  one(".result-story p:last-child").textContent = "1장 16쪽에서 ‘소프트웨어의 정의’를 읽고 “" + memo + "”라고 적었습니다. 같은 쪽을 다시 펼쳐 원문과 메모를 나란히 읽어 보세요.";
  const memoAlt = name + " 화면에 소프트웨어 공학 16쪽과 ‘" + memo + "’라는 메모가 나란히 보이는 모습";
  const memoCaption = caption + " · 16쪽 메모";
  const savedFile = android ? "android-memo-saved.webp" : "ipad-review.webp?v=se1";
  screen(one("#results figure"), savedFile, width, height, memoAlt, memoCaption);

  if (android) {
    const starAlt = "Android 필기만 모드에서 ‘소프트웨어의 정의’ 옆에 그린 빨간 별표";
    const preview = one(".lecture-page img");
    preview.width = width;
    preview.height = height;
    preview.alt = starAlt;
    preview.src = "assets/android-step-memo.webp";
    const gallery = document.querySelectorAll(".work-gallery figure");
    screen(gallery[0], "process-ink.webp?v=take2", 1280, 800, "Android에서 강의 PDF 16쪽과 필기 도구를 연 화면", "Android 태블릿 · 강의 PDF");
    screen(gallery[1], "android-step-memo.webp", width, height, starAlt, caption + " · 빨간 펜으로 표시한 16쪽");
    const details = document.querySelectorAll(".work-index details");
    details[0].querySelector("p").textContent = "소프트웨어 공학 과목에서 강의 PDF를 열고 16쪽 ‘소프트웨어의 정의’로 이동합니다.";
    details[1].querySelector("summary").textContent = "빨간 펜으로 별표 그리기";
    details[1].querySelector("p").textContent = "‘필기만’으로 PDF를 넓게 펼치고 빨간 펜으로 정의 옆에 별표를 그립니다.";
    details[2].querySelector("summary").textContent = "쪽 메모 남기기";
    details[2].querySelector("p").textContent = "‘메모’를 눌러 그 쪽에 수업 중 들은 설명을 적습니다. 여기서는 설계 문서와 테스트 결과를 예로 적었습니다.";
    details[3].querySelector("summary").textContent = "저장한 메모 다시 읽기";
    details[3].querySelector("p").textContent = "다시 같은 쪽으로 돌아와 메모를 열면 그날 적어 둔 설명을 PDF와 함께 읽을 수 있습니다.";
  }

  // The last two accordion entries share a figure in the desktop and narrow layouts.
  const savedMemo = one(".work-index details:last-child");
  function showMemo() {
    const saved = savedMemo.open;
    const file = saved ? savedFile : android ? "android-step-review.webp" : "ipad-memo.webp?v=se1";
    screen(one(".work-gallery figure:last-child"), file, width, height,
      memoAlt, caption + (saved ? " · 저장한 메모 다시 보기" : " · 16쪽 메모"));
  }
  savedMemo.addEventListener("toggle", showMemo);
  showMemo();
})();
