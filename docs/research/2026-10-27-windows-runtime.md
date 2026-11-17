# Solasi Windows 런타임 조사

확인일: 2026-10-27. 대상 체크아웃: `/Users/kimhuijung/Documents/ChatGPT/dev/solasi-serverless`.

## 범위와 판단

Windows 11 x64를 먼저 지원하되 현재 기능과 화면을 유지하고 OS 의존 부분을 교체한다. 녹음 후 전사와 선택적 실시간 전사 경로도 보존한다. 최종 사용자가 Python·Node·Ollama를 따로 설치하지 않도록 앱이 런타임을 포함하고 모델은 선택적으로 다운로드한다. Mac 구현은 유지한다. CPU 전용 16GB 노트북은 검증 대상이며 성능 보증으로 취급하지 않는다.

**권장안은 Windows에 앱 소유 llama.cpp worker를 추가하고 기존 Mac MLX 경로와 공통 기능 계층을 유지하는 것이다.** 생성은 Qwen3.5 4B의 GGUF와 대응 mmproj, 임베딩은 현재 EmbeddingGemma v1 계약, ASR은 현재 whisper.cpp 모델·CLI 계약을 유지한다. Ollama 설치나 상주 서버를 사용자의 필수 조건으로 추가할 이유는 없다. 이 문서는 소스·문서 조사 결과이며 Windows에서 실행한 결과가 아니다.

## 현재 코드의 실제 경계

아래 경로는 모두 위 체크아웃 기준이며 조사 시점의 줄 번호다.

| 위치 | 확인한 동작 | Windows 영향 |
|---|---|---|
| `runtime-manifest.json:3-4,15-40` | `darwin-arm64`, macOS source/build assets 및 Ollama tarball | Windows 전용 파일·SHA256·라이선스·receipt 필요 |
| `lecture_study/runtime.py:39-56,150-170` | frozen 앱의 `engines/asr` 조회, 실행 파일명 확장자 없음, 개발 실행 자동 준비는 Apple Silicon 강제 | `.exe` 경로와 Windows receipt 검증 및 배포 자산을 분기 |
| `lecture_study/transcription.py:184-193,219-248` | FFmpeg 정규화 → Whisper large-v3-turbo CLI → UTF-8 JSON, 한국어·용어 prompt·VAD·preview 옵션 | 알고리즘은 재사용 가능. 바이너리 경로와 subprocess 동작을 확인 |
| `lecture_study/transcription.py:266-289` | 별도 `whisper-vad-speech-segments` 보조 실행 파일과 centisecond 파서 | 해당 exe를 함께 빌드/동봉하고 실제 출력 단위 검증 |
| `lecture_study/local_models.py:13-25` | 플랫폼별 runner catalog. Qwen `llamacpp` 항목은 존재 | catalog에 있다는 것만으로 실제 Windows 실행이 구현된 것은 아님 |
| `lecture_study/direct_models.py:61-99,169-196` | Qwen을 MLX safetensors로 검증·view 생성, generation worker 호출 | Windows GGUF+mmproj 자산 검증·실행 분기 필요 |
| `lecture_study/model_worker.py:13-30` | `mlx_direct.generate`만 import | Windows에서는 C++ worker 또는 별도 직접 llama 실행 backend 필요 |
| `lecture_study/mlx_direct.py:7-13,26-48,51-88` | Mac용 MLX 버전/양자화/prompt/JSON schema/이미지 제한 고정 | MLX 파일을 이름만 바꿔 Windows로 가져올 수 없음. 현재의 생성 응답·제약 계약을 새 backend가 구현해야 함 |
| `lecture_study/direct_models.py:143-167,209-247` | 임베딩 receipt의 `arm64` 및 고정 revision, worker명·768차원·2048 context·mean pooling 확인 | `.exe` 및 x64 receipt 분기, 단순 architecture 검사 삭제는 부적절 |
| `macos/EmbeddingWorker.cpp:17-33` | SIGPIPE 처리, GPU layers 99, 4 threads, mean pooling | Windows SIGPIPE guard, binary stdin/stdout, CPU `n_gpu_layers=0` 필요 |
| `macos/EmbeddingCompat.hpp:3-6,47-67,74-106` | POSIX mmap/open/no-follow, 고정 Ollama 가중치와 tensor/metadata 변환 | Windows 파일 매핑 또는 검증한 native GGUF 경로 필요 |
| `scripts/build_embedding_worker.py:15-29,41-79` | llama.cpp b11669, dylib, arm64, clang/macOS linker 고정 | 같은 revision으로 Windows worker와 DLL 묶음을 빌드·검증 |
| `lecture_study/token_budget.py:45-64` | 직접 실행 tokenizer profile이 MLX manifest digest와 tokenizer.json에 의존 | GGUF tokenizer 사용/동일 tokenizer asset 연결과 model identity를 함께 교체해야 함 |
| `lecture_study/retrieval.py:239-319,352-398`, `lecture_study/schema.sql:108` | index의 model/digest/dim/format 저장 및 재확인, 새 index ready 후 active 전환 | 모델·pooling·tokenizer 변경 시 기존 벡터와 섞지 않고 재색인 |

## 1. ASR: whisper.cpp Windows CPU

공식 v1.9.5 릴리스는 nightly b5454를 연결한다. v1.9.5 태그 자산 목록에는 소스만 있고, b5454 자산 목록에는 **`whisper-bin-x64.zip`** CPU 후보가 실제 존재한다. 이를 CUDA ZIP과 혼동하면 안 된다. 게시 SHA256은 `6ba69e3482d7826214f90a6a9c84ca07782aec1e1d0c6a7c30c994fd5d816ccb`이다. [공식 릴리스](https://github.com/ggml-org/whisper.cpp/releases/tag/v1.9.5), [b5454 자산 목록](https://github.com/ggml-org/whisper.cpp/releases/expanded_assets/b5454).

현재 사용 중인 CLI의 `--version`, 출력 JSON, VAD 관련 인자는 고정 v1.9.5 소스에서 확인된다. `preview`는 Solasi의 청크/스케줄링과 CLI 옵션 조합이므로 Windows에서도 같은 경로를 살리는 것이 적절하다. 업스트림의 별도 streaming 예제로 전체 전사 구조를 바꿀 필요가 없다. [고정 CLI 소스](https://raw.githubusercontent.com/ggml-org/whisper.cpp/d1be6fde11ac6e0407606b4e42fe72d34add8037/examples/cli/cli.cpp).

**확인되지 않은 것:** ZIP 내부에 현재 Solasi가 요구하는 `whisper-vad-speech-segments.exe`까지 포함되는지, DLL/VC runtime 의존성, 한글·긴 경로에서 실행, 실시간 청크가 노트북에서 처리 속도를 따라가는지. 자산 목록 확인은 압축파일 내용 및 실기기 실행 검증을 대체하지 않는다. 누락된 utility가 있으면 CI에서 동일 고정 소스를 빌드하여 포함한다. FFmpeg/ffprobe는 별도 Windows 배포 자산이며 whisper ZIP의 존재로 확보되었다고 간주하지 않는다.

## 2. 생성과 이미지: llama.cpp Qwen3.5 4B

Qwen 공식 모델 카드는 Qwen3.5-4B를 vision encoder가 있는 causal LM으로 명시하고 Apache-2.0을 표시한다. 그 페이지의 기본 weights는 Transformers 형식이므로 GGUF 제공 여부와는 별개다. [Qwen 공식 모델 카드](https://huggingface.co/Qwen/Qwen3.5-4B/raw/main/README.md).

현재 임베딩이 고정한 llama.cpp revision `620d2225cc436ab0b001e3200e590e3b286ef9ab`(b11669/v0.7.0)에 Qwen3.5 텍스트 아키텍처 구현과 `Qwen3_5ForConditionalGeneration`의 vision projector 변환 등록이 실제 존재한다. 따라서 **소스 지원은 확인했지만 현재 Solasi의 Windows 이미지 실행은 미검증**이다. [Qwen3.5 모델 구현](https://raw.githubusercontent.com/ggml-org/llama.cpp/620d2225cc436ab0b001e3200e590e3b286ef9ab/src/models/qwen35.cpp), [텍스트 converter](https://raw.githubusercontent.com/ggml-org/llama.cpp/620d2225cc436ab0b001e3200e590e3b286ef9ab/conversion/qwen.py), [vision converter](https://raw.githubusercontent.com/ggml-org/llama.cpp/620d2225cc436ab0b001e3200e590e3b286ef9ab/conversion/qwen3vl.py).

이미지 경로는 `libllama` 단독으로 완성되지 않는다. 언어 GGUF 외에 대응 projector GGUF와 `libmtmd`가 필요하다. CPU 사용은 언어 모델의 GPU offload를 끄는 것에 더하여 projector의 `use_gpu=false`(CLI에서는 `--no-mmproj-offload`)까지 적용해야 한다. [멀티모달 문서](https://raw.githubusercontent.com/ggml-org/llama.cpp/620d2225cc436ab0b001e3200e590e3b286ef9ab/docs/multimodal.md), [mtmd 설명](https://raw.githubusercontent.com/ggml-org/llama.cpp/master/tools/mtmd/README.md).

Windows x64 CPU 배포 후보는 **`llama-b11669-bin-win-cpu-x64.zip`**이며 게시 SHA256은 `37b3efcf962847ca869745fd4ccf7f5e7e8dacfeff9fa3523b4ca8cdc66d632b`이다. 동일 b11669는 기존 Mac 임베딩 pin과 맞아 이식 시 변경 변수를 줄인다. 업스트림 CMake는 Windows shared library의 mtmd export를 명시하고, 공식 build 문서는 Windows x64 CPU 빌드를 설명한다. ZIP 내부 mtmd DLL·헤더·실행 파일의 정확한 목록은 아직 열어 검증하지 않았다. [b11669 자산](https://github.com/ggml-org/llama.cpp/releases/expanded_assets/b11669), [Windows build 문서](https://github.com/ggml-org/llama.cpp/blob/master/docs/build.md), [mtmd CMake](https://raw.githubusercontent.com/ggml-org/llama.cpp/master/tools/mtmd/CMakeLists.txt).

### 구현할 수 있는 직접 실행 계약

1. 앱이 소유하는 Windows C++ `ModelWorker.exe`에 현재와 같은 길이 제한 frame 입력을 보내고 stderr와 JSON 결과 채널을 분리한다. stdout/stdin은 Windows binary mode로 설정한다. 사용자가 compiler나 Python을 설치할 필요 없이 CI에서 exe와 DLL을 빌드한다.
2. 검증한 language GGUF와 **동일 모델에 대응하는** mmproj를 로컬 경로로 연다. `n_gpu_layers=0`, projector `use_gpu=false`, 명시적 context/output 예산을 사용한다. 모델 최대 context 262144를 16GB에서 기본 할당해도 된다는 의미로 해석하지 않는다.
3. 기존 `messages`의 system/user/assistant와 `enable_thinking=false`에 해당하는 template 처리, 최대 4개 PNG/JPEG, output limit, schema 제한을 보존한다. 이미지 token/position 계산은 `mtmd` helper를 사용한다. Qwen M-RoPE는 token 수와 position 수가 다를 수 있으므로 단순 `n_past += image_tokens`로 구현하지 않는다. [고정 mtmd API](https://raw.githubusercontent.com/ggml-org/llama.cpp/620d2225cc436ab0b001e3200e590e3b286ef9ab/tools/mtmd/mtmd.h), [고정 helper API](https://raw.githubusercontent.com/ggml-org/llama.cpp/620d2225cc436ab0b001e3200e590e3b286ef9ab/tools/mtmd/mtmd-helper.h).
4. `DirectModels.generate/status/pull`, 자산 검증, tokenizer profile, engine/model identity, context 한도, schema sampler를 하나의 backend 계약으로 연결한다. 기존 caller를 Ollama HTTP 형태로 바꾸는 것은 필수가 아니다.
5. `llama-mtmd-cli`는 이미지 smoke test용으로 사용할 수 있지만 업스트림 자체가 production-ready binary가 아니라고 명시한다. stdout 문자열을 대충 잘라 앱 응답으로 쓰는 방식은 현재 frame/schema/error 계약을 충족하지 못한다. [CLI 소스](https://raw.githubusercontent.com/ggml-org/llama.cpp/620d2225cc436ab0b001e3200e590e3b286ef9ab/tools/mtmd/mtmd-cli.cpp).

**Qwen GGUF 배포의 남은 선택:** 기존 Ollama registry의 `llamacpp` runner 자산이 upstream vanilla GGUF+projector인지, 별도 호환 계층이 필요한지는 manifest/layer와 실제 load로 확인해야 한다. 현재 `model_assets.py:93-117`는 `json/tensor/model` 이외 mediaType을 실행 자산 목록에서 건너뛴다. projector layer를 조용히 누락시키지 않도록 별도 처리한다. 이름이나 catalog의 digest만으로 로딩 가능성을 선언하지 않는다. 공식 Qwen/ggml-org의 `Qwen3.5-4B-GGUF` URL은 이번 web 도구에서 접근되지 않았으므로 해당 배포물이 확인됐다고 기록하지 않는다. 검증된 community 변환본을 배포 후보로 채택하거나 CI에서 공식 weights를 변환하되 파일별 SHA256·revision·license를 고정한다. 변환은 최종 사용자 PC에서 수행하지 않는다.

## 3. 임베딩: 현재 EmbeddingGemma 유지가 이식 범위를 줄임

현재 실제 direct embedding은 `embeddinggemma` v1이다. catalog의 `embeddinggemma-2:270m-mxfp8-text`는 MLX 전용이며 `DirectModels.asset` 지원 목록에 포함되지 않는다. 새 모델 이름이 catalog에 있다는 이유로 현재 semantic index가 v2로 구축된 것으로 해석하면 안 된다 (`local_models.py:15-16`, `direct_models.py:81-83`).

Google 문서는 v1을 308M 텍스트 임베딩, v2를 별도의 270M 텍스트 backbone과 multimodal 모델로 구분한다. v2의 라이선스·context·매체 기능을 현재 v1에 적용하면 안 된다. [Google 현재 문서](https://ai.google.dev/gemma/docs/embeddinggemma).

현재 v1 가중치는 Ollama 형태의 `gemma3` metadata와 dense tensor 이름을 포함한다. `EmbeddingCompat.hpp:64-106`는 이를 upstream `gemma-embedding`으로 변환하여 `llama_model_init_from_user`에 전달한다. 이 변환은 Windows 이식에서도 보존하거나, 검증된 native upstream GGUF로 바꾸면서 새 index identity를 부여해야 한다. Ollama 공식 호환 문서도 embedding markers가 있는 gemma3를 gemma-embedding metadata로 옮기고 dense/norm tensors를 보정한다고 설명한다. [Ollama 공식 compat 문서](https://github.com/ollama/ollama/blob/main/llama/compat/README.md).

선택지는 두 가지다.

| 후보 | 이점 | 필수 작업 |
|---|---|---|
| 기존 가중치+호환 worker를 Windows로 이식 | 모델·prompt·chunking·768 mean/L2를 유지 | POSIX mapping을 Windows API로 이식하거나 bounded read로 교체, 같은 pin/DLL로 build, 기존 출력 대비 벡터와 검색 회귀 확인 |
| upstream native EmbeddingGemma v1 GGUF+표준 libllama | Ollama metadata 호환 코드를 줄일 수 있음 | weights/tokenizer/quantization·pooling 검증, 새 digest/format, 원문에서 재색인 |

첫 구현은 기존 가중치와 계산 계약을 보존하는 쪽을 우선한다. 임베딩 모델 업그레이드는 Windows 지원의 필수 조건이 아니다. 동일 768차원이라도 다른 모델의 벡터 공간은 동일하지 않다. 기존 index는 `model/digest/format/dim`으로 구분하고 새 index를 완성한 후 active를 전환하는 현재 원자적 흐름을 유지한다 (`retrieval.py:286-323`). Windows CPU와 Mac Metal의 결과 차이가 허용 범위인지 확인되기 전에는 저장된 index의 무조건 호환을 약속하지 않는다.

EmbeddingGemma 2의 이미지 임베딩은 별도 위험이다. 업스트림 issue #30082에는 해당 revision 계열에서 서버 이미지 입력이 무시되어 text-only 벡터가 반환된 사례가 보고되어 있다. 이는 이번 환경에서 재현한 사실이 아니지만 v2의 지원 명칭만 믿고 이식하면서 멀티모달 검색까지 묶어 업그레이드해서는 안 되는 구체적 이유다. 현재 Solasi의 텍스트 semantic search에는 이 확장이 필요하지 않다. [업스트림 보고](https://github.com/ggml-org/llama.cpp/issues/30082).

## 4. 앱에 직접 포함 vs Ollama

| 방식 | 사용자 별도 설치 | 앱 종료 후 inference listener | 현재 코드와의 관계 | 판단 |
|---|---|---|---|---|
| 앱 소유 C++ worker + libllama/libmtmd | 없음 | 필요 없음 | 현재 direct frame/취소/프로세스 소유 모델 유지 | 우선 |
| 앱에 Ollama ZIP 포함 후 앱 소유 `serve` | 없음으로 구성 가능 | 앱이 종료 관리해야 함 | `OwnedOllama` 구조 재사용 가능하나 HTTP·port·identity·모델 포맷 계층 추가 | 직접 worker 구현이 막힐 때 비교 후보 |
| 사용자가 Ollama 설치 | 필요 | 기본 background API | 현재 배포 목표에 추가 설치 단계 발생 | 기본 배포에서 제외 |

Ollama 공식 Windows 문서는 native Windows background app과 localhost:11434 API를 설명한다. 독립 CLI ZIP도 제공하므로 'Ollama는 무조건 사용자가 설치해야 한다'는 주장은 틀리다. 다만 최종 목표인 앱 내부 직접 실행을 충족하려고 반드시 Ollama daemon을 도입할 필요도 없다. [Ollama Windows 문서](https://docs.ollama.com/windows).

현재 `OwnedOllama`는 app-owned port/model path, `OLLAMA_NO_CLOUD=1`, 버전 검증을 이미 구현하지만 standard `~/.ollama` identity와의 관련성을 주석으로 남긴다 (`local_models.py:29-56`). 실행 경로에 `.exe` 분기가 있는 것과 Windows runtime manifest가 준비된 것은 별개의 사실이다.

## 5. 기능 보존을 확인할 검증 순서

1. **배포물 검사:** 고정 ZIP/source SHA256 → exe/DLL/라이선스 목록 → PE x64 architecture → dependency/VC runtime 검사 → 개발 도구 없는 Windows VM에서 실행. ZIP 존재만으로 완전한 번들이라고 선언하지 않는다.
2. **ASR:** 현재 테스트 fixture WAV로 FFmpeg→Whisper→JSON 파싱·구간 시각 확인. 한국어 용어 prompt, VAD, preview, 취소, 실패 후 재시도, 파일 import, 선택적 실시간 전사 및 녹음 중 지연 누적까지 확인한다.
3. **생성:** 한국어 텍스트 요약, 같은 이미지에서 식별 가능한 내용 확인, 이미지가 없는 요청/다중 이미지/잘못된 파일, JSON schema 결과, output/context 한도, 취소와 worker crash 회복. 이미지가 바뀔 때 응답 또는 image prefill이 실제 달라지는지 확인한다.
4. **임베딩:** 정상/빈/잘못된 UTF-8/2048 초과 입력, finite·nonzero·768·L2, query/document prefix와 tokenizer, 같은 원문의 기존 worker 대비 cosine 및 검색 순위. index 중단 재개/엔진 변경/원자적 active 전환을 확인한다.
5. **16GB CPU 실기기:** 모델 warm/cold load, peak working set/private bytes, swap, ASR real-time factor, first-token/초당 token/요약 전체 시간, 이미지 prefill 지연, UI 응답·발열·배터리 영향을 측정한다. 모델의 파일 크기를 runtime RAM 또는 성능 수치로 대체하지 않는다. 측정 전 tok/s나 '실시간 가능' 보장은 하지 않는다.
6. **오프라인:** 모델 다운로드 완료 후 network를 끊고 녹음·전사·요약·이미지·semantic search를 실행한다. inference 중 외부 연결 및 앱 종료 후 자식 프로세스/listener 잔존을 점검한다.

## 부모 작업에서 이어 붙일 플랫폼 조사

다음 주제는 AI 엔진 조사와 독립된 플랫폼 검토 범위다. 이 섹션 아래에 해당 담당자가 현재 코드와 검증 근거를 추가할 수 있다.

### Windows 앱 shell과 패키징

### PDF·OCR 및 파일 연동

### 실행 환경·경로·설치·서명

## 초기 조사에서 실행하지 않은 항목

초기 조사 단계에서는 모델 다운로드·설치·Windows 빌드·벤치마크·앱 코드 변경을 수행하지 않았다. 이후 사용자의 구현 승인으로 아래 작업을 진행했다. Windows에서 실제 전체 기능이 동작한다는 결론은 아직 내리지 않는다.

## 구현 승인 후 AI 엔진 작업 기록

`lecture_study/windows_models.py`는 기존 DirectModels의 lock·취소·프로세스 회수·임베딩 계약을 재사용한다. Windows 생성 가중치는 [변환 배포자 metadata](https://huggingface.co/api/models/unsloth/Qwen3.5-4B-GGUF?blobs=true)의 고정 revision `e87f176479d0855a907a41277aca2f8ee7a09523`에서 Q4_K_M와 F16 mmproj를 선택했다. tokenizer와 라이선스는 [Qwen 공식 metadata](https://huggingface.co/api/models/Qwen/Qwen3.5-4B?blobs=true)의 revision `851bf6e806efd8d0a36b00ddf55e13ccb7b8cd0a`를 사용한다. 가중치·projector·tokenizer의 게시 LFS SHA256, 정확한 크기, 고정 URL과 실제 확인한 라이선스 SHA256을 코드에 기록했다. 모델 자체는 이번 작업에서 다운로드하지 않았다.

`windows/ModelWorker.cpp`는 libllama/libmtmd를 직접 사용하고 JSON schema를 실제 GBNF sampler로 적용한다. 모델을 HTTP server로 열지 않는다. `scripts/build_windows_models.py`는 SHA256 `1d4a987d9bd048f6e93107e838026438df70fbde237fc0c69c63d600512b4bd9`의 고정 llama.cpp source를 검사하고 두 worker를 static CPU executable로 빌드한다. Windows C++ runtime도 정적 링크 대상으로 설정했다. 범용 x64 기본 빌드는 AVX/AVX2/FMA/F16C를 끄며, 최적화 variant의 속도는 별도 측정 대상이다. Windows에서의 실제 executable 의존성 검사는 아직 필요하다.

Windows 생성 context 정책은 **한 번의 호출에 최대 8192 tokens**이다. 기존 Mac 모델의 262144-token 최대 context와 같다고 주장하지 않는다. `token_budget.effective_context`, `answers.freeze_request`, `outputs.check_budget`가 Windows 실행 요청을 이 한도에 맞추어 기존 긴 강의/요약/회의록 분할 흐름으로 전달한다. 원문을 버리거나 무음 truncation하지 않으며, 원본 설정 객체는 보존하고 frozen 실행 요청에 실제 한도를 기록한다. 32768을 요청한 긴 한국어 요약을 8192 단위의 여러 입력으로 나누어 모든 source text와 마지막 정정 문장이 남는 회귀 테스트를 통과했다. 기존에 승인된 다른 엔진용 frozen 작업은 호환성 검사를 우회하지 않는다.

Windows 경로는 native `wmain`에서 UTF-8로 변환하고 이미지 파일은 `std::filesystem::u8path`로 연다. EmbeddingGemma mapping은 UTF-8→wide `CreateFileW`/`CreateFileMappingW`를 사용한다. 고정 ggml 소스의 `ggml_fopen`도 UTF-8→wide `_wfopen` 구현임을 확인했다. 현재 Mac에서 실제 C++ worker를 고정 source와 CMake 3.31.6으로 compile/link하고 frame 경계·invalid 입력·한글 executable/이미지/model 경로 전달 검사를 통과했다. 이는 Windows CRT·Win32 mapping 실행 검증과 별개이며 Windows에서 같은 검사를 실행해야 한다. 실제 텍스트·이미지 모델 추론 테스트는 `SOLASI_GENERATION_WORKER`와 `SOLASI_GENERATION_MODEL_DIR`를 지정하여 실행할 수 있도록 두었다.

현재 Mac 코드에서 사용하던 EmbeddingGemma v1 가중치·query/document prefix·mean pooling·L2·768차원·index identity는 유지했다. EmbeddingGemma 2 또는 다른 모델 업그레이드는 포함하지 않았다.
