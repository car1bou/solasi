# C3 로컬 그림 질문: Ollama 이미지·JSON 출력 계약

확인일: 2026-10-14 (Asia/Seoul)

범위: Ollama **v0.40.3**, 후보 `qwen3.5:4b`와 `qwen3.5:4b-mlx`. 목표 PC는 사용자에게 전달받은 Mac M4 / 16 GiB이며 API 키가 없다. PC 사양과 설치 상태를 이번 조사에서 직접 조회하지 않았다. 공식 문서·고정 버전 소스만 읽었으며 모델·미디어 다운로드, 앱 실행, 추론, 설치, 코드 수정은 수행하지 않았다.

## 확인 결과

**v0.40.3의 MLX Qwen3.5에는 실제 이미지 처리 구현과 JSON / JSON Schema 제약 출력 구현이 모두 있다. 같은 요청의 이미지와 `format`을 MLX runner로 전달한다. 특정 설치·모델에서 C3가 성공했다는 실행 결과는 아직 없다.** [MLX Qwen3.5 vision](https://github.com/ollama/ollama/blob/v0.40.3/mlxrunner/model/qwen3_5/vision.go), [completion client](https://github.com/ollama/ollama/blob/v0.40.3/mlxrunner/client.go), [pipeline](https://github.com/ollama/ollama/blob/v0.40.3/mlxrunner/pipeline.go)

| 질문 | 현재 근거로 확인한 사실 | 미확인 경계 |
|---|---|---|
| MLX Qwen3.5가 이미지를 받는가? | `Model`이 `MediaModel`을 구현한다. `PrepareMedia`가 이미지 토큰·전처리 픽셀·배치 layout을 만들고, `EncodeMedia`가 vision tower를 실행한다. 이미지 데이터를 버리고 텍스트 placeholder만 처리하는 구조가 아니다. [Qwen3.5 model](https://github.com/ollama/ollama/blob/v0.40.3/mlxrunner/model/qwen3_5/qwen3_5.go), [vision](https://github.com/ollama/ollama/blob/v0.40.3/mlxrunner/model/qwen3_5/vision.go), [media](https://github.com/ollama/ollama/blob/v0.40.3/mlxrunner/media.go) | 내려받은 모델 manifest·vision weights·배포 runner가 이 계약에 맞는지 실행하지 않았다. |
| 이미지와 구조화 JSON을 동시에 사용하는가? | `Client.Completion`은 `Media`와 변환한 `Format`을 함께 전달한다. `Runner.Prepare`는 grammar를 준비한 다음 media를 처리하고, 생성 decoder는 grammar token mask를 적용한다. 공식 문서에도 vision과 `format`을 함께 사용하는 예제가 있다. [client](https://github.com/ollama/ollama/blob/v0.40.3/mlxrunner/client.go), [pipeline](https://github.com/ollama/ollama/blob/v0.40.3/mlxrunner/pipeline.go), [공식 structured outputs](https://docs.ollama.com/capabilities/structured-outputs) | 특정 모델의 이미지+스키마 요청 성공과 실제 해석 정확도는 미검증이다. |
| `/api/show`로 vision을 판정하는가? | 응답의 `capabilities` 배열에 `vision`이 있는지 확인할 수 있다. 이는 선택한 manifest의 모델 metadata·projector·config 등으로 계산한 지원 표시다. [Show 문서](https://docs.ollama.com/api-reference/show-model-details), [ShowResponse](https://github.com/ollama/ollama/blob/v0.40.3/api/types.go), [capability 계산](https://github.com/ollama/ollama/blob/v0.40.3/server/images.go) | `vision`이 있어도 vision tower 로드·이미지+schema 실행 성공을 검증한 응답은 아니다. 구조화 JSON 전용 capability 항목은 확인되지 않았다. |
| `4b`가 항상 GGUF이고 `4b-mlx`만 MLX인가? | v0.40.3은 manifest list를 지원한다. darwin/arm64의 기본 선호 순서는 MLX → llama.cpp → ggml이다. `runner`를 명시하면 해당 child를 선택한다. 현재 `4b` 공식 페이지에는 MLX tensor 구성과 GGUF/projector 구성 모두가 보이며 `4b-mlx` 페이지에는 MLX tensor 구성이 보인다. [manifest 선택](https://github.com/ollama/ollama/blob/v0.40.3/manifest/manifest.go), [4b 페이지](https://ollama.com/library/qwen3.5:4b), [4b-mlx 페이지](https://ollama.com/library/qwen3.5:4b-mlx) | 태그 문자열만으로 사용자의 설치에서 실제 선택된 runner·digest를 확정하지 않는다. 두 태그가 반드시 서로 다른 엔진 비교라는 보장도 없다. |

공식 릴리스 페이지에서 v0.40.3 태그를 확인했다. 문서·모델 라이브러리 페이지는 버전 고정 자료가 아니며 이후 바뀔 수 있다. 아래 소스 근거는 전부 v0.40.3으로 고정했다. [릴리스](https://github.com/ollama/ollama/releases/tag/v0.40.3)

## 이미지 요청과 이미지 제한

- REST `/api/chat`은 메시지의 `images` 배열에 base64 이미지 데이터를 받는다. 메시지에는 질문 `content`도 함께 들어간다. SDK의 파일 경로·URL 편의 기능과 REST의 base64 계약을 구분한다. [Vision 문서](https://docs.ollama.com/capabilities/vision), [API Message / ImageData](https://github.com/ollama/ollama/blob/v0.40.3/api/types.go)
- Qwen3.5 MLX의 `PrepareMedia`는 여러 segment를 순회하며 이미지마다 전처리한다. vision tower가 로드되지 않았으면 `this model does not support … input`, 이미지 이외의 media이면 `qwen3.5 does not support … input` 오류가 난다. [vision.go, PrepareMedia](https://github.com/ollama/ollama/blob/v0.40.3/mlxrunner/model/qwen3_5/vision.go)
- `preprocessImage`는 `image.Decode`로 실제 이미지 bytes를 디코딩한다. 실패는 `decode image: …` 오류다. 확장자 이름만으로 입력을 받아들이는 함수가 아니다. 이번에 확인한 문서는 Ollama의 전체 이미지 codec·애니메이션 처리 계약을 열거하지 않는다. 앱이 관리하는 페이지 PNG의 실제 디코딩 성공은 남은 확인이다. [process_image.go](https://github.com/ollama/ollama/blob/v0.40.3/mlxrunner/model/qwen3_5/process_image.go)
- `smartResize`는 높이·너비가 0 이하이면 오류, 긴 변 / 짧은 변이 **200을 넘으면 오류**를 반환한다. 높이·너비를 `patch_size * spatial_merge_size` 배수로 맞추고, 종횡비를 보존하며 이미지 면적 예산을 **65,536–16,777,216 pixels**에 맞춰 확대·축소한다. 이는 원본 파일 bytes 상한이나 PC 메모리 상한이 아니다. [process_image.go, smartResize](https://github.com/ollama/ollama/blob/v0.40.3/mlxrunner/model/qwen3_5/process_image.go)
- 기본 vision config의 patch size는 16, spatial merge size는 2다. 이미지 토큰 수는 전처리 grid 높이 × grid 너비 / merge²이며, 이미지 expansion에는 시작·종료 토큰도 붙는다. 이미지가 늘거나 해상도가 높아지면 입력 토큰 수가 늘어난다. `Runner.Prepare`는 확장 후 입력 토큰 수가 context length 이상이면 오류를 반환하고, 남은 context에 맞춰 생성 길이를 제한한다. [vision.go](https://github.com/ollama/ollama/blob/v0.40.3/mlxrunner/model/qwen3_5/vision.go), [process_image.go](https://github.com/ollama/ollama/blob/v0.40.3/mlxrunner/model/qwen3_5/process_image.go), [pipeline.go, Prepare](https://github.com/ollama/ollama/blob/v0.40.3/mlxrunner/pipeline.go)
- 검토한 Qwen3.5 MLX media 처리에는 고정된 한 장 제한이 보이지 않는다. 서버의 한 장 제한은 `mllama` family에 대한 분기다. 이를 Qwen3.5에 적용하지 않는다. 검토한 `/api/chat` 경로에서 공통 파일 bytes·이미지 개수의 명시적 수치 상한은 확인하지 못했다. 무제한이라는 뜻은 아니다. [prompt.go, imageTaggedMessages](https://github.com/ollama/ollama/blob/v0.40.3/server/prompt.go), [routes.go](https://github.com/ollama/ollama/blob/v0.40.3/server/routes.go)

## JSON 출력의 조건과 실패

`format: "json"`은 MLX client에서 `{"type":"object"}` 스키마로 변환된다. JSON Schema 객체를 `format`에 주면 `json_schema` structural tag로 감싸서 xgrammar에 전달한다. 따라서 JSON mode와 특정 필드·타입을 강제하는 schema mode는 구분된다. [client.go, requestGrammar](https://github.com/ollama/ollama/blob/v0.40.3/mlxrunner/client.go)

MLX grammar engine은 tokenizer, 유효 vocabulary, native library, xgrammar compiler 준비에 실패하면 사용할 수 없다. 이 상태의 구조화 출력 요청은 runner에서 **501 `structured output is unavailable`**을 반환한다. 내부 grammar는 **1 MiB 이하, 중첩 깊이 128 이하**여야 하고 UTF-8·JSON·structural tag 검사를 통과해야 한다. compiler가 스키마를 거부하면 **400 `invalid structured output grammar`** 오류가 있다. 이 한계는 JSON 응답의 최대 길이라는 뜻이 아니다. [grammar.go, newGrammarEngine / prepare / parseGrammar / compile](https://github.com/ollama/ollama/blob/v0.40.3/mlxrunner/grammar.go)

제약 생성은 출력이 완결되었다는 실행 증거를 대신하지 않는다. 생성 토큰 제한, context 부족, 취소, runner 오류로 중단한 응답이 앱의 결과 schema를 충족했는지는 별도 확인 대상이다. 공식 예제도 응답을 schema로 다시 검증한다. [공식 출력 검증 예제](https://docs.ollama.com/capabilities/structured-outputs), [pipeline 생성 길이 제한](https://github.com/ollama/ollama/blob/v0.40.3/mlxrunner/pipeline.go)

vision config가 있으나 vision weights가 없으면 load 단계에서 오류가 난다. vision tensors가 있으나 `vision_config`가 없는 조합도 오류다. `deepstack_visual_indexes`가 비어 있지 않은 config는 이 버전에서 지원하지 않는다. 이 때문에 원본 Qwen 모델의 이미지 능력과 특정 Ollama 변환 모델·runner 조합을 같은 증거로 취급할 수 없다. [vision.go, parseMultimodalConfig / loadVisionWeights](https://github.com/ollama/ollama/blob/v0.40.3/mlxrunner/model/qwen3_5/vision.go)

## `/api/show` 확인 계약

버전 고정 source의 `ShowRequest`는 `model`, 선택적인 `runner`, `all_manifests`, `verbose`를 포함한다. `ShowResponse`에는 `capabilities`, `details`, `manifests`가 있으며 `details`에는 `format`과 `runner`, 각 manifest summary에는 `digest`, `runner`, `format`, `selected`가 있다. docs 페이지의 간단한 OpenAPI에는 이 모든 추가 필드가 설명되어 있지는 않다. [api/types.go](https://github.com/ollama/ollama/blob/v0.40.3/api/types.go), [Show 공식 문서](https://docs.ollama.com/api-reference/show-model-details)

아래는 요청 형태 예시이며 이번 조사에서 호출하지 않았다.

```json
{"model":"qwen3.5:4b","runner":"mlx","verbose":false}
```

지원 표시 판정은 응답의 `capabilities`에 정확한 문자열 `vision`이 있는지에 기반한다. `ShowHandler`가 돌려주는 값은 `m.publicCapabilities()`이고 일반 모델에서는 config, GGUF vision metadata, projector 등으로 계산한다. API 키 존재 여부나 모델 이름의 `qwen` / `mlx` 문자열만으로 vision을 판정하지 않는다. [routes.go, ShowHandler / GetModelInfo](https://github.com/ollama/ollama/blob/v0.40.3/server/routes.go), [images.go, Capabilities / publicCapabilities / configCapabilities / projectorCapabilities](https://github.com/ollama/ollama/blob/v0.40.3/server/images.go)

## 아직 실행하지 않은 확인

다음 목록은 실행 결과가 아니라 C3의 남은 확인 계약이다.

1. 실제 Ollama 버전과 두 후보의 설치 여부, model tag·selected digest·runner·format·`vision` capability 응답을 기록한다.
2. 관리된 PNG 한 장과 질문을 사용해 텍스트 답변, `format: "json"`, 앱의 JSON Schema를 각각 요청하고 오류·완료 상태와 schema 검증 결과를 기록한다.
3. 그림을 보지 않고도 맞힐 수 있는 설명만으로 성공을 판단하지 않는다. 입력 그림과 맞는 관찰·내용이 있는지 원본과 대조한다.
4. 같은 자료에서 Korean text, 도표·색·화살표, 작은 글자와 이미지 영역 출처 연결이 실제로 맞는지 확인한다.
5. M4 / 16 GiB에서 페이지 해상도·context·생성 길이별 RAM / swap·실패와 전사 동시 실행을 측정한다. 모델 파일 크기를 실행 RAM으로 간주하지 않는다.

이번 기록은 공식 소스의 지원 계약을 확인한 것이다. **사용자 PC의 C3 성공, 한국어 해석 정확도, 지연, 메모리 적합성은 미확인이다.**

## 구조화 출력 제약 재확인 — 2026-10-14

실제Qwen4B의 출처 ID 오류와 서술형 선택지 오류를 재현한 뒤 전달 출처 enum과 choice/free anyOf, 정확히5개 배열 조건을 추가했다. 서버의 원래 인용·문제 검증은 유지한다. [OpenAI strict schema](https://developers.openai.com/api/docs/guides/structured-outputs?api-mode=responses#supported-schemas)와 [Gemini JSON Schema subset](https://ai.google.dev/api/generate-content#GenerationConfig)은 해당 문자열 enum·중첩anyOf·minItems/maxItems를 지원한다고 명시한다. OpenAI fine-tuned 모델은 배열 제약을 지원하지 않는 추가 제한이 있다.

[Claude 공식 제한](https://platform.claude.com/docs/en/build-with-claude/structured-outputs#json-schema-limitations)은 배열 minItems의0/1만 지원하고 maxItems를 지원하지 않는다. HTTPX에는SDK 변환이 없으므로 Claude 전송 사본에서만 maxItems와 minItems>1을 제거한다. 질문5개·객관식2~6개·서술형 빈 선택지는 서버가 계속 검사하며, 지시문에도 명시한다. 원본 schema를 바꾸지 않는 계약 테스트를 통과했다. 제공자 문서 확인과 mock 성공은 실제API 수락/품질 검증과 구분한다. 외부API 키는 사용하지 않았다.
