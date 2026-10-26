# 필기 이미지·인식 엔진 분리 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [x]`) syntax for tracking.

**Goal:** Mac의 실제 필기 이미지·인식 결과·승인·검색을 보존하며 다른 OS의 생성기·인식기를 연결할 호출 경계를 만든다.

**Architecture:** Mac helper는 기존 렌더링을 그대로 유지하고 `--render-only`와 기존 `--recognize-image`로 역할을 나눈다. Python 조합 함수는 생성기와 이미지 인식기를 별도로 호출하며, Mac helper 실행은 전용 adapter로 모은다. Qwen·Gemma 모델 함수는 준비된 이미지 파일만 받는다.

**Tech Stack:** 기존 Python·Swift/AppKit/CoreGraphics/PDFKit/Vision·Pillow·SQLite. 새 의존성 없음.

**Spec:** [승인한 설계](../specs/2026-10-27-handwriting-adapters-design.md)

## Global Constraints

- 기존 renderer의 white/black pen·압력·round cap/join·2400px/3배·highlighter 제외·좌표·PDF cropBox를 유지한다.
- 기존 engine ID·revision·languages·bbox·candidates·`/page`·Mac 잘림 경고·Qwen/Gemma 이미지 전처리와 프롬프트를 유지한다.
- DB·획 형식·승인·검색 조건·기존 인식문·수정문·초안·과거 출처를 바꾸지 않는다.
- 다른 OS 앱·모델·클라우드·동기화·엔진 등록 시스템은 추가하지 않는다.
- `deliverables/`와 현재 사용자 보관함을 수정하지 않는다. 기존 연결 원본과 모델은 읽기만 한다.

## Review Focus

- 원본 페이지의 `/page` 유실 → 자동 작업이 같은 페이지를 반복하지 않아야 한다.
- Qwen/Gemma 잘림 진단 → Mac 기존 경고 유지, 다른 OS의 진단 생략을 '잘림 없음'으로 확정하지 않는다.
- 사진의 EXIF·위장 확장자·큰 이미지 → 기존 최종 모델 입력 픽셀과 크기를 유지한다.
- 실패·취소·미저장 상태 → 요청 소유 프로세스·임시 이미지만 정리하고 기존 초안·승인 출처를 보존한다.
- 비Mac 실행 → 대체 생성기·인식기를 지정한 공통 흐름이 Swift/Vision을 호출하지 않는다.

---

### Task 1: Mac 렌더링·인식 adapter 분리

**Files:** `macos/HandwritingRecognition.swift`, 새 `lecture_study/handwriting_macos.py`, `tests/test_native_handwriting.py`, 새 `tests/test_handwriting_adapters.py`.

**Interfaces:**

- `async render_ink(payload: dict, image_path: Path, *, page_source: str | None = None, page: int = 1) -> dict`: 검증된 렌더 입력을 받아 PNG와 크기 metadata를 만든다. OCR은 실행하지 않는다.
- `async recognize_image(image_path: Path) -> dict`: 이미지 파일만 받아 기존 Vision 결과를 반환한다. 렌더링하지 않는다.
- adapter 내부 공통 helper 실행기는 기존 frozen binary 경로·Swift 개발 경로·플랫폼 검사·입력 크기·timeout·프로세스 정리를 보존한다.

- [x] 기존 helper를 `.local-state/handwriting-adapters-20261027/`에 별도 빌드하고 동일 획·사진·PDF의 PNG·Vision 결과를 기록한다.
- [x] RED: render-only에서 한국어 Vision 지원이나 OCR을 요구하지 않고 PNG를 만드는 native 검사를 추가한다. dot·위/아래 방향·압력·highlighter 제외·원본 합성과 invalid payload도 검사한다.
- [x] 기존 helper에 render-only 종료 경로를 최소 추가한다. 기존 결합 CLI와 image-only CLI는 유지한다.
- [x] Python adapter의 렌더·이미지 인식 함수를 분리하고 Mac 플랫폼 검사는 이 모듈에 둔다.
- [x] 집중 검사 및 분리 전후 PNG 크기·픽셀·Vision 출력·좌표·엔진 metadata 대조를 통과시킨다.

### Task 2: 공통 흐름·로컬 이미지 엔진 연결

**Files:** `lecture_study/handwriting.py`, `tests/test_handwriting.py`, `tests/test_handwriting_adapters.py`, 필요 시 `tests/test_second_brain.py`.

**Interfaces:**

- `recognize_ink(snapshot, image_path=None, *, renderer=None, recognizer=None)`: 기존 호출을 유지하며 대체 생성기와 이미지 인식기를 받을 수 있다. 기본은 Mac adapter다.
- renderer는 Task 1의 `render_ink` 서명을, recognizer는 `recognize_image` 서명을 따른다.
- `recognize_local_ink(snapshot, manager, before_local=None, model='qwen3.5:4b', *, renderer=None, diagnostic_recognizer=None)`: 기본 Mac renderer 사용 시 기존 Vision 진단을 별도 실행한다. 대체 renderer를 지정한 경우 진단은 명시적으로 전달하거나 생략한다.
- `async recognize_local_image(image_path, manager, before_local=None, model='qwen3.5:4b') -> dict`: 준비된 이미지와 manager만 사용한다. renderer·Vision 호출이 없다. 모델 식별·생성 text·usage·finish reason을 반환한다.
- 원본 사진 선택·EXIF·한 번 확대는 조합 함수의 입력 준비에서 유지하고, 실제 ink bbox와 `/page`는 공통 조합 단계에서 보존한다.

- [x] RED: 비Mac 환경 + 대체 renderer/recognizer의 결과가 후보·승인·검색까지 이어지고 Mac helper를 호출하지 않는 검사를 추가한다.
- [x] RED: 이미지 입력 로컬 엔진이 renderer/Vision 없이 실행되고, 진단이 생략되면 `edge_touching`을 확인된 false로 만들지 않는 검사를 추가한다.
- [x] 기존 로컬 모델 검사의 patch 위치를 새 접점에 맞추고, 동일 이미지·EXIF·큰 사진·위장 확장자·잘림 경고·빈 필기·모델 제한 assertion은 유지한다.
- [x] 위 인터페이스로 기존 함수를 연결한다. engine ID와 `/page`를 보존하며 DB·서버·프런트엔드 API는 변경하지 않는다.
- [x] 기존 승인·검색·stale·과거 출처·미승인 리뷰 초안 검사와 `/page` 자동작업 중복 방지 검사를 통과시킨다.

### Task 3: Mac 실행 검증·문서·main 반영

**Files:** 개발/검증 문서와 필요한 검증 fixture. 빌드 helper 이름은 유지한다.

- [x] 같은 실제 혼합 노트에서 기존/분리 renderer의 픽셀과 Vision JSON을 대조하고, 설치된 Qwen·Gemma의 실제 최종 이미지와 출력도 대조한다. 모델은 새로 받지 않는다.
- [x] 격리된 보관함의 Mac 실행 경로에서 필기 저장·인식·수정·승인·검색·필기 변경 후 제외·과거 출처·초안 복구를 확인한다. 실제 사용자 보관함을 검증 데이터로 수정하지 않는다.
- [x] 전체 Python 회귀 검사, frontend test/check, helper 컴파일과 frozen engine에 새 adapter가 포함되는지 확인한다. 실패는 이름과 원인을 기록한다.
- [x] 개발 문서에 대체 renderer/recognizer 연결 예제와 실제 다른 OS 구현·MLX 실행은 미검증임을 명시한다.
- [x] 독립 코드·증거 검토를 받고 지적을 해결한다.
- [ ] 정확한 변경 파일만 커밋·`origin main`에 푸시하고 원격 SHA·작업 트리를 확인한다.

## 실행 방식

현재 세션에서 직접 구현하고 마지막에 독립 검토하는 방식을 추천한다. 렌더링·metadata·후보 저장의 연결을 같은 문맥에서 확인하기 위함이다. 현재 경로는 이미 linked Git worktree이므로 재사용하며, 기존 사용자 파일을 이동하거나 초기화하지 않는다.

## 검증 결과

[Mac 실제 대조·한계](../../handwriting-adapters-validation-20261027.md). Python 674통과·5선택생략, frontend 104통과·검사·빌드 통과. frozen 엔진과 Mac WKWebView에서 승인·검색·초안 복구를 확인했다. 현재 설치 앱 교체와 Windows·Android 실행은 이번 검증에 포함하지 않았다.
