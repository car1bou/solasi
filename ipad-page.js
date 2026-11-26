(() => {
  if (document.documentElement.dataset.device !== "ipad") return;

  const image = (name, version = "se1") => "assets/ipad-" + name + ".webp?v=" + version;
  const step = (name, description, alt) => ({
    description, alt,
    image: image("start-" + name, "take2"),
    video: "assets/ipad-" + name + ".mp4?v=take2"
  });
  const pdfAlt = "소프트웨어공학 개요 PDF 16쪽 ‘소프트웨어의 정의’를 펼친 iPad 화면";
  const inkAlt = "iPad에서 소프트웨어 정의에 형광펜으로 표시한 화면";
  window.renderPlatformPage({
    name: "iPad", demoCaption: "iPad 화면 예시",
    hero: {eyebrow: "iPad · iPadOS", image: image("ink"), width: 1536, height: 1152, alt: inkAlt},
    steps: [
      step("course", "이번 학기에 들을 과목을 만들고 그 안에 강의 자료를 모읍니다.", "홈 화면에서 소프트웨어 공학 과목을 추가하는 과정"),
      step("pdf", "강의 PDF를 손글씨 노트로 연결하고 수업에서 다룰 쪽을 펼칩니다.", pdfAlt),
      step("ink", "중요한 구절에 형광펜을 긋습니다. 펜으로는 원래 자료 위에 필기할 수 있습니다.", inkAlt)
    ],
    gallery: [
      {image: image("pdf"), alt: pdfAlt, caption: "iPad 화면 예시 · 강의 자료"},
      {image: image("ink"), alt: inkAlt, caption: "iPad 화면 예시 · PDF 필기"},
      {image: image("memo"), alt: "16쪽 메모에 테스트 결과에 관한 질문을 적는 화면", caption: "iPad 화면 예시 · 쪽 메모"}
    ],
    details: [
      {title: "PDF 펼쳐 보기", description: "과목에서 강의 PDF를 선택하고 페이지 번호로 필요한 쪽을 펼칩니다."},
      {title: "중요한 문장 표시하기", description: "형광펜으로 표시한 문장은 페이지를 다시 열어도 같은 자리에 남습니다."},
      {title: "쪽 메모에 질문 쓰기", description: "페이지 옆에 질문을 적어 두면 나중에 어떤 대목에서 막혔는지 알 수 있습니다."},
      {title: "저장한 메모 확인하기", description: "해당 쪽의 메모를 펼치고 원문을 읽으며 앞서 적은 내용을 보충합니다."}
    ]
  });
})();
