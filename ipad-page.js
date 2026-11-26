(() => {
  if (document.documentElement.dataset.device !== "ipad") return;

  const screens = {
    course: {title: "과목 만들기", description: "홈에서 과목 옆의 +를 누르고 ‘소프트웨어 공학’을 입력해 새 과목을 만듭니다.", alt: "홈 화면에서 소프트웨어 공학 과목을 추가하는 과정"},
    pdf: {title: "강의 PDF 펼치기", description: "손글씨 노트로 연결을 켠 뒤 ‘자료 연결’로 1장 강의 PDF를 연결해 16쪽을 펼칩니다.", alt: "소프트웨어공학 개요 PDF 16쪽 ‘소프트웨어의 정의’를 펼친 화면"},
    ink: {title: "형광펜으로 표시하기", description: "형광펜을 골라 소프트웨어의 정의를 설명한 구절에 표시합니다.", alt: "강의 PDF의 소프트웨어 정의에 형광펜을 긋는 화면"},
    memo: {title: "쪽 메모 남기기", description: "같은 쪽의 메모에 ‘테스트 결과도 산출물에 포함될까?’라고 적습니다.", alt: "16쪽 메모에 테스트 결과에 관한 질문을 적는 화면"},
    review: {title: "저장한 메모 다시 보기", description: "16쪽에서 메모를 접었다가 다시 펼쳐 저장된 질문과 표시한 문장을 함께 봅니다.", alt: "소프트웨어 정의에 표시한 구절 옆에 저장된 쪽 메모를 다시 펼친 화면"}
  };
  const steps = Object.entries(screens).map(([id, step]) => ({
    ...step, image: "assets/ipad-start-" + id + ".webp?v=se1", detail: "assets/ipad-" + id + ".webp?v=se1",
    video: "assets/ipad-" + id + ".mp4?v=se1"
  }));
  window.renderPlatformPage({
    name: "iPad", demoCaption: "iPad 화면 예시",
    hero: {eyebrow: "iPad · iPadOS", title: ["강의 자료 위에", "생각을 쓰다."],
      description: "iPad에서 강의 PDF를 펼치고, Apple Pencil로 표시한 쪽에 질문을 남겨 보세요.",
      image: steps[2].detail, width: 1536, height: 1152, alt: steps[2].alt},
    tourTitle: ["수업 자료부터", "나의 필기까지."],
    steps,
    map: ["자료", "필기", "메모", "페이지"],
    features: [
      {title: "과목별 자료 정리", description: "수업마다 과목을 만들고, 그 과목의 자료 목록에서 강의 PDF를 엽니다.", tag: "과목"},
      {title: "쪽을 넘겨 읽기", description: "페이지 번호나 앞뒤 화살표로 오늘 수업에 쓸 쪽을 펼칩니다.", tag: "PDF"},
      {title: "Apple Pencil로 표시하기", description: "형광펜으로 중요한 구절을 짚고, 펜으로 강의 자료에 짧은 설명을 덧붙입니다.", tag: "필기"},
      {title: "쪽마다 질문 남기기", description: "이해가 덜 된 부분을 해당 페이지의 메모에 적어 둡니다.", tag: "메모"},
      {title: "자료와 필기 다시 보기", description: "과목의 PDF로 돌아와 수업 중 표시한 부분을 원래 페이지에서 확인합니다.", tag: "복습"}
    ],
    result: {description: "프로그램과 소프트웨어의 차이가 헷갈리면 1장 16쪽을 다시 펼쳐 보세요. 표시해 둔 정의와 테스트 결과에 관해 적어 둔 질문을 함께 읽을 수 있습니다.",
      image: steps[2].detail, alt: steps[2].alt, items: [
        {title: "표시해 둔 구절", description: "수업에서 읽은 소프트웨어의 정의를 형광펜 표시로 다시 찾습니다."},
        {title: "쪽마다 남긴 질문", description: "테스트 결과도 산출물에 포함되는지 적어 둔 질문을 확인합니다."},
        {title: "강의에서 본 예시", description: "설계 문서와 사용자 매뉴얼 등 강의에 나온 산출물의 예를 찾아봅니다."},
        {title: "이어지는 수업 자료", description: "다음 수업에도 같은 과목을 열어 앞에서 읽은 자료와 필기를 이어 봅니다."}
      ]},
    gallery: [
      {image: steps[1].detail, alt: steps[1].alt, caption: "iPad 화면 예시 · 강의 자료"},
      {image: steps[2].detail, alt: steps[2].alt, caption: "iPad 화면 예시 · PDF 필기"},
      {image: steps[3].detail, alt: steps[3].alt, caption: "iPad 화면 예시 · 쪽 메모"}
    ],
    details: [
      {title: "PDF 펼쳐 보기", description: "과목을 열고 ‘Ch1_소프트웨어공학_개요.pdf’를 선택하면 쪽을 넘기며 수업 자료를 읽을 수 있습니다."},
      {title: "중요한 문장 표시하기", description: "형광펜을 골라 소프트웨어의 정의에 표시합니다. 쪽을 다시 열어도 그 자리에 남습니다."},
      {title: "쪽 메모에 질문 쓰기", description: "메모를 펼쳐 수업 중 떠오른 질문을 적습니다. 작성한 내용은 그 페이지에 저장됩니다."},
      {title: "저장한 메모 확인하기", description: "자료의 같은 쪽으로 돌아와 정의와 사례를 보면서 적어 둔 질문을 읽습니다."}
    ]
  });
  const problems = document.querySelectorAll(".problem-copy");
  problems[1].querySelector("h3").textContent = "수업 자료를 보고 떠올린 질문은 어디에 적었을까요?";
  problems[1].querySelector("p").textContent = "수업 중에는 이해한 내용도 나중에는 원래 자료와 함께 봐야 맥락이 떠오릅니다.";
  const note = document.querySelector(".sound-sketch");
  note.className = "problem-visual file-sketch";
  note.replaceChildren(...["강의 PDF", "16쪽 정의", "쪽 메모"].map(label => {
    const item = document.createElement("span"); item.textContent = label; return item;
  }));
  problems[2].querySelector("p").textContent = "다음 주에 이어 볼 자료와 그때 남긴 필기를 다시 찾는 데 시간이 걸립니다.";
})();
