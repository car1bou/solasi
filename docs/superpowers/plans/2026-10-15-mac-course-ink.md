# Mac Course Materials and Page Ink Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [x]`) syntax for tracking.

**Goal:** Mac 설치형 앱 안에서 과목 자료·강의 기록·PDF 페이지 메모와 필기를 사용하고 기존 기록·원본을 보존한다.

**Architecture:** 기존 React·FastAPI·SQLite와 로컬 모델을 유지한다. 과목 자료·문서 해시별 페이지 문서를 추가하고 화면을 AppKit/WKWebView 창 안에 연다. OS와 무관한 페이지 좌표·데이터 모델을 유지하여 Windows·Android·iPadOS 후속 이식에 활용한다.

**Tech Stack:** 기존 Python 3.12, SQLite, React 19, TypeScript, LiteParse, Swift/AppKit/WebKit/AVFoundation. 클라우드 SDK·동기화 엔진·추가 모델 다운로드 없음.

**Spec:** ../specs/2026-10-15-local-course-notes-design.md

## Global Constraints

- 각 기기 독립 로컬 저장. 드라이브·NAS·계정·페어링·원격 작업함 없음.
- 외부 원본은 참조하며 원본 삭제·덮어쓰기 금지. 기존 기록·source ID·과거 인용 보존.
- Mac부터 실제 실행한다. Windows·Android·iPadOS 빌드·실기 검증을 완료한 것으로 표시하지 않는다.
- 설계 검토 grilling, 코드 Ponytail. 사용자의 ‘일단 진행하고 사용 후 피드백’ 지시에 따라 실행 중 반복 승인 질문 없이 진행한다.
- 이번 요청에서 자동 테스트 추가·실행은 별도로 요청되지 않았다. 빌드·타입·구문·격리된 실행 확인을 사용하고 검사 범위를 명확히 보고한다.
- 현재 미커밋 README·macos·scripts는 앞서 만든 실행기 작업이다. 보존하고 필요한 파일만 수정한다.

## Review Focus

- 마지막 강의 회차 삭제 후에도 과목 자료·페이지 필기가 유지되어야 한다.
- 같은 PDF 재추출은 기존 필기를 유지하며 원본 내용 교체는 다른 문서로 구분해야 한다.
- 페이지·과목 이동 또는 저장 실패에서 필기를 잃거나 다른 페이지에 저장하지 않아야 한다.
- 앱 창·새 PDF 창·내보내기·마이크 권한이 외부 브라우저나 다른 origin에 넘겨지지 않아야 한다.
- 과목-only 생성과 예전 회차 생성·인용이 함께 작동하고 원음 작업은 화면 이동으로 중단되지 않아야 한다.

## 공통 인터페이스

### 자료와 페이지

```text
GET  /api/courses/{cid}/materials               -> {assets: Asset[]}
POST /api/courses/{cid}/files/select            -> 기존 파일 선택 응답
POST /api/courses/{cid}/assets/{aid}/extract    -> Job
GET  /api/assets/{aid}/document                -> DocumentMetadata
GET  /api/assets/{aid}/pages/{page}?document_sha256={hash} -> PNG
GET  /api/courses/{cid}/assets/{aid}/pages/{page}/document?document_sha256={hash}
PUT  /api/courses/{cid}/assets/{aid}/pages/{page}/document
```

`DocumentMetadata`: `{asset_id,sha256,total_pages,pages:[{page,width,height,rotation,ref}]}`. `ref`는 추출 실패 여부와 독립적으로 페이지 질문에 쓸 수 있는 관리된 SourceRef다.

GET 페이지 문서 응답: `{id,course_id,asset_id,document_sha256,page,revision,text,ink,source_id,updated_at}`. 미작성은 `id/source_id/updated_at=null`, `revision=0`, 빈 text/ink.

PUT 본문: `{document_sha256,expected_revision,text,ink}`. 해시·revision 불일치는409. text 최대200,000자, ink 직렬화 최대8MiB, 최대2,000획·전체100,000점.

`InkStroke`: `{id,tool:'pen'|'highlighter',color:'#RRGGBB',width,opacity,input:'mouse'|'pen'|'touch',points:[{x,y,pressure,tilt_x?,tilt_y?}]}`. 좌표·필압은0..1 유한수, width는 페이지 폭의0.0002..0.1, opacity0.05..1, tilt는-90..90. UI 기본 pen width0.0025, highlighter0.018. 페이지 내용 해시와 필기 수정 revision을 구분한다.

### 과목 AI

기존 `/api/ai/jobs`에 `course_id` 소유자를 허용한다. 회차 요청은 기존 `session_id` 그대로 사용하고 두 소유자를 동시에 지정하지 않는다.

과목 scope: `{course_id,mode:'course',asset_id?,page?,document_sha256?}`. 과목-only는 answer/explain/summary/vision만 허용한다.

```text
GET /api/courses/{cid}/jobs
GET /api/courses/{cid}/artifacts
```

기존 artifact 조회·내보내기·재시도·부분 요약 경로를 재사용한다. SourceRef는 page_note 및 course_id/document_id/document_sha256을 지원한다. 회의·퀴즈·회차 메모 보강은 기존 회차 검증을 유지한다.

## Task 1: 과목·페이지 저장과 검색·AI 범위

**Files:** `lecture_study/schema.sql`, `db.py`, `models.py`, `materials.py`, `material_worker.py`, `retrieval.py`, `lifecycle.py`, `answers.py`, `outputs.py`, `jobs.py`, `server.py`; 필요한 경우 작은 `course_materials.py` 모듈.

**Interfaces:** 위 API·JSON을 생산하며 기존 회차 API 계약을 유지한다.

- [x] 스키마17과 트랜잭션 마이그레이션: course_assets, 원본 hash 메타데이터, 페이지 문서·수정 버전, 과목 결과 소유자. artifacts FK를 보존하여 재생성한다.
- [x] 기존 과목 지정 강의 자료 연결을 추가형으로 backfill하고 삭제 GC 조건·근거 조회를 함께 수정한다.
- [x] 실제 원본 페이지 메타데이터·렌더링을 추출 성공 페이지와 분리한다. 같은hash 재추출과 진짜 원본 변경을 구분한다.
- [x] 페이지 문서 저장의 hash·revision·입력 크기·좌표를 검증하고 text만 최신 검색 색인에 포함한다.
- [x] 과목-only 요청·과목 공용 자료·페이지 메모의 검색, vision, 요약, 인용, 재시도·내보내기를 연결한다.
- [x] Python 구문·의존성 확인 및 제품 데이터가 아닌 복사본의 마이그레이션·핵심 API 실행을 확인한다. 원본 DB는 재시작 전까지 수정하지 않는다.

## Task 2: 과목 탐색·PDF 메모·필기

**Files:** `frontend/src/App.tsx`, `SessionView.tsx`, `MaterialView.tsx`, `QuestionView.tsx`, `types.ts`, `styles.css`; 새 `CourseView.tsx`, `PageNotebook.tsx`, `ink.ts`, 필요시 IndexedDB 초안 helper.

**Interfaces:** Task1 API를 소비한다. 기존 Recorder와 회차 노트 API는 유지한다.

- [x] 왼쪽 과목 목록·선택·과목 내 강의 생성·회의/미지정 분리를 구현한다. 활성 녹음의 SessionView가 탐색으로 언마운트되어 원음이 끊기지 않게 한다.
- [x] 과목 자료 화면을 전체 PDF 페이지·메모·필기로 구성하고 추출 Markdown/OCR 항목 나열을 숨긴다.
- [x] normalized 문서 좌표·실제 압력으로 pen/highlighter, 획/부분 지우기, lasso 이동/크기, undo/redo를 구현한다. 회전·확대·입력 취소를 처리한다.
- [x] IndexedDB 초안과 DB revision 대조, 저장 대기·실패·충돌 보존·페이지 전환을 연결한다. 전사·모델 추론과 입력 렌더링을 분리한다.
- [x] course 또는 session 소유자를 받는 QuestionView로 답변·페이지 설명·전체 요약과 저장 결과를 재사용한다.
- [x] TypeScript 확인과 Vite 빌드를 실행한다. 빌드 산출물은 전환 시점까지 격리된 출력 폴더에 둔다.

## Task 3: Mac 앱 창

**Files:** `macos/Solasi.swift`, `scripts/install_macos_app.py`. 기존 server CLI 계약 유지.

**Interfaces:** 기존 launcher stdout의1회 bootstrap 링크를 health 준비 후 WKWebView.load에만 전달한다.

- [x] AppKit 주 창·영구 WKWebsiteDataStore·표준 Edit 메뉴를 추가하고 재열기에서 페이지를 reload하지 않는다.
- [x] 정확한 loopback origin/frame의 사용자 요청 마이크만 OS permission에 연결한다. 카메라·다른 origin은 거절한다.
- [x] target blank의 로컬 PDF는 별도 앱 창에서 열고 download 내보내기는 NSSavePanel과 WKDownload로 처리한다. 기존 목적지 파일을 먼저 삭제하지 않는다.
- [x] 창 닫기는 백그라운드 서버를 보존하고 Dock/⌘Q 종료는 기존 Process 정상 종료를 따른다. 로드 실패·웹 프로세스 종료를 표시한다.
- [x] 설치 스크립트에 마이크 설명을 추가하고 기존 앱을 안전한 백업 후 교체할 수 있게 한다. CLT swiftc 빌드·ad-hoc 서명 검사를 수행한다.

## Task 4: 통합·사용 가능한 앱 전환

**Files:** 위 변경 파일과 README, 이 계획의 진행 기록.

- [x] 인터페이스·저장/삭제·과거 근거·입력 경계를 새로운 리뷰어가 전체 변경에서 검토한다.
- [x] 빌드·격리된 데이터 실행에서 실제 화면·원본 페이지·메모·필기 재열기를 확인하고 확인하지 못한 하드웨어 경로는 표시한다.
- [x] 현재 녹음·작업 유무를 확인하고, 안전한 시점에 DB 백업 후 새 앱으로 전환한다. 실제 마이크 녹음은 사용자 클릭으로 시작한다.
- [x] 데이터 보존·앱 응답·원본 참조를 확인하고 변경을 커밋한다. 원본 음성·모델·개인 경로/토큰이 Git에 포함되지 않게 한다.
- [x] Mac 사용 방법과 남은 다른 OS 작업을 분리해 보고한다. 구현하지 않은 플랫폼을 지원 완료로 표현하지 않는다.

## 진행 기록

- 2026-10-15: 사용자 추가 지시로 설치형 앱 대상 확정. Mac 완성 후 다른 OS 순서로 진행. 클라우드·동기화 취소 유지.
- Ruling: Mac AppKit/WKWebView 창을 사용한다 — 기존 기능·Python·모델을 보존하고 새 플랫폼 SDK 없이 실제 설치형 사용을 먼저 완성할 수 있다. 다른 OS 셸/모바일 엔진은 후속 별도 이식이 필요하다.
- Pre-flight: Task1→Task2는 위 API 계약을 공유한다. Task3는 기존 launcher 계약만 사용하며 다른 구현 파일과 겹치지 않는다. 마지막 통합에서 실제 API·타입·창 동작을 대조한다.

### 통합 확인 기록

- 기존 schema16 DB를 복사하고 원본 DB·이전 화면 빌드를 별도 백업했다. 원본에는4회차·3녹음·436전사·2노트·1생성 결과가 있었다. 복사본 schema17 마이그레이션 뒤 FK 위반은0건이다.
- 별도 bundle ID·포트62435의 Mac Preview에서 실제 WKWebView bootstrap, 과목 탐색, 원본3쪽 PDF 표시, 페이지 메모 저장, 마우스 획 저장과 페이지 이동 후 메모 복원을 확인했다. 창 닫기 후 서버가 유지되고 앱 재열기에서 기존 화면이 유지됐다.
- 새 리뷰어2명이 프런트/네이티브와 백엔드를 각각 검토했다. 원본 교체 뒤 이전 OCR 인용이 새 PDF를 여는 회귀, 갱신 중 필기 덮어쓰기, 임의 포트 사용 시 초안 저장소가 분리되는 문제를 수정하고 재검토했다.
- Mac 앱은 고정 포트를 사용한다. 다른 프로그램이 같은 포트를 점유하면 명시적으로 실패하며, CLI 기본 실행의 임의 포트 선택은 유지한다.
- 최종 Swift는 macOS13 target·warnings-as-errors 컴파일을 통과했다. Python 구문, TypeScript, 격리 Vite 빌드와 diff 공백 검사를 통과했다. 설치기의 임시 앱 생성·교체·백업·설정 보존과 ad-hoc 서명 검사를 확인했다.
- 실제 모델 재추론, 마이크 녹음, 물리적 펜·터치와 장시간 동시 실행은 이번 변경에서 재검증하지 않았다. 자동 테스트 스위트는 추가·실행하지 않았다. 다른OS 빌드도 수행하지 않았다.

- 사용자가 Preview에서 추가한 필기를 실제 앱으로 보존하는 전환을 승인했다. 기존 테이블의 이전 열을 대조하여 내용 변경이 없음을 확인하고, 전환 전 원본 DB와 필기 포함 Preview DB를 각각 백업했다. 자료 캐시2개와 페이지 수정 이력7개를 보존했다. 전환 뒤 integrity_check=ok, FK 위반0건이다.
- 실제 `~/Applications/Solasi.app`을 백업 후 교체하고 ad-hoc 서명 검사를 통과했다. 고정 포트62434에서 자체 창 bootstrap·과목 자료·저장된 페이지 v7·메모 복원을 확인했다. 원본 PDF는 별도 앱 창에서3쪽 모두 열렸으며 그 창을 닫아도 메모 화면은 유지됐다.
- 현재 앱은 사용자가 계속 사용할 수 있도록 열어 두었다. 신규 설치본의 마이크 권한·물리적 펜 입력·다운로드 저장 대화상자와 모델 추론은 실제 실행 확인에 포함하지 않았다.
