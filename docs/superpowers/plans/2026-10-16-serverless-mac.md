# Mac 내부 실행 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Python·Ollama 서버 없이 실행되는 Mac 앱을 만들고 기존 기록·원음·필기 초안을 이어 사용한다.

**Architecture:** 기존 React 화면과 Python 도메인 코드를 재사용한다. Swift 앱이 번들 자산·마이크·파일 선택을 제공하고, 단일 Python 작업 엔진과 크기가 제한된 파이프로 통신한다. 설치 모델을 직접 실행할 수 있는지 먼저 검증하고, 검증된 엔진만 새 로컬 provider에 연결한다.

**Tech Stack:** AppKit/WKWebView/AVAudioEngine, React/TypeScript, Python 3.12+, FastAPI의 소켓 없는 ASGI 호출, SQLite, 직접 MLX·llama.cpp 후보, 기존 Whisper/Qwen ASR.

**Spec:** `docs/superpowers/specs/2026-10-16-serverless-mac-design.md`

## Global Constraints

- 기본 실행은 앱 소유 HTTP/WebSocket/TCP/UDP 리스너를 시작하지 않는다.
- 앱 실행에 개발 checkout·별도 Python·Node·컴파일러가 필요하지 않아야 한다.
- 기존 제품 소스·런타임·사용자 보관함에 검증 작업을 쓰지 않는다. 별도 worktree·가상환경·임시 보관함에서 구현한다.
- 기존 가중치를 읽기 전용으로 재사용한다. 새 대형 모델 다운로드·변환 사본은 크기와 조건을 제시한 뒤 사용자 동의를 받는다.
- 모델별 직접 실행 결과를 확인한다. 파일 형식·라이브러리 지원 목록만으로 준비 완료를 표시하지 않는다.
- 기록·원음·전사/메모/필기 버전·자료 연결·미저장 writer journal·복구 사본을 보존한다.
- 녹음 종료 후 전사 기본, 실시간 잠정 인식 10초, 최초 연결 30초 제한, 실제 입력 복귀 후 최대 한 번 자동 복구를 유지한다.
- 기존 전사 우선순위·사용자 적용 재전사 후보·로컬 원문 발췌 요약·외부 API 선택을 유지한다.
- 제품 앱 교체 전에 새 앱의 별도 보관함 검증과 기존 origin 초안 이전을 모두 확인한다.
- 호환성 실패·검증 미완료를 서버 제거 완료로 보고하지 않는다. 기존 앱을 실패 fallback으로 자동 실행하지 않는다.

## Review Focus

- EOF나 강제 종료가 PCM 저장 도중 발생했을 때 ACK한 프레임과 저장한 원음이 일치해야 한다(Task 2, 4).
- 긴 WAV의 Range 취소·seek가 전체 파일 메모리 적재나 고아 요청을 만들지 않아야 한다(Task 3).
- 다른 창의 미저장 journal과 dirty=false 행의 backup도 이전되며 같은 과목 ID를 가진 다른 보관함에 섞이지 않아야 한다(Task 6).
- 이전 모델과 새 엔진의 모델명이 같아도 입력 template·양자화·embedding format이 다르면 같은 작업/색인으로 취급하지 않아야 한다(Task 1, 5).
- 새 앱 권한 허용이 늦게 도착하거나 잠자기 뒤 입력 장치가 바뀌어도 취소한 녹음을 되살리거나 빈 원음을 이어 붙이지 않아야 한다(Task 4, 7).

## Task 1: 설치 모델 직접 실행 관문

**Files:** Create `lecture_study/model_assets.py`, `tests/test_model_assets.py`, `scripts/probe_direct_models.py`, `docs/direct-model-compatibility.md`. 실험 결과·라이브러리는 `.local-state/serverless-mac-20261016/`에 두고 사용자 음성·가중치를 커밋하지 않는다.

**Interfaces:** `installed_asset(models_dir: Path, model: str) -> dict`는 검증한 manifest 식별자·파일 목록·파일명·형식을 반환한다. `prepare_mlx_view(asset: dict, destination: Path) -> Path`는 검증 전용 메타데이터와 읽기 전용 가중치 참조를 구성하며 기존 blob을 변경하지 않는다. 호환성 보고서는 모델별 text/JSON/vision/embedding 성공 여부와 엔진 버전을 명시한다.

- [ ] 먼저 synthetic manifest의 정상 파일 재사용, 잘못된 digest/크기/경로, 누락 blob, 중복 tensor key 거절 검사를 작성한다. `test_model_assets`는 원래 파일의 bytes·mtime 불변을 확인한다.
- [ ] `.venv/bin/python -m unittest tests.test_model_assets -v` 실행: 새 모듈 부재로 실패를 확인한다.
- [ ] `model_assets.py`에 manifest·header의 크기 제한, SHA256/파일 크기 대조, 경로 제한을 구현한다. 가중치 파일 전체를 JSON이나 메모리로 읽지 않는다.
- [ ] 같은 명령을 실행해 모든 synthetic 검사가 통과해야 한다.
- [ ] 기존 Qwen3.5 4B를 직접 로드해 한국어 text, 구조화 JSON, 이미지 입력, 출력 제한·취소를 시험한다. EmbeddingGemma는 arm64 직접 엔진으로 query/document prefix, 차원·유한 값·정규화·검색 순위를 확인한다. Gemma4 등 설치 모델은 각각 기록한다.
- [ ] 실제 결과에 따라 라이브러리 버전·weight digest·template·지원 기능을 고정한다. 실패 시 traceback과 최소 재현을 보존하고, 해당 모델을 usable로 등록하지 않는다. 모델 교체가 필요한 경우 의존 단계는 보류하고 독립된 통신·보존 작업만 진행한다.
- [ ] `git add lecture_study/model_assets.py tests/test_model_assets.py scripts/probe_direct_models.py docs/direct-model-compatibility.md` 후 `git commit -m "feat: verify installed assets for direct model execution"`.

## Task 2: 단일 ASGI 작업 엔진과 파이프 프로토콜

**Files:** Create `lecture_study/native_worker.py`, `tests/test_native_worker.py`; modify `lecture_study/config.py`, `server.py`, `process_owner.py`.

**Interfaces:** `AppConfig.embedded: bool = False`는 앱 내부 경로에서만 managed Ollama 자동 시작을 금지한다. `serve(config, reader, writer)`는 한 lifespan을 유지한다. 프레임은 4-byte big endian header length + UTF-8 JSON header + 별도 body이며 header에 `version=1`, `id`, `op`, `body_length`가 있다. header 64KiB, JSON 요청 10MiB, binary chunk 256KiB, 동시에 32개 요청을 상한으로 둔다. `http`/`cancel`/`audio_open`/`audio_packet`/`audio_close`/`shutdown`만 허용한다.

- [ ] `test_native_worker`에 분할 pipe read, 잘못된 length/op/id, 동시 요청 분리, 409/422 보존, streaming 취소, EOF 후 DB 락 해제·녹음 복구 검사를 작성한다. 테스트는 실제 subprocess와 임시 보관함을 사용한다.
- [ ] `.venv/bin/python -m unittest tests.test_native_worker -v`의 실패를 확인한다.
- [ ] 기존 ASGI 핸들러를 재사용한다. 내부 자격 정보는 worker가 주입하며 UI가 Host/Cookie/CSRF를 지정하지 못한다. 요청 경로는 `/api/`로 제한하고 임의 URL·파일 경로·bootstrap 요청을 거절한다. body는 ACK된 chunk 단위로 전송하고 취소 시 ASGI task를 정리한다.
- [ ] 같은 검사와 `tests.test_core tests.test_audio_socket` 실행: 소켓 bind 없이 CRUD/녹음 ACK/수명 검사가 통과해야 한다.
- [ ] `git commit -am "feat: run application worker through bounded pipes"` (새 파일을 먼저 명시적으로 add).

## Task 3: Swift 화면 연결·자료·내보내기

**Files:** Create `macos/WorkerBridge.swift`, `macos/AppResources.swift`; modify `macos/Solasi.swift`, `frontend/src/api.ts`, `PageNotebook.tsx`, `MaterialLibrary.tsx`, `SourceLink.tsx`, `TranscriptView.tsx`, `lecture_study/transcription.py`, `scripts/install_macos_app.py`; add bridge/resource contract tests.

**Interfaces:** `WorkerBridge.request(header: [String: Any], body: Data, completion: ...)`는 Task 2의 id/op 프레임을 사용한다. `solasi-app://app/`는 번들 화면과 제한된 `/api/` 자산을 제공한다. `window.webkit.messageHandlers.solasi.postMessage`는 신뢰한 main frame의 JSON 요청만 받는다. `solasi://audio/<vault>/<audio-id>?start_ms=...&end_ms=...`는 재생만 허용한다.

- [ ] 실패 검사: 외부 frame·경로 탈출·잘못된 ID 거절, 206/HEAD/Range 취소, export 취소·동명 파일 보존, 선택 음성 seek, 새 창 자료 보기.
- [ ] 기존 HTTP 기본 구현과 native bridge를 `api()` 한 곳에서 분기한다. File picker는 NSOpenPanel에서 받은 경로만 worker에 전달하고 NSSavePanel/임시 파일/exclusive rename을 재사용한다. 긴 자산은 JSON/base64 전체 전달하지 않는다.
- [ ] `npm run check && npm test && npm run build` 및 Swift 컴파일/fixture: 오류 없이 통과해야 한다. 별도 앱에서 PDF와 긴 WAV seek를 실제 실행한다. WKWebView 미디어 제약이 있으면 네이티브 AVPlayer 재생으로 동일 범위를 처리한다.
- [ ] `git commit -am "feat: connect bundled Mac interface to internal worker"`.

## Task 4: 네이티브 마이크와 저장 ACK

**Files:** Create `macos/AudioCapture.swift`; modify `macos/Solasi.swift`, `frontend/src/recording-capture.ts`, `lecture_study/native_worker.py`; add native audio fixture and worker audio tests.

**Interfaces:** native `startCapture(recordingID: String, requestID: String)`, `stopCapture(requestID: String)`; UI receives recording state/input level/saved frame count/error. Native queue sends existing `<QQI>` seq/first_frame/frame_count followed by mono PCM16 via Task 2 `audio_packet`; worker returns ACK only after existing append_pcm succeeds.

- [ ] 실패 검사: 30초 연결 timeout 후 늦은 권한 응답, 입력 장치 변경, 중복/순서 위반 packet, bounded queue 초과, stop 중 pending ACK, EOF 복구.
- [ ] AVAudioEngine tap은 실제 rate의 입력만 직렬 큐에 넘긴다. callback에서 파일·DB·모델 호출하지 않는다. 중단은 기존 원음을 종료하고 실제 새 입력 프레임이 온 경우에만 한 번 새 구간을 연다.
- [ ] worker audio 검사와 native fixture 통과 후 실제 마이크를 시작·중지한다. 사용자의 실제 절전·복귀 결과는 모의 이벤트와 구분하여 기록한다.
- [ ] `git commit -am "feat: capture Mac audio without browser sockets"`.

## Task 5: 검증된 직접 모델 provider와 새 검색 색인

**Files:** Create `lecture_study/direct_models.py`, `lecture_study/model_worker.py`, `tests/test_direct_models.py`; modify `local_models.py`, `providers.py`, `retrieval.py`, `token_budget.py`, `models.py`, `server.py`, `answers.py`, `jobs.py`, runtime/settings UI and tests.

**Interfaces:** provider `local`는 직접 엔진을 사용한다. 기존 `ollama` 값은 과거 snapshot으로 읽을 수 있다. `DirectModels.status(model)`, `generate(config,messages,images,schema,output_limit)`, `embed(texts,query,title)`, `stop()`은 Task 1에서 검증한 기능만 제공한다. 모델 결과 digest에는 weight/template/engine 식별자를 포함한다.

- [ ] 실패 검사: 미검증 모델 선택 거절, 출력 길이 종료와 JSON 오류, 취소 후 자식 회수, 전사 적체 중 대기, API 요청 독립, 과거 미완료 snapshot 엔진 변경 거절, 다른 embedding format 혼합 거절.
- [ ] Task 1 결과를 사용해 직접 실행 subprocess를 연결한다. Ollama와 모델 HTTP 요청은 embedded 경로에서 제거한다. 모든 로컬 provider 조건·SQL·tokenizer·후보 추출·요약 budget을 같은 판별로 갱신한다.
- [ ] 기존 설치 catalog 다운로드는 고정 manifest와 blob을 직접 받고 digest·크기 확인 후 원자적으로 완료한다. 새 weight 동의와 사용자가 선택한 API 정책을 유지한다.
- [ ] 새 engine/template/pooling/dimension별 embedding set을 만들어 완료한 뒤 교체한다. 기존 set과 결과를 삭제하지 않는다.
- [ ] `.venv/bin/python -m unittest tests.test_direct_models tests.test_providers tests.test_retrieval -v` 및 Task 1 실제 모델 probe를 실행해 결과가 유효해야 한다. 같은 입력의 cold/warm 시간과 peak RAM을 기록한다.
- [ ] `git commit -am "feat: replace managed model servers with direct workers"`.

## Task 6: 초안 이전과 자체 포함 앱 패키지

**Files:** Create `lecture_study/native_drafts.py`, `frontend/src/draft-migration.ts`, `scripts/freeze_macos_engine.py`; modify `frontend/src/page-drafts.ts`, `theme.ts`, `macos/Solasi.swift`, `scripts/install_macos_app.py`, worker subprocess entrypoints; add migration/package tests.

**Interfaces:** versioned export `{version:1, vault_id, origin, drafts, theme}`는 IndexedDB `drafts` store의 모든 raw row를 보존한다. native draft command는 vault의 SQLite 테이블에 main/journal을 한 transaction으로 commit한 후 완료하며 key와 writer suffix를 그대로 보존한다. import는 hash/count/keys 비교를 완료해야 성공이다.

- [ ] 실패 검사: 여러 writer journal·dirty=false backup·빈/손상 export·동일 key 다른 내용·다른 vault·충돌 재시도·write 실패 중 기존 사본 보존.
- [ ] 기존 origin의 모든 창에서 입력을 잠시 멈추고 storage queue를 flush한 후 전체 export를 chunk로 별도 파일에 저장·검증한다. 메모리에만 있는 일반 노트·대본 편집도 별도 보존한다. 새 앱에서 import·restart·복구·409 선택 흐름을 확인한다. 기존 IndexedDB를 삭제하지 않는다.
- [ ] PyInstaller onedir로 Python과 필요한 extension/MLX Metal/tokenizer/도메인 자산을 bundle한다. material/Qwen/model subprocess는 frozen executable의 명시한 entrypoint를 사용한다. 실행 중 pip/npm/Swift build를 호출하지 않는다.
- [ ] 패키지 검사: 외부 checkout/Python 경로가 없어도 별도 보관함에서 실행되고 코드·런타임 manifest/hash가 일치해야 한다. 라이선스 파일을 포함한다. 대형 모델 복사 없이 기존 사용자 위치를 참조한다.
- [ ] 기존 앱·data·원음 hash·draft export를 보존한 채 새 앱을 교체하고 재실행한다. 어느 검사가 실패하면 현재 앱을 유지한다.
- [ ] `git commit -am "feat: preserve native drafts and bundle Mac runtime"`.

## Task 7: 전체 흐름·수명·성능 검증 및 통합

**Files:** update `docs/mac-internal-runtime-validation.md`, this plan, relevant verification JSON (private 음성·전사 제외), README/사용 설명서.

- [ ] 기존 backend 전체 검사, frontend check/test/build, native fixture/build를 실행한다. 새 변경으로 발생한 실패를 해결한다.
- [ ] 별도 앱으로 과목→자료→필기→마이크→전사→선택 재생/수정→요약/검색→내보내기를 실행한다. 기록·원음·페이지 버전·초안의 전후 hash/count를 비교한다.
- [ ] 기존 포트 점유 상태에서 기동하고 app-owned process tree의 TCP/UDP listener 0을 확인한다. 외부 API outbound와 구분한다.
- [ ] 긴 실제 한국어 음성으로 동시 처리, 장시간 실제 마이크·절전/복귀·강제 종료·재시작을 확인한다. 단어 정확도와 요약 품질은 통신 변경만으로 개선됐다고 추정하지 않는다.
- [ ] 같은 weight/input/output limit의 cold/warm 시작·메모리·전사/생성 완료시간을 비교한다. 엔진 변경과 서버 통신 제거 효과를 구분한다.
- [ ] fresh reviewer에게 전체 diff와 미검증 경계를 검토받고 중요한 오류를 수정·재검사한다. 완료한 범위만 commit/push하며 미완료 기능은 분명히 기록한다.

## 실행 기록 위치

재개용 상태는 `.local-state/serverless-mac-20261016/TASK_STATE.md`, task별 검증은 `.superpowers/sdd/2026-10-16-serverless-mac/progress.md`에 기록한다. 현재 앱은 Task 6 관문 전까지 교체하지 않는다. 사용자가 설계대로 계획 작성과 진행을 함께 지시했으므로 같은 범위의 일반 구현 승인을 재요청하지 않는다.
