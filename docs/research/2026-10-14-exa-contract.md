# Exa Search HTTP 계약

확인일: 2026-10-14 (Asia/Seoul). 승인된 B4 계획 (로컬 검증 자료·공개본 미포함)에 필요한 공식 공개 문서와 OpenAPI만 읽었다. Exa 검색·키 조회·제품 코드·제품 테스트는 실행하지 않았다.

## 요청과 응답

`POST https://api.exa.ai/search`는 `Content-Type: application/json`, `x-api-key: <Exa API 키>`를 사용한다. `Authorization: Bearer <키>`도 지원하지만 앱은 한 방식만 사용한다. `query`는 길이 1 이상 문자열, `type:"auto"`는 현재 지원/default, `numResults:5`는 지원 범위 1–100 안이다. 최대 5개 요청이지 항상 5개를 보장하지는 않는다. `contents.highlights:true`는 현재 정식 지원이며 beta 헤더가 필요 없다. [Search reference](https://exa.ai/docs/reference/search), [공식 OpenAPI](https://exa.ai/docs/exa-spec.json), [Highlights 안내](https://exa.ai/docs/search/highlights)

아래는 **실제로 실행하지 않은 설명용 요청·응답 한 쌍**이다. 응답 URL과 구절은 예시이며 조사에서 얻은 실제 검색 결과가 아니다.

요청:

```json
{
  "query": "나선형 학습 개념 정의",
  "type": "auto",
  "numResults": 5,
  "contents": {"highlights": true}
}
```

설명용 응답:

```json
{
  "requestId": "EXAMPLE_REQUEST_ID",
  "results": [
    {
      "id": "EXAMPLE_TEMPORARY_ID",
      "title": "예시 자료 제목",
      "url": "https://example.org/spiral-learning",
      "publishedDate": "2026-10-01T00:00:00Z",
      "highlights": ["실제 요청에서는 이 위치에 검색 페이지에서 추출한 구절이 반환됩니다."]
    }
  ]
}
```

| 필드 | 확인한 계약·앱 처리 |
|---|---|
| `results` | 배열. 검색 결과는 관련성으로 정렬되며 pagination은 제공하지 않는다. 빈 배열은 정상적인 결과 없음이다. |
| `results[].url/title` | OpenAPI의 필수 문자열. 실제 반환 URL만 사용하고 앱은 http/https 허용 여부를 따로 검사한다. |
| `highlights` | **`string[]`**. request의 highlights 옵션은 bool/object 모두 가능하지만 response의 highlights는 객체 배열이 아니다. 문자열만 trim하여 빈 구절을 제외한다. 객체를 문자열로 강제 변환해 근거로 쓰지 않는다. |
| `publishedDate` | 선택적 문자열이며 HTML에서 추정한 생성일이다. 누락 시 미확인으로 두며 조회 시각을 대신 넣지 않는다. 예제는 date-time이지만 설명에는 YYYY-MM-DD도 있어 원문 값을 보존한다. |
| `author/id/highlightScores` | 선택적 metadata. id는 임시 document ID이며 영구 앱 근거 ID로 그대로 쓰지 않는다. highlightScores가 반드시 있다고 가정하지 않는다. |
| `requestId/costDollars/searchTime` | 선택적으로 보존 가능. 누락 사용량·비용을 0으로 만들지 않는다. searchTime은 서버 처리 ms이며 전체 클라이언트 지연과 같지 않다. `resolvedSearchType`은 deprecated/빈 문자열 가능이므로 분기 기준으로 쓰지 않는다. |

위 타입은 공식 OpenAPI의 `SearchResultsResponse/SearchResultOutput`을 직접 확인했다. 생성형 `outputSchema`를 요청하지 않는 B4는 `results` 응답을 사용한다. [OpenAPI](https://exa.ai/docs/exa-spec.json), [Search 안내](https://exa.ai/docs/search/quickstart)

**metadata와 본문 근거:** `contents`를 생략한 검색은 제목·URL·날짜 등의 metadata만 반환한다. 이번 요청은 highlights를 명시해 query 관련 발췌를 요청한다. 그래도 개별 결과의 highlights가 없거나 빈 경우에는 “본문 근거 미확인”으로 표시하고 답변의 웹 Evidence로 넣지 않는다. URL/title은 본문 주장을 확인한 증거가 아니다. highlights는 페이지 전체나 원본 위치 offset을 보장하지 않는다. 반환 구절·URL·실제 retrieved_at을 함께 보존한다. [공식 검색 참조](https://github.com/exa-labs/agent-skills/blob/main/skills/build-with-exa/references/search.md), [발췌 계약](https://exa.ai/docs/search/highlights)

## 오류·timeout

| 상태 | 처리에 필요한 확인 사실 |
|---|---|
| 400/401/402/403 | 각각 요청 형식/키/credits·budget/접근·정책 문제. 오류 문자열을 성공 결과로 전달하지 않는다. |
| 429 | key/team/network의 rate 또는 concurrency 한도. `Retry-After`가 있으면 기다리고 없으면 backoff하는 것이 공식 안내다. B4 최소 구현에서는 명시 실패와 사용자 재시도로 처리할 수 있다. |
| 500/503 | 서버 오류/과부하·가용성 문제. 공식 문서는 503 요청이 처리되지 않았고 과금되지 않는다고 설명한다. 이 보장을 다른 오류·client timeout에 확장하지 않는다. |
| 504 | 공식 오류 안내에는 처리 deadline 초과가 있다. 현재 /search OpenAPI의 명시 응답 목록에는 504가 없지만 generic HTTP 오류로 수용한다. |
| HTTP 클라이언트 timeout | 응답을 못 받은 별도 상태. 서버 미처리·무과금을 입증하지 않는다. 실패를 표시하고 앱이 자동으로 추가 과금 검색을 반복하지 않는다. |

오류 JSON은 `requestId/error/tag`다. 먼저 HTTP status로 처리하며 tag 집합은 열린 계약이므로 모르는 tag를 파싱 오류로 만들지 않는다. 요청 body·키·원문 exception을 사용자 응답/로그에 그대로 노출하지 않는다. `contents.livecrawlTimeout`은 웹페이지 live crawl에 대한 ms 한도이고 HTTP 클라이언트 전체 timeout이 아니다. /contents의 URL별 crawl status를 /search 전체 실패 형식으로 혼동하지 않는다. [Error codes](https://exa.ai/docs/admin/error-codes), [Rate limits](https://exa.ai/docs/admin/billing), [ContentsOptions OpenAPI](https://exa.ai/docs/exa-spec.json)

## 앱 커넥터·배포 API 키와 확인 경계

- Codex/ChatGPT의 Exa 플러그인은 계정 로그인으로 MCP 도구를 제공한다. 별도 앱 코드에서 HTTPS Search API를 호출하는 방식은 Exa API 키를 설정하는 별도 연결이다. **현재 Codex의 커넥터 연결을 배포 앱의 키로 간주하거나 커넥터의 토큰을 추출하지 않는다.** [Codex·ChatGPT 연결](https://exa.ai/docs/integrations/chatgpt-codex), [공식 quickstart의 두 연결 방식](https://exa.ai/docs/get-started/quickstart)
- B4 구현 정책: 사용자가 검색 칸에 직접 입력하고 검색을 실행한 용어 query만 전송한다. 강의/회의 원문·전체 질문·개인 이름을 앱이 자동으로 검색어에 추가하지 않는다. 외부 결과는 지시문으로 실행하지 않고 웹 참고로 분리한다. 외부 자료로 교수의 발언·회의의 고유 결정을 확정하지 않는다.
- **확인한 것:** 요청·응답 schema, metadata-only와 highlights의 차이, 오류 문서, MCP/API 연결 구분. OpenAPI 조회본은 535,059 bytes, SHA-256 `f71afb48ea12c417c0e9efe9aeced18b161ca0b6d9441e69a55d33c64bc61a01`, OpenAPI 3.1.0 / info.version 2.0.0이었다. 이는 API 모델 버전이나 실제 실행 성공을 의미하지 않는다.
- **미확인:** 사용자 API 키의 접근·잔액·rate limit, 실제 한국어 용어 검색 품질·발췌 정확성·지연·과금, 런타임 error/tag/header. 사용자 키로 명시적인 실제 호출을 하기 전에는 mock 확인과 실제 성공을 구분해야 한다.
