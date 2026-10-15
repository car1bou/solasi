# 수업·회의 앱의 기본 로컬 LLM 런타임 검토

확인일: 2026-10-13 (Asia/Seoul)

검토 범위: 로컬 FastAPI와 브라우저로 실행하는 수업·회의 앱. whisper.cpp 라이브 전사, PDF·이미지 자료 질의, 로컬 임베딩, 사용자 API 또는 로컬 생성, Apple Silicon macOS 우선·Windows 후속 지원을 전제로 한다. 현재 설계는 수업·회의 기록과 학습 지원 서비스 설계 (로컬 검증 자료·공개본 미포함)를 확인했다. 사용자의 추가 요청에 따라 실행 도구와 실제 모델을 함께 비교했다.

확인 수준: 공식 문서·프로젝트 소스·라이선스 조회. 패키지 설치, 모델 다운로드, 추론 실행, 패키징 실행 및 성능 측정은 수행하지 않았다. 저장소 `main`에 관한 항목은 실제 배포 버전과 다를 수 있다.

## 판단

**Ollama는 이 프로젝트의 첫 개발 런타임으로 합리적이다. 일반 사용자에게 기본 제공할 런타임의 최선인지는 앱이 관리하는 실행·모델 준비·메모리 정책과 실제 전사 동시 실행 결과까지 확인해야 한다.** 개발 편의성과 배포 적합성을 따로 평가한다.

현재 Ollama에는 MLX 엔진도 있다. 따라서 “Ollama는 llama.cpp의 포장이고 Mac에서는 MLX로 바꾸면 무조건 빨라진다”는 전제는 최신 상태와 맞지 않는다. Ollama의 관리 기능을 사용하면서 호환 모델을 MLX로 실행하는 선택도 가능하다. 아래 근거는 런타임 선택의 사실을 확인한 것이며, 이 앱의 성능 우열을 확인한 결과는 아니다.

## Ollama: 확인한 사실

| 항목 | 사실과 제품에 대한 의미 |
|---|---|
| 추론 엔진 | 2026-03-30에 Apple Silicon MLX preview를 발표했고, 2026-06-11에 MLX 엔진 개선을 발표했다. v0.40.3 소스는 `mlx`, `llamacpp`, `ggml` runner를 정의하며 Apple Silicon에서는 호환 manifest 선택 시 MLX를 우선한다. 모든 모델이 MLX 지원 모델이라는 뜻은 아니다. [MLX 발표](https://ollama.com/blog/mlx), [MLX 개선](https://ollama.com/blog/mlx-performance), [v0.40.3 manifest 소스](https://github.com/ollama/ollama/blob/v0.40.3/manifest/manifest.go) |
| 플랫폼 | macOS 문서는 Sonoma 14 이상, Apple M 시리즈 CPU·GPU와 x86 CPU를 지원 범위로 제시한다. Windows에는 공식 설치 프로그램과 standalone CLI 패키지가 있다. 지원 GPU·모델·runner 조합은 플랫폼별로 확인해야 한다. [macOS 문서](https://docs.ollama.com/macos), [Windows 문서](https://docs.ollama.com/windows) |
| API | `/api/chat`은 스트리밍, JSON/JSON schema 출력, 실행 옵션과 `keep_alive`를 문서화한다. `/api/embed`는 문자열 또는 문자열 배열의 임베딩을 생성한다. 임베딩 입력 초과는 기본 truncate하므로 자료 조각의 누락을 발견하려면 앱에서 길이를 분할하고 필요한 경우 `truncate=false`를 사용한다. [Chat API](https://docs.ollama.com/api/chat), [Embed API](https://docs.ollama.com/api/embed) |
| 이미지 | 이미지 지원 모델에 텍스트와 이미지를 함께 전달한다. REST API는 base64 이미지 배열을 받는다. 이는 이미지 질의 지원이며 PDF 추출·페이지 출처 관리까지 자동 제공한다는 뜻은 아니다. [Vision 문서](https://docs.ollama.com/capabilities/vision) |
| 모델 준비와 수명 | CLI에 `pull`, `ls`, `rm`, `ps`, `stop`, `serve`가 있다. 다운로드·목록·삭제·실행 상태·해제 기능을 앱이 이용할 수 있다. [CLI 문서](https://docs.ollama.com/cli) |
| 재배포 | Ollama 저장소의 MIT 라이선스는 배포·판매 등을 허용하며 저작권·허가 고지를 포함해야 한다. 모델은 별도 라이선스를 가진다. Ollama의 Modelfile 문서에도 공유·배포하는 모델의 `LICENSE`가 별도 항목이다. [Ollama LICENSE](https://github.com/ollama/ollama/blob/main/LICENSE), [Modelfile LICENSE](https://docs.ollama.com/modelfile#license) |

Windows 문서는 standalone CLI를 기존 애플리케이션에 포함하고 `ollama serve`로 실행하는 용도를 명시한다. macOS 문서는 앱 내부 CLI 경로 `Ollama.app/Contents/Resources/ollama`와 기본 위치 이외의 설치를 문서화한다. 따라서 **최종 사용자의 별도 Ollama 설치는 필수 조건이 아니다.** Ollama를 앱이 관리하는 보조 프로세스로 배포하는 설계는 가능하며, 실제 macOS 패키징·서명·라이브러리 포함·업데이트·정리 동작은 별도 확인 대상이다. 이는 문서와 라이선스에서 얻은 설계 판단이다. [Windows standalone CLI](https://docs.ollama.com/windows#standalone-cli), [macOS 설치 위치](https://docs.ollama.com/macos#changing-install-location), [라이선스](https://github.com/ollama/ollama/blob/main/LICENSE)

앱이 프로세스를 소유한다면 `OLLAMA_HOST`로 loopback 포트, `OLLAMA_MODELS`로 앱의 모델 보관 위치, `OLLAMA_NO_CLOUD=1`로 로컬 전용 경로를 지정할 수 있다. 설치된 사용자 Ollama를 공유한다면 앱의 설정 변경이 다른 앱에 미치는 영향을 따로 다뤄야 한다. [Ollama FAQ](https://docs.ollama.com/faq)

## MLX 계열: 확인한 사실

MLX는 Apple의 배열·기계학습 프레임워크이며, MLX-LM은 텍스트 모델 사용을 위한 패키지다. MLX-VLM은 별도 프로젝트의 비전 언어 모델 패키지다. 프레임워크, 텍스트 패키지, 비전 패키지를 하나의 완성된 소비자 앱으로 혼동하지 않는다. [MLX](https://github.com/ml-explore/mlx), [MLX-LM](https://github.com/ml-explore/mlx-lm), [MLX-VLM](https://github.com/Blaizzy/mlx-vlm)

| 항목 | 사실과 제품에 대한 의미 |
|---|---|
| 플랫폼 | MLX의 현재 설치 문서는 Apple Silicon macOS 14 이상에 더해 Linux CUDA·CPU 패키지도 설명한다. MLX-LM `main`의 pyproject는 Python 3.11 이상, MacOS/Linux 분류, CUDA·CPU extras를 포함한다. 따라서 “MLX 전체가 Mac 전용”은 부정확하지만, 검토한 Python 공식 설치 범위에서 Windows 소비자 배포는 확인하지 못했다. [MLX 설치](https://ml-explore.github.io/mlx/build/html/install.html), [MLX-LM pyproject](https://github.com/ml-explore/mlx-lm/blob/main/pyproject.toml) |
| 텍스트 API | MLX-LM은 Python `load`, `generate`, `stream_generate`와 HTTP 서버를 제공한다. Hugging Face 모델 또는 로컬 모델 경로를 사용한다. [MLX-LM README](https://github.com/ml-explore/mlx-lm) |
| 서버 범위 | `mlx_lm.server`는 OpenAI chat API와 비슷한 인터페이스다. 공식 SERVER 문서는 기본 보안 검사만 있으므로 production 사용을 권장하지 않는다고 명시한다. 앱 내부 사용의 가능성을 부정하는 문구는 아니지만, 이를 제품의 완성된 서버 계약으로 바로 채택해서는 안 된다. [SERVER.md](https://github.com/ml-explore/mlx-lm/blob/main/mlx_lm/SERVER.md) |
| 이미지와 임베딩 | 현재 MLX-VLM README는 이미지·텍스트 chat, `/v1/embeddings`, 모델 발견, `/unload`를 문서화한다. 이미지 질의를 위해 MLX-LM만 보는 것은 불충분하다. 추가 기능의 존재는 한국어 OCR·표·수식 이해나 검색 품질을 보장하지 않는다. [MLX-VLM README](https://github.com/Blaizzy/mlx-vlm) |
| 배포 구성 | Python 기반 FastAPI 앱에서는 MLX 모델을 직접 사용하는 구성 또는 별도 Python 프로세스 구성이 가능하다. Python 환경·의존성·모델 파일·프로세스 복구를 제품 배포에 포함하는 일은 앱의 책임이라는 설계 판단이다. 이미 Python을 사용하는 것만으로 관리 부담이 사라지는 것은 아니다. [MLX-LM Python API](https://github.com/ml-explore/mlx-lm), [의존성 정의](https://github.com/ml-explore/mlx-lm/blob/main/pyproject.toml) |
| 라이선스 | 검토한 MLX, MLX-LM, MLX-VLM 프로젝트 라이선스는 MIT다. 실제 포함하는 의존성과 모델의 고지는 따로 확인해야 한다. [MLX LICENSE](https://github.com/ml-explore/mlx/blob/main/LICENSE), [MLX-LM LICENSE](https://github.com/ml-explore/mlx-lm/blob/main/LICENSE), [MLX-VLM LICENSE](https://github.com/Blaizzy/mlx-vlm/blob/main/LICENSE) |

## 전사와 생성의 동시 실행

MLX의 배열은 공유 메모리에 있고 CPU/GPU가 데이터 복사 없이 접근한다. whisper.cpp도 Apple Silicon에서 Metal과 Core ML을 지원한다. **둘을 별도 프로세스로 나눠도 하드웨어 자원은 공유하므로**, 로컬 전사·생성·임베딩을 함께 실행하면 메모리와 GPU 처리 자원을 경쟁할 수 있다는 설계 추론이다. 전사에 Metal을 사용할지, Core ML을 사용할지, CPU를 사용할지는 아직 이 앱에서 확인하지 않았다. [MLX unified memory](https://github.com/ml-explore/mlx), [whisper.cpp](https://github.com/ggml-org/whisper.cpp)

Ollama는 `OLLAMA_NUM_PARALLEL`, `OLLAMA_MAX_LOADED_MODELS`, `OLLAMA_MAX_QUEUE`로 서버 내부 동시성과 대기를 조절한다. 병렬 수가 늘면 컨텍스트 메모리도 늘고, 메모리가 부족하면 요청이 대기하거나 모델이 교체된다. `keep_alive=0`은 응답 후 해제, 음수는 계속 상주다. 이 설정은 whisper.cpp를 포함한 앱 전체의 자원 스케줄러가 아니므로 앱에서도 전사 우선순위와 생성 작업 수를 제한해야 한다. [동시성·수명 FAQ](https://docs.ollama.com/faq)

MLX-LM은 prefill 단계 크기와 KV cache 크기를 조절한다. 작은 prefill 단계는 피크 메모리를 줄이지만 프롬프트 처리 속도에 비용이 있다. 공식 서버 문서는 `--kv-bits`를 사용하는 경우 batching을 지원하지 않는다고 적는다. 현재 MLX-VLM 문서는 continuous batching을 지원한다고 적으므로 두 서버의 옵션·제약을 동일하다고 가정하면 안 된다. [MLX-LM 긴 입력](https://github.com/ml-explore/mlx-lm#long-prompts-and-generations), [MLX-LM SERVER](https://github.com/ml-explore/mlx-lm/blob/main/mlx_lm/SERVER.md), [MLX-VLM batching](https://github.com/Blaizzy/mlx-vlm#continuous-batching)

MLX `set_memory_limit`은 그래프 실행의 메모리 가이드이며 프로세스 전체의 엄격한 RAM 상한이라고 문서화돼 있지 않다. `set_wired_limit`은 macOS 15 이상에서 의미가 있고 전체 메모리보다 작아야 한다. 다른 전사 프로세스와 OS까지 보호하는 것으로 오해하지 않는다. [memory limit](https://ml-explore.github.io/mlx/build/html/python/_autosummary/mlx.core.set_memory_limit.html), [wired limit](https://ml-explore.github.io/mlx/build/html/python/_autosummary/mlx.core.set_wired_limit.html)

초기 제품 정책 제안은 **전사 계속 실행, 생성은 한 작업, 대량 자료 임베딩은 낮은 우선순위**다. 사용자가 긴 생성 작업을 취소하거나 메모리가 부족할 때 앱의 작업 수를 줄이고 필요하면 모델을 해제한다. 이 정책은 현재 성능 측정으로 확정된 설정이 아니라 검증할 시작점이다.

## 기본값과 성능 해석의 한계

- Ollama FAQ는 기본 컨텍스트를 4096이라고 적지만 별도 Context length 문서는 VRAM별 4k/32k/256k 기본값을 제시한다. 문서 불일치가 있어 고정 기본값을 전제로 RAM을 계산하지 않는다. 앱은 선택한 모델의 컨텍스트를 명시하고 `ollama ps`에서 실제 할당을 확인한다. [FAQ](https://docs.ollama.com/faq), [Context length](https://docs.ollama.com/context-length)
- Ollama의 3월 MLX 발표 성능 비교는 같은 모델의 NVFP4와 기존 Q4_K_M을 비교한다. 이 수치를 순수 런타임 차이 또는 모든 Mac·모델의 속도 우열로 일반화하지 않는다. [측정 조건](https://ollama.com/blog/mlx)
- 엔진 비교는 같은 PC, 원본 모델·revision, 토크나이저·템플릿, 정밀도·양자화 품질, 입력·출력 길이, cache 상태·동시성을 맞춰야 한다. 형식 차이로 같은 양자화 가중치를 사용할 수 없으면 품질 차이와 조건 차이를 함께 기록한다. 이는 이 앱의 비교 실험 설계다.
- 생성 tokens/s만으로 기본 런타임을 고르지 않는다. 전사 중 첫 응답 시간, 전사 처리 지연·대기 누적, RAM·swap, 실패·취소 복구, 한국어 답변·자료 인용 품질, 첫 설치·모델 다운로드·업데이트가 실제 선택 기준이다.

## 바로 사용할 수 있는 선택 규칙

| 상황 | 제안 |
|---|---|
| 현재 개발과 첫 MVP | Ollama로 시작한다. 모델 준비·목록·해제와 텍스트/이미지/임베딩 경로를 이용하면서 앱 기능을 먼저 확인한다. 추론 엔진과 모델 지원을 버전별로 기록한다. |
| 일반 사용자에게 기본 제공 | 사용자가 앱 안에서 모델을 준비하고 사용하는 경험을 목표로 한다. Ollama를 앱이 관리하는 보조 프로세스로 포함하는 구성도 후보이므로, 별도 설치가 번거롭다는 이유만으로 배제하지 않는다. |
| Mac에서 특정 모델의 품질·메모리·지연이 부족함 | Ollama의 해당 모델·runner와 직접 MLX-LM/MLX-VLM을 같은 실제 업무로 비교한다. 직접 MLX에서 개선이 확인되면 그때 Mac 구현으로 채택한다. |
| 후속 Windows 지원이 중요함 | Python MLX를 공통 기본으로 확정하기 전에 Windows 실행·배포 범위를 확인한다. Ollama의 공식 Windows 경로는 현재 확인돼 있다. |

## 제품 기본값 확정 전에 남은 확인

1. 목표 Mac과 최소 RAM에서 전사 단독, 생성 단독, 전사+생성, 전사+임베딩을 같은 자료로 비교한다.
2. text/vision/embedding 각 후보의 실제 지원·모델 digest·출력 계약을 설치 버전에서 확인한다.
3. 깨끗한 사용자 계정에서 앱 첫 실행·모델 준비·네트워크 중단·재시작·취소·업데이트를 확인한다.
4. 앱이 관리하는 Ollama 또는 MLX 프로세스의 시작·종료·포트 충돌·모델 캐시·디스크 부족 처리를 확인한다.

아직 이 확인을 실행하지 않았으므로 어느 런타임이 이 앱에서 더 빠르거나 최종 배포에 더 안정적이라고 확정하지 않는다.

## llama.cpp와 LM Studio 비교

| 항목 | llama.cpp / llama-server | LM Studio / llmster |
|---|---|---|
| 플랫폼 | Apple Silicon Metal, Windows CPU/CUDA/Vulkan 등 공식 빌드 | macOS Apple Silicon·Windows·Linux 공식 지원 |
| 연결 | HTTP API 또는 C/C++ 라이브러리. 현재 FastAPI에는 앱 소유 자식 서버가 단순한 선택 | OpenAI 호환 API·자체 API·SDK. llmster는 GUI 없는 daemon |
| 기능 | 텍스트·지원 VLM·전용 모델의 임베딩 | 텍스트·지원 VLM·전용 모델의 임베딩 |
| 모델 관리 | v0.6.0 문서에 router·자동 로드·load/unload·다운로드 상태·idle sleep이 있음 | 다운로드·load/unload·JIT·TTL·Auto-Evict |
| 제품 배포 | MIT와 고지 조건. 앱이 엔진·모델·프로세스·복구 정책을 관리 | 설치된 사용자의 서버 연결은 지원. Desktop 약관의 재배포 제한과 llmster 동봉 허가 여부는 별도로 확인 필요 |
| 이 프로젝트 제안 | Ollama보다 직접 제어해야 할 요구가 생기거나 실제 문제가 해결되는지 비교할 대안 | 이미 사용하는 사람의 선택 연결 후보 |

플랫폼·기능 근거: [llama.cpp README](https://github.com/ggml-org/llama.cpp), [버전 고정 서버 문서](https://github.com/ggml-org/llama.cpp/blob/v0.6.0/tools/server/README.md), [멀티모달](https://github.com/ggml-org/llama.cpp/blob/master/docs/multimodal.md), [LM Studio 요구사항](https://lmstudio.ai/docs/app/system-requirements), [headless](https://lmstudio.ai/docs/developer/core/headless), [임베딩 API](https://lmstudio.ai/docs/developer/openai-compat/embeddings). 배포 조건 근거: [llama.cpp MIT](https://github.com/ggml-org/llama.cpp/blob/master/LICENSE), [LM Studio 약관](https://lmstudio.ai/app-terms).

llama.cpp가 추론 바이너리만 제공하고 모델 관리를 모두 직접 만들어야 한다는 설명은 현재 서버 문서와 맞지 않는다. LM Studio도 GUI가 필수이거나 내부 업무 사용이 금지된 도구가 아니다. 설치·실행과 앱 동봉의 권리는 별도다.

생성과 검색 임베딩은 서로 다른 모델이 필요하다. llama-server에서는 전용 서버 또는 router 구성이 가능하다. 공식 ggml-org 카드는 `llama-server -hf ggml-org/embeddinggemma-300M-GGUF --embeddings`를 안내하며 Q8_0 파일은 334 MB다. 파일 크기는 실행 RAM이나 검색 품질이 아니다. [공식 EmbeddingGemma GGUF](https://huggingface.co/ggml-org/embeddinggemma-300M-GGUF)

## 실제 로컬 모델 비교

Exa 검색의 요청 결과 수 합은 50건(주 작성자 13, 모델 조사 37)이다. 중복과 미적합 결과가 포함되며 50개가 모두 최종 근거라는 뜻은 아니다. 최종 근거는 제작자의 공식 모델 카드·저장소·라이선스로 한정했다. 사양은 확인한 사실, 아래 선택은 앱 요구를 바탕으로 한 설계 판단이다. 제작사 평가를 독립 재현이나 한국어 수업·회의 성능 순위로 표현하지 않는다.

| 모델 | 실제 규모·입력 | 한국어 관련 근거 | 라이선스 | 제안 |
|---|---|---|---|---|
| [Qwen3.5-4B](https://huggingface.co/Qwen/Qwen3.5-4B) | 언어 모델 4B + vision encoder, 텍스트·이미지·프레임 | 201개 언어·방언 지원, 이 앱의 한국어 인용·회의록 평가는 미확인 | Apache 2.0 | 기본 비교 후보, Q4부터 확인 |
| [Qwen3.5-9B](https://huggingface.co/Qwen/Qwen3.5-9B) | 언어 모델 9B + vision encoder, 같은 입력 | 같은 언어 범위, 일부 자체 장문·문서 평가가 4B보다 높음 | Apache 2.0 | 메모리 여유·품질 우선 비교 |
| [Gemma 4 E2B IT](https://huggingface.co/google/gemma-4-E2B-it) | 2.3B effective / embedding 포함 5.1B, 텍스트·이미지·오디오 | 140개 이상 언어로 학습, 한국어 앱 업무의 개별 평가는 미확인 | Apache 2.0 | 공식 QAT GGUF로 4B와 비교 |
| [Gemma 4 E4B IT](https://huggingface.co/google/gemma-4-E4B-it) | 4.5B effective / embedding 포함 8B, 텍스트·이미지·오디오 | E2B와 같은 언어 범위 | Apache 2.0 | Qwen 9B와 비교, 일반 4B RAM으로 계산하지 않음 |
| [EXAONE 4.0 1.2B](https://huggingface.co/LGAI-EXAONE/EXAONE-4.0-1.2B) | 총 1.28B, 텍스트 전용 | 한국어·영어·스페인어 명시, 한국어 자체 평가 | EXAONE 1.2-NC | 연구·교육의 저메모리 비교 |
| [EXAONE 3.5 7.8B](https://huggingface.co/LGAI-EXAONE/EXAONE-3.5-7.8B-Instruct) | 7.8B, 텍스트 전용 | 영어·한국어 bilingual 명시, 한국어 RAG 자체 평가 | EXAONE 1.1-NC | 기존 모델과 한국어 텍스트 대조 |
| [Phi-4-mini](https://huggingface.co/microsoft/Phi-4-mini-instruct) | 3.8B, 텍스트 전용 | 한국어 지원을 명시하나 영어 중심 학습·비영어 품질 차이를 설명 | MIT | 가벼운 텍스트 기준선 |

라이선스 원문: [Qwen](https://huggingface.co/Qwen/Qwen3.5-4B/raw/main/LICENSE), [Gemma 4](https://ai.google.dev/gemma/docs/gemma_4_license), [EXAONE 4.0](https://huggingface.co/LGAI-EXAONE/EXAONE-4.0-1.2B/raw/main/LICENSE), [EXAONE 3.5](https://huggingface.co/LGAI-EXAONE/EXAONE-3.5-7.8B-Instruct/raw/main/LICENSE), [Phi](https://huggingface.co/microsoft/Phi-4-mini-instruct/raw/main/LICENSE). EXAONE의 NC 체크포인트는 제품 기본 동봉과 상용 사용을 자유롭게 허용한다고 간주하지 않는다. 엔진 라이선스와 모델 라이선스는 각각 확인한다.

Qwen의 공식 공개 이력은 Qwen3.8까지 이어지지만 이번에 확인한 소형 4B·9B 후보는 Qwen3.5다. 최신 family 이름만 보고 소형 버전을 만들어 표기하지 않는다. EXAONE 4.0은 1.2B·32B 계열이며 최신 4.5는 총 33B 비전 모델이다. 4비트 packed tensor 목록의 크기 표시나 1.2B vision encoder를 전체 모델 규모로 읽지 않는다. [Qwen 공식 이력](https://github.com/QwenLM/Qwen3.6), [EXAONE 4.0](https://github.com/LG-AI-EXAONE/EXAONE-4.0), [EXAONE 4.5](https://github.com/LG-AI-EXAONE/EXAONE-4.5), [EXAONE 33B AWQ](https://huggingface.co/LGAI-EXAONE/EXAONE-4.5-33B-AWQ)

Google의 Gemma E2B Q4_0 2.9GB·E4B Q4_0 4.5GB는 가중치 로딩 추정이다. KV cache·추론 소프트웨어·전사·임베딩·OS까지 포함하는 전체 실행 RAM이 아니다. 실제 기기 RAM은 이번 조회에서 확인하지 못했다. [메모리 표와 제한](https://ai.google.dev/gemma/docs/core)

## 모델을 고르는 실제 확인 예

기본 Qwen3.5-4B Q4와 Gemma E2B IT QAT Q4_0을 같은 한국어 강의·회의·그림으로 비교한다. 메모리 여유가 있는 프로필은 Qwen9B와 Gemma E4B, 저메모리는 [Qwen3.5-2B](https://huggingface.co/Qwen/Qwen3.5-2B)를 추가 비교한다. 이 프로필이 특정 RAM에서 정상 동작한다는 보장은 하지 않는다.

| 입력 예 | 확인할 결과 |
|---|---|
| 이전 강의 정의와 현재 응용을 질문 | 실제 두 회차의 근거 위치, 다른 과목 배제 |
| 자료에 없는 정의·교수의 결정을 질문 | 근거 부족 표시, 웹 참고와 내부 기록 구분 |
| “검토해 보자”만 있는 회의 | 확정 결정으로 쓰지 않음, 없는 담당자·기한은 미정 |
| PDF 차트·수식·작은 글자 | 원본과 설명의 일치, 불확실한 수치 표시 |
| 녹음 중 질문·요약 | 원음 저장 지속, 첫 응답·전사 지연·대기·peak RAM/swap |
| 같은 요청을 재시도 | JSON schema 준수와 근거 ID 일치, 결과 중복 없음 |

Qwen의 thinking 모드와 직접 응답 모드도 같은 조건으로 비교한다. JSON 문법 준수와 인용 정확성은 서로 다른 확인 항목이다. Gemma 등의 오디오 입력 지원은 현재 whisper.cpp의 한국어 라이브 전사를 자동 대체하는 근거가 아니다. 엔진이 해당 모델의 이미지·오디오 기능을 실제 지원하는지 별도로 확인한다.

현 시점 권고는 **Ollama 0.40.3을 첫 실행 도구, Qwen3.5-4B를 기본 모델 후보, Gemma 4를 비교 후보**로 둔다. 최종 기본값은 위 앱 기능과 전사 동시 실행으로 확인한다. 하나의 실행 도구에 여러 모델을 둘 수 있고 생성 모델을 바꾸어도 RAG 자료와 원본 근거를 바꾸지 않는다.
