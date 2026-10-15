# Gemini·Claude BYOK HTTP 계약

확인일: 2026-10-14 (Asia/Seoul). 범위: 승인된 B2 계획 (로컬 검증 자료·공개본 미포함)의 Gemini `generateContent`, Claude `Messages`. 기존 [로컬 런타임 검토](2026-10-13-local-llm-runtime.md)와 [Ollama 계약](2026-10-14-ollama-provider-contract.md)을 읽었다. 공개 공식 문서·소스만 조회했다. 키 조회, 인증된 모델 목록 호출, 생성 API 호출, 모델 다운로드, 제품 코드·테스트 변경은 하지 않았다.

## 1. Gemini 구조화 출력 충돌과 최소 선택

| 확인한 공식 자료 | 실제 형식 |
|---|---|
| 현재 [Structured outputs 기본 안내](https://ai.google.dev/gemini-api/docs/structured-output) | `/v1beta/interactions`와 `response_format`. B2의 `generateContent`와 다른 API다. |
| [Legacy generateContent 안내](https://ai.google.dev/gemini-api/docs/generate-content/structured-output?hl=en) | REST 예제는 `generationConfig.responseFormat.text.{mimeType:"application/json",schema:...}` 객체다. |
| [generateContent REST reference](https://ai.google.dev/api/generate-content?hl=en#v1beta.GenerationConfig) | `responseFormat`은 객체, `text.mimeType`은 `APPLICATION_JSON` enum으로 설명한다. 이전 schema 필드에 deprecated 설명이 있고, `_responseJsonSchema`/`responseJsonSchema` 설명에도 내부 필드 표기가 혼재한다. |
| 공식 Python SDK 커밋 `8540d12f676aca015145a597e1be69aa07cdf988` (2026-10-13) | Gemini 변환은 `response_mime_type→responseMimeType`, `response_json_schema→responseJsonSchema`를 매핑한다. `response_format`은 Vertex GenerationConfig에서 list로 매핑하고 `ResponseFormat` 타입은 Gemini API 미지원으로 설명한다. [변환 소스](https://github.com/googleapis/python-genai/blob/8540d12f676aca015145a597e1be69aa07cdf988/google/genai/models.py#L1147), [타입](https://github.com/googleapis/python-genai/blob/8540d12f676aca015145a597e1be69aa07cdf988/google/genai/types.py#L11481) |
| 공식 공개 v1beta proto 마지막 변경 커밋 `bc7e3baa28fbb223fa93782e130260fab8205bfc` (2025-12-18) | 기존 MIME/schema 필드가 있고 새 `response_format`은 없다. 공개 proto가 최신 서버 전체를 설명한다고 단정할 수 없다. [proto](https://github.com/googleapis/googleapis/blob/bc7e3baa28fbb223fa93782e130260fab8205bfc/google/ai/generativelanguage/v1beta/generative_service.proto#L411) |

**구현 제안:** 현재 공식 SDK의 Gemini 변환과 일치하는 `responseMimeType + responseJsonSchema`를 B2의 첫 호환 형식으로 사용한다. 이는 조사에 따른 선택이며 실제 서버 수용을 검증한 결론은 아니다. 새 `responseFormat`의 객체/list 차이와 MIME 문자열/enum 차이는 사용자 키가 제공된 뒤 명시적인 계약 확인으로 해결한다. 두 형식을 동시에 보내거나 400 뒤 자동으로 다른 형식을 재호출하지 않는다. Interactions API 확장은 이번 범위에 없다.

### 최소 요청 예시

`POST https://generativelanguage.googleapis.com/v1beta/models/{MODEL_ID}:generateContent`

헤더: `x-goog-api-key: <저장된 키>`, `Content-Type: application/json`. 키를 URL query에 넣지 않는 방식을 사용한다. 현재 공식 안내는 authorization API key로의 전환을 설명하며, 과거 standard key의 지속 수용을 전제하지 않는다. [API key 안내](https://ai.google.dev/gemini-api/docs/api-key?hl=en)

아래 JSON은 작성한 계약 예시이며 실제 호출 결과가 아니다. MODEL_ID는 목록에서 확인한 식별자를 사용한다.

```json
{
  "systemInstruction": {"parts": [{"text": "제공한 근거로 답하고 근거 ID를 반환하세요."}]},
  "contents": [{"role": "user", "parts": [{"text": "[E1] 회의에서 일정 재검토가 제안됐습니다. 내용을 정리하세요."}]}],
  "generationConfig": {
    "maxOutputTokens": 1024,
    "responseMimeType": "application/json",
    "responseJsonSchema": {
      "type": "object",
      "properties": {
        "answer": {"type": "string"},
        "evidence_ids": {"type": "array", "items": {"type": "string"}}
      },
      "required": ["answer", "evidence_ids"],
      "additionalProperties": false
    }
  }
}
```

대화에서 assistant는 Gemini의 `role:"model"`로 매핑한다. 이미지 지원이 확인된 모델에만 같은 `parts` 배열에 아래 블록을 추가한다. DATA는 실제 이미지의 raw base64로 교체하며 Data URL 접두어나 로컬 경로를 보내지 않는다. [Content·Part·Blob 계약](https://ai.google.dev/api/generate-content?hl=en#v1beta.Content)

```json
{"inlineData": {"mimeType": "image/png", "data": "DATA"}}
```

### 응답 예시와 완료 판정

```json
{
  "candidates": [{
    "index": 0,
    "content": {"role": "model", "parts": [{"text": "{\"answer\":\"일정 재검토가 제안됐습니다.\",\"evidence_ids\":[\"E1\"]}"}]},
    "finishReason": "STOP"
  }],
  "usageMetadata": {
    "promptTokenCount": 90,
    "candidatesTokenCount": 28,
    "thoughtsTokenCount": 12,
    "totalTokenCount": 130
  },
  "modelVersion": "RETURNED_MODEL_VERSION",
  "responseId": "RETURNED_RESPONSE_ID"
}
```

- B2의 비스트리밍·단일 후보 요청은 candidate 0의 `thought!=true`인 text part만 연결한다. `promptFeedback.blockReason`, 후보 없음, text 없음, `finishReason!=STOP`을 명시 오류로 처리한다. `MAX_TOKENS`는 불완전 출력, `SAFETY/RECITATION` 등은 차단/중단이다. STOP 뒤에도 JSON 파싱과 앱 스키마·근거 ID 검증이 필요하다. [응답·후보·Part reference](https://ai.google.dev/api/generate-content?hl=en#v1beta.GenerateContentResponse)
- 사용량은 원래 이름으로 보존한다. `promptTokenCount`는 cached input을 포함하므로 `cachedContentTokenCount`를 다시 더하지 않는다. `candidatesTokenCount`와 `thoughtsTokenCount`를 구분하고 제공자가 준 `totalTokenCount`를 우선한다. 빠진 항목은 미확인이다. [UsageMetadata](https://ai.google.dev/api/generate-content?hl=en#v1beta.UsageMetadata)

## 2. Claude Messages 계약

현재 안정 형식은 `output_config.format = {type:"json_schema",schema:...}`이다. 이전 `output_format`은 deprecated beta이고, 안정 형식에는 structured-output beta 헤더가 필요 없다. `strict:true`는 tool schema용 별도 설정이다. [구조화 출력 안내](https://platform.claude.com/docs/en/build-with-claude/structured-outputs#using-a-raw-json-schema)

### 최소 요청 예시

`POST https://api.anthropic.com/v1/messages`

헤더: `anthropic-version: 2023-06-01`, `Content-Type: application/json`, `Authorization: Bearer <저장된 키>`. 기존 `x-api-key`도 공식적으로 지원한다. 한 요청에서 인증 방식을 하나로 정한다. [인증 안내](https://platform.claude.com/docs/en/manage-claude/authentication)

```json
{
  "model": "MODEL_ID_FROM_MODELS_API",
  "max_tokens": 1024,
  "stream": false,
  "system": "제공한 근거로 답하고 근거 ID를 반환하세요.",
  "messages": [{
    "role": "user",
    "content": [{"type": "text", "text": "[E1] 회의에서 일정 재검토가 제안됐습니다. 내용을 정리하세요."}]
  }],
  "output_config": {
    "format": {
      "type": "json_schema",
      "schema": {
        "type": "object",
        "properties": {
          "answer": {"type": "string"},
          "evidence_ids": {"type": "array", "items": {"type": "string"}}
        },
        "required": ["answer", "evidence_ids"],
        "additionalProperties": false
      }
    }
  }
}
```

system은 최상위 `system`이며 메시지 role은 user/assistant다. 이미지 입력이 확인된 모델에만 user content에 아래 블록을 추가한다. JPEG/PNG/GIF/WebP가 지원되는 media_type이며 MIME과 실제 파일 형식을 일치시킨다. [Messages 요청 reference](https://platform.claude.com/docs/en/api/messages/create)

```json
{"type": "image", "source": {"type": "base64", "media_type": "image/png", "data": "DATA"}}
```

직접 HTTP를 사용하므로 SDK가 자동 제거하는 제약을 기대하면 안 된다. 모든 object는 `additionalProperties:false`로 만들고, 기본 type/properties/required/items 중심으로 작성한다. numerical minimum/maximum/multipleOf, 문자열 minLength/maxLength, 재귀 schema 등 미지원 제약은 보내지 않는다. 숫자·길이·인용 위치는 앱에서 검증한다. 네이티브 citations와 JSON outputs는 함께 사용하면 400이며, 앱의 evidence_ids는 일반 JSON 필드로 사용한다. [스키마 제한과 기능 호환성](https://platform.claude.com/docs/en/build-with-claude/structured-outputs#json-schema-limitations)

### 응답 예시와 완료 판정

```json
{
  "id": "msg_EXAMPLE",
  "type": "message",
  "role": "assistant",
  "model": "RETURNED_MODEL_ID",
  "content": [{"type": "text", "text": "{\"answer\":\"일정 재검토가 제안됐습니다.\",\"evidence_ids\":[\"E1\"]}"}],
  "stop_reason": "end_turn",
  "stop_sequence": null,
  "usage": {
    "input_tokens": 90,
    "output_tokens": 28,
    "cache_creation_input_tokens": 0,
    "cache_read_input_tokens": 0
  }
}
```

- B2는 text 블록만 연결하고 thinking/tool 블록은 답으로 합치지 않는다. `stop_reason:"end_turn"` 뒤 JSON·앱 검증에 성공한 경우만 완료로 처리한다. `max_tokens`, `model_context_window_exceeded`, `pause_turn`, `tool_use`, 미설정 stop_sequence 등은 별도 상태다. [Messages 응답 reference](https://platform.claude.com/docs/en/api/messages/create)
- `refusal`은 HTTP 200일 수 있고 schema를 따르지 않을 수 있다. 거절을 JSON 파싱 실패에 숨기지 않는다. `stop_details`가 있으면 type을 확인하며 category/explanation은 null일 수 있고 설명 문구는 불안정하다. 토큰 제한 출력도 완성된 JSON으로 저장하지 않는다. [거절·중단 안내](https://platform.claude.com/docs/en/build-with-claude/structured-outputs#invalid-outputs), [중단 사유 reference](https://platform.claude.com/docs/en/api/messages/create)
- `usage.input_tokens`, `cache_creation_input_tokens`, `cache_read_input_tokens`는 서로 구분하며 전체 입력은 세 항목의 합이다. 캐시 값이 null/누락이면 정확한 전체 입력을 미확인으로 둔다. `output_tokens`는 표시된 문자 수와 같지 않으며 빈 text에도 0이 아닐 수 있다. 원본 사용량을 보존하고 가격은 별도 기준으로 계산한다. [Usage reference](https://platform.claude.com/docs/en/api/messages/create)
- 공식 문서는 enum의 대소문자가 달라질 수 있다고 설명한다. 공통 어휘 enum을 선택할 때 대소문자만 다른 값을 만들지 않는다. **근거 ID는 대소문자를 바꾸지 않고 원본과 정확히 대조한다.** [enum 제한](https://platform.claude.com/docs/en/build-with-claude/structured-outputs#invalid-outputs)

## 3. 모델 목록: 접근 확인과 기능 확인

| 제공자 | 목록·특정 모델 확인 | 기능 판정 |
|---|---|---|
| Gemini | `GET /v1beta/models`, `GET /v1beta/models/{id}`; `nextPageToken→pageToken`으로 전체 조회. `name`, `supportedGenerationMethods`에 generateContent, `inputTokenLimit/outputTokenLimit` 확인. | 목록 Model 스키마에 image-input/structured-output bool이 없다. 정확한 모델별 공식 기능표를 함께 사용한다. 예: 현재 [gemini-3.8-flash](https://ai.google.dev/gemini-api/docs/models/gemini-3.8-flash)는 이미지 입력·텍스트 출력·structured outputs를 명시한다. 목록에 있다는 사실만으로 vision을 켜지 않는다. [Models REST](https://ai.google.dev/api/models) |
| Claude | `GET /v1/models`; `has_more`면 `after_id=last_id`로 진행. `GET /v1/models/{model_id}`는 alias를 실제 ID로 해결한다. | `capabilities.image_input.supported`, `capabilities.structured_outputs.supported`를 직접 확인한다. capabilities와 `max_input_tokens/max_tokens`는 null일 수 있다. lifecycle=retired 모델은 선택하지 않는다. [목록](https://platform.claude.com/docs/en/api/models), [특정 모델](https://platform.claude.com/docs/en/api/models/retrieve) |

**상태 예:** 목록 요청 성공 → credential/model lookup 확인; 해당 기능 메타데이터·공식 기능표 확인 → documented capability; 해당 기능 실제 생성 성공 → runtime 확인. 앞 두 상태만으로 과금·quota·실제 생성 성공을 표시하지 않는다. unknown capability는 false로 표시하고 근거 날짜/출처를 보존한다.

## 4. 구현·확인 경계

1. 인증키는 OS credential/session 메모리에서 헤더에만 넣고, provider 오류를 사용자 메시지로 옮길 때 Authorization/x-api-key, 요청 body, 원문 exception을 노출하지 않는다.
2. 400/401/403/404/429/timeout, 차단·거절·불완전 출력·스키마 실패를 구분한다. 외부 제공자 실패 후 로컬/다른 제공자를 자동 호출하지 않는다. 이는 승인된 앱 정책이다.
3. 동일 최소 schema로 text 완료, capability 확인 뒤 image 완료, truncation/refusal/no-candidate/누락 usage를 부모 구현의 mock 계약에서 다룬다. 이 연구에서는 제품 테스트를 작성하거나 실행하지 않았다.
4. **미확인:** 사용자 키의 현재 접근 권한·quota, 실제 HTTP 응답, Gemini 새 responseFormat 수용 및 MIME 표현, 해당 모델의 한국어 인용·이미지 해석 품질. 키가 제공된 뒤 선택된 모델로 명시적인 실제 확인이 필요하다. 본 문서의 JSON은 설명용이며 실측 결과가 아니다.

출처 고정 확인: SDK main 파일 두 개는 위 커밋 원문과 byte 일치, 공개 proto도 마지막 파일 변경 커밋과 byte 일치를 확인했다. 문서 페이지는 2026-10-14 조회본이며 이후 변경될 수 있다.
