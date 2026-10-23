# Solasi 개발 안내

[제품 소개](../README.md) · [사용 가이드](guide.md) · [공개본 범위](../PUBLIC_EXPORT.md)

## 구조

Mac 기본 실행은 앱에 포함한 화면·Python 작업 엔진·직접 모델 실행을 사용합니다. 앱이나 모델용 HTTP/WebSocket 서버를 시작하지 않습니다. 무거운 추론은 앱이 관리하는 별도 프로세스로 실행합니다. 모델 가중치와 사용자 기록은 별도 보관함을 재사용하며 앱 패키지에 복사하지 않습니다.

현재 Mac 패키지는 Apple Silicon 전용입니다. 포함된 전사 바이너리의 배포 대상 때문에 **macOS 27.0 이상**이 필요합니다. 로컬 빌드는 **ad-hoc 서명**이며 공개 배포용 서명·공증을 제공하지 않습니다. 다른 Mac·깨끗한 OS에서 검증한 설치판이 아닙니다.

| 경로 | 내용 |
| --- | --- |
| `frontend/` | React·TypeScript 화면 |
| `macos/` | Mac 창·녹음·재생·내부 작업 연결 |
| `lecture_study/` | 보관함·전사·검색·생성 작업 |
| `scripts/` | 엔진 패키징·Mac 앱 설치 |
| `tests/`, `frontend/tests/` | 백엔드·프런트엔드 회귀 검사 |
| `experiments/`, `docs/` | 비교 도구·설계·검증 기록 |

Python 패키지와 개발용 실행 명령 이름은 `lecture-study`입니다. 앱 이름은 Solasi입니다.

## Mac 앱 빌드

### 1. 빌드 환경

Apple Silicon Mac, Python 3.12, Node/npm, Apple Command Line Tools가 필요합니다. `requirements-macos.lock`은 직접 추론·패키징용 고정 환경이며 기존 개발용 `requirements.lock`과 섞어 설치하지 않습니다.

저장소 루트에서 실행합니다.

```sh
python3.12 -m venv .venv-macos
.venv-macos/bin/python -m pip install -r requirements-macos.lock
cd frontend
npm ci
npm run build
cd ..
```

### 2. 런타임과 임베딩 엔진 준비

패키징에는 `asr/receipt.json`이 있는 전사 런타임과 직접 임베딩 엔진이 필요합니다. 모델·소스·빌드·임시 파일의 저장 공간을 따로 확보하세요. 전사 준비의 다운로드는 약 1.73GB이며 빌드 공간은 추가로 필요합니다. 모델과 구성요소의 용량·라이선스는 [runtime-manifest.json](../runtime-manifest.json)에 고정되어 있습니다.

기존 런타임이 없다면 개발용 화면에서 **모델·키 설정 → 엔진·OCR 준비 → 전사**를 준비합니다. 아래 보관함은 개발용으로 새 경로를 사용하세요. 전사 준비에는 생성용 Ollama 서버가 필요하지 않습니다.

```sh
.venv-macos/bin/python -m lecture_study.launcher \
  --data-dir /absolute/path/to/build-vault \
  --runtime-dir /absolute/path/to/prepared-runtime
```

준비가 끝나면 개발용 실행을 종료합니다. 직접 임베딩 엔진은 [고정 archive·headers와 빌드 절차](embedding-worker.md#build)를 따라 준비합니다. 엔진 빌드에는 모델 가중치가 포함되지 않습니다.

### 3. 엔진 패키징과 설치

아래 경로를 실제 준비한 경로로 바꾸세요. 패키징 출력은 **아직 없는 새 폴더**를 지정하고, 설치할 보관함·런타임 폴더는 먼저 준비합니다.

```sh
.venv-macos/bin/python scripts/freeze_macos_engine.py \
  --runtime-dir /absolute/path/to/prepared-runtime \
  --embedding-engine /absolute/path/to/embedding-engine \
  --destination /absolute/path/to/new-bundled-engine

.venv-macos/bin/python scripts/install_macos_app.py \
  --engine /absolute/path/to/new-bundled-engine \
  --data-dir /absolute/path/to/vault \
  --runtime-dir /absolute/path/to/prepared-runtime
```

기본 설치 위치는 `~/Applications/Solasi.app`입니다. 빌드 기록에 포함 파일의 해시와 실제 macOS 최소 버전을 남깁니다. 모델·사용자 기록은 엔진 패키지에 복사하지 않습니다. 앱 실행 시 개발 checkout·Python·Node·컴파일러를 따로 설치할 필요는 없습니다.

기존 앱을 갱신하려면 작업·편집을 저장하고 앱을 **⌘Q**로 종료한 뒤 `--replace`를 추가합니다. 기존 앱은 백업하며 보관함·런타임 경로를 유지합니다. 실행 중인 앱이나 다른 앱을 덮어쓰지 않습니다.

### 이전 HTTP 앱에서 이행

기존 화면의 미저장 입력을 모두 저장하고 앱을 종료합니다. 기존 WebKit origin의 초안을 내보내고 가져오기·해시 대조를 마친 뒤 `--draft-backup`을 지정해야 합니다. 백업이 없는 교체는 거절합니다. [이전과 검증 절차](mac-internal-runtime-validation.md)를 따르세요. 원래 IndexedDB와 앱 백업은 자동 삭제하지 않습니다.

### 자산과 모델 호환성

앱 아이콘은 `macos/Solasi.icns`, 화면 아이콘 원본은 `frontend/public/solasi-icon.png`입니다. 화면은 시스템·라이트·다크 모드를 제공합니다. [UI 설계·Figma](orbit-ui-design.md).

직접 생성·임베딩 호환성은 [내장 모델 실행](direct-gemma-models.md)과 [임베딩 worker](embedding-worker.md)를 참고하세요. Gemma 4 E2B·12B 직접 생성·이미지 입력, Qwen3.5 4B MLX 생성·구조화 출력·이미지 입력과 EmbeddingGemma 768차원 검색을 확인한 기록이 있습니다. 이는 모든 모델·하드웨어의 호환성을 의미하지 않습니다. QAT 실측의 수정 헤더 artifact와 catalog의 공식 Ollama 배포물은 [비교 문서](gemma4-actual-comparison.md)에서 구분합니다. 모델 기본값은 비교만으로 자동 변경하지 않습니다.

## 개발용 브라우저 실행

이 경로는 개발·회귀 검사에 사용하며 loopback 서버와 Ollama를 사용합니다. Mac 앱의 기본 실행 경로와 다릅니다.

```sh
python3.12 -m venv .venv
.venv/bin/python -m pip install -r requirements.lock
.venv/bin/python -m pip install --no-deps -e .
.venv/bin/lecture-study --data-dir /absolute/path/to/development-vault
```

브라우저 경로의 앱 소유 Ollama는 전용 loopback 포트·모델 폴더와 cloud 비활성화를 사용합니다. 공식 Ollama `serve`는 표준 `~/.ollama`의 identity·서버 설정을 참조할 수 있으므로 완전히 격리된 홈 환경은 아닙니다.

## 검사

변경한 경로에 맞는 환경을 사용합니다. 내장 Mac 엔진·직접 모델 코드는 `.venv-macos`, 개발용 브라우저 경로는 `.venv`가 대상입니다.

```sh
.venv-macos/bin/python -m unittest discover -s tests -v
cd frontend
npm test
npm run check
npm run build
```

모델·마이크·실제 절전이 필요한 검사는 각각 별도 준비가 필요합니다. 단위 검사나 제공자 payload 검사가 실제 모델·외부 API 호출의 성공을 증명하지 않습니다. 음성 비교의 원음·모델·DB·비공개 실행 자료는 공개 저장소에 포함하지 않습니다.

## 문제 진단

- 내장 앱의 엔진 로그: `~/Library/Logs/local.solasi.launcher/engine.log`
- 같은 보관함을 두 Solasi 프로세스에서 동시에 열 수 없습니다.
- 재현 보고에는 macOS·칩·앱 버전, 실행 순서, 기대 결과·실제 결과를 포함하세요. 공개 로그에서 API 키·원음·전사·개인 경로를 제거하세요.
- 자료 접근 문제는 원본 이동·변경·권한 상태를 먼저 확인하고 다시 선택하세요. 전체 디스크 접근을 일괄 요구하는 절차는 아닙니다.

## 동작 설계

- [로컬 과목·필기 설계](superpowers/specs/2026-10-15-local-course-notes-design.md)
- [메모 보강·요약 병합·질문 후보](assistance.md)
- [직접 Mac 런타임·이행](mac-internal-runtime-validation.md)
- [런타임 자산·URL·해시·고지](../runtime-manifest.json)

전사 확정 구간은 최대 30초이며 조용한 경계를 선택합니다. 종료 후 처리도 같은 전사 모델·확정 설정을 사용합니다. 실시간 잠정 전사는 10초 주기로 요청하며 처리 중에는 최신 요청을 유지합니다. 종료할 때 오래된 잠정 작업을 중단해 확정 전사를 우선합니다. 재인식 후보·무음·요약 정책은 [후속 검증](fidelity-followup.md)에 정리되어 있습니다.

질문을 요청할 때 근거 버전과 확정 전사 cutoff를 고정합니다. 요청 뒤 자료가 변경되어도 저장된 결과의 근거 버전을 현재 원문으로 바꾸지 않습니다.

## 검증 기록

각 문서는 해당 시점의 코드·환경에서 관찰한 결과입니다. 이전 실측을 현재 버전이나 다른 Mac의 보장으로 해석하지 마세요. Windows, 깨끗한 OS 설치, 장시간 실내 회의·겹침 발화와 서명 배포판은 별도 검증 대상입니다.

### Mac 사용 흐름과 복구

- [정리 후 실제 앱 흐름·원음·필기·저장 복구](mac-post-cleanup-validation-20261018.md)
- [검증 기록 전체](verification.md)
- [실제 앱 전체 흐름·저장 창·본문 접근 조사](mac-native-flow-validation-20261017.md)
- [미저장 입력·필기 설정·JSON·대본·요약 원문·재연결 UX](ux-recovery-validation-20261017.md)
- [680px 툴바·화면 모드·키보드](mac-toolbar-validation-20261017.md)
- [대본·필기 저장·내보내기](mac-script-validation.md)
- [긴 한국어 파일 전사·요약 동시 실행](mac-long-file-validation.md)
- [마이크 시작·핵심 원문 요약](mac-microphone-summary-validation.md)
- [실제 절전·강제 종료·미저장 필기 복구](mac-recovery-validation.md)
- [30분 녹음·늦은 복귀·초안 복구](mac-recovery-followup-validation.md)

### 전사·요약 품질

- [발화 사이 200ms·400ms 쉼을 이용한 분할 경계 비교](speech-boundaries-20261023.md)
- [긴 한국어 원음의 구간 앞뒤 0·1·2초 겹침 비교](chunk-overlap-20261023.md)
- [VAD 1초·2초·전체 구간 문맥 보존 비교](vad-context-20261023.md)
- [로컬 소음 제거·앞구절 누락의 쌍별 비교와 적용 판정](local-denoise-20261021.md)
- [저음량 한국어·생활 소음의 VAD 미검출·수동 후보 비교](quiet-korean-vad-20261021.md)
- [같은 한국어 음성의 Qwen VAD 비교·자동 후보 보류](qwen-vad-20261020.md)
- [Mac 설치 앱의 자동 보류·원음·수동 재인식 검증](mac-qwen-vad-validation-20261021.md)

- [실제 강연 슬라이드·긴 발화·생활 소음의 힌트 비교](lecture-material-hints-20261020.md)

- [색인 작업의 임베딩 worker 재사용·양보·실측](embedding-worker-reuse-20261019.md)

- [단계별 시간·중복 변환 제거와 동일 음성 비교](local-stage-performance-20261019.md)

- [한국어 210조건·추가 55원음·Qwen 후보](korean-asr-validation-20261017.md)
- [긴 요약 문맥·후반 누락과 내장 엔진](summary-context-validation-20261017.md)
- [사람 음성 ASR 비교](asr-model-comparison.md)
- [연속 사람 음성 14분 38초 동시 실행](long-human-recording.md)
- [다화자·생활 소음·긴 요약](conversation-robustness.md)
- [주어·가정·후반 요약 보존과 브라우저 중단 조사](summary-fidelity.md)
- [재전사 후보·무음 환각·요약 주어·가정](fidelity-followup.md)
- [문장 내부 오류·긴 요약·11분 동시 실행](sentence-fidelity.md)
- [추가 음성 검증](diverse-audio-test.md)

### 모델과 남은 과제

- [새 로컬 모델 비교](new-local-models.md)
- [Gemma 4 전체 변형·M4 후보](gemma4-variants.md)
- [E2B QAT·E4B QAT·12B 비교와 소음·자연 발화](gemma4-actual-comparison.md)
- [남은 개선·미확인 경로](improvements.md)
