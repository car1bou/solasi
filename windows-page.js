(() => {
  if (document.documentElement.dataset.device !== "windows") return;

  // These captures use the desktop UI shared by the Windows app and a public sample course.
  const image = (name, version = "se1") => "assets/windows-" + name + ".webp?v=" + version;
  const step = (name, description, alt) => ({
    description, alt,
    image: image("step-" + name, "take2"),
    video: "assets/windows-step-" + name + ".mp4?v=take2"
  });
  window.renderPlatformPage({
    name: "Windows", demoCaption: "Windows 화면 예시",
    hero: {
      eyebrow: "Windows PC · Windows 11 x64",
      image: image("pdf"), width: 1600, height: 900,
      alt: "Windows용 Solasi 화면 예시. 소프트웨어공학 개요 PDF의 16쪽과 쪽 메모를 나란히 펼친 모습"
    },
    steps: [
      step("course", "과목을 열면 그 수업의 자료와 회차별 강의 기록을 볼 수 있습니다.", "최근 기록에서 소프트웨어 공학 과목으로 이동하는 화면"),
      step("pdf", "‘자료·필기’에서 연결한 강의 PDF를 열고 수업에서 다룰 쪽으로 이동합니다.", "자료 목록에서 강의 PDF를 열어 16쪽으로 이동하는 화면"),
      step("memo", "수업에서 들은 설명을 자료 옆에 적습니다. 저장한 메모는 그 페이지에 남습니다.", "소프트웨어 정의 옆에 개발 산출물의 예를 메모하는 화면"),
      step("record", "홈의 최근 기록에서 지난 강의를 열고, 대본 탭에서 그날의 설명을 찾습니다.", "메모를 저장한 뒤 홈으로 돌아가 강의 기록의 대본을 여는 화면"),
      step("replay", "대본에서 문장을 고르면 그 구간의 녹음을 다시 들을 수 있습니다.", "선택한 대본 문장의 원음이 재생되는 화면")
    ],
    gallery: [
      {image: image("pdf"), caption: "Windows 화면 예시 · 강의 PDF", alt: "소프트웨어 공학 강의 PDF와 페이지 메모 패널을 표시한 Solasi 데스크톱 화면"},
      {image: image("memo"), caption: "Windows 화면 예시 · 페이지 메모", alt: "16쪽 ‘소프트웨어의 정의’ 옆에 쪽 메모를 저장한 화면"},
      {image: image("replay"), caption: "Windows 화면 예시 · 강의 대본", alt: "대본에서 문장을 고르고 원음 재생기를 펼친 강의 기록 화면"}
    ],
    details: [
      {title: "강의 PDF 펼치기", description: "‘자료·필기’에서 PDF를 열면 현재 쪽과 메모 칸을 나란히 볼 수 있습니다."},
      {title: "쪽에 메모 남기기", description: "그림이나 문장을 보면서 메모를 입력합니다. 다음에 같은 쪽을 열어 이어 쓸 수 있습니다."},
      {title: "강의 녹음 확인하기", description: "과목 안에서 회차를 고르면 그날의 녹음과 대본을 함께 볼 수 있습니다."},
      {title: "대본에서 다시 듣기", description: "대본의 문장을 선택하고 ‘선택 구간 듣기’를 눌러 들린 내용과 대조합니다."}
    ]
  });
})();
