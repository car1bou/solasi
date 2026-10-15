# Samsung Notes 필기 경험과 웹 입력 제약 조사

확인일: 2026-10-15 (Asia/Seoul)

범위: Samsung 공식 지원 문서, W3C Pointer Events Level 3, WebKit·Apple·Wacom·Mozilla 공식 문서 조회. 이 문서는 공개된 조작 방식과 입력 API의 조사 기록이다. Samsung Notes 바이너리·APK를 확보하거나 REA로 분석하지 않았으며, 내부 자료구조·저장 포맷·필압 곡선·보정 알고리즘을 확인한 결과가 아니다. 펜 장치·태블릿·브라우저에서의 실제 필기는 검증하지 않았다.

## 확인한 조작 방식

| 동작 | 공식 문서에서 확인한 내용 | 근거와 한계 |
|---|---|---|
| 펜·형광펜 | 펜 종류·크기·색, 형광펜 종류·크기·불투명도·색을 선택한다. | [Samsung PC 지원](https://www.samsung.com/us/support/answer/ANS10001469/). Galaxy Book용 설명으로 Android와 메뉴가 완전히 같다는 근거는 아니다. |
| 획·영역 지우개 | 획 지우개는 선택한 선 전체, 영역 지우개는 지나간 부분을 지운다. 영역 크기와 형광펜만 지우는 옵션도 있다. S Pen 버튼을 누르는 동안 지우고 놓으면 이전 도구로 돌아간다. | [Samsung 손글씨 지원](https://www.samsung.com/us/support/answer/ANS10003634/). 실제 지우개 충돌 판정·획 분할 방식은 공개되지 않았다. |
| 선택·이동·크기 | 올가미 또는 사각 선택, 일부 걸친 객체 포함 옵션, 드래그 이동, 모서리 크기 조절을 제공한다. | [Samsung 손글씨 지원](https://www.samsung.com/us/support/answer/ANS10003634/). 선택 판정의 내부 기하 알고리즘을 뜻하지 않는다. |
| 실행 취소·다시 실행 | 최근 필기·그림 작업을 되돌리거나 다시 적용한다. | [Samsung PC 지원](https://www.samsung.com/us/support/answer/ANS10001469/). 히스토리 크기·앱 재실행 이후 유지 여부는 미확인이다. |
| 손가락과 펜 | 손가락 그리기를 켜는 설정과 두 손가락 확대를 안내한다. | [Samsung 손글씨 안내](https://www.samsung.com/ae/support/mobile-devices/samsung-notes-composing-notes-with-handwriting/). 손바닥 구분의 센서·드라이버 구현은 설명하지 않는다. |
| PDF 위 필기 | PDF에 그림·메모를 추가할 수 있고 기존 PDF 본문은 직접 편집하지 않는다. | [Samsung Notes 기능·설정](https://www.samsung.com/us/support/answer/ANS10001384/). 원본 파일을 참조하는지 복사하는지, 주석 직렬화 방식까지 확정할 수 없다. |
| 자동 저장 | 별도 저장 조작 없이 저장되며 뒤로 가기로 저장하는 흐름을 안내한다. | [Samsung Notes 기능·설정](https://www.samsung.com/us/support/answer/ANS10001384/). 강제 종료 직전 모든 점 저장, 트랜잭션 간격, 충돌 복구 보장은 이 문서에 없다. |

필압은 별도 경계다. Samsung은 특정 Note9 S Pen의 4,096단계 필압을 공개했지만, 이것은 해당 하드웨어의 설명이다. Samsung Notes의 모든 펜·형광펜이 같은 필압 곡선을 사용한다거나 브라우저까지 그 단계가 그대로 전달된다는 증거로 쓰지 않는다. [Samsung Developer의 해당 장치 소개](https://developer.samsung.com/sdp/blog/en/2018/10/04/new-developer-features-for-the-galaxy-note9-s-pen)

## 브라우저가 실제로 받을 수 있는 정보

Pointer Events는 `pointerType`으로 `mouse`·`pen`·`touch`를 구분하고 좌표·필압·기울기·버튼 상태 등을 전달한다. `pressure` 범위는 0–1이며 필압을 지원하지 않으면 눌림 중 **0.5**, 해제 시 **0**이다. 이 기본값을 실제 필압 측정값으로 표현하면 안 된다. OS·브라우저의 손바닥 무시는 웹 페이지가 해제할 수 없는 경우도 있다. [W3C Pointer Events 3의 인터페이스·입력 타입](https://www.w3.org/TR/pointerevents3/#pointerevent-interface)

`getCoalescedEvents()`는 하나의 이동 이벤트로 묶인 측정점을 얻는 API다. 예측 이벤트는 앞으로 움직일 위치의 추정이며 실측 경로와 구분해야 한다. `touch-action`은 스크롤·확대 허용을 선언한다. 브라우저가 제스처를 가져가면 `pointercancel`과 capture 해제가 발생할 수 있으므로 `pointerup`만 기다리는 처리로는 충분하지 않다. [W3C 병합·예측 이벤트](https://www.w3.org/TR/pointerevents3/#coalesced-and-predicted-events), [제스처](https://www.w3.org/TR/pointerevents3/#declaring-direct-manipulation-behavior), [취소](https://www.w3.org/TR/pointerevents3/#the-pointercancel-event)

WebKit은 Safari **18.2**에서 `getCoalescedEvents()`·`getPredictedEvents()` 및 Apple Pencil의 `altitudeAngle`·`azimuthAngle` 지원을 발표했다. 이는 공개 API의 지원 근거이며 모든 iPad·Pencil 세대의 센서, 지연, 버튼·쥐기 제스처까지 동일하게 제공한다는 뜻은 아니다. 실제 기능 존재와 이벤트 값을 장치에서 확인해야 한다. [WebKit Safari 18.2 발표](https://webkit.org/blog/16301/webkit-features-in-safari-18-2/)

## 기기별 가능한 범위

| 사용 환경 | 근거로 말할 수 있는 범위 | 남은 확인 |
|---|---|---|
| Mac + 마우스·트랙패드 | 좌표로 필기·선택·지우기를 조작할 수 있다. 일반적인 필압 미지원 입력의 0.5는 진짜 펜 필압이 아니다. [W3C](https://www.w3.org/TR/pointerevents3/#pointerevent-interface) | 작은 한글 필기 편의성·스크롤 충돌은 사용 기기로 확인한다. 속도로 선 굵기를 바꾸더라도 실제 필압과 구분한다. |
| Mac + 펜 태블릿 | 호환 태블릿·적절한 드라이버가 있으면 웹 Pointer Events의 위치·필압·기울기·버튼을 사용하는 경로가 있다. [Wacom 공식 웹 API](https://developer-docs.wacom.com/docs/icbt/web/web-api-basics/) | 특정 Mac·브라우저·드라이버의 실제 `pointerType`, 필압 범위, 지우개 버튼 매핑을 확인해야 한다. 모든 제품 호환을 확정한 결과가 아니다. |
| Galaxy Tab + S Pen | 삼성 앱의 공식 조작 흐름은 참고할 수 있다. 웹은 브라우저가 노출하는 Pointer Events만 받는다. [Samsung 손글씨 지원](https://www.samsung.com/us/support/answer/ANS10003634/), [W3C](https://www.w3.org/TR/pointerevents3/#pointerevent-interface) | Samsung Internet·Chrome의 실제 필압·측면 버튼·손바닥 무시, 서버 연결·인증 경로를 확인한다. Samsung Notes의 네이티브 엔진이 웹에 제공된다는 근거는 없다. |
| iPad Safari + Apple Pencil | Safari의 Pencil 이벤트 경로가 있다. [Apple Safari 13 릴리스](https://developer.apple.com/documentation/safari-release-notes/safari-13-release-notes), [WebKit 18.2](https://webkit.org/blog/16301/webkit-features-in-safari-18-2/) | iPad·Pencil 모델별 입력 특성과 제스처를 확인한다. Swift의 UIKit/PencilKit 기능을 웹 API 기능으로 옮겨 적지 않는다. |
| iPad를 Mac의 Sidecar 화면으로 사용 | Apple은 Pencil로 포인팅·그리기를 안내하며 고급 필압·기울기는 AppKit 태블릿 이벤트 경로를 설명한다. [Apple 지원](https://support.apple.com/102597), [Apple Sidecar 기술 문서](https://www.apple.com/macos/big-sur/docs/Sidecar_Tech_Brief_Oct_2019.pdf) | iPad Safari 직접 실행과 다른 경로다. Mac 브라우저까지 필압이 전달되는지 실측하지 않아 보장할 수 없다. |

**판단:** 도구 전환·선택·지우기·복원·페이지 메모의 조작을 재현하는 것은 독립 구현의 목표가 될 수 있다. S Pen과 Samsung Notes의 감촉·필압 응답·지연을 그대로 보장하려면 원본 장치와 구현 결과의 직접 비교가 필요하다. 공개 매뉴얼 확인만으로 동일 경험을 달성했다고 표현하지 않는다.

## PDF 좌표·보존에서 확인할 사항

PDF.js 공식 예제는 페이지 viewport가 크기·배율·회전을 포함하고 PDF의 왼쪽 아래 원점과 canvas의 왼쪽 위 원점 사이 변환을 수행한다고 설명한다. CSS 표시 크기와 HiDPI canvas 픽셀 크기도 구분한다. 따라서 페이지를 화면에 렌더링하는 것과 주석을 그 페이지 좌표에 고정하는 것은 별도로 확인할 문제다. [Mozilla PDF.js 페이지 렌더링 예제](https://mozilla.github.io/pdf.js/examples/#rendering-the-page)

아래는 이번에 실행한 시험 결과가 아니라 **후속 비교를 위한 관찰 체크리스트**다. 저장 방식이나 UI 배치를 확정하는 설계 명세가 아니다.

- [ ] 실제 장치·OS·브라우저·드라이버 버전과 `pointerType`, 필압·기울기·버튼 값의 지원 여부를 기록한다.
- [ ] 펜/형광펜, 굵기/색/불투명도, 짧은 점·느린 획·빠른 곡선·작은 한글을 비교한다. 필압 곡선은 원본 삼성 구현을 추정해 확정하지 않는다.
- [ ] 획 전체 지우기와 부분 지우기 결과, 가는 선 교차점, 형광펜과 일반 펜이 겹친 부분을 비교한다.
- [ ] 올가미의 일부 걸친 획, 여러 획 이동·크기 조절, 취소·다시 실행 후 위치와 도구 스타일 보존을 확인한다.
- [ ] 손가락 스크롤/확대와 펜 쓰기가 충돌하는지, 펜 사용 중 손바닥 접촉과 `pointercancel` 이후 다음 획이 이어 붙는지 확인한다.
- [ ] 확대·축소·창 크기 변경·Retina 배율·페이지 회전 후 원문 밑줄과 잉크가 같은 위치에 남는지 확인한다. 페이지 이동 후 다른 페이지에 잉크·텍스트 메모가 섞이지 않아야 한다.
- [ ] 완료한 획·텍스트 메모가 페이지 전환·새로 고침·앱 종료 후 유지되는지 확인한다. 저장 실패·네트워크 지연·동시 탭 수정·강제 종료 후에는 실제 저장 확인 이전의 상태를 저장 완료로 표시하지 않는지 확인한다.
- [ ] 원본 PDF의 이동·수정·삭제 시 다른 버전의 페이지에 예전 잉크가 조용히 덮이는지 확인한다. 원본 변경과 주석 복구를 구분한다.

미확인: Samsung Notes 내부 엔진·노트 포맷, REA 분석 결과, Mac 펜 장치·Galaxy Tab·iPad 실측, 입력 지연 수치, 강제 종료 복구 보장. 제품 코드·의존성·모델·테스트는 변경하지 않았다.
