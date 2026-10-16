# Mac 앱 내부 실행 전환과 검증

2026-10-16. 작업 중인 통합 기록이며, 마지막 상태는 아래 실행 결과와 함께 갱신한다.

## 실행 경계

- 기본 Mac 앱은 자체 HTTP/WebSocket·Ollama 서버를 시작하지 않는다. Swift가 앱에 포함한 Python 엔진과 제한된 파이프로 통신한다. 기존 FastAPI 라우팅은 ASGI 함수로 재사용한다.
- 화면·PDF 추출·메타데이터 도우미·Whisper/FFmpeg·MLX·직접 임베딩 실행 파일을 앱 안에 포함한다. 모델 blob과 사용자 보관함은 기존 위치를 재사용한다.
- 외부 API와 사용자가 선택한 웹 검색은 기존 명시적 선택을 유지한다. 원음 업로드를 자동으로 켜지 않는다.
- 모델 변경은 가중치 변환이 아닌 메모리 내 키·양자화·대화 형식 매핑이다. 원본 모델 파일은 해시로 검증한다.
- Qwen3.5 4B, Gemma4 E2B/12B의 텍스트·이미지·JSON 실행과 기본 EmbeddingGemma의 직접 검색을 검사했다. 대규모 품질 향상을 의미하지 않는다. [Gemma 결과](direct-gemma-models.md), [임베딩 엔진](embedding-worker.md).
- 실제 포함 Mach-O 전체의 최소 macOS 버전을 빌드 때 확인한다. 이번 ASR 바이너리는 macOS27.0, MLX는26.2를 요구하므로 이번 앱은27.0 이상이다. 현재 Mac27.0.1에서 실행한다. 임베딩 엔진만의13.3 하한을 앱 전체 하한으로 표시하지 않는다.

## 기존 앱에서 이전

먼저 녹음과 작업을 마치고, **모든 창의 노트·대본 수정 등 미저장 입력을 저장한 뒤 기존 Solasi를 종료**한다. 아래 도우미는 이미 종료된 앱의 IndexedDB를 읽으며 React 메모리의 입력을 추출하지 않는다. 저장 여부를 확인하지 않고 앱을 강제 종료하면 안 된다.

1. 기존 앱 번들, SQLite 보관함·원음, `~/Library/WebKit/local.solasi.launcher`를 별도 로컬 폴더에 백업한다. 실행 중 DB 사본은 SQLite backup API를 사용한다. 종료한 뒤 최종 파일 사본과 해시를 다시 대조한다.
2. 기존 `Solasi.app/Contents/Resources/launch.json`의 `data`, `runtime`, `port`를 확인한다. 보관함 UUID가 아직 없다면 새32자리소문자hex를 한 번 정하고 아래 과정 전체에 같은 값을 사용한다.
3. 다음 명령으로 이전 HTTP origin에 해당하는 **모든 원시 초안 행**을 내보낸다. 앱과 같은 bundle ID의 별도 도우미가 WebKit의 기존 저장소를 읽는다. HTTP 서버는 띄우지 않는다. 도우미는 진행·취소 창만 표시한다.

```sh
.venv/bin/python scripts/export_legacy_drafts.py \
  --origin http://127.0.0.1:62434 \
  --vault-id <32자리보관함UUID> \
  --output /absolute/new/export-directory \
  --build-dir /absolute/new/helper-directory \
  --quiescent
```

4. `drafts.jsonl`의 각 행·전체 SHA256, 키·개수·길이를 확인한다. main뿐 아니라 다른 창 journal, dirty=false 행, backup, 알 수 없는 원시 필드도 보존한다. 도우미가 전체 저장소를 두 번 읽어 대조한다. 전체64MiB 제한은 없고 한 행은64MiB로 제한한다. 실패 시 원본과 partial을 남기고 완료 manifest를 발행하지 않는다.
5. 먼저 복사한 보관함에서 가져오기·재시작 대조를 검증한다. 실제 이전은 기존 앱이 종료되고 보관함의 배타적 잠금이 확보된 경우에만 다음 명령을 실행한다.

```sh
.venv/bin/python scripts/import_legacy_drafts.py \
  --app /Users/<user>/Applications/Solasi.app \
  --backup /absolute/export-directory \
  --editors-saved-and-closed
```

6. 새 SQLite 초안 행을 백업 원문과 대조한다. 같은 키의 내용이 다르면 원래 행을 덮어쓰지 않고 별도 복구 행을 보존한다. 한 행이라도 실패하면 전체 가져오기를 rollback한다. 이미 완료한 같은 export는 다시 삽입하지 않는다.
7. 설치기에 `--replace --draft-backup /absolute/export-directory`를 전달한다. 앱이 다시 실행됐거나 실제 origin·보관함·원문 대조가 다르면 교체하지 않는다. 원래 IndexedDB와 이전 앱 백업은 삭제하지 않는다.

## 앱 안의 저장·종료

- 페이지 초안의 main과 작성 창 journal은 같은 SQLite transaction으로 저장하며 commit 이후에만 완료 응답을 보낸다.
- 중단된 청크 전송은 기존 초안을 덮어쓰지 않는다. 보관함 잠금을 획득한 새 엔진이 이전 프로세스의 재개 불가능한 임시 전송만 정리한다.
- 정상 종료·추가 창 닫기는 진행 중인 필기를 확정하고 초안 큐를 기다린다. 저장 실패/대기 초과 시 창을 유지하고 입력을 다시 허용한다. 수동 저장이 필요한 노트·대본 수정은 구체적인 안내와 함께 닫기를 중단한다.
- 파이프 EOF나 강제 종료 후에는 기존 녹음 복구 경로로 저장된 PCM을 보존한다. 실제 입력이 돌아오기 전에는 절전 복구 기회를 소비하지 않는다.
- 새 원음 링크는 `solasi://audio/<vault>/<recording>?start_ms=…&end_ms=…`다. 같은 보관함의 읽기·재생만 허용하며 화면 수신기가 준비된 후 전달한다.

## 실행에서 발견하고 고친 문제

| 문제 | 수정·근거 |
| --- | --- |
| Swift가 작은ready프레임을 읽지 못하고 시작 대기 | `read(upToCount:)` 대신 `availableData`; 실제 Swift↔작업 엔진 fixture 통과 |
| WK custom scheme의 HTMLaudio가 readyState0으로 대기 | AVPlayer+범위 읽기. 실제600초WAV를599초로 탐색 |
| 캐시 보기 생성 중 종료 뒤 모든 재시도 실패 | 고유staging→검증→배타적원자rename. 불완전 이전캐시는 보존한 뒤 재생성 |
| 네 번 강제 종료 후 초안 저장이 한 시간 차단 | 배타적 엔진 시작 때 재개불가 전송만 정리; 기존commit초안 유지 |
| 엔진 receipt 상대 경로가 출력 폴더 밖을 덮어씀 | 정규상대경로·출력 containment 검사와 회귀 검사 |
| frozen 모델 종료가 resource_tracker를 일반 앱으로 실행 | `multiprocessing.freeze_support()`를 엔진 시작 직후 호출; v3에서 실제 자식 종료 재검증 |
| frozen 음성 파일 등록이 외부 ffprobe를 참조 | 모델만 있는runtime에서422재현→검증된동봉실행파일선택으로수정→v5전사·요약완료 |
| 막힌 stdin 쓰기 때문에 종료 신호도 대기 | 소유PGID 검증과 별도9초TERM/11초KILL 기한; TERM무시엔진·자식회수fixture통과 |
| 재생기 자원이 일시정지 후에도 누적 | 커서·음량만보존하고자원해제, 새재생기는seek완료후재생; 늦은이벤트격리 |
| 백그라운드 WK 이전 도우미가 macOS에 의해 정지 | 진행·취소 창과 활동 유지, 다른 앱 파일명/동일bundleID·72MiB export 재검증 |

## 현재까지 실제 확인한 범위

- 패키지v1: checkout밖 `/private/tmp`, 외부PYTHONPATH 없이 pipehealth·PDF추출·페이지PNG·버전메모·PCM16000프레임 저장ACK·EOF원음보존 통과. 네트워크소켓 없음.
- Swiftfixture: 가속 입력한10분 합성PCM600ACK,9,600,044바이트WAV,600초duration·599초seek. 실제 마이크/물리절전 시험을 대신하지 않는다.
- 직접 모델: venv에서 실행계약을 확인한 뒤 frozenv2에서 실제 모델을 다시 실행. E2B JSON 뒤 종료대기를 발견하여 v3로 수정한 뒤 8개 실제 모델 호출이 모두 통과했다. Qwen/E2B/12B의 한국어·JSON, 임베딩768차원/L2, 실제FLEURS QwenASR를 검사했다. 130회소켓표본없음·모델원본해시불변·잔여자식없음도 확인했다.
- QwenASR환경비교: 같은실제FLEURS15.78초와성인clean은정답대비결과동일. 성인음성+실제식당소음10dB파생혼합은기존4/31→새환경5/31오류,반복1회에서도동일. 후보엔진 호환성이며 정확도동등성으로 해석하지 않는다.
- 이전 exporter: 별도WebKit저장소에서 원시5행/72,352,115바이트, 각행·전체해시와backup/custom필드 보존 확인.
- 최종v5기준 백엔드440개회귀검사통과(실제모델선택검사5개skip), 화면70개검사·TypeScript·Vite빌드통과. 별도 실제모델검사는 위와 같이 수행했다.
- frozenv5의 모델만 있는 runtime에서 실제FLEURS15.78초 연결→기본Whisper10.80초→기본Qwen원문발췌요약15.74초가 완료됐다. 전사는 해당 정답과 동일했고2.140–12.540초 범위였다. 152회소켓표본없음, 종료코드0·잔여자식0, 음성과모델해시불변. 한 클립의 통합 확인이며 일반적인 정확도·지연 비교가 아니다.
- 실제 기존 앱을 사용자가 저장·종료한 뒤 전체WK초안1행/660바이트를 내보내 복사한보관함에서가져오기·재시작대조를완료했다. `backup: undefined`는 별도경로목록과해시로보존했다. 실제보관함교체여부는 마지막설치기록과구분한다.

새 패키지의 실제 마이크·물리절전, 최종 설치·실제 사용자 초안 이전 결과는 통합 검증 뒤 아래에 추가한다. 현재 이 문서만으로 제품 앱 교체 완료를 주장하지 않는다.

## 설치된 검증 앱의 화면 확인

v5 엔진을 포함한 별도 `Solasi Internal Validation` 앱은 기존 보관함의 복사본을 사용한다. 화면 도구의 접근성 트리와 캡처에는 회색 빈 창이 나왔지만, 사용자가 실제 Mac에서 과목·홈 화면이 보인다고 확인했다.

같은 실행 경로를 계측한 별도 전체 앱 복제본에서도 다음을 관찰했다.

- `solasi-app://app/` 탐색 및 HTML 응답 성공
- 신뢰한 main frame의 원본 검사 통과, `ui_ready` 수신
- 상태·과목·기록 API가 모두 200 응답
- 실제 화면 크기 1200×820, DOM 자식 존재, JavaScript 오류 없음

따라서 이 현상은 화면 도구의 가시성 제한으로 구분했다. 이 진단을 위해 CSP·브리지 원본 검사·앱 배치를 완화하지 않았다. 실제 PDF·필기·마이크·재시작 흐름은 사용자 조작과 보관함 변경 대조로 이어 확인한다. 홈 화면 확인만으로 전체 흐름을 통과했다고 표시하지 않는다.

구현 커밋은 `69f82ff`이며 `codex/serverless-mac` 작업 브랜치에 보존한다. 현재 제품 앱 교체와 실제 보관함 가져오기는 별도 관문으로 남아 있다.
