# Verification

## 2026-10-13: sessions and referenced materials

- Environment: Apple M4,16GiB,macOS27.0.1; Python3.12.14,FastAPI0.143.0,LiteParse2.16.0,React19.3.0,TypeScript7.0.2,Vite8.3.4.
- A1: Python3/3,Node1/1,TypeScript/build passed; browser course/session creation and restart persisted data. Host/Origin/cookie/CSRF regressions passed.
- A2: PDF/PNG/UTF-8 TXT parsed in isolated native workers. Three-page PDF preserved pages1/2/3,point bbox,embedded raster metadata and PNG page render. Partial fixture retained pages1/3 and missingpage2. Broken PDF retained original and failedjob state.
- File access: macOS native selector was opened from the browser and /private/tmp/lecture-study-check.pdf selected. The app directory contained extraction.json and a requested pagePNG, no original copy. Paths were supplied by the native selector; arbitrary-path/upload API requests were rejected.
- Browser: selected3쪽,highlighted the source text bbox,saved a Korean note,and reloaded the page to reopen persisted data. DOM image478x637.453px and overlay left39.828/top52.203/width319.516/height14.227px matched600x800point source ratios. Screen (로컬 검증 자료·공개본 미포함).
- Cache/version tests: source modification/missingfile returned visible states; re-extraction retained previous text snapshots. Oversized cache entries were served and removed without touching the external original.
- Korean OCR diagnostic: directly rendered3-line PNG with AppleSDGothicNeo54px. kor+eng completed with text,bbox,confidence, but reading order split the first two lines. The expected full first phrase assertion failed; this is a quality defect under investigation, not a successful accuracy check.
- No user-provided PDF/audio,live microphone,external API call,Windows run,or LLM inference was verified at this stage.

### OCR layout correction

- Direct LiteParse JSON reproduced the app order defect. Nine-option comparison ruled out language order,images flag,and app postprocessing. Markdown uses the official region layout renderer.
- Set output_format=markdown and keep_headers_footers=True; store page.markdown or page.text in the app's own Extraction JSON. The header option is required: default Markdown removed all3page fixture's repeated top lines,leaving only an image placeholder on page1.
- Real generated KoreanPNG now preserves the full expected character sequence when whitespace is ignored. OCR still inserts spaces inside Korean words; original native item boxes can overlap. No guessed text correction or global coordinate sorting was applied.
- Independent native3page contract comparison preserved page numbers/sizes/items/confidence/images/errors. A generated two-column diagnostic read all left text then all right text; table body cell pairs were maintained. Its header row was separated,so complete table semantics remain unverified.
- Python OCR layout regression changed from wrong first phrase to expected Markdown. Total backend12/12,Node1/1 and TypeScript/Vite build passed before A2 completion.

- Interrupted parse restart regression failed with running status,then passed with failed/interrupted state; original links now use inline media viewing rather than automatic download. Final A2 backend12/12,Node1/1,TypeScript/Vite exit0.

## 녹음 (2026-10-13)

사용자 승인 후 로컬 IAB 마이크로 녹음 시작·종료. 도구 왕복 동안 총20.56초,48000Hz,986880frames. WAV와 DB의 sample_rate·frame 수 일치, 누락 없음, UI 대기 복귀. 외부 전송 없음.

WebSocket 인증·소속·잘못된 JSON·중복 패킷·저장 실패와 재시작 복구 테스트 통과. 브라우저 권한 거절 화면은 미확인(컴퓨터 사용 도구가 Codex 네이티브 앱 접근을 거절).

## 전사 (2026-10-13)

준비된 whisper.cpp1.9.5/base 모델 SHA256 검증 후 합성 Yuna 한국어10.318875초를 실제 처리. 프로세스 종료·JSON offsets ms·출력 WAV 길이 확인. 첫 문장 전문용어의 인식 오류 존재. CPU -ng 기본 beam5/best_of5 후보를 사용하며 다른 장치 성능은 미확인.

IAB에서 native 오디오 선택→원본 참조→확정4문장→첫 문장 사용자 수정→v2와 원래 인식문 보존을 확인. 외부 원본은 /private/tmp/lecture-study-asr-check.wav, 앱 raw 복사0건. 임시 구간은 작업 종료 후 제거. 기존 마이크 원음은 유지됨.

전사 최종/잠정 순서·잔여1초·누락 원음 위치·실패/취소/같은 ID 재시도·재시작 테스트 통과. 라이브 입력과 ASR의 동시 장시간 지연·정확도는 아직 미확인. 외부 오디오 파일은20초 구간으로 처리하며 문장 경계에 걸칠 수 있음.


## 재생·삭제와 공개 사람 음성 (2026-10-13)

- 전사 근거를 열어 원음 1.74초 seek·duration 10.318875초·재생·구간 종료·Escape 닫기를 IAB에서 확인했다. 종료 목표 4.4초에 실제 pause 4.578441초: HTML timeupdate 기반 종료이므로 frame 단위 정확한 편집기가 아니다.
- 자료·전사·노트 탭을 전환해 미저장 노트 유지 확인. 실제 삭제 확인 창을 열고 취소했다. 실제 사용자 검증 자료의 삭제는 수행하지 않았다.
- 별도 임시 fixture에서 세션/원음 삭제 확인·공유 자료 보존·외부 원본 삭제 0건·HTTP Range·삭제 중 ASR 취소·관리 파일 정리 실패와 재시작을 검증했다. 삭제 파일 정리는 DB의 file_cleanup을 통해 재시도한다.
- 공개 사람 음성 5개·50.88초를 두 입력 경로로 검증하고 작은 음량 1개를 실시간 속도 ASGI WebSocket으로 동시 전사했다. [상세 결과와 한계](human-audio-test.md), 결과 JSON (로컬 검증 자료·공개본 미포함).

A5 최종 검증: Python unittest39/39, frontend Node5/5, TypeScript 검사·Vite 빌드·git diff --check 성공. 공개 음성 진단 스크립트도 별도 실행했다. 브라우저의 실제 삭제는 취소했으며 삭제 동작은 임시 API fixture에서 확인했다.


## 세션별 전사 용어 (2026-10-13)

- 고정 명칭 힌트는 일부 고유명사를 복구하지만 관련 없는 단어를 악화시킬 수 있어 전역 자동 삽입을 사용하지 않는다. 이번 세션의 명칭만 사용자가 저장한다.
- 저장·재시작·다른 세션 배제·200 UTF-8 bytes 초과 거절·원음/기존 전사 보존·기록 삭제 시 용어 설정 정리 테스트를 먼저 실패시킨 뒤 구현했다. 사용한 명칭 힌트를 transcript_ranges.prompt에 저장한다.
- IAB에서 검증 수업에 프로세스·스레드를 저장하고 새로고침 후 값을 다시 확인했다. 기존 전사는 변경되지 않았다. 화면 (로컬 검증 자료·공개본 미포함).
- 전체 Python43/43,Node5/5,TypeScript/Vite 통과. 해당 UI 값으로 새 실제 마이크 녹음은 하지 않았다.


## 2026-10-14 전사 품질 우선 비교

[모델 비교·제품 경로·한계](asr-model-comparison.md). 공개 사람 음성 25개에 base/small/Komix/turbo/Qwen을 실제 실행했다. Raon은 GPU 경로·용량·라이선스 조사만 수행했다. 기본 전사는 turbo/native Metal/Silero이며 외부 ASR 전송은 없다. 추가 20개의 full-clip CER 2.96%, 제품 20초 분할은 파일 3.38%/PCM 3.17%로 구분한다.

Python 47/47, Node 5/5, TypeScript/Vite exit0. 실제 turbo의 선행 무음/무음 꼬리/원음 시각/재시도/취소/DB v6→v7 보존 검증. 실제 속도 12.54초 PCM의 51ACK/누락0/종료 후3.37초 done. IAB 준비 상태의 turbo 준비됨과 기존 v2 사용자 수정 전사 보존 확인. 화면 (로컬 검증 자료·공개본 미포함), 제품 파일/PCM (로컬 검증 자료·공개본 미포함), 동시 WebSocket (로컬 검증 자료·공개본 미포함).

실제 방 마이크/겹침 발화/긴 회의/LLM 동시 실행/Windows는 미확인. 20초 경계의 문맥 오류와 남은 고유명사 오류가 있다. Qwen은 한국어 forced alignment 검증 전 제품 엔진으로 연결하지 않았다. B/C의 누적 검색·생성·회의록 기능은 아직 진행 중이다.

## 누적 검색·개념 (2026-10-14)

57 Python tests, 5 frontend tests, TypeScript check and Vite build passed. App schema8 preserves earlier source snapshots and edited transcripts. At port62434, lecture2 retrieved lecture1 note and final transcript; current-only scope excluded lecture1. Alias search returned scoped evidence. A course concept was saved, edited with the same ID to v2 and retained after reload. Source link opened the earlier transcript and audio controls without new microphone capture. Screenshot: `verification/cumulative-concept.jpg`.

Embedding protocol, dimension errors, remote model rejection, context splitting, atomic failed/cancelled rebuild and recording-priority pause are covered by HTTP mocks. No real embedding model was connected yet; its Korean retrieval validation remains pending in B2. Search explicitly shows keyword mode before preparation.

## API·로컬 모델 설정 (2026-10-14)

63 Python tests, TypeScript check and Vite build passed. Mock contracts cover text/images/schema/usage, 401/429/500/timeout/incomplete results, cloud model rejection, no provider switching, secret exclusion from responses/SQLite, sanitized validation errors, unchanged HOME and terminating only the app child. Native macOS keyring backend was confirmed; a unique test-only service value was written/read/deleted, then absence asserted. No actual API key was read or used.

Browser at62434 showed consent-disabled downloads and correct sizes. The app started its own Ollama0.40.3 loopback server with its private model directory, and connection succeeded without pulling any model. Screenshot: `verification/model-settings.jpg`. This is engine readiness, not successful LLM/embedding/image inference. Qwen4B+EmbeddingGemma preparation awaits the user download choice. Official serve still uses normal ~/.ollama identity/server.json as documented in the provider research; app does not inspect or replace these files.

## 근거 고정 질문 (2026-10-14)

70 Python tests, 5 frontend tests, TypeScript and Vite build passed. API mocks verified failure→explicit local retry keeps job ID, one artifact and both provider attempts; repeated stored result GETs generated nothing. Tests include note edits after freeze, invalid IDs/page/time/extra URL, cancelled AI with continued PCM append, conservative budget errors, source excerpt joins, cross-session evidence deletion, and current1000ms cutoff retaining previous10000ms transcript. Latest targeted23 tests passed after error-copy/metadata guards.

Actual browser at62434 loaded schema9, retained both lectures and opened the question view with course scope/input. Screenshot: `verification/question-view.jpg`. Real answer generation while recording remains unrun because model preparation awaits consent. Graceful app shutdown stopped the app-owned Ollama child; scoped process lookup afterward found no such serve command. Standard user's Ollama was not killed or reconfigured.

## 선택적 웹 참고 (2026-10-14)

73 Python tests, 5 frontend tests, TypeScript and Vite build passed. Mocks verify exact explicit query payload, string highlights, metadata-only exclusion, actual returned URLs, timestamp reuse, web data kept out of system instructions and primary index, missing key/timeout/429/504, manual concept membership and safe links. Latest9 targeted tests plus frontend build passed after UI error fixes.

Actual browser: separate question and Exa query inputs, absent key shown as 웹 검색 미연결, no downloaded generation model shown as failure, explicit retry uses the same frozen job. No new answer artifact was created. Settings→record navigation was observed broken, fixed at its sidebar caller and rechecked. Screenshot: `verification/web-reference.jpg`. No actual Exa request or successful LLM inference occurred. API keys for deployment remain user-supplied; Codex connector token is not extracted.


## 로컬 모델·학습·회의·vision 실제 실행 — 2026-10-14

앞 절의 다운로드 대기와 B/C 미진행 상태는 당시 기록이다. 사용자 승인 후 Qwen3.5 4B MLX와 EmbeddingGemma를 앱 전용 모델 폴더에 다운로드했고 고정digest를 확인했다. Ollama0.40.3의 실제 구조화 텍스트 생성과 이미지 입력을 실행했다. 외부 API·Exa 키는 제공되지 않아 실제 호출하지 않았다.

- 실제 모델 통합 JSON (로컬 검증 자료·공개본 미포함): 합성 수업/회의 기록에 실제 모델을 사용했다. EmbeddingGemma768차원·digest854626...·무색인0, 같은 질의의 keyword전/hybrid후와 동의어·과거 수업·현재만·타 과목 배제 확인. Qwen digest7f325...를 결과별 저장했다.
- 이전/현재 회차 연결 답변, 전체3구간 요약, 실제두 구간 완료 후 검증용 의도적중단→나머지만 재개, 완료 결과 재열기 확인. 임의 ID 출력 오류를 발견해 전달 출처 enum을 적용했다. 새 제약을 포함한8192 기본 예산으로 발췌하는 경계 테스트도 추가했다.
- 실제5문제(객관식3/서술형2) 생성, 제출 전 정답/기준/해설 제외, 저장한 정답 제출5건 모두correct, 코드 비교와 실제 자유 채점, 사용자 수정의 원래 판정 보존 확인. 서술형 선택지 오류는choice/free anyOf·빈배열·정확히5개 조건으로 보강했다. Claude에는 공식 미지원 배열조건만 전송사본에서 제거하고 서버 검증을 유지한다.
- 실제회의 fixture는 제안을결정으로 확정하지 않고 명시한 기존서버 결정만 기록했다. 김민수·다음주금요일 원문 표현, 미정 담당자, 사용자 확인/Markdown네 섹션을 확인했다. 이것은 합성회의 의미 사례이며 실제 다중화자 회의ASR 평가가 아니다.
- 실제PDF 벡터페이지 PNG와 추출래스터 PNG를 Qwen에 전달하고 출처/page/bbox/버전/digest/AI해석을 보존했다. 색상블록을 인식했지만 영문 글자를 한글체로 부르거나 중국어 표현을 섞는 오류가 남았다. handwrite/복잡한 차트의 정확성을 확정하지 않는다.
- 별도UI 모델 대역에서 요약/정답가림/오답재풀이/수정이력/회의록 확인/내보내기/vision배치/재열기를 확인했다. ui-*.jpg는모델품질 증거가 아니다. 실제main앱에서 모델준비·의미색인·이전회차 검색·실제Qwen답변 저장을 확인했다. semantic-ready.jpg/local-answer.jpg가 실제main 증거다.

## 런타임·최종 점검

설치120.27초 (로컬 검증 자료·공개본 미포함), 실행 (로컬 검증 자료·공개본 미포함): 현재Mac의 별도폴더에 검증된 공개캐시를 이용해 Whisper/FFmpeg 소스를 빌드하고 실제사람음성8.94초를 처리했다. 깨끗한OS 설치 검증은 아니다. 전체Ollama payload/고지, 모델/VAD/한국어OCR 고지와SHA를 검사했다. 별도owned engine 시작·종료, CLI포트예약/충돌선택, 상대경로, 중단파일/취소/기존설치rollback, DBv13보존, 데이터폴더중복실행거절을 검사했다. 원본파일을 복사/삭제하지 않았다.

실제 단독/동시 (로컬 검증 자료·공개본 미포함): 동일12.54초 사람음성을250ms속도 ASGI WebSocket으로 replay. 두 경우51ACK/601920frames/저장gap0/CER4.00%, 최대관찰pending1. 전사종료후3.16초→동시7.52초. Qwen완료관찰12.02→22.18초, 생성토큰212/282로 다르다. streamFalse이므로첫토큰시간이 아닌 완료시간이다. host swap은시험시작전부터약8.99GB였고 감소했으며 앱 단독RAM으로 해석하지 않는다. 브라우저/TCP/마이크 재녹음 시험은 아니다.

[추가93시험파일](diverse-audio-test.md), 37.62초 replay (로컬 검증 자료·공개본 미포함): 기본30초를 넘는151ACK/1805760frames/저장gap0/pending최대2/종료후2.10초/done/CER7.33%. 기존12.54초를3회반복한 파생조건이며 새화자나회의가 아니다. 추가원음82개와파생11개/총59.16MB를 구분했다. 30초 cap에서도 고유명사·문맥 오류가 남아 있다.

최종전체 unittest100개, frontend5개, TypeScript/Vite는마지막 실행 출력으로 확인한다. 외부API·Exa live, Raon/GPU, Windows, 개발도구 없는 cleanMac, 서명/동봉 배포판, 실제30–60분회의·겹침발화·학습효과는 미확인으로 둔다. 무음 추가문장/힌트 악화/긴입력·메모리 압박을 계속 개선한다.

## 2026-10-14: Mac 경계·명칭·동시 실행 개선

최신 구현과 시험은 [Mac 전사 개선 기록](mac-asr-improvements.md)에 정리했다. 같은600.96초에서241/2149→102/2149, 실제 속도37.62초에서151ACK/gap0/CER0, 고정 출력 동시 실행의 종료 후 중앙값5.07→3.47초를 확인했다. 명칭 힌트의 개선과 악화 사례를 함께 남겼다. 백엔드112개·프런트엔드5개·타입/빌드·문법·diff 검사 통과. 앞 절의 수동 명칭만 사용하는 정책과 고정30초 경계는 당시의 기록이다. 현재는 범위를 제한한 등록 명칭과 조용한 경계를 사용한다.
반복 취소 시 네이티브 종료가 끊기는 리뷰 지적을 재현·수정했고 새 PCM·부모 취소·kill fallback 회귀 검사와 리뷰 재확인까지 완료했다.


## 2026-10-14: 새 로컬 요청의 확정 전사 대기

- 전체 백엔드123개가184.970초에 통과했다. 프런트엔드6개·TypeScript/Vite 빌드·Python 문법 검사를 통과했다. 새 검사는 대기·취소·재시도·저장한 답안·요청 당시 출처 버전·API 생성 계속·임시 전사 제외·모델 조회 뒤 재확인을 포함한다.
- 독립 코드 리뷰의 두 지적을 재현·수정하고 재확인했다. 다른 회차 삭제 시 저장된 검색 결과도 발췌문을 지우며, 채점 대기 중/추론 중 근거 삭제 시 성공 판정을 저장하지 않는다. 시작 전에 취소한 작업이 queued에 남는 문제도 수정했다.
- 별도 임시 DB·모델 대역의 IAB에서 질문 대기→취소→같은 작업 재시도→확정 전사 해제 후 결과 표시를 관찰했다. 자유 답안은 대기 중 제출 내용이 보이고 취소 후에도 보존됐다. 브라우저에서 채점 재시도 완료와 검색 전체 흐름은 수동으로 확인하지 않았고 백엔드 통합 검사로 확인했다. 질문 화면 (로컬 검증 자료·공개본 미포함), 답안 화면 (로컬 검증 자료·공개본 미포함).
- 이 대기 정책은 이미 진행 중인 추론을 중단하지 않고 모델 가중치를 자동으로 내리지 않는다. GPU 계산과 통합 메모리 경쟁이 완전히 없어지는 정책은 아니다. [구현·실측 조건](mac-asr-improvements.md).

- 회귀 검사와 겹치지 않게 실제 모델 비교4회를 완료했다. 전 실행 입력259/출력200토큰·51ACK/gap0/CER4% 일치. 전사 종료 후 중앙값50.92→30.52초, 대기 포함 답변77.02→88.50초로 전사 우선의 대가가 관측됐다. 실행별 편차·높은 기기 swap으로 일반적인 개선 배수를 보장하지 않는다. 원자료 (로컬 검증 자료·공개본 미포함), [실행 조건과 제외한 실패 기록](mac-asr-improvements.md#실제-모델-비교-결과).
- 측정 종료 뒤 앱 소유 Ollama·측정 프로세스·임시 UI 서버가 남지 않은 것을 확인했다. 외부 사용자 서비스는 종료하지 않았다.


## 2026-10-14: 녹음 자동 복구·검색 중복 억제

- grilling에서 사용자가 가능한 자동 복구와 보수적 중복 억제를 승인했다. 기존 입력 트랙이 살아 있을 때 사용자 시작당 한 번 새 녹음 ID/AudioContext/worklet으로 복구한다. 새 PCM과 저장 ACK가 확인되면 `자동 복구됨 · 녹음 중`을 표시한다. 종료된 트랙·복구 실패·두 번째 장애는 원음과 사유를 보존하고 재시작 버튼을 표시한다. 정상 무음은 계속 수집한다.
- PCM·ACK·mute 5초, 타이머 지연 10초 초과·context 중단·processor 오류를 감지한다. 시작/저장 요청 5초, flush 1초, ACK drain 3초, context close 1초의 유한 대기를 사용한다. 서버는 미연결 시작/입력 15초 무응답을 종료한다. 임계값은 현재 Mac의 검증 설정이며 모든 하드웨어에서 보장하는 값은 아니다.
- 실제 IAB에 [재현 fixture](../experiments/serve_recording_fixture.py)를 열어 합성 무음 300.4747초·5구간·14,422,784프레임을 저장했다. `Recorder → RecordingCapture → AudioWorklet → TCP WebSocket → SQLite/WAV`는 실제 코드이며 getUserMedia는 합성 스트림, 전사 추론은 완료 표시 대역이다. 입력 획득 3회 중 자동 복구 2회는 추가 획득 없이 처리했다. 원자료와 조건 (로컬 검증 자료·공개본 미포함).
- 4분 이상 무음 유지 → PCM 입력 끊기 → 새 구간 복구 → 두 번째 context 중단으로 종료, 사용자 재시작 → 기존 연결 ACK 차단 → 새 연결에서 ACK 전달 복원·10초 이상 유지·정상 종료, 다시 시작 → 트랙 종료·자동 재획득 없음 순서로 확인했다. PCM 복구 화면 (로컬 검증 자료·공개본 미포함), 중단 화면 (로컬 검증 자료·공개본 미포함), ACK 복구 화면 (로컬 검증 자료·공개본 미포함).
- 최종 5개 WAV의 sample rate/frame 수가 DB와 일치했다. 수집된 프레임의 누락 0, 첫 복구 구간 사이 실제 시각 간격 7,618ms를 유지했다. 수집되지 않은 음성을 되살린 결과가 아니다. 임의 무음을 WAV에 넣지 않는다. 브라우저에서 발견한 마지막 버퍼와 장애 감지 패킷 누락을 각각 실패하는 회귀 검사로 재현한 뒤 수정했다.
- 연결 종료 시 서버가 받은 꼬리 구간을 확정 전사에 넘기고 두 번째 소켓의 소유권 침범을 거절한다. 서버가 먼저 종료해도 뒤늦게 알려진 end_frame은 같은 작업 ID로 누락 길이를 늘린다. 입력 시간 초과만 복구 가능 코드로 전달하며 인증·PCM·저장 오류와 구분한다. 독립 코드 리뷰의 세 지적을 회귀 검사로 재현·수정했다.
- 검색은 키워드·하이브리드·답변 근거의 공통 collector에서 반복 문구를 서로 다른 설명 뒤로 보낸다. 원문은 유지하고 큰 결과 한도에는 반복 근거도 포함한다. 숫자 부호·수량·요일·영문 월·한국어/영어 부정 표식 차이를 보호한다. 문구 40자 이상·trigram 겹침 0.9는 보수적 임시 기준이며 의미 동등성 판정기가 아니다. 후보 순위 밖의 모든 자료까지 비교하지 않는다. 하이브리드 질의 임베딩 1회 외 추가 모델 호출이 없음을 검사했다.
- 최종 백엔드 134개/45.983초, 프런트엔드 21개 통과. TypeScript/Vite 빌드·Python 문법·diff 검사 통과. 범위·cutoff·고정 출처 버전·기존 보안·전사 우선 대기 회귀 검사를 포함한다.
- 최신 앱을 기존 검증 데이터로 포트62434에서 다시 시작하고, 기존3기록과 수업의 녹음 대기 화면을 IAB에서 확인했다. 임시 시험 서버는 모두 종료했다.
- 실제 마이크 장치 분리, Mac 물리 절전/복귀, 장시간 실제 회의는 이번 fixture에서 검사하지 않았다. ASR 정확도나 생성 동시 실행 속도를 새로 측정한 시험도 아니다.

재현: 앱 폴더에서 `.venv/bin/python experiments/serve_recording_fixture.py /private/tmp/new-recording-check`를 실행하고 출력 URL을 연다. 새 임시 폴더만 허용한다. 녹음 시작 후 PCM/ACK/context/track 결함 버튼을 사용하고 서버 종료 후 `data/app.sqlite3`와 `data/audio/*/raw.wav`를 대조한다. 실제 마이크 권한은 요청하지 않는다.


## 2026-10-14: 메모 보강·병합·후보·새 모델·연속 사람 음성

- 사용자가 승인한 정책으로 메모 시점·인근 확정 전사 보강안·수정 후 명시 적용·노트 새 버전을 구현했다. 적용 대기 중 새 편집문, 원본v1, 승인한 수정문·확인 결과·Markdown 일치를 검사했다.
- 질문 후보는 기본 꺼짐, 로컬30초 간격·활성1작업·확정 전사 우선, API 수동 호출만 허용한다. 원문 인용·편집·고정·무시·명시 답변과 일반/재시도 경로의 중복 실행을 검사했다. 선택하지 않은 후보의 답변은 생성하지 않는다.
- 요약·회의록은 인용 별칭을 사용하는 다단계 병합과 구간/병합 캐시를 사용한다. 입력 인용 ID의 정확한 집합과 회의록 원문 계약을 검사한다. 실제 로컬 모델에서 구간2개 뒤 실패를 주입하고 두 구간 캐시로 재개해 전체5구간·병합을 완료했다. 인용 보존과 의미 정확도는 별개다.
- UI 검증 (로컬 검증 자료·공개본 미포함)과 질문 카드 화면 (로컬 검증 자료·공개본 미포함)은 모델 대역·작성 자료를 쓴 브라우저/API/DB 확인이다. 실제 모델 실행은 별도 JSON (로컬 검증 자료·공개본 미포함)과 [해석](assistance.md)에 기록했다. Qwen 후보 인용은 실패했고 의미·용어 오류가 남았다.
- 승인한 Gemma4 E2B MLX7.477GB·EmbeddingGemma2 270M0.442GB를 받았다. 모델 identity digest, 참조 파일 크기를 확인하고 모델별 순차 실행·unload 후 비교했다. 새 모델은 선택 후보이며 기존 생성/임베딩 기본값·기존 색인은 유지했다. 다운로드 (로컬 검증 자료·공개본 미포함), [실제 비교](new-local-models.md).
- 같은 사람 음성10클립에서 E2B CER29/545=5.32%, 명칭3/6,76.416초였다. 제품 Whisper large-v3-turbo는15/545=2.75%,4/6,30.089초였다. 힌트 없음·작성 지시·진단 정규화 조건이며 공식 FLEURS 수치가 아니다. E2B를 ASR 기본값으로 바꾸지 않았다.
- 한국어 작성12문서/12질의의 의미 검색은 기존/새 임베딩 @1동률11/12, @3 11/12→12/12였다. 작은 진단으로 일반적 우위를 주장하지 않는다. 새 모델의 검색 profile을 분리했다.
- [연속 사람 음성14분38초](long-human-recording.md)에서 실제worklet/WebSocket/WAV/Whisper/Qwen을 사용했다. 초기 bridge 시험의 음성 길이 손실을 발견하고 렌더 시계·공백·마지막 버퍼 처리를 보완했다. 수정 fixture는878.304초 저장·경계 공백16ms·interrupted, 생성15건과 모든 전사 작업 완료였다. 1kHz 파형 상관0.999999999957은 샘플링 진단이며 비트 동일성·단어 정확도 증명이 아니다.
- 장기 동시 실행의 확정 전사 지연 중앙39.790초/P9559.090초, 종료 뒤 마지막ASR22.637초, 생성 포함149.966초로 지연이 남았다. 다른 입력 경로·호스트 부하·swap 때문에 A/B 속도 개선율로 해석하지 않는다. 실제 마이크·겹침 발화·물리 절전 검증과 구분한다.
- [Gemma4 전체 계열](gemma4-variants.md)은 E2B/E4B/12B/26B-A4B/31B, QAT·MLX·GGUF·MTP·관련DiffusionGemma까지 공식 정보로 확인했다. E2B 외 새 가중치를 받거나 실행하지 않았다. M5 Max의 코딩 가속 수치를 M4 한국어 전사에 적용하지 않는다.
- 최신 최종 코드: 백엔드 **150개/16.813초**, 프런트엔드 **24개**, TypeScript·Vite빌드·Pythoncompileall·git diff --check 통과. 독립 정적 리뷰의 기존5지적을 수정했고 최종 작은 변경 재검토에서 추가 중요한 회귀를 찾지 못했다. 이 리뷰는 실제 의미 검증과 구분한다.
- 포트62434의 앱을 최신 backend/frontend로 재시작했다. schema13 DB를 로컬 백업하고14로 이행, 기존3기록·노트2·출처11·결과1·원음2의 **모든 원래 컬럼 값** 보존, integrity/FK검사와health200을 확인했다. 후보 기본 꺼짐과 과거 메모의 시점 직접 입력을 브라우저에서 확인했다. 이행 검사 (로컬 검증 자료·공개본 미포함), 최신 앱 화면 (로컬 검증 자료·공개본 미포함).
- 임시 모델/장기/대역 UI 서버·관측기를 종료하고 최신 사용자 앱과 해당 앱 소유 Ollama만 유지했다. 사용자 주도 NVIDIA/Raon 시험은 계속 보류했다. 외부 API·M5·실제 회의 정답 평가는 이번에 실행하지 않았다.


## 2026-10-14: Gemma4 QAT·12B와 일반 발화·잡음의 실제 비교

- 사용자 승인 순서 E2B QAT→E4B QAT→12B를 실제 다운로드·실행했다. QAT는 Google 수정 공식 GGUF의 전체 SHA 일치를 확인한 custom artifact이며 Settings의 기존 Ollama QAT tag와 구분한다. 실측 뒤 새 QAT만 삭제하고12B·기존4모델을 보존했다. [파일·정리·모든 결과의 해석](gemma4-actual-comparison.md).
- 고유명사 중심10클립뿐 아니라 평소 말투·말 고침·반복·저음량·Gaussian 잡음·세 방·TED의39클립302.63초를 같은 SHA/정답으로 비교했다. 즉흥은 한 남성16세 화자43.053초, 실내는 읽기 문장이라 실제 성인 회의·다화자 대표 벤치마크가 아니다. 원음은 Git에 배포하지 않는다. 공식 Seoul archive prefix의 항목 CRC·길이와 재조회4파일 SHA를 확인했다. 무결성 증거 (로컬 검증 자료·공개본 미포함).
-39개 최초 Whisper는 변경 전30ms였다. E4B 즉흥44/256=17.19%, E2B140/256=54.69%, Whisper78/256=30.47%. 12B는11/12 성공·77/227=33.92%이며5.249초 한 건1024토큰 미완결47.167초를 별도 실패로 기록했다. 실행 실패를 평균 CER에서 숨기지 않는다. 잡음은 Whisper19/223=8.52%, E4B23/223=10.31%였다.
- 같은39개 Whisper200ms 시험은166→151/1270자, 즉흥78→68자·잡음19→16자·실내14→10자·강연10→12자였다. 결과를 보고 짧은 확정 전사에도200ms를 적용했다. preview/긴녹음/무음skip/원음/시각clamp는 보존했다. preview→final 옵션 검사를 먼저 실패시킨 뒤 한 줄 수정·관련 대역 대응 후 통과했다. ‘감사합니다’ 환각은 줄었으나 앞부분 누락은 남았다. 실제200ms (로컬 검증 자료·공개본 미포함).
- 연속 인간 낭독878.3035초를 실제 Browser worklet/WebSocket/WAV/Whisper와 생성에 사용했다. E2B/E4B 저장878.304초, 각각 생성15/15·확정 범위34/34 완료. 확정 지연 중앙20.840/22.080초, 생성 실제 추론 중앙13.765/19.131초다. E4B 시작/끝gap과 interrupted상태를 정상 완료로 바꾸지 않았다. 12B는63.253/54.091초 원음 보존 뒤 두 입력/ACK 실패, 첫 생성96.637/99.560초였다.12B 전체878초 P95는 없다. 공유 AudioContext 복구는 fixture 제약이며 물리 마이크 복구의 실패 증명은 아니다.
- 같은 녹음 사본120초(37전사+작성메모1) 최신 label 제외·전역별칭·최소 인용 schema 비교: E2B 요약113.732초 통과, E4B227.879초와12B343.382초 최종 인용 검사 실패·38구간 보존. 메모10.070/21.175/50.893초는 모두 ID·적용v3 검사를 통과했지만 비유 오해·요청 복사·원문 조각 복사로 품질이 부족했다.12B 품질 우위는 확인하지 못했다.
-12B 전체292전사+메모 제품 요약은1811.420초 뒤232번째 빈 인용 Section으로 실패해231구간을 보존했다. 요청 schema의 evidence_ids 최소1/최대64를 검증과 맞췄다. 수정 뒤 전체 완료는 미확인이다. 전체입력 보조 probe도180초 HTTP read timeout으로 실패했으며 제품 map/reduce 완료나 실측 완료 시간으로 보고하지 않는다.
- 실제 생성에서 나타난 제목 메타데이터 혼입과 구간별 `s1` 충돌을 공통 입력/별칭 생성에서 수정했다. 저장된 label·원문·출처 위치·ID·버전은 유지하고 요약/메모의 전달용 딕셔너리만 바꿨다. 인용을 자동 덧붙여 통과시키지 않는다.8개 batch와 추가 수선 모델 호출은 진단 실패 뒤 제품에서 제외했다.
- **최종 backend165개/11.618초, frontend24개, TypeScript·Vite·Python compileall·git diff 검사 통과**. 낮은 음량/새200ms 무음 꼬리·프레임·재시도·범위·근거/메모 원본·보안 회귀를 포함한다. 독립 정적 리뷰의 Whisper 실패 상태와200ms 실패 조건 저장 문제도 수정·재확인했다.
- 포트62434를 최신 코드로 재시작하고 schema14·모든 DB 행의 hash/개수가 같음을 확인했다. 기존3기록·2메모·11출처·1artifact·2녹음 유지, 기본Qwen·기존임베딩 설정 유지, 설치5모델과 새QAT부재를 확인했다. 최종 검증 (로컬 검증 자료·공개본 미포함), 설치 화면 (로컬 검증 자료·공개본 미포함).
- 실제 물리 마이크·Mac 절전·30–60분 실제 수업/회의·겹침·카페/바람·여러 즉흥 화자·M5/NVIDIA/외부API는 이번 비교에서 미확인이다. 일반 발화·잡음과 의미 오류를 고유명사와 함께 다음 개선 항목에 둔다.


## 2026-10-14–15: 성인 대화·생활 소음·후보 전사·문맥 요약

- grilling Q1–Q4의 합의대로 최초 전사/원음 우선·추가1회·후보 명시 적용·처리 범위/최종 인용 분리·공개자료 검증을 구현했다. [정책·전체 표·내용 오류·재현](conversation-robustness.md).
- 서울 성인 인터뷰3개와 DEMAND 사무실/식당의 실제300.004초 음원을 확보했다. 정답 발화15개×3조건45개+기존39개, 연속 턴교대18개를 평가했다. 인터뷰어 정답이 없어 전체 대화 CER·화자 분리 정답 검증은 하지 않는다. 파생10dB 혼합과 실제 현장 회의를 구분하며 음원은 Git/앱 배포에서 제외했다.
- Whisper250ms/100ms/off를 동일자료로 순차 실행했다. 뉴스 문구 환각·악화 때문에 기본250ms·pad200ms를 유지한다. off는84개 중13개 개선/10개 악화/61개 동일, 전체209→230편집/1726자다. 저음량/일반말의 앞부분 회복도 확인해 자동 교체 없이 후보로 제시한다. 쌍별 결과 (로컬 검증 자료·공개본 미포함).
- 재처리 대기·최초 확정 전사 preemption·수동 수정 충돌·취소/종료·빈 원음·반복 적용·전체 범위 후보의 옛ID/버전/출처/원음 보존을 검사했다. 선택적 원음 검증 실패가 최초 전사 큐를 멈추지 않는 경계도 red/green으로 보완했다.
- 같은666.3299375초 대화+사무실을 실제 속도로 ASR단독/동시Qwen 생성11건으로 실행했다. 모두 입력/저장PCM SHA 동일·ACK2666개·공백/오류0·확정26범위 완료. 확정ASR 호출 중앙/P95는4.01/5.35초→4.51/9.81초, 종료 뒤 마지막 확정6.76→7.62초였다. 실제TCP 증거 (로컬 검증 자료·공개본 미포함), 집계 (로컬 검증 자료·공개본 미포함).
- 브라우저worklet 실행은651.5초 뒤 연결닫힘·21.333ms공백으로 완료되지 않았다. 도구탭 소실 원인은 확정하지 못했다. TCP성공은 물리마이크/브라우저/절전 검증을 대체하지 않는다. 중단 기록 (로컬 검증 자료·공개본 미포함).
- 새 일반 요약은 시간순 문맥·검증한 Qwen 토크나이저·2048 이하 출력예약·최대6항목/6직접인용 병합·처리범위 분리를 사용한다. 이전 고정작업/회의록의 인용 계약은 유지하며 없는ID·임의시각을 거절한다. 완료 구간과 병합은 캐시와 실패시UI로 보존한다.
- 실제 기본8K 인터뷰는345.904초 뒤 byte예산 때문에 실패했다. tokenizer와 nativeprompt 상한 검사 후 구간7+병합1,164.798초에180원문/30최종인용/6항목 완료. 다른runner는fallback이며 프로필고정 뒤 모델변경은chat전/생성후거절이다. 최종 설치tag의 metadata wrapper 문제도 회귀 검사로 보완했다. 입력계산 (로컬 검증 자료·공개본 미포함).
- Gemma12B의14분38초 낭독은9구간+3병합,915.602초 완료했다. Qwen의 실제 구간9개 재생 후 새병합1은47.691초이나 전체 새 실행시간이 아니다. 메모 인근8개의 시간순 정렬·로컬빈문자열금지 후11.650초의 후보/인용/적용 통과. ASR오탈자·가정/주어/비유 오해는 남아 초안품질을 전체통과로 보고하지 않는다.
- 임시[s52,…,l113]목록은 원문동일변수를 보존하면서 정리한다. 기존12B 실제결과 후처리에서13목록제거·구조화인용/입력불변을 확인했다. 새모델추론이나 의미수정으로 해석하지 않는다. 별도 후처리 (로컬 검증 자료·공개본 미포함).
- 작성내용을 두문맥구간에 나누어120만원·4→3정정·미승인·외부금지/로컬조건·계약미결을 실제모델로 검사했다. Qwen일반35.663초/Gemma일반109.049초guard통과; Qwen회의록은결정근거검사거절/Gemma회의록136.211초구조·담당이서연·기한2026-10-19통과. lexicalguard와 수동표본대조이며 일반의미완전성의 증명은 아니다.
- 대역UI에서 전사후보편집/적용·빈9초수동버튼·완료요약2구간을 브라우저/API/DB로 확인했다. UI증거 (로컬 검증 자료·공개본 미포함), 후보적용 (로컬 검증 자료·공개본 미포함), 실패구간보존 (로컬 검증 자료·공개본 미포함). 실제음성/모델실행과 구분한다.
- 독립정적리뷰에서 전사큐·취소wake·shutdown·담당부정·대기중모델교체·다른runner와tagwrapper 경계를 찾아 수정·재확인했다. 모델추론과 테스트는 리뷰와 별도로 실행했다.

- 최종 현재tag 검증 프로필로 Qwen 기본8K의14분38초 전체를 **캐시 없이9구간+병합1,299.378초**에 완료했다. 처리293개·최종인용26개·6항목이다. 눈동자가 손톱을 침투한다는 원문 밖 설명과 후반 누락이 남아 내용품질은 통과가 아니다. 전체 새 실행 (로컬 검증 자료·공개본 미포함).
- 마지막 wrapper 수정 후 최종 백엔드212개/31.599초·프런트엔드24개·TypeScript/Vite·Python compileall·pip check·diff·문서링크 검사를 통과했다. 최종 검사 (로컬 검증 자료·공개본 미포함).
- 포트62434 앱을 최종코드로 재시작했다. schema14→15, 모든 원래 DB컬럼/행 동일, integrityok/FK0·health200, 기존3기록/2노트/11출처/1결과/2녹음과 기본설정·설치5모델 유지. 브라우저에서 기존수업·녹음대기·수동원음다시인식 버튼을 확인했다. 저장검사 (로컬 검증 자료·공개본 미포함), 최신화면 (로컬 검증 자료·공개본 미포함).
- 임시 추론·음성·UI 서버를 종료하고 사용자앱과 해당앱 소유Ollama만 유지했다. 회원가입·새모델가중치·외부API/M5/NVIDIA·물리마이크/절전/30–60분회의/화자겹침은 실행하지 않았다. 최종한번씩의 고정순서·호스트상태가 다른 실측을 고정가속비로 보고하지 않는다.


## 2026-10-21: 로컬 소음 제거·앞구절 누락

- [고정 조건·쌍별 결과·적용 판정·재현 방법](local-denoise-20261021.md)과 [비식별 집계](verification/local-denoise-20261021.json)를 공개한다. 원음·정답 전사·모델·개인 보관함은 포함하지 않는다.
- 같은 실제 한국어 6개 발화의 원본·감쇠·생활 소음 혼합·환경음·SIL 57조건을 Whisper와 Qwen에서 비교했다. 별도 한국어 낭독 10개도 고정해 유망한 조건을 확인했다. 반복 조건을 서로 다른 발화로 계산하지 않는다.
- 대역 필터·시간축 보정 FFT·체크포인트 수식으로 검증한 DeepFilterNet3·레벨 보정 DeepFilterNet3를 순차 실행했다. 일반 발화·저음량·SIL의 개별 회귀나 처리 실패가 남아 기본 입력에는 적용하지 않았다. 앞구절 누락·소음 오인식이 해결됐다는 판정이 아니다.
- 실험 도구의 FFT 25ms 지연·꼬리 손실, DF 가중치 대입 순서, 미완료 manifest 수용을 수정하고 검사했다. 잘못된 초기 비교는 판정에서 제외하고 수정된 입력으로 새로 실행했다.
- 최종 코드의 Python 전체 647개 중 642개 통과·선택 검사 5개 생략, 프런트엔드 104개와 TypeScript 검사 통과. 실제 모델·원음 해시·시간축 검사는 별도로 수행했다.
- 제품 코드·설치 앱·기록·원음·필기·초안·기본 후보 정책은 변경하지 않았다. 설치 앱 GUI·새 마이크·절전·강제 종료 복구 재시험은 이번 검증에 포함하지 않는다.


## 2026-10-23: VAD 경계·현재 구간 문맥 보존

- [같은 한국어 음성의 1초·2초·검출 후 전체 구간 비교](vad-context-20261023.md)와 [비식별 집계](verification/vad-context-20261023.json)를 남긴다. 원음·정답·인식문·개인 보관함은 공개하지 않는다.
- 기존과 동일한 57조건 및 별도 낭독 10개를 세 방식으로 순차 실행해 201행·실패 0행을 확인했다. 새 기준의 57개 출력은 이전 기준 실행과 문자열까지 같았다. 원음·출처 69개와 별도 낭독 10개 해시가 유지됐다.
- 앞구절 사례의 오류는 두 대안 모두 7→1로 줄었지만, 2초 여백은 별도 일반 낭독 14→18·전체 구간은 14→16으로 악화했다. 주 비교의 다른 저음량·소음 조건에서도 삭제나 오류 증가가 남았다. SIL은 모두 빈 출력이었으나 두 대안 모두 기본 경로에는 적용하지 않았다.
- 실험기의 Whisper 전용 옵션과 실패·시각·원음·Qwen 경로 분리 검사를 추가했다. Python 651개 중 646개 통과·선택 5개 생략, 관련 19개·프런트엔드 104개·TypeScript 검사 통과.
- 제품의 1초 기본값과 원음·기존 전사·사용자 적용 정책, 실제 설치 앱·기록·필기·초안은 바꾸지 않았다. 현재 구간 밖 문맥 연결·설치 앱 GUI·새 마이크·긴 녹음 복구 시험이 아니다.
