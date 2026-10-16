# Mac 내부 실행 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Python·Ollama 서버 없이 실행되는 Mac 앱을 만들고 기존 기록·원음·필기 초안을 이어 사용한다.

**Architecture:** 기존 React 화면과 Python 도메인 코드를 재사용한다. Swift 앱이 번들 자산·마이크·파일 선택을 제공하고, 단일 Python 작업 엔진과 크기가 제한된 파이프로 통신한다. 설치 모델을 직접 실행할 수 있는지 먼저 검증하고, 검증된 엔진만 새 로컬 provider에 연결한다.

**Tech Stack:** AppKit/WKWebView/AVAudioEngine, React/TypeScript, Python 3.12+, FastAPI의 소켓 없는 ASGI 호출, SQLite, 직접 MLX·llama.cpp 후보, 기존 Whisper/Qwen ASR.

**Spec:** `docs/superpowers/specs/2026-10-16-serverless-mac-design.md`

## 진행 상태 — 2026-10-16 정리 시점

아래 표는 당시 기록이다. 장시간·절전·강제 종료·후속 제품 설치의 최신 결과는 [2026-10-17 후속 검증](../../mac-native-resilience-validation.md)과 이 문서 마지막 기록을 따른다.

`[x]`는 아래에 적은 구현 또는 검사 범위만 완료됐다는 뜻이다. 제품 전환 전체의 완료를 뜻하지 않는다. `[ ]`는 남은 실행이며, `[이력 미확인]`은 과거 실행 여부를 현재 기록으로 입증하지 못한 항목이다.

| 범위 | 현재 확인한 결과 | 남은 관문 |
| --- | --- | --- |
| Tasks 1–2 | 설치 모델 직접 실행·bounded pipe 구현 및 검사 | 미확인 최초 RED 이력을 완료로 소급 표시하지 않음 |
| Tasks 3–4 | 네이티브 화면/오디오, 합성 10분 PCM, 실제 13초 마이크·선택 재생·메모 저장·재시작 | 전체 실패 UI 흐름, 장시간 입력·물리 절전/복귀 |
| Task 5 | 직접 provider·별도 임베딩 색인 코드, 실제 frozen 모델·짧은 음성→요약 | 기존 앱 대비 장시간 품질·cold/warm·메모리 비교 |
| Task 6 | 실제 raw 초안 import·제품 앱 교체·실제 PDF/메모 표시·39개 테이블 및 원음 8개 보존 | 실제 저장 실패/충돌·강제 종료 흐름 |
| Task 7 | 회귀 검사, 제품 앱 포트 독립 실행·내보내기·종료, fresh migration 검토, 구현 커밋·푸시 | 장시간·물리 절전·동시 부하와 성능 비교 |

최신 통합 기록 기준 백엔드 **총 440개 중 435개 통과·5개 선택적 실제 모델 검사 skip**, 프런트엔드 **70개 통과**, TypeScript·Vite 빌드 통과다. 선택적 skip과 별도로 frozen v3의 실제 모델 호출 8건 및 v5의 실제 한국어 음성→Whisper→Qwen 원문 발췌 요약을 확인했다. 이전 SDD/TASK_STATE에 남은 388·436개 수치와 초기 Gemma 실패는 이전 시점 기록이다.

Tasks 1–6의 구현은 예정된 개별 커밋 대신 `69f82ff`에 통합했고, 검증 문서는 `593c604`에 기록했다. 두 커밋은 `origin/codex/serverless-mac`에 푸시했다. 아래에서 아직 확인하지 않은 물리 시험과 전체 UI 실패 분기는 계속 미완료로 남긴다.

**근거 문서:** [통합 실행 기록](../../mac-internal-runtime-validation.md), [직접 Gemma·frozen 모델 실행](../../direct-gemma-models.md), [직접 임베딩](../../embedding-worker.md), [Swift 화면·오디오 fixture](../../native-ui-bridge-validation.md), [이전 초안 보존](../../legacy-draft-migration.md). 실제 앱 설치 상태는 통합 기록의 마지막 설치 결과로 다시 확인한다.

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

**Files:** `lecture_study/model_assets.py`, `tests/test_model_assets.py`, `scripts/probe_direct_models.py`, `lecture_study/mlx_direct.py`, `gemma_direct.py`, `macos/EmbeddingWorker.cpp`. 호환성 결과는 실제 작성된 `docs/direct-gemma-models.md`, `docs/embedding-worker.md`, `docs/mac-internal-runtime-validation.md`에 기록했다. 처음 예정한 `docs/direct-model-compatibility.md`는 생성하지 않았다. 실험 결과·라이브러리는 `.local-state/serverless-mac-20261016/`에 두고 사용자 음성·가중치를 커밋하지 않는다.

**Interfaces:** `installed_asset(models_dir: Path, model: str) -> dict`는 검증한 manifest 식별자·파일 목록·파일명·형식을 반환한다. `prepare_mlx_view(asset: dict, destination: Path) -> Path`는 검증 전용 메타데이터와 읽기 전용 가중치 참조를 구성하며 기존 blob을 변경하지 않는다. 호환성 보고서는 모델별 text/JSON/vision/embedding 성공 여부와 엔진 버전을 명시한다.

- [x] `test_model_assets`에 원본 bytes·mtime 보존, digest/크기/경로/누락 blob/중복 tensor key/과대 header 거절, 중단된 view의 재시도·배타적 publish 검사를 작성하고 현재 회귀 검사에서 통과했다.
- [x] manifest·header의 크기 제한, SHA256/파일 크기·경로 대조와 원본 가중치의 읽기 전용 재사용을 구현했다. 검증 view의 불완전 캐시를 보존하고 새 staging에서 재생성하도록 보완했다.
- [x] Qwen3.5 4B의 실제 한국어·JSON·이미지·출력 제한·취소를 확인했다. Gemma4 E2B/12B도 공식 template·양자화 매핑 보완 후 한국어·JSON·이미지·한도·취소를 확인했다. 초기 Gemma 반복 출력 실패를 그대로 usable로 등록하지 않았다.
- [x] 기본 EmbeddingGemma의 직접 arm64 엔진에서 query/document prefix, 768차원·유한 값·L2 정규화와 작은 한국어 검색 순위 fixture를 확인했다. EmbeddingGemma 2는 별도 호환성 probe만 통과했으며 제품 provider에는 등록하지 않았다.
- [x] engine·template·weight digest·지원 기능을 고정했다. frozen v3에서 Qwen/E2B/12B 한국어·JSON, 기본 임베딩, 실제 FLEURS Qwen ASR 등 8건을 다시 실행했고 원본 모델 해시가 유지됐다.
- [x] 예정 제목 `feat: verify installed assets for direct model execution`의 구현은 개별 커밋 대신 통합 커밋 `69f82ff`로 보존·푸시했다.

**[이력 미확인]** `test_model_assets`의 최초 모듈 부재 RED 실행 기록은 현재 근거에서 확인하지 못했다. 현재 검사 통과와 구분한다. 별도 Gemma RED 로그(`embedding-probe/gemma-tests-red.log`)는 보존돼 있다. 이 결과만으로 원래 계획의 모든 test-first 순서를 완료했다고 표시하지 않는다.

## Task 2: 단일 ASGI 작업 엔진과 파이프 프로토콜

**Files:** Create `lecture_study/native_worker.py`, `tests/test_native_worker.py`; modify `lecture_study/config.py`, `server.py`, `process_owner.py`.

**Interfaces:** `AppConfig.embedded: bool = False`는 앱 내부 경로에서만 managed Ollama 자동 시작을 금지한다. `serve(config, reader, writer)`는 한 lifespan을 유지한다. 프레임은 4-byte big endian header length + UTF-8 JSON header + 별도 body이며 header에 `version=1`, `id`, `op`, `body_length`가 있다. header 64KiB, JSON 요청 10MiB, binary chunk 256KiB, 동시에 32개 요청을 상한으로 둔다. `http`/`ack`/`cancel`/`audio_open`/`audio_packet`/`audio_close`/`shutdown`만 허용한다. 응답은 `response_start → body(sequence) → complete`이며 body는 별도 `ack(target,sequence)`를 30초 안에 받은 뒤 다음 조각을 보낸다.

- [x] 분할 read·잘못된 length/op/id·동시 ID·409/422·stream 취소·ACK timeout·요청 상한·PCM 저장 ACK·EOF/종료 후 보관함 락 해제를 실제 subprocess와 임시 보관함에서 검사했다. `test_native_worker` 14개가 현재 전체 회귀 검사에 포함된다.
- [x] 기존 ASGI handler와 lifespan을 재사용하고 worker가 내부 자격 정보를 주입한다. `/api/` 경로·헤더·파일 선택 범위를 제한하며 bootstrap/임의 URL/외부 경로 주입을 거절한다.
- [x] body별 ACK·취소·EOF 정리와 종료 기한을 구현했다. Swift stdin 정체와 TERM 무시를 다루는 소유 process group 회수도 별도 fixture로 보완했다.
- [x] 현재 backend 전체 검사에 `tests.test_core`, `tests.test_audio_socket`, worker 검사가 함께 통과했다. frozen 실행의 소켓 표본과 자식 회수 결과는 Task 7에 별도로 기록한다.
- [x] 예정 제목 `feat: run application worker through bounded pipes`의 구현은 개별 커밋 대신 통합 커밋 `69f82ff`로 보존·푸시했다.

**[이력 미확인]** 최초 `test_native_worker` RED 실행 여부는 별도 실행 로그가 확인되기 전까지 미확인으로 둔다. 현재 성공 결과로 과거 실행 순서를 소급 확정하지 않는다.

## Task 3: Swift 화면 연결·자료·내보내기

**Files:** `macos/WorkerBridge.swift`, `AppResources.swift`, `AudioPlayback.swift`; `macos/Solasi.swift`, `frontend/src/api.ts`, `PageNotebook.tsx`, `MaterialView.tsx`, `SourceLink.tsx`, `TranscriptView.tsx`, `PlaybackAudio.tsx`, `NativePlayback.tsx`, `lecture_study/transcription.py`, `scripts/install_macos_app.py`; bridge/resource/frontend contract tests.

**Interfaces:** `WorkerBridge.request(header: [String: Any], body: Data, completion: ...)`는 Task 2의 id/op 프레임을 사용한다. `solasi-app://app/`는 번들 화면과 제한된 `/api/` 자산을 제공한다. `window.webkit.messageHandlers.solasi.postMessage`는 신뢰한 main frame의 JSON 요청만 받는다. `solasi://audio/<vault>/<audio-id>?start_ms=...&end_ms=...`는 재생만 허용한다.

- [x] 신뢰한 main frame·API/resource 경로·보관함/원음 ID·Range를 제한하고, export 취소·동명 파일 보존·배타적 rename을 구현·fixture 검사했다. 파일 선택 경로는 NSOpenPanel에서만 만든다.
- [x] `api()`에서 개발 HTTP와 native bridge를 분기한다. 번들 화면·자료는 custom scheme, 긴 원음은 AVPlayer의 Range loader로 전달하며 전체 파일을 JSON/base64로 적재하지 않는다.
- [x] 실제 WKWebView에서 번들 ES module·secure context·crypto API를 확인했다. custom scheme HTML audio의 `readyState=0` 정체를 재현한 후 AVPlayer로 600초 합성 WAV를 읽고 599초 seek를 확인했다.
- [x] Swift 앱·fixture 컴파일과 프런트엔드 TypeScript·70개 검사·Vite 빌드가 통과했다. native 원음 링크의 UI 준비 대기와 재생 자원 회수 수정도 포함한다.
- [x] 최종 앱에서 기존 PDF·메모·필기 표시, 클릭 선택 재생, NSSavePanel의 Markdown 내보내기를 직접 확인했다.
- [ ] 새 창·NSOpenPanel·드래그 선택·대본 수정 및 내보내기 전체 UI 흐름을 확인한다. API·fixture 성공으로 이 항목을 대신하지 않는다.
- [x] 예정 제목 `feat: connect bundled Mac interface to internal worker`의 구현은 개별 커밋 대신 통합 커밋 `69f82ff`로 보존·푸시했다.

**[이력 미확인]** 모든 브리지 실패 검사의 최초 RED 실행 순서는 확인되지 않았다. 작은 ready 프레임 대기와 custom scheme 미디어 실패는 실제 재현 후 수정한 기록이 있다.

## Task 4: 네이티브 마이크와 저장 ACK

**Files:** Create `macos/AudioCapture.swift`; modify `macos/Solasi.swift`, `frontend/src/recording-capture.ts`, `lecture_study/native_worker.py`; add native audio fixture and worker audio tests.

**Interfaces:** native `startCapture(recordingID: String, requestID: String)`, `stopCapture(requestID: String)`; UI receives recording state/input level/saved frame count/error. Native queue sends existing `<QQI>` seq/first_frame/frame_count followed by mono PCM16 via Task 2 `audio_packet`; worker returns ACK only after existing append_pcm succeeds.

- [x] AVAudioEngine 입력 복사·직렬 처리·mono PCM16 변환·bounded queue·저장 ACK·30초 최초 연결 제한·종료 시 pending 입력 전달을 구현했다. tap callback에서 파일·DB·모델을 호출하지 않는다.
- [x] native fixture에서 정상 무음·clipping·sampleTime gap·시간 역행 거절·취소한 권한 응답 거절·실제 새 입력에 한 번만 복구하는 상태 정책을 검사했다. worker의 PCM ACK·EOF·재시작 검사가 통과했다.
- [x] 실제 Swift→Python 파이프로 600개 합성 패킷을 가속 전달해 600 ACK, 4,800,000 PCM 프레임, 9,600,044바이트 WAV와 정상 종료를 확인했다. 실제 10분 마이크 녹음 기록은 아니다.
- [x] 새 내장 앱에서 실제 마이크 시작·13초 입력·중지·후처리·선택 재생을 확인했다. 48kHz·624,000프레임과 저장 WAV가 일치하고 정상 종료·재시작 후 해시가 같았다.
- [x] 실제 권한 응답 지연 시30초 취소·늦은 응답의 자동 시작 차단과30분 이상 실제 마이크 입력을 확인했다. [후속 검증](../../mac-native-resilience-validation.md).
- [x] 새 내장 앱의 물리 잠자기/복귀와 강제 종료 후 원음·필기·dirty초안 복구를 확인했다. [후속 검증](../../mac-native-resilience-validation.md).
- [ ] 실제 장치 변경과 실제 녹음 종료 중 ACK를 의도적으로 지연시키는 검사는 남아 있다. ACK 지연·늦은 콜백의 코드 fixture 검증과 구분한다.
- [x] 예정 제목 `feat: capture Mac audio without browser sockets`의 구현은 개별 커밋 대신 통합 커밋 `69f82ff`로 보존·푸시했다.

**[이력 미확인]** 최초 RED 및 모든 queue/장치 변경 실패 분기의 개별 실행 로그는 확인되지 않았다. 정책 fixture 통과를 macOS 권한·물리 입력 검증 완료로 확대하지 않는다.

## Task 5: 검증된 직접 모델 provider와 새 검색 색인

**Files:** Create `lecture_study/direct_models.py`, `lecture_study/model_worker.py`, `tests/test_direct_models.py`; modify `local_models.py`, `providers.py`, `retrieval.py`, `token_budget.py`, `models.py`, `server.py`, `answers.py`, `jobs.py`, runtime/settings UI and tests.

**Interfaces:** provider `local`는 직접 엔진을 사용한다. 기존 `ollama` 값은 과거 snapshot으로 읽을 수 있다. `DirectModels.status(model)`, `generate(config,messages,images,schema,output_limit)`, `embed(texts,query,title)`, `stop()`은 Task 1에서 검증한 기능만 제공한다. 모델 결과 digest에는 weight/template/engine 식별자를 포함한다.

- [x] 검증된 direct subprocess를 `local` provider에 연결하고 embedded 경로의 Ollama·모델 HTTP 요청을 제거했다. generation/embedding 입장 제어, tokenizer·후보 추출·요약 budget·과거 snapshot 구분을 갱신했다.
- [x] 미준비 모델·잘못된 출력·취소/자식 회수·전사 적체 대기·과거 Ollama snapshot 유지·embedding format 혼합 거절·불완전 model view 복구 검사가 통과했다.
- [x] 고정 manifest/blob의 직접 다운로드, digest·크기 대조, 실패 시 기존 manifest 보존을 구현·검사했다. 기존 가중치로 실제 실행을 검증했으며 대형 모델을 다시 다운로드한 검사는 아니다.
- [x] engine/template/pooling/dimension을 구분하는 새 embedding set 생성·교체와 기존 set 보존을 구현하고 회귀 검사했다. 실제 사용자 과목 전체의 색인 재생성·검색 UI는 Task 7에서 확인한다.
- [x] direct/provider/retrieval 회귀 검사와 실제 모델 probe가 통과했다. frozen v5의 실제 FLEURS 15.78초 입력에서 기본 Whisper 전사 10.80초, 기본 Qwen 원문 발췌 요약 15.74초가 완료됐다. 한 클립 결과이며 장기 품질·속도 개선의 근거로 확대하지 않는다.
- [ ] 같은 weight/input/output limit의 기존 앱 대비 cold/warm 시간·peak RAM·긴 전사/생성 동시 실행을 비교한다. 현재 단일 실행의 시간·메모리 관찰과 구분한다.
- [x] 예정 제목 `feat: replace managed model servers with direct workers`의 구현은 개별 커밋 대신 통합 커밋 `69f82ff`로 보존·푸시했다.

**[이력 미확인]** Task 5 모든 검사에 대한 최초 RED 실행 순서는 확인되지 않았다. 현재 provider 계약 검사와 실제 모델 결과를 각각 근거로 사용한다.

## Task 6: 초안 이전과 자체 포함 앱 패키지

**Files:** `lecture_study/native_drafts.py`, `legacy_drafts.py`, `frontend/src/draft-migration.ts`, `native-lifecycle.ts`, `scripts/freeze_macos_engine.py`, `export_legacy_drafts.py`, `import_legacy_drafts.py`, `macos/LegacyDraftExport.swift`; `frontend/src/page-drafts.ts`, `theme.ts`, `macos/Solasi.swift`, `scripts/install_macos_app.py`, worker subprocess entrypoints; migration/package tests.

**Interfaces:** native draft command는 vault SQLite의 main/journal을 한 transaction으로 commit한 뒤 완료하며 key와 writer suffix를 보존한다. legacy 이전은 전체 배열 대신 `drafts.jsonl`과 `manifest.json`을 사용한다. manifest는 `version:1`, `format`, `vault_id`, `origin`, 실제 bundle ID, 원래 theme, 행별 offset/bytes/key/SHA256과 전체 해시를 가진다. 정상적인 `undefined`는 `undefined_paths`와 별도 SHA256으로 보존하며 가져오기에서도 대조한다. 라이브 편집 메모리 보존 여부는 이 파일만으로 판정하지 않는다.

- [x] native SQLite main/journal·backup, 중단된 upload, 다른 vault, 충돌 별도 보존·재시도·idempotence·transaction rollback을 구현·검사했다. sidecar 경로만 변조한 경우도 import 전 거절하도록 해시 검증을 추가했다.
- [x] 서버 없는 별도 WK helper로 raw 초안 행을 chunk 내보내기하고 두 번 대조한다. 격리 fixture의 5행/72,352,115바이트, 일반 `backup:undefined`·중첩 객체/배열의 정확한 복원, 실패 시 원본 유지, 동명 결과·동시 실행 거절을 확인했다.
- [x] 사용자가 기존 입력 저장·앱 종료를 확인한 뒤 실제 기존 origin에서 **1행/660바이트** raw 초안을 내보냈다. 기존 앱·보관함·원음·WebKit의 종료 후 사본과 해시를 보존했다. 사용자 확인과 raw 저장소 export를 실제 React 메모리 추출 완료로 표현하지 않는다.
- [x] 복사한 보관함에서 실제 export 가져오기·재시작·원문 대조를 확인했다. 기존 IndexedDB는 삭제하지 않았다. 실제 사용자 보관함의 가져오기·대조도 아래 단계에서 완료했다.
- [x] PyInstaller onedir와 네이티브 도우미·MLX/Metal/tokenizer/ASR/FFmpeg·라이선스를 번들했다. frozen entrypoint와 receipt 검사, 실행 중 개발 도구 불필요 경로를 구현했다.
- [x] `/private/tmp`·system PATH·외부 Python 환경 제거 조건에서 frozen v1의 PDF/페이지/PCM, v3의 실제 모델 8건, v5의 실제 Whisper→Qwen 요약을 확인했다. v4의 외부 ffprobe 참조 실패를 재현·수정했다. 원본 모델/음성 해시는 유지됐다.
- [x] 최종 v5 엔진 receipt·서명·최소 macOS27.0을 대조하고 제품 앱0.3.0/build10으로 설치했다. launch.json은 기존 data/runtime만 보존한다.
- [ ] 별도 최종 앱에서 페이지 필기·일반 노트·대본의 종료 대기/저장 실패/취소와 재시작 복구·409 선택 UI를 확인한다.
- [x] 실제 보관함의 종료·배타적 잠금을 확인해 raw export1행/660바이트를 가져왔고 원문을 대조했다. 가져오기 전후와 제품 앱 종료 후 기존39개테이블·live원음5개·연결음성3개가 동일했다.
- [x] 백업을 유지한 채 ~/Applications/Solasi.app을 교체·실행했다. 기존 과목·PDF·필기·메모를 확인했고 제품 앱 정상 종료 후 보존 검사를 다시 통과했다.
- [x] 예정 제목 `feat: preserve native drafts and bundle Mac runtime`의 구현은 개별 커밋 대신 통합 커밋 `69f82ff`로 보존·푸시했다.

**[이력 미확인]** 전체 migration/package 검사의 최초 RED 순서는 확인되지 않았다. abandoned upload, receipt 경로 탈출, frozen resource_tracker 종료 정체, ffprobe 외부 의존, undefined sidecar 변조는 재현·수정 기록이 있는 개별 문제다.

## Task 7: 전체 흐름·수명·성능 검증 및 통합

**Files:** update `docs/mac-internal-runtime-validation.md`, this plan, relevant verification JSON (private 음성·전사 제외), README/사용 설명서.

- [x] 현재 통합 기록의 backend 440개(435 통과·5 skip), frontend 70개·TypeScript·Vite 빌드, Swift 컴파일·정책/PCM/종료 fixture가 통과했다. 실제 모델은 Task 1의 별도 실행으로 확인했다.
- [x] 제품 설치에서 Swift빌드·서명검사를 통과했고 백엔드를 재실행해440개 중435개통과·5개skip을 확인했다(23.202초). 프런트엔드와 엔진은 앞서 검사한 v5와 동일하다.
- [x] 기존 과목→PDF·메모 저장→새 회의→마이크→전사→클릭 선택 재생→정상 종료·재시작을 직접 확인했다. 제품 앱의 Markdown 내보내기와 원본 보존도 대조했다.
- [ ] 새 과목·새 파일 연결부터 대본 수정·전체 요약/검색까지 이어지는 남은 UI 흐름을 확인한다.
- [x] isolated frozen 모델 v3에서 130회, v5 음성→요약에서 152회 Internet 소켓 표본이 비어 있었고 정상 종료·잔여 자식 0을 확인했다. 연속 패킷 캡처나 최종 앱 전체 검사로 표현하지 않는다.
- [x] 별도 시험 프로세스가62434포트를 점유한 상태에서 최종 제품 앱을 열었다. 당시 앱·유일한소유엔진의3회표본에서 Internet소켓0개였다. 종료 후 소유프로세스가 남지 않았다.
- [x] 실제14분38초 한국어 음성의 동일 앱 전사·생성 동시 실행과33분33.7초 실제 마이크·물리 절전22초·강제 종료·재시작·dirty필기 복구를 확인했다. ACK 취소와 수신 버퍼 누적을 수정했으며, 후속UTF-8 후보 경로도 같은 오류 원음으로 검증했다. [상세 근거](../../mac-native-resilience-validation.md). 단어 정확도와 요약 품질 개선으로 확대하지 않는다.
- [ ] 같은 weight/input/output limit의 cold/warm 시작·메모리·전사/생성 완료시간을 비교한다. 엔진 변경과 서버 통신 제거 효과를 구분한다.
- [x] 중간 fresh review에서 초안 임시 전송 누적, 불완전 view cache, receipt 출력 경로 탈출 등을 찾아 수정·회귀 검사했다.
- [x] fresh reviewer가 설치·이전·종료·직접 실행 경로를 재검토했고 새P0/P1은 발견하지 못했다. 별도 reviewer의 원본 보존 대조도 통과했다. 장시간·물리 절전·강제 종료 범위는 제외했다.
- [x] 구현69f82ff·검증문서593c604를 origin/codex/serverless-mac에 푸시했다. 실제 이전·UI 확인의 후속 기록은 통합 검증 문서에서 별도로 갱신한다. 미완료 검증은 위에 명시했다.

## 실행 기록 위치

재개용 상태는 `.local-state/serverless-mac-20261016/TASK_STATE.md`, task별 검증은 `.superpowers/sdd/2026-10-16-serverless-mac/progress.md`에 기록한다. Task 6 검증 관문을 통과한 뒤 실제 앱 교체를 완료했다. 사용자가 설계대로 계획 작성과 진행을 함께 지시했으므로 같은 범위의 일반 구현 승인을 재요청하지 않는다.


## 2026-10-17 최종 후속 기록

제품0.3.2/build12의 앱 내부 실행·기존 과목/PDF/메모/필기 표시와 정상 종료 후43개 테이블·86개 스키마 객체·18개 원본 참조의 동일성을 확인했다. 전체 백엔드452개 중447개 통과·5개 선택 검사skip, 프런트엔드71개·TS/Vite·Swift빌드·엄격한 서명 검사 통과. 새 오류 후보 정책은 사용자 grilling승인 후 구현했으며 원래 전사·오류 이력과 사용자의 적용 결정을 보존한다.

이전 서버 앱과의 cold/warm 동등조건 비교 및 위에 별도로 남긴 전체UI·타기기 과제는 수행 범위를 확대해 통과로 표시하지 않는다. 현재 요청의 장시간 녹음·복구·동시 실행과 제품 데이터 보존 관문은 완료했다.
