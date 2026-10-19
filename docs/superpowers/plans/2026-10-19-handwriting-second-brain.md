# Handwriting Second Brain Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking. Execution method requires user selection before implementation.

**Goal:** Mac에서 확인한 손글씨 인식문을 원문에 연결된 지식으로 편입하고 로컬 유휴 시간에 색인과 관련 기록·개념 후보를 갱신한다.

**Architecture:** 기존 SQLite·SourceRef·페이지 버전·작업·DirectModels를 확장한다. 손글씨 인식 후보와 승인 출처를 분리하고, 최신 유효 출처만 검색한다. 원음 저장·전사·사용자 요청 뒤에 자동 작업을 처리하며 Exa 실행 경로는 제거한다.

**Tech Stack:** Python 3.12/Pydantic/SQLite, Swift Vision·AppKit, React/TypeScript, 기존 MLX 이미지 입력·EmbeddingGemma.

**Spec:** `docs/superpowers/specs/2026-10-19-handwriting-second-brain-design.md` (사용자 승인 완료).

## Global Constraints

- Mac 우선, 각 기기 독립 로컬 저장, 포트 없는 내장 엔진.
- 확인·수정한 인식문만 답변·요약·개념 연결 근거로 사용한다.
- 원본 PDF·획·텍스트 메모·전사·미저장 초안·과거 출처를 보존한다.
- 개념 자동 확정·병합, 자동 외부 API 호출, 새 대형 모델 자동 다운로드를 금지한다.
- 모델과 전처리 형식이 같은 경우에만 임베딩을 재사용한다.
- 실행 중인 모델 호출은 강제 선점하지 않는다. 자동 작업은 호출 사이에서 양보한다.
- 현재 Exa 제거 미커밋 변경을 보존한다. 다른 사람의 변경을 일괄 stage하지 않는다.
- 이 문서는 계획이다. 아래 검증 명령은 아직 실행하지 않았다. 테스트 추가·실행은 구현 실행 승인에 포함되는 검증 범위를 확인한 뒤 수행한다.

## Review Focus

- **검토 중 필기 수정:** 오래된 후보 적용은 409로 거절한다. Task 3이 검증한다.
- **형광펜·회전 PDF·부분 지우기:** 본문과 손글씨를 혼동하지 않고 영역·출처가 맞아야 한다. Task 2·3이 검증한다.
- **벡터 기록 중 강제 종료:** 재시작 후 누락을 복원하고 다른 모델 벡터를 혼합하지 않는다. Task 4가 검증한다.
- **자동 작업 중 녹음/생성 요청:** 새 자동 호출을 중지하고 원음 저장·사용자 요청을 우선한다. Task 5가 검증한다.
- **거절/삭제 뒤 재등장:** 같은 입력의 후보는 반복 생성하지 않고 과거 답변 근거만 보존한다. Task 3·6이 검증한다.

---

## 파일 책임

- 신규 `lecture_study/handwriting.py`: 필기 스냅샷·인식 후보·승인·무효화. 신규 `macos/HandwritingRecognition.swift`: 잉크 렌더링과 Vision 결과 JSON.
- 기존 `models.py`, `schema.sql`, `db.py`, `course_materials.py`, `retrieval.py`, `lifecycle.py`, `answers.py`, `outputs.py`: 출처·버전·검색·수명 주기·내보내기 연결.
- 신규 `lecture_study/second_brain.py`: 자동 작업 선택·관련 기록·개념 후보. 서버는 기존 요청·작업 등록과 수명 주기만 연결한다.
- 기존 `server.py`, `jobs.py`, `direct_models.py`: 요청·작업·자원 우선순위 연결. 기존 모델 엔진을 복제하지 않는다.
- 신규 `frontend/src/HandwritingReview.tsx`, `frontend/src/RelatedKnowledge.tsx`: 검토와 관련 근거 표시. 기존 `PageNotebook.tsx`, `ConceptView.tsx`, `SourceLink.tsx`, `SettingsView.tsx`, `types.ts`, 실제 스타일 파일에서 통합한다.
- 기존 `scripts/freeze_macos_engine.py`: Swift helper 번들 포함. `macos/AppResources.swift`는 신규 바이너리 리소스 경로가 필요한 경우에만 수정한다.

## Task 1: Exa 제거 변경 확정

**Files:** 현재 변경된 `answers.py`, `models.py`, `server.py`, `credentials.py`, `assistance.py`, 질문·설정 UI, README·guide·improvements, Exa 전용 모듈과 관련 검사.

**Interfaces:** 신규 AI 입력은 `web`·`web_query`를 받지 않는다. 과거 AIRequest 로딩만 해당 필드를 버린다. 기존 web SourceRef·저장된 인용은 해석 가능해야 한다.

- [ ] 새 요청의 retired 필드 거절, 과거 작업 읽기, 실행 전 web 요청 중단, 과거 인용 열기·내보내기를 검증하는 기존 검사 위치를 찾아 최소 회귀 검사를 작성한다.
- [ ] `.venv/bin/python -m unittest discover -s tests -p 'test_materials.py'` 및 해당 요청·키·이전 작업 검사 파일을 실행해 호환성을 확인한다. 제거한 Exa mock 성공을 통과 기준으로 삼지 않는다.
- [ ] 실제 활성 코드에서 Exa 호출·키 조회가 없음을 확인하고 `cd frontend && npm run build`, `git diff --check`를 실행한다. 참고용 과거 조사 문서와 web 인용 보존 타입은 남긴다.
- [ ] 해당 변경만 명시적으로 stage하고 `refactor: remove Exa search integration`으로 커밋한다.

## Task 2: 실제 잉크 인식 엔진 비교

**Files:** 신규 `macos/HandwritingRecognition.swift`, `experiments/compare_handwriting.py`; 기존 모델 호출 인터페이스를 재사용한다.

**Interfaces:** helper stdin JSON `{page_width,page_height,strokes}` → stdout JSON `{engine,revision,languages,regions:[{bbox,text,candidates}]}`. bbox는 페이지 좌상단 원점 정규화 xywh. 문자 인식만 반환하며 의미 설명을 합치지 않는다. 입력은 InkStroke 스냅샷, 출력은 원문·영역만 사용한다.

- [ ] `tests/test_handwriting.py`에 회전·좌표 변환, 형광펜 단독 제외, 비정상/과대 입력 거절 검사를 작성한다. 불변 조건: bbox가 페이지 안에 있고 highlighter-only 입력에서 인식 대상이 생기지 않는다.
- [ ] `.venv/bin/python -m unittest discover -s tests -p 'test_handwriting.py'`로 미구현 실패를 확인한다.
- [ ] AppKit으로 저장 획을 흰 배경에 렌더링하고 Vision accurate, Korean/English 지원 언어 조회 결과를 사용한다. 굵기·압력·회전을 현재 페이지 표현과 맞춘다. 네트워크 요청과 런타임 다운로드는 넣지 않는다.
- [ ] 정답을 직접 확인할 수 있는 한국어/영어/숫자/혼합 필기·작은 글씨·수식·도형·화살표·형광펜 원본을 동일하게 Vision과 설치된 이미지 모델에 입력한다. 실제 손글씨가 부족하면 폰트 이미지를 실제 필기 성능으로 보고하지 않는다.
- [ ] 원본/정답/엔진/지연/누락/추가 문자/수식·도형 오류를 로컬 결과 파일로 비교한다. 사용자 자료를 저장소에 커밋하지 않는다. 품질이 부족하면 지원 불가 구간을 표시하고 기본 엔진 선택을 보류한다.
- [ ] 검사 통과 및 helper 비정상 입력 종료 확인 뒤 구현과 공개 가능한 비교 방법만 커밋한다.

## Task 3: 인식 검토·승인 출처·페이지 UI

**Files:** 신규 `handwriting.py`, `HandwritingReview.tsx`, `tests/test_handwriting.py`; 기존 파일 책임 목록의 출처·DB·UI·내보내기 모듈.

**Interfaces:** `capture_ink(db,course_id,asset_id,page,digest)->dict`, `save_recognition(db,snapshot,result)->dict`, `approve_recognition(db,recognition_id,text,expected_ink_hash)->SourceRef`, `reject_recognition(db,recognition_id)->dict`. API는 과목·자료·페이지 소유권을 확인한다. DB 레코드는 후보/승인/거절/stale와 불변 원문·수정문을 구분한다.

- [ ] candidate/rejected/stale의 검색 제외, 승인 후 ink_note 포함, 적용 직전 획 수정 시 409, 같은 획의 텍스트 메모 수정 시 재인식 없음, 부분 지우기 무효화 검사를 작성한다.
- [ ] 새 검사 실패를 확인하고 DB migration과 `ink_note` SourceRef·searchable view·scope·라벨·checked_evidence를 연결한다. 승인과 버전 확인은 같은 트랜잭션으로 처리한다.
- [ ] 페이지 옆 접이식 후보 검토에 원본 영역/인식문/적용·수정·거절·다시 인식을 구현한다. 새 인식문으로 기존 텍스트 메모를 덮어쓰지 않는다.
- [ ] SourceLink·resolve_source·내보내기에서 당시 필기 영역과 승인 텍스트를 보이고, 자료 삭제 경로에 인식 레코드를 연결한다. 과거 답변의 승인 출처는 원래 버전을 유지한다.
- [ ] `test_handwriting.py`, `test_retrieval.py`, `test_lifecycle.py`, `test_materials.py`를 실행한다. 마이그레이션은 보관함 복사본에서 전후 레코드·원음 해시·초안을 대조한다.
- [ ] frontend build 및 680×480 라이트·다크의 키보드 검토·원문 위치·스크롤을 확인한 뒤 커밋한다.

## Task 4: 증분 의미 색인

**Files:** 기존 `retrieval.py`, `schema.sql`, `db.py`, `tests/test_retrieval.py`; 신규 자동 작업 모듈은 다음 Task에서 연결한다.

**Interfaces:** `async sync_embeddings(db,model,client,job_id=None)->dict`는 현재 모델·형식에 맞는 활성 색인의 누락 chunk만 채운다. 반환은 기존 index_status 형태에 completed/total을 더한다. 모델·형식이 다르거나 초기 색인이 없으면 기존 rebuild_embeddings 경로로 새 색인을 완성한 뒤 교체한다.

- [ ] 동일 버전 두 번 갱신 시 추가 embed 0회, 새 chunk만 처리, 구버전 검색 제외, 모델/format 변경 시 혼합 없음, 중간 취소 후 재실행으로 누락 복원 검사를 추가한다.
- [ ] 검사가 미구현 상태에서 실패함을 확인한다.
- [ ] 동일 index+chunk+part의 UNIQUE 키와 트랜잭션으로 멱등성을 보장한다. chunk의 전체 part를 한 번에 저장하여 부분 성공을 완료로 오인하지 않는다. 시작·재개 시 실제 searchable_chunks와 벡터를 대조한다.
- [ ] `.venv/bin/python -m unittest discover -s tests -p 'test_retrieval.py'`를 실행한다. 같은 고정 한국어 입력에서 전체 재색인과 증분의 벡터·검색 순위를 비교하고 실행 횟수·시간을 기록한다.
- [ ] 변경 내용을 커밋한다.

## Task 5: 로컬 자동 처리와 재시작 복구

**Files:** 신규 `second_brain.py`, `tests/test_second_brain.py`; 기존 `server.py`, `jobs.py`, `course_materials.py`, `materials.py`, 전사 확정 저장 경로, SettingsView.

**Interfaces:** `mark_knowledge_dirty(db,source_id)->None`, `next_background_work(db)->dict|None`, `related_sources(db,scope,source_id,client)->SearchResult`. 원문 저장을 자동 작업 성공 여부에 묶지 않는다. 설정 키 `second_brain_auto`의 기본값 true, pause 시 대기 유지.

- [ ] 연속 저장 합치기, 최신 버전만 처리, 녹음/전사/사용자 요청 존재 시 새 자동 호출 0회, cancel·오류·재시작 시 중복 방지 검사를 작성한다.
- [ ] 실패를 확인하고 저장 이벤트에서 dirty 표시를 연결한다. 작업 상태와 dedup 키는 DB에 보관하고 시작 시 누락 대상을 재조정한다. 자동 작업은 단일 실행으로 합친다.
- [ ] 자동 인식→승인 대기, 승인 후 의미 색인, 관련 기록 조회 순서로 진행한다. 다음 모델 호출 전에 우선순위를 재확인하고 기존 DirectModels/DirectEmbeddings 해제·취소를 재사용한다.
- [ ] 설정의 일시 정지·재개·대기/실패 표시를 연결한다. API 모델 선택이 백그라운드 외부 전송을 일으키지 않도록 분기한다.
- [ ] `test_second_brain.py`와 기존 worker/취소 검사를 실행한다. 긴 실제 음성 전사·생성 중 원음 프레임과 대기 상태를 대조하고 강제 종료 후 작업 복구를 확인한다.
- [ ] 자동화 구현을 커밋한다.

## Task 6: 관련 기록·개념 후보

**Files:** `second_brain.py`, 신규 `RelatedKnowledge.tsx`, 기존 ConceptView/PageNotebook·개념 저장 API, `tests/test_second_brain.py`.

**Interfaces:** `related_sources`를 사용하고 `async propose_concepts(db,source_id,provider,explicit=False)->dict`는 근거가 있는 표준 표기·별칭·인용 후보만 반환한다. 외부 provider에서 explicit=false이면 실행하지 않는다. 승인 저장은 기존 save_term을 사용한다.

- [ ] 같은 과목 이전 회차 포함, 다른 과목/현재 출처/복제본 제외, 정확한 인용 검증, 가정과 사실·상반 진술 보존, 거절 후보 반복 방지 검사를 추가한다.
- [ ] 실패를 확인하고 원문 버전·작업 종류의 dedup 키로 관련 기록과 개념 후보를 저장한다. 숫자·조건을 바꾼 생성 후보는 확정하지 않는다.
- [ ] 관련 발췌·페이지/시각·검토 버튼을 표시하고 승인하면 기존 개념 버전 경로로 저장한다. 외부 API 버튼에는 전송 대상 설명을 붙인다.
- [ ] 검사·frontend build·좁은 창 키보드 동작을 확인하고 커밋한다.

## Task 7: 내장 앱 통합·설치 전 확인

**Files:** `scripts/freeze_macos_engine.py`, 앱 패키징 버전·문서·관련 helper 등록.

- [ ] HandwritingRecognition helper를 번들에 포함하고 개발 도구 없이 실행되는지, HTTP 리스너 없이 동작하는지 확인한다.
- [ ] 보관함 복사본에서 실제 필기 저장→인식→수정·승인→검색→이전 강의 연결→질문·요약→내보내기를 실행한다. 수식·도형 해석이 승인 OCR로 섞이지 않는지 확인한다.
- [ ] 680×480 라이트·다크에서 검토 패널·탭 순서·포커스·스크롤·원문 영역을 확인한다. 녹음·절전·강제 종료 뒤 원음·필기·초안 복구와 승인 출처를 비교한다. 실제 절전은 사용자 깨우기 협조가 필요한 시점에 요청한다.
- [ ] 사용자 입력을 저장·종료한 뒤에만 설치 앱을 교체한다. 데이터는 별도 로컬 백업과 보호 해시로 비교하며 OS 권한 요청은 실제 발생한 경우만 안내한다.
- [ ] 문서에 측정 결과와 미검증 범위를 기록하고 변경을 검토한다. main 반영·푸시는 해당 실행 요청의 승인 범위에 따라 수행하고 원격 SHA를 확인한다.

## 계획 자체 검토

- Spec 1–2 → Tasks 2–3, Spec 3 → Tasks 4–5, Spec 4 → Task 6, Spec 5 → Task 5, Spec 6 → 각 검증 단계 및 Task 7.
- 새 출처의 수명 주기·기존 내보내기·부분 지우기·오래된 후보·중단된 임베딩·외부 전송 분기를 각 소유 Task에 포함했다.
- 아직 실행하지 않은 품질 비교와 설치 앱 검증은 완료로 표시하지 않았다.
