# Ollama 임베딩 계약

확인일: 2026-10-14 (Asia/Seoul)

범위: 공식 문서·Ollama **v0.40.3** 소스(commit `eab97e9f92b9a25c2d52d2cc6c1b1c99bd9fae21`)·공개 모델 manifest 조회. 모델 다운로드/pull, 서버 기동, 로컬 임베딩 추론은 수행하지 않았다. HTTP 응답 계약은 소스에서 확인했으며 이 PC의 실행 결과로 표현하지 않는다.

## 요청·입력 한도·오류

`POST /api/embed`의 텍스트 입력은 문자열 또는 문자열 배열이다. `truncate` 기본값은 true이므로 누락 방지를 위해 명시적으로 false를 전달한다. [공식 API](https://docs.ollama.com/api/embed)

```json
{"model":"embeddinggemma:300m","input":["title: 운영체제 | text: 프로세스는 실행 중인 프로그램이다."],"truncate":false}
```

v0.40.3의 실효 한도는 모델 context와 `options.num_ctx` 중 작은 값이다. tokenize 결과에 빠져 있는 BOS/EOS 토큰 공간을 추가로 예약할 수 있다. 따라서 모델의 2,048은 **토큰 한도**이며 문자·단어 한도가 아니다. 제목과 retrieval prefix도 한도에 들어간다. `num_ctx`를 크게 지정해도 모델의 훈련 context를 늘리지 않는다. [EmbedHandler 소스](https://github.com/ollama/ollama/blob/v0.40.3/server/routes.go#L1170-L1289)

초과 시 두 경로가 있다:

- 서버 사전 검사: **HTTP 400**, JSON `{"error":"the input length exceeds the context length"}`.
- 사전 검사 이후 runner가 context/physical batch 한도를 거부: llama runner는 같은 error 문자열의 **HTTP 413**으로 정규화한다. `truncate:false`이면 잘라 재시도하지 않고 해당 status를 전달한다.

한 배열 항목에서 실패하면 전체 batch가 오류이며 부분 벡터를 응답하지 않는다. 한도 오류일 때만 원문 위치를 보존해 작은 조각으로 분할하는 계약이 맞다. 다른 400·모델 누락 404·연결 실패를 길이 문제로 처리하지 않는다. [서버 처리](https://github.com/ollama/ollama/blob/v0.40.3/server/routes.go#L1228-L1360), [runner 오류 정규화](https://github.com/ollama/ollama/blob/v0.40.3/llm/llama_server.go#L2541-L2590)

빈 문자열/빈 배열은 `embeddings:[]`인 200 응답이 가능하므로 앱에서 빈 조각을 제외하고 벡터 수를 검사한다. 모델이 로컬에 없으면 오류를 반환하며 이 handler가 자동 pull을 수행하지 않는다. [입력·모델 검사](https://github.com/ollama/ollama/blob/v0.40.3/server/routes.go#L1098-L1160)

## 응답·차원·usage

| 필드 | 계약 |
|---|---|
| `model` | 요청 모델 이름 |
| `embeddings` | 입력 순서와 같은 `number[][]`; 내부 타입 float32 |
| `total_duration`, `load_duration` | nanoseconds |
| `prompt_eval_count` | 모든 입력의 처리 토큰 수 합; 항목별 usage 아님 |
| 차원·digest | 별도 응답 필드 없음 |

벡터는 L2 정규화된다. `dimensions`는 출력 벡터를 줄이고 다시 정규화하는 옵션이며, 입력 context를 줄이는 옵션이 아니다. 모델/runner가 허용 차원 집합을 제공하면 그 집합도 검사한다. 최초 벡터의 실제 길이를 기록하고 batch 전체의 수량·차원·finite 값·0이 아닌 norm을 검증한다. Google의 기존 300M 모델은 기본 768차원, MRL 512/256/128을 문서화하지만 실제 runner 응답 확인은 별도다. [공식 응답](https://docs.ollama.com/api/embed), [정규화·배열 순서](https://github.com/ollama/ollama/blob/v0.40.3/server/routes.go#L1306-L1390), [응답 타입](https://github.com/ollama/ollama/blob/v0.40.3/api/types.go#L630-L642), [Google 모델 카드](https://ai.google.dev/gemma/docs/embeddinggemma/model_card#inputs_and_outputs)

usage/duration 필드는 Go 타입에서 `omitempty`라 0이면 생략될 수 있다. llama runner의 오래된 array 응답 fallback도 token count 0을 반환한다. 누락 값을 실제 관측한 0으로 단정하지 않고 사용량 미제공으로 기록한다. [타입](https://github.com/ollama/ollama/blob/v0.40.3/api/types.go#L633-L642), [runner 파싱](https://github.com/ollama/ollama/blob/v0.40.3/llm/llama_server.go#L2500-L2538)

## 모델 식별과 retrieval prefix

`GET /api/tags`의 `models[].digest`는 **manifest digest**다. 가중치 blob의 SHA와 다르다. 단일 manifest는 자신의 digest, manifest list는 선택된 runnable child digest를 반환하고 `sha256:` 접두사를 제거한다. 태그 이름만으로 기존 벡터와 호환된다고 판단하지 않는다. 모델 이름·digest·실제 차원·prefix/청킹 버전을 index에 기록하고, 인덱싱과 질의에 같은 모델을 사용한다. [공식 tags](https://docs.ollama.com/api/tags), [목록 소스](https://github.com/ollama/ollama/blob/v0.40.3/server/model_list.go#L53-L115), [단일 manifest](https://github.com/ollama/ollama/blob/v0.40.3/server/model_list.go#L184-L200)

Google의 retrieval 형식은 다음과 같다. 제목이 없으면 `none`을 사용한다.

```text
query:    task: search result | query: {질문}
document: title: {자료 제목 또는 none} | text: {조각 원문}
```

Ollama EmbedHandler는 전달된 text를 runner에 넘기고 query/document 템플릿을 적용하지 않는다. 앱에서 입력 유형에 맞는 prefix를 붙이고 그 버전을 기록한다. [Google prompt 지침](https://ai.google.dev/gemma/docs/embeddinggemma/model_card#prompt_instructions), [runner 호출](https://github.com/ollama/ollama/blob/v0.40.3/server/routes.go#L1250-L1263)

## EmbeddingGemma 300M의 지원·크기·라이선스

2026-10-14 조회한 Ollama `embeddinggemma:latest`는 기존 **Gemma 3 기반 307.58M BF16** 모델이며 `300m` 별칭과 연결된다. 공식 요구 버전은 v0.11.10 이상이므로 v0.40.3의 문서 지원 범위에 포함된다. 기본 params는 `num_ctx:2048, num_batch:2048`다. [Ollama 모델 상세](https://ollama.com/library/embeddinggemma:latest)

| 현재 registry 메타데이터 | 값 |
|---|---|
| manifest digest | `85462619ee721b466c5927d109d4cb765861907d5417b9109caebc4e614679f1` |
| 모델 layer bytes | 621,867,104 (약 622 MB / 593 MiB) |
| 모델 layer SHA-256 | `0800cbac9c2064dde519420e75e512a83cb360de3ad5df176185dc69652fc515` |
| layers 합계 | 621,875,501 bytes; config 416 bytes 별도 |
| 라이선스 | Gemma Terms of Use; registry copy 날짜 2025-03-24 |

이는 [공개 registry manifest](https://registry.ollama.ai/v2/library/embeddinggemma/manifests/latest)의 작은 JSON과 설정·params·license layer만 읽은 결과다. **모델 layer를 다운로드하거나 해시 검증하지 않았다.** 다운로드 크기는 실제 RAM 사용량이 아니다. 실제 설치 후 digest는 로컬 `/api/tags`에서 다시 확인한다.

기존 300M은 100개 이상 언어로 학습한 텍스트 임베딩 모델이다. 제작자 논문 Table 12에 한국어(ko) XOR-Retrieve 결과가 명시돼 있어 한국어 검색 평가 근거가 있다. 해당 표는 cross-lingual retrieval 조건이며 이 앱의 한국어 강의·OCR·전문용어 검색 품질을 검증한 값은 아니다. [Google 모델 카드](https://ai.google.dev/gemma/docs/embeddinggemma/model_card), [한국어 평가](https://arxiv.org/html/2509.20354v1#A1)

주의할 세대 구분: Google의 공통 소개 페이지는 현재 **EmbeddingGemma 2, 740M multimodal, 8,192 tokens, Apache 2.0**을 먼저 소개한다. 이를 현재 Ollama 300M 태그의 기능·한도·라이선스로 적용하면 안 된다. [Google 소개의 새 모델과 이전 버전](https://ai.google.dev/gemma/docs/embeddinggemma#previous_versions)

기존 300M은 Gemma Terms다. 배포에는 약관 사본·사용 제한 고지·Notice 등 조건을 확인해 포함해야 한다. 코드 예제/문서의 Apache 또는 Ollama 엔진의 MIT와 모델 라이선스를 구분한다. [Gemma 약관 3.1](https://ai.google.dev/gemma/terms#distribution_and_redistribution)

미확인: 이 PC의 실제 모델 로딩·임베딩 수치·한국어 자료 검색 품질·전사와의 동시 실행 메모리/지연. 이번 조사는 제품 코드와 모델 상태를 변경하지 않았다.
