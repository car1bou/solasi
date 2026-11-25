(() => {
  if (document.documentElement.dataset.device !== "ipad") return;

  const screens = {
    course: {title: "과목 만들기", description: "‘과목 추가’를 눌러 이번 학기에 들을 인지심리학 과목을 만듭니다.", alt: "빈 과목 이름 칸에서 시작하는 인지심리학 과목 만들기"},
    pdf: {title: "강의 PDF 펼치기", description: "과목의 자료 목록에서 ‘기억과 학습.pdf’를 열고 계열 위치 효과를 설명하는 쪽으로 넘깁니다.", alt: "인지심리학 자료에서 계열 위치 효과 그래프가 있는 2쪽을 펼친 화면"},
    ink: {title: "형광펜으로 표시하기", description: "형광펜을 골라 회상 실험의 조건을 설명한 구절에 표시합니다.", alt: "강의 PDF 본문에 형광펜으로 표시한 구절과 회상률 그래프"},
    memo: {title: "쪽 메모 남기기", description: "같은 쪽의 메모에 ‘가운데 단어를 덜 떠올리는 이유는?’이라고 적습니다.", alt: "2쪽 메모에 가운데 단어의 회상률을 묻는 질문을 적은 화면"},
    review: {title: "표시한 쪽 다시 보기", description: "앞쪽을 살펴본 뒤 2쪽으로 돌아와 그래프와 표시한 구절을 함께 확인합니다.", alt: "쪽을 넘겼다가 계열 위치 효과 그래프와 형광펜 표시가 있는 쪽으로 돌아온 화면"}
  };
  const steps = Object.entries(screens).map(([id, step]) => ({
    ...step, image: "assets/ipad-" + id + ".webp", video: "assets/ipad-" + id + ".mp4"
  }));
  window.renderPlatformPage({
    name: "iPad", demoCaption: "iPad 화면 예시",
    hero: {eyebrow: "iPad · iPadOS", title: ["강의 자료 위에", "생각을 쓰다."],
      description: "iPad에서 강의 PDF를 펼치고, Apple Pencil로 표시한 쪽에 질문을 남겨 보세요.",
      image: steps[2].image, width: 1536, height: 1152, crop: [353, 385, 1124, 746], alt: steps[2].alt},
    tourTitle: ["수업 자료부터", "나의 필기까지."],
    steps,
    map: ["자료", "필기", "메모", "페이지"],
    features: [
      {title: "과목별 자료 정리", description: "수업마다 과목을 만들고, 그 과목의 자료 목록에서 강의 PDF를 엽니다.", tag: "과목"},
      {title: "쪽을 넘겨 읽기", description: "페이지 번호나 앞뒤 화살표로 오늘 수업에 쓸 쪽을 펼칩니다.", tag: "PDF"},
      {title: "Apple Pencil로 표시하기", description: "형광펜으로 중요한 구절을 짚고, 펜으로 그래프 옆에 짧은 설명을 덧붙입니다.", tag: "필기"},
      {title: "쪽마다 질문 남기기", description: "이해가 덜 된 부분을 해당 페이지의 메모에 적어 둡니다.", tag: "메모"},
      {title: "자료와 필기 다시 보기", description: "과목의 PDF로 돌아와 수업 중 표시한 부분을 원래 페이지에서 확인합니다.", tag: "복습"}
    ],
    result: {description: "‘계열 위치 효과’가 헷갈리면 인지심리학 자료의 2쪽을 다시 펼쳐 보세요. 형광펜으로 짚어 둔 문장을 읽고, 그날 남긴 질문을 회상률 그래프와 대조할 수 있습니다.",
      image: steps[2].image, alt: steps[2].alt, items: [
        {title: "표시해 둔 구절", description: "수업에서 강조한 실험 조건을 PDF의 형광펜 표시로 다시 찾습니다."},
        {title: "쪽마다 남긴 질문", description: "가운데 단어가 왜 잘 떠오르지 않았는지 적어 둔 메모를 같은 쪽에서 확인합니다."},
        {title: "강의 중 본 그래프", description: "목록의 위치에 따라 달라지는 회상률을 원래 수업 도표에서 살펴봅니다."},
        {title: "이어지는 수업 자료", description: "다음 수업에도 같은 과목을 열어 앞에서 읽은 자료와 필기를 이어 봅니다."}
      ]},
    gallery: [
      {image: steps[1].image, alt: steps[1].alt, caption: "iPad 화면 예시 · 강의 자료"},
      {image: steps[2].image, alt: steps[2].alt, caption: "iPad 화면 예시 · PDF 필기"},
      {image: steps[3].image, alt: steps[3].alt, caption: "iPad 화면 예시 · 쪽 메모"}
    ],
    details: [
      {title: "PDF 펼쳐 보기", description: "과목을 열고 ‘기억과 학습.pdf’를 선택하면 쪽을 넘기며 수업 자료를 읽을 수 있습니다."},
      {title: "중요한 문장 표시하기", description: "형광펜을 골라 실험 조건을 표시합니다. 쪽을 다시 열어도 그 자리에 남습니다."},
      {title: "쪽 메모에 질문 쓰기", description: "메모를 펼쳐 수업 중 떠오른 질문을 적습니다. 작성한 내용은 그 페이지에 저장됩니다."},
      {title: "저장한 메모 확인하기", description: "자료의 같은 쪽으로 돌아와 그래프를 보면서 적어 둔 질문을 읽습니다."}
    ]
  });
  const problems = document.querySelectorAll(".problem-copy");
  problems[1].querySelector("h3").textContent = "그래프를 보고 떠올린 질문은 어디에 적었을까요?";
  problems[1].querySelector("p").textContent = "수업 중에는 이해한 내용도 나중에는 원래 자료와 함께 봐야 맥락이 떠오릅니다.";
  const note = document.querySelector(".sound-sketch");
  note.className = "problem-visual file-sketch";
  note.replaceChildren(...["강의 PDF", "2쪽 그래프", "쪽 메모"].map(label => {
    const item = document.createElement("span"); item.textContent = label; return item;
  }));
  problems[2].querySelector("p").textContent = "다음 주에 이어 볼 자료와 그때 남긴 필기를 다시 찾는 데 시간이 걸립니다.";
})();
