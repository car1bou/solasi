(() => {
  if (document.documentElement.dataset.device !== "windows") return;

  // These captures use the desktop UI shared by the Windows app and a public sample course.
  const image = name => "assets/windows-" + name + ".webp?v=se1";
  const step = (name, title, description, alt) => ({
    title, description, alt,
    image: image("step-" + name),
    video: "assets/windows-step-" + name + ".mp4?v=se1"
  });
  window.renderPlatformPage({
    name: "Windows", demoCaption: "Windows 화면 예시",
    hero: {
      eyebrow: "Windows PC · Windows 11 x64",
      title: ["강의 자료 옆에", "나의 기록을."],
      description: "PC에서 강의 PDF를 펼치고 쪽마다 메모하세요. 복습할 때는 대본에서 필요한 설명을 골라 다시 듣습니다.",
      image: image("pdf"), width: 1600, height: 900,
      alt: "Windows용 Solasi 화면 예시. 소프트웨어공학 개요 PDF의 16쪽과 쪽 메모를 나란히 펼친 모습"
    },
    steps: [
      step("course", "과목 열기", "왼쪽 과목 목록에서 소프트웨어 공학을 선택해 이번 수업의 작업 공간을 엽니다.", "최근 기록에서 소프트웨어 공학 과목으로 이동하는 화면"),
      step("pdf", "강의 PDF 펼치기", "‘자료·필기’에서 1장 PDF를 열고 16쪽 ‘소프트웨어의 정의’를 펼칩니다.", "자료 목록에서 강의 PDF를 열어 16쪽으로 이동하는 화면"),
      step("memo", "쪽에 메모 남기기", "16쪽의 메모 칸에 설계 문서와 테스트 결과도 산출물에 포함된다고 적습니다.", "소프트웨어 정의 옆에 개발 산출물의 예를 메모하는 화면"),
      step("record", "강의 기록 찾기", "홈으로 돌아가 최근 기록에서 ‘소프트웨어 공학 개요’를 열고 대본 탭을 선택합니다.", "메모를 저장한 뒤 홈으로 돌아가 강의 기록의 대본을 여는 화면"),
      step("replay", "한 구간 다시 듣기", "대본의 한 문장을 고르고 ‘선택 구간 듣기’로 그 부분의 원음을 확인합니다.", "선택한 대본 문장의 원음이 재생되는 화면")
    ],
    features: [
      {title: "강의 자료 연결하기", description: "PC에 있는 강의 PDF를 과목에 연결합니다. 다음 수업에도 같은 과목에서 자료를 열 수 있습니다.", tag: "자료"},
      {title: "쪽마다 메모하기", description: "PDF의 그림이나 문장을 보면서 옆에 메모를 입력합니다. 메모는 해당 페이지에 저장됩니다.", tag: "메모"},
      {title: "강의 기록 모으기", description: "한 과목 안에서 회차별 강의와 녹음을 찾습니다. 수업 제목을 골라 그날의 기록을 확인하세요.", tag: "기록"},
      {title: "문장에서 원음 듣기", description: "강의 대본에서 문장을 선택해 해당 음성 구간을 재생하고 수업 표현을 확인합니다.", tag: "대본"},
      {title: "대본 내보내기", description: "복습에 사용할 강의 대본을 텍스트 또는 Markdown 파일로 저장합니다.", tag: "파일"}
    ],
    result: {
      description: "프로그램과 소프트웨어의 차이를 복습할 때는 1장 16쪽을 펼치세요. 수업 중 남긴 메모와 그날의 대본을 확인한 뒤, 다시 듣고 싶은 문장을 고를 수 있습니다.",
      image: image("memo"), alt: "소프트웨어 정의 옆에 설계 문서와 테스트 결과를 적은 쪽 메모",
      items: [
        {title: "다시 보는 정의", description: "1장 16쪽에서 프로그램과 소프트웨어의 정의를 다시 확인합니다."},
        {title: "쪽마다 남긴 메모", description: "설계 문서와 테스트 결과도 소프트웨어에 포함된다고 적은 메모를 다시 읽습니다."},
        {title: "그날의 설명", description: "강의 대본에서 한 문장을 고른 뒤, 해당 구간을 들으며 설명을 확인합니다."},
        {title: "회차별 강의 기록", description: "같은 과목에 모인 기록에서 원하는 회차를 찾아 지난 수업과 이어서 공부합니다."}
      ]
    },
    gallery: [
      {image: image("pdf"), caption: "Windows 화면 예시 · 강의 PDF", alt: "소프트웨어 공학 강의 PDF와 페이지 메모 패널을 표시한 Solasi 데스크톱 화면"},
      {image: image("memo"), caption: "Windows 화면 예시 · 페이지 메모", alt: "16쪽 ‘소프트웨어의 정의’ 옆에 쪽 메모를 저장한 화면"},
      {image: image("replay"), caption: "Windows 화면 예시 · 강의 대본", alt: "대본에서 문장을 고르고 원음 재생기를 펼친 강의 기록 화면"}
    ],
    details: [
      {title: "강의 PDF 펼치기", description: "소프트웨어 공학 과목에서 ‘소프트웨어 공학 개요’ PDF를 열면 자료 옆에 페이지 메모가 표시됩니다."},
      {title: "쪽에 메모 남기기", description: "강의 자료에서 확인한 개발 산출물의 예를 키보드로 입력해 저장합니다."},
      {title: "강의 녹음 확인하기", description: "강의 기록의 대본에서 문장을 고르면 선택 구간 듣기로 해당 녹음을 확인할 수 있습니다."},
      {title: "대본에서 다시 듣기", description: "‘선택 구간 듣기’를 누르면 고른 문장의 원음이 재생됩니다."}
    ],
    map: ["자료", "메모", "녹음", "대본"]
  });
})();
