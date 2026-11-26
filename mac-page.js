(() => {
  if (document.documentElement.dataset.device !== "mac") return;

  const image = name => "assets/mac-tour-" + name + ".webp";
  const step = (name, description, alt) => ({
    description, alt,
    image: image(name) + "?v=take2",
    video: "assets/mac-tour-" + name + ".mp4?v=take2"
  });
  const pdfAlt = "Mac에서 소프트웨어 공학 1장 PDF의 16쪽을 펼친 전체 화면";
  const noteAlt = "Mac에서 소프트웨어 공학 16쪽의 본문 옆에 메모를 남긴 화면";
  window.renderPlatformPage({
    name: "Mac",
    hero: {eyebrow: "Apple Silicon Mac · macOS 27 이상", image: image("pdf-detail"), width: 1280, height: 800, alt: pdfAlt},
    steps: [
      step("course", "과목을 열어 이번 수업에서 사용할 강의 자료를 찾습니다.", "Mac에서 소프트웨어 공학 과목을 여는 과정"),
      step("material", "강의 자료에서 PDF를 열고 수업에서 다룰 쪽을 펼칩니다.", pdfAlt),
      step("note", "자료 옆에 설명을 적고 해당 쪽의 메모로 저장합니다.", noteAlt)
    ],
    gallery: [
      {image: image("pdf-detail"), alt: pdfAlt, caption: "Mac · 강의 자료"},
      {image: image("note-detail"), alt: noteAlt, caption: "Mac · 쪽 메모"},
      {image: "assets/mac-transcript.png?v=se1", alt: "Mac에서 소프트웨어 공학 강의 대본을 읽는 화면", caption: "Mac · 강의 대본"}
    ],
    details: [
      {title: "강의 PDF 펼치기", description: "과목에서 강의 자료를 열어 원하는 쪽을 찾아봅니다."},
      {title: "쪽 메모 남기기", description: "PDF 옆에 수업 중 들은 설명을 적습니다. 저장한 메모는 그 쪽에서 다시 볼 수 있습니다."},
      {title: "강의 녹음 확인하기", description: "과목의 강의 기록에서 녹음과 대본을 함께 확인합니다."},
      {title: "대본에서 다시 듣기", description: "대본에서 문장을 고르고 ‘선택 구간 듣기’를 눌러 그때의 설명을 듣습니다."}
    ]
  });
})();
