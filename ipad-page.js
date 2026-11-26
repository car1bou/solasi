(() => {
  if (document.documentElement.dataset.device !== "ipad") return;

  const screens = {
    course: {title: "과목 만들기", description: "이번 학기에 들을 과목을 만들고 그 안에 강의 자료를 모읍니다.", alt: "홈 화면에서 소프트웨어 공학 과목을 추가하는 과정"},
    pdf: {title: "강의 PDF 펼치기", description: "강의 PDF를 손글씨 노트로 연결하고 수업에서 다룰 쪽을 펼칩니다.", alt: "소프트웨어공학 개요 PDF 16쪽 ‘소프트웨어의 정의’를 펼친 화면"},
    ink: {title: "형광펜으로 표시하기", description: "형광펜으로 중요한 구절에 표시합니다. 펜으로는 원래 자료 위에 필기할 수 있습니다.", alt: "강의 PDF의 소프트웨어 정의에 형광펜을 긋는 화면"},
    memo: {title: "쪽 메모 남기기", description: "자료를 읽다 생긴 질문을 쪽 메모에 입력합니다.", alt: "16쪽 메모에 테스트 결과에 관한 질문을 적는 화면"},
    review: {title: "저장한 메모 다시 보기", description: "메모를 다시 펼치면 적어 둔 질문을 원래 문장과 함께 읽을 수 있습니다.", alt: "소프트웨어 정의에 표시한 구절 옆에 저장된 쪽 메모를 다시 펼친 화면"}
  };
  const steps = Object.entries(screens).map(([id, step]) => ({
    ...step, image: "assets/ipad-start-" + id + ".webp?v=se1", detail: "assets/ipad-" + id + ".webp?v=se1",
    video: "assets/ipad-" + id + ".mp4?v=se1"
  }));
  window.renderPlatformPage({
    name: "iPad", demoCaption: "iPad 화면 예시",
    hero: {eyebrow: "iPad · iPadOS",
      image: steps[2].detail, width: 1536, height: 1152, alt: steps[2].alt},
    tourTitle: ["강의 PDF부터", "필기와 쪽 메모까지."],
    steps,
    gallery: [
      {image: steps[1].detail, alt: steps[1].alt, caption: "iPad 화면 예시 · 강의 자료"},
      {image: steps[2].detail, alt: steps[2].alt, caption: "iPad 화면 예시 · PDF 필기"},
      {image: steps[3].detail, alt: steps[3].alt, caption: "iPad 화면 예시 · 쪽 메모"}
    ],
    details: [
      {title: "PDF 펼쳐 보기", description: "과목에서 강의 PDF를 선택하고 페이지 번호로 필요한 쪽을 펼칩니다."},
      {title: "중요한 문장 표시하기", description: "형광펜으로 표시한 문장은 페이지를 다시 열어도 같은 자리에 남습니다."},
      {title: "쪽 메모에 질문 쓰기", description: "페이지 옆에 질문을 적어 두면 나중에 어떤 대목에서 막혔는지 알 수 있습니다."},
      {title: "저장한 메모 확인하기", description: "해당 쪽의 메모를 펼치고 원문을 읽으며 앞서 적은 내용을 보충합니다."}
    ]
  });
})();
