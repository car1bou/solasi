# Ollama 생성 모델 준비 계약

확인일: 2026-10-14 (Asia/Seoul)

범위: 공식 registry의 작은 manifest/config/params/license, Ollama **v0.40.3** 소스(`eab97e9f92b9a25c2d52d2cc6c1b1c99bd9fae21`), API 문서 조회. 가중치 다운로드/pull·서버 기동·추론·제품 코드 변경은 수행하지 않았다. 파일 크기는 다운로드 데이터이며 실행 RAM·성능을 뜻하지 않는다.

## 같은 태그의 두 실행 파일 구성

`qwen3.5:4b`와 `qwen3.5:9b`는 MLX/safetensors와 llama.cpp/GGUF child를 가진 manifest list다. v0.40.3은 Darwin arm64에서 **MLX→llamacpp→ggml**, 다른 플랫폼에서 **llamacpp→ggml→MLX**를 우선한다. 따라서 Mac 준비 동의에 GGUF 크기만 제시하면 기본 선택과 맞지 않는다. `/api/pull`, `/api/chat`, `/api/show`의 `runner` 필드로 명시할 수 있다. [선택 소스](https://github.com/ollama/ollama/blob/v0.40.3/manifest/manifest.go#L843-L857), [PullRequest 타입](https://github.com/ollama/ollama/blob/v0.40.3/api/types.go#L813-L822), [공식 4B](https://ollama.com/library/qwen3.5:4b), [공식 9B](https://ollama.com/library/qwen3.5:9b)

### 빈 캐시 기준 다운로드 bytes

아래 “payload”는 선택된 child의 **unique layers + config** 합계다. 두 모델 모두 child 내부 중복 digest가 없었다. HTTP headers·인증 요청·재시도와 파일시스템 overhead는 제외한다. 실제 기존 blob을 재사용하면 새 다운로드는 줄어든다.

| 태그·runner | 가중치 bytes | 이미지 구성 | 기타 layers + config | payload bytes | parent+child JSON 포함 |
|---|---:|---|---:|---:|---:|
| 4B llamacpp | 언어 모델 2,648,593,216 | projector 675,569,120 | 11,598 | **3,324,173,934** (3.324 GB / 3.096 GiB) | 3,324,175,492 |
| 4B MLX | 모든 tensors 3,953,741,896 | tensor 합계 안에 vision 667,061,456 포함 | 19,563,117 | **3,973,305,013** (3.973 GB / 3.700 GiB) | 3,973,456,016 |
| 9B llamacpp | 언어 모델 5,629,109,120 | projector 921,704,832 | 11,598 | **6,550,825,550** (6.551 GB / 6.101 GiB) | 6,550,827,108 |
| 9B MLX | 모든 tensors 7,619,594,552 | tensor 합계 안에 vision 912,057,944 포함 | 19,634,879 | **7,639,229,431** (7.639 GB / 7.115 GiB) | 7,639,445,283 |

MLX의 vision 값은 layer 이름으로 분류한 소계이며 별도 projector 다운로드로 더하지 않는다. 9B MLX tensor 합계에는 MTP tensors 486,582,864 bytes도 포함된다. 현재 9B MLX params에는 `draft_num_predict:3`이 있다. 모델 layer로 실제 받은 값을 확인한 것이 아니라 **공개 manifest를 합산한 값**이다.

두 태그를 같은 빈 저장소에 준비하면 shared layers는 llama.cpp 11,421 bytes, MLX 19,548,226 bytes다. 두 모델의 unique payload 합계는 각각 **9,874,988,063**과 **11,592,986,218 bytes**다. 기존 EmbeddingGemma의 비용은 이 표에 포함하지 않는다. 그 모델은 [별도 계약](2026-10-14-embedding-contract.md)을 사용한다.

합계의 재현용 고정 메타데이터: [4B MLX child JSON](https://registry.ollama.ai/v2/library/qwen3.5/blobs/sha256:7f3251fa6878a78a606bcb3c074283306e5ad2ea411a7774a9dd98a4bc7f2d13), [9B MLX child JSON](https://registry.ollama.ai/v2/library/qwen3.5/blobs/sha256:d63f830f28d515fefea546f213fca7a75e9dd5176ef51a6deabc952d1c99a911). 이 링크는 tensor 파일이 아닌 작은 manifest JSON이다.

### 조회 시점의 digest

`/api/tags`는 selected child의 manifest digest를 기록한다. 부모 list digest와 언어 가중치 blob SHA를 구분한다.

| 항목 | SHA-256 |
|---|---|
| 4B 부모 list | `492e37dc69072c5a189a0cf21d32d844c983d599e4553a1e4d2ebd3f6b1299e2` |
| 4B llamacpp child | `d8b0f5e9760cd1682034f292d7ef72ec46f432149be0df7574bf2d6e92e38c04` |
| 4B MLX child | `7f3251fa6878a78a606bcb3c074283306e5ad2ea411a7774a9dd98a4bc7f2d13` |
| 9B 부모 list | `fdf5fd4cd409881fac86077d7be23e1cb1a4d1c0083108ff81ad557b3dfd7b01` |
| 9B llamacpp child | `56671c2ab9385f9cfcb404638e32cd62d88e3501d44822208363c010179a3c90` |
| 9B MLX child | `d63f830f28d515fefea546f213fca7a75e9dd5176ef51a6deabc952d1c99a911` |

Registry 조회는 `Accept: application/vnd.ollama.manifest.list.v2+json, application/vnd.docker.distribution.manifest.v2+json`을 사용한다. Docker manifest만 요청하면 classic GGUF 구성만 받을 수 있다. child JSON은 `/manifests/<digest>`가 아닌 **`/blobs/sha256:<child-digest>`**로 읽는다. 각 child JSON의 실제 SHA가 부모의 digest와 일치함을 검증했다. [4B registry](https://registry.ollama.ai/v2/library/qwen3.5/manifests/4b), [9B registry](https://registry.ollama.ai/v2/library/qwen3.5/manifests/9b), [공식 Accept 구성](https://github.com/ollama/ollama/blob/v0.40.3/server/images.go#L1610-L1618), [child 처리](https://github.com/ollama/ollama/blob/v0.40.3/server/images.go#L1388-L1434)

가중치 blob의 기대 SHA는 GGUF 4B 언어 `a9d0a3e1d8c91732a3812becd31f8d4a8ff57414903f226306069f0437e2ac50` / vision `e56a899b1540860385465756dd308c84417410b94dbc1c380adffd20a921ca60`, 9B 언어 `02d45dc1cf451ba2475ac33b301c2dd8f985abe4c182ce04a1f2f5bf0260278d` / vision `f836f08f921193f4d6b6a6952dba0a6fb116759d26a757bcb395d570d73976ca`다. **가중치 자체는 아직 다운로드하거나 SHA 검증하지 않았다.**

## 라이선스·버전·지원

네 child 모두 **Apache 2.0** license layer를 포함한다. license 텍스트를 읽고 해당 small blob SHA를 검증했다. GGUF 및 9B MLX license SHA는 `50cbab8a892c5f2993b8c7351a99182507472def3b1374558308605d99b86b32`, 4B MLX는 `5f3a3c817e78f5b8a4ad2d2c458a3e4b2cce470d6c12642c4eeb12cb8a9bf51d`다. 배포할 때 모델의 license/고지를 보존한다. Ollama 엔진의 라이선스와 별도로 취급한다. [Qwen 공식 license](https://huggingface.co/Qwen/Qwen3.5-4B/blob/main/LICENSE), [Ollama 4B의 license](https://ollama.com/library/qwen3.5:4b)

현재 registry config의 최소 요구 버전은 GGUF 두 모델 **0.30.0**, 4B MLX **0.19.0**, 9B MLX **0.22.0**이다. 따라서 v0.40.3의 버전 조건은 충족한다. 이는 이 PC의 실제 추론 성공을 확인한 결과가 아니다.

MLX config에는 4B `completion/vision/thinking`, 9B `completion/vision/tools/thinking`이 선언돼 있다. GGUF는 두 모델에 projector가 포함돼 있다. 실제 선택된 모델의 `POST /api/show`를 읽어 `capabilities`에 **`vision`**이 있는지 확인한다. REST 이미지 입력은 `messages[].images`의 **raw base64 배열**이며, SDK의 파일 경로 입력과 혼동하지 않는다. [show 문서](https://docs.ollama.com/api-reference/show-model-details), [vision REST](https://docs.ollama.com/capabilities/vision)

구조화 출력은 `/api/chat`의 `format:<JSON schema>`, `stream:false`다. vision 요청에도 같은 format을 사용한다. v0.40.3 MLX client는 schema를 structural grammar로 변환하며 xgrammar 준비에 실패하면 **501: structured output is unavailable** 오류를 낼 수 있다. `capabilities`에 별도 `structured_outputs` 플래그가 있다고 가정하지 않는다. 실제 준비 후 작은 schema 응답을 검사해야 한다. [구조화 출력](https://docs.ollama.com/capabilities/structured-outputs), [MLX schema 변환](https://github.com/ollama/ollama/blob/v0.40.3/mlxrunner/client.go#L159-L185), [MLX 준비 오류](https://github.com/ollama/ollama/blob/v0.40.3/mlxrunner/grammar.go#L143-L162)

## 로컬 프로세스·요청 설정

| 설정 | v0.40.3 계약 |
|---|---|
| `OLLAMA_HOST` | 기본 `http://127.0.0.1:11434`; 앱 소유 서버는 전용 loopback 포트를 지정 |
| `OLLAMA_MODELS` | 모델 저장 경로; 기본 사용자 홈의 `.ollama/models`; 앱 전용 절대 경로 사용 가능 |
| `OLLAMA_NO_CLOUD=1` | Ollama cloud inference·web search 비활성화; 모델 pull 등 모든 네트워크를 차단하는 설정은 아님 |
| `OLLAMA_NUM_PARALLEL=1` | 모델당 병렬 요청 한도; v0.40.3 기본도 1. 앱 전체 전사/생성 스케줄러는 별도 |
| `options.num_ctx` | 생성 요청의 context 설정; 앱의 승인된 예는 8192. 기본값은 VRAM 기반 4K/32K/256K이므로 명시하고 실제 `/api/ps` context_length를 확인 |

`OLLAMA_MODELS`는 홈 전체를 바꾸는 값이 아니다. 기존 사용자 서버에 연결하는 경우 환경·모델 저장소·프로세스를 임의로 변경하지 않는다. [환경 소스](https://github.com/ollama/ollama/blob/v0.40.3/envconfig/config.go), [FAQ](https://docs.ollama.com/faq), [context 설정](https://docs.ollama.com/context-length)

요청 형태 예(실행하지 않음):

```json
{"model":"qwen3.5:4b","runner":"mlx","stream":false,"think":false,"options":{"num_ctx":8192},"messages":[{"role":"user","content":"질문"}],"format":{"type":"object","properties":{"answer":{"type":"string"}},"required":["answer"]}}
```

## 원격 모델 판별

`/api/tags`의 모델 row와 `/api/show` 응답, 생성/채팅 응답 타입에는 `remote_model`, `remote_host`가 있다. 비어 있으면 생략될 수 있다. **endpoint가 loopback인 것만으로 모델이 로컬이라고 단정하지 않는다.** 로컬 모델 선택에서는 해당 필드가 있는 원격 모델과 명시적 `:cloud` source 요청을 제외하고, 앱 소유 서버에 NO_CLOUD를 지정한다. 서버의 remote proxy 경로도 NO_CLOUD 상태를 검사한다. [타입](https://github.com/ollama/ollama/blob/v0.40.3/api/types.go#L763-L783), [tags 필드](https://github.com/ollama/ollama/blob/v0.40.3/api/types.go#L888-L899), [source 판별](https://github.com/ollama/ollama/blob/v0.40.3/server/model_resolver.go#L27-L43), [chat 원격 경로](https://github.com/ollama/ollama/blob/v0.40.3/server/routes.go#L2993-L3028)

준비 동의에 제시할 값: **정확한 모델 태그·runner·새 다운로드 bytes·저장 위치·license**. 현재 조회 digest를 기록하고 실제 준비 때 다시 비교한다. tag 변경, 재시도, 기존 cache 여부 때문에 위 합계를 실제 전송량의 보장으로 표현하지 않는다.

미확인: 실제 Qwen 로딩·schema/이미지 응답·한국어 근거 인용 품질·M4 16GiB에서 전사/임베딩 동시 실행 RAM과 지연. 모델 준비 전 검증 완료로 표시하지 않는다.


## 모델 저장소와 사용자 홈의 분리 범위

v0.40.3 tag는 commit `eab97e9f92b9a25c2d52d2cc6c1b1c99bd9fae21`로 확인했다. **`OLLAMA_MODELS`는 모델 저장 경로만 바꾼다. 앱 소유 `ollama serve`의 키·설정까지 private 디렉터리로 격리하는 설정은 아니다.** 아래는 실제 사용자 파일을 읽은 결과가 아니라 고정 공식 소스의 호출 경로 확인이다. [고정 tag 참조](https://api.github.com/repos/ollama/ollama/git/ref/tags/v0.40.3), [Models 경로](https://github.com/ollama/ollama/blob/eab97e9f92b9a25c2d52d2cc6c1b1c99bd9fae21/envconfig/config.go#L104-L117)

| 파일·상태 | `serve` 및 관련 명령의 동작 |
|---|---|
| `~/.ollama/id_ed25519`·`id_ed25519.pub` | `RunServer`는 listen 전에 `initializeKeypair`를 실행한다. 개인키 존재를 stat하고, 없으면 홈의 `.ollama`를 생성하여 개인키 0600·공개키 0644로 저장한다. 기존 개인키가 있으면 초기화에서는 덮어쓰지 않는다. 새 공개키는 stdout에도 표시한다. |
| `~/.ollama/server.json` | `Serve → internalcloud.Status → NoCloudSource → loadServerConfig`가 읽는다. `NoCloudSource`는 `OLLAMA_NO_CLOUD=1`이어도 설정 파일을 읽는다. 확인한 serve 경로의 이 함수는 설정 파일을 쓰지 않는다. |
| 개인키 내용·registry 인증 | `auth.Sign`·`GetPublicKey`는 기본 홈의 개인키를 읽는다. registry challenge 처리도 `auth.Sign`을 호출하므로 모델 pull 인증에서 기존 사용자 키를 사용할 수 있다. `NO_CLOUD`를 인증/파일 격리 설정으로 해석하지 않는다. |
| `~/.ollama/config.json` | CLI launcher·integration 설정 경로다. 확인한 `serve` 단독 경로에는 이 설정의 load/save 호출이 없다. 관련 CLI 명령은 기본 홈을 사용하며 legacy `config/config.json`을 이동·삭제하는 migration도 있다. |
| `~/.ollama/history` | interactive `run`의 readline 생성 과정이 파일을 생성/읽는다. `OLLAMA_NOHISTORY`는 이후 기록 저장을 비활성화하므로 초기 파일 접근까지 방지하지 않는다. 확인한 `serve` 단독 경로에는 readline 호출이 없다. |

근거: [서버 시작·키 생성](https://github.com/ollama/ollama/blob/eab97e9f92b9a25c2d52d2cc6c1b1c99bd9fae21/cmd/cmd.go#L2223-L2284), [serve 시작](https://github.com/ollama/ollama/blob/eab97e9f92b9a25c2d52d2cc6c1b1c99bd9fae21/server/routes.go#L2371-L2375), [cloud Status](https://github.com/ollama/ollama/blob/eab97e9f92b9a25c2d52d2cc6c1b1c99bd9fae21/internal/cloud/policy.go#L9-L16), [server.json 로딩·NoCloudSource](https://github.com/ollama/ollama/blob/eab97e9f92b9a25c2d52d2cc6c1b1c99bd9fae21/envconfig/config.go#L368-L438), [키 읽기](https://github.com/ollama/ollama/blob/eab97e9f92b9a25c2d52d2cc6c1b1c99bd9fae21/auth/auth.go#L21-L68), [registry 서명](https://github.com/ollama/ollama/blob/eab97e9f92b9a25c2d52d2cc6c1b1c99bd9fae21/server/auth.go#L53-L75), [CLI 설정·migration](https://github.com/ollama/ollama/blob/eab97e9f92b9a25c2d52d2cc6c1b1c99bd9fae21/cmd/config/config.go#L83-L181), [history 초기화](https://github.com/ollama/ollama/blob/eab97e9f92b9a25c2d52d2cc6c1b1c99bd9fae21/readline/history.go#L24-L79), [readline constructor](https://github.com/ollama/ollama/blob/eab97e9f92b9a25c2d52d2cc6c1b1c99bd9fae21/readline/readline.go#L48-L63), [NOHISTORY 적용 순서](https://github.com/ollama/ollama/blob/eab97e9f92b9a25c2d52d2cc6c1b1c99bd9fae21/cmd/interactive.go#L118-L130)

확인한 환경 설정과 위 키/config/history 함수에는 private root를 지정하는 `OLLAMA_HOME`·config/key 경로 override가 없다. 해당 함수들은 `os.UserHomeDir()`와 고정 상대 경로를 결합한다. `XDG_CONFIG_HOME`이나 `OLLAMA_MODELS`가 이를 바꾼다고 가정하지 않는다. 운영 규칙에 따라 `HOME`은 재지정하지 않는다. [환경 설정 목록](https://github.com/ollama/ollama/blob/eab97e9f92b9a25c2d52d2cc6c1b1c99bd9fae21/envconfig/config.go#L293-L342)

최소 분리 운영 예:

1. 앱 소유 child process에 private `OLLAMA_MODELS`, 전용 loopback `OLLAMA_HOST`, `OLLAMA_NO_CLOUD=1`, `OLLAMA_DEBUG_LOG_REQUESTS=false`를 지정하고 stdout/stderr를 앱 로그 경로로 받는다. serve의 기본 서버 로그는 stderr이며, 요청 본문 로그는 별도 opt-in temp 파일이다. [서버 logger](https://github.com/ollama/ollama/blob/eab97e9f92b9a25c2d52d2cc6c1b1c99bd9fae21/server/routes.go#L2371-L2375), [요청 로그 gate](https://github.com/ollama/ollama/blob/eab97e9f92b9a25c2d52d2cc6c1b1c99bd9fae21/server/inference_request_log.go#L24-L46)
2. 앱 대화는 REST API로 호출한다. interactive CLI·launcher를 실행하지 않아 그 경로의 history·integration 설정 부작용을 피한다.
3. 모델·포트 분리와 함께 **키/server.json은 기존 사용자 홈과 공유한다**는 계약을 유지한다. 앱 정리 시 사용자 홈의 키·설정을 삭제하지 않는다. 엄격한 전체 격리가 필요하면, 표준 환경변수만으로 충족한다고 주장하지 않고 별도 OS 사용자·격리 실행 환경 또는 경로를 수정한 빌드를 검토한다. 이 대안들의 Mac GPU 호환성은 이번 조사에서 검증하지 않았다.

이번 확인에서는 서버 실행·모델 다운로드·실제 사용자 키/설정/history 조회를 수행하지 않았다. 공유 홈의 어떤 파일이 현재 존재하는지도 확인하지 않았다.
