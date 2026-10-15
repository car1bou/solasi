# Foresight 공개 근거와 적용 검토

확인일: 2026-10-14 (Asia/Seoul)

범위: Google 공식 제품 페이지·발표문·SDK 문서·공개 저장소·모델 카드와 제작자 기술보고서를 읽었다. 제품 페이지의 본문은 iframe이어서 브라우저의 렌더링된 텍스트로 확인했다. Foresight 설치·실행, 모델 다운로드, 사용자 앱/네트워크/개인 DB 검사, 성능 실험은 하지 않았다. 아래는 공식 자료의 주장과 공개 범위이며 로컬 실행 검증이 아니다.

## 1. 공식 제품에서 확인한 범위

| 항목 | 현재 공개 근거 | 해석의 한계 |
|---|---|---|
| 정체·배포 | Google AI Edge Team의 **2026-10-06** 발표는 **Google AI Edge Foresight for Mac**을 실험 앱으로 소개한다. 공식 제품 페이지에 macOS 다운로드 링크가 있다. | 상용 서비스의 안정성·지원 기간을 보장하는 발표가 아니다. [발표문](https://developers.googleblog.com/google-ai-edge-with-embeddinggemma-2/), [제품 페이지](https://developers.google.com/edge/foresight) |
| 하드웨어 | 제품 FAQ는 Apple Silicon에 최적화되었다고 설명한다. | 확인한 제품 페이지에는 최소 macOS 버전·RAM·칩 세대의 정량 요구표가 없었다. 이를 근거로 특정 Mac에서 원활하다고 단정하지 않는다. [제품 FAQ](https://developers.google.com/edge/foresight) |
| 처리 구조 | Google은 시스템 오디오·마이크를 사용하며, AI 추론·전사·오디오·로컬 검색이 기기에서 처리되고 오프라인 사용이 가능하다고 명시한다. | 이는 공식 제품 주장이다. 설치 파일·통신·텔레메트리의 독립 감사 결과가 아니다. [발표문](https://developers.googleblog.com/google-ai-edge-with-embeddinggemma-2/), [개인정보·오프라인 FAQ](https://developers.google.com/edge/foresight) |
| 회의 기능 | 축약 메모를 회의 전사로 보완하고, 파일 기반 채팅 및 Live Assistance를 제공한다. FAQ는 질문/주제가 등장할 때 인용을 포함한 선제적 문맥 카드를 표시한다고 설명한다. | 질문감지 정확도·오탐률·지연·근거 충실도 수치는 확인하지 못했다. [제품 기능·FAQ](https://developers.google.com/edge/foresight) |
| 지식 자료 | 로컬 폴더·Google Drive 연결과 PDF, Google Docs, Office, plain text, Markdown, web bookmarks를 명시한다. | 연결/가져오기 과정 전체의 오프라인 가능성이나 모든 형식의 파싱 품질은 확인되지 않았다. [제품 기능·FAQ](https://developers.google.com/edge/foresight) |
| 공개 모델 계열 | 발표와 현재 제품 페이지는 **EmbeddingGemma 2 + Gemma 4**를 명시한다. | 특정 세부 크기·체크포인트·질문감지/전사 용도별 배치를 공개한 것은 아니다. [발표문](https://developers.googleblog.com/google-ai-edge-with-embeddinggemma-2/), [제품 모델 설명](https://developers.google.com/edge/foresight) |

**언어 지원:** 확인한 공식 제품 페이지·발표문에는 Foresight 앱의 지원 언어표나 한국어 지원/미지원 문구가 없었다. 한국어 미지원은 **사용자가 이번 메시지에 직접 알려준 조건**이다. 제공된 정적 보고서에서 관찰한 사실이나 공식 지원표로 바꾸어 인용하지 않는다. 사이트 상단의 한국어 언어 선택은 개발자 웹사이트 번역 기능이며 앱 지원 언어 근거가 아니다. [제품 페이지](https://developers.google.com/edge/foresight)

사용자 보고서의 빌드 `1.0.0.28.20261005`와 공개 발표일 `2026-10-06`은 서로 다른 식별 정보다. 이번 공개 조사에서는 해당 빌드와 현재 제품 설명의 모델/동작 동일성을 확인하지 못했다.

## 2. 독립 앱에서 검토할 수 있는 공개 모델·SDK

| 공개 구성요소 | 확인한 계약·이용 경로 | 적용 시 구분 |
|---|---|---|
| **EmbeddingGemma 2** | 공식 모델 카드: 740M multimodal, text-only 270M / text+vision 440M로 선택적 encoder 로딩, 8,192-token 공유 문맥, 기본 768차원 및 512/256/128차원 MRL. Apache 2.0. Google의 Hugging Face 공개 모델과 LiteRT용 변환 모델이 있다. [모델 카드, 2026-10-06 갱신](https://ai.google.dev/gemma/docs/embeddinggemma/model_card_2), [Google 모델](https://huggingface.co/google/embeddinggemma-2), [LiteRT text 270M](https://huggingface.co/litert-community/embeddinggemma-2-text-270m-litert-lm) | 기존 `embeddinggemma-300m`과 다른 세대다. 차원이 같아도 기존 인덱스와 호환된다는 근거가 없고, 새 모델로 문서·질의를 함께 임베딩해야 한다. 모델 다운로드·로딩은 이번에 수행하지 않았다. |
| **Gemma 4** | 공식 카드: 공개 가중치 PT/IT, E2B/E4B/12B/26B-A4B/31B, 140개 이상 언어. E2B/E4B/12B는 audio input을 지원하며 Apache 2.0. [모델 카드, 2026-07-30 갱신](https://ai.google.dev/gemma/docs/core/model_card_4), [Google 모델 컬렉션](https://huggingface.co/collections/google/gemma-4) | 공개 계열의 이용 가능성이 Foresight의 내부 checkpoint·미세조정·프롬프트 공개를 뜻하지 않는다. E4B는 effective 4.5B이며 임베딩 포함 총 8B라고 카드가 구분한다. |
| **LiteRT-LM** | Google 공개 추론 프레임워크, 저장소 라이선스 Apache 2.0. 현재 v0.18.0 설명에 embedding API가 있다. Swift 가이드는 iOS/macOS, Metal GPU, SPM 통합과 로컬 `.litertlm` 경로 로딩을 문서화한다. [저장소](https://github.com/google-ai-edge/LiteRT-LM), [Swift 가이드](https://developers.google.com/edge/litert-lm/swift) | README의 Swift 상태는 Early Preview다. 상위 소개 페이지의 “macOS coming soon” 문구와 세부 Swift 가이드의 macOS 지원 설명이 달라 실제 채택 시 사용할 tag·API·패키지 지원을 고정해 확인한다. 이번에는 설치하지 않았다. |
| **MediaPipe Universal Embedder / Semantic Retriever** | 공식 가이드는 기기 내 임베딩·저장·검색과 SQLite 등의 vector store, chunking, topK 결과·점수를 문서화한다. 플랫폼별 예제가 공개되어 있다. [Embedder](https://developers.google.com/edge/mediapipe/solutions/retrieval/universal_embedder), [Retriever](https://developers.google.com/edge/mediapipe/solutions/retrieval/semantic_retriever) | 공개 API의 기능이다. Foresight의 graph 검색·live transcript 재순위화·카드 TTL 등 내부 구현이 공개된 것으로 해석하지 않는다. |
| **AI Edge Gallery** | Apache 2.0인 공개 앱과 예제 구현이 있다. [공식 저장소](https://github.com/google-ai-edge/gallery) | Gallery의 라이선스를 별도 제품인 Foresight 전체의 라이선스로 확대하지 않는다. |

라이선스 문서의 불일치: MediaPipe의 두 retrieval 가이드는 EmbeddingGemma V2를 설명하면서 예전 Gemma Terms 링크를 연결한다. 반면 **EmbeddingGemma 2 공식 모델 카드·출시 발표·Google 공개 모델은 Apache 2.0을 명시**한다. 실제 사용할 모델 artifact의 LICENSE/NOTICE와 revision을 기준으로 다시 확인해야 한다. 기존 300M에 새 모델의 조건을 적용하지 않는다. 이는 공개 조건의 기술적 확인이며 특정 재사용 방식의 법률적 적법성 판단은 아니다. [EmbeddingGemma 2 출시, 2026-10-06](https://blog.google/innovation-and-ai/technology/developers-tools/embeddinggemma-2/), [Apache 2.0 본문](https://ai.google.dev/gemma/apache_2), [기존 Gemma Terms](https://ai.google.dev/gemma/terms)

## 3. 한국어와 품질 근거의 경계

EmbeddingGemma 2 카드는 100개 이상 언어와 multilingual MTEB v2 평균 **61.36**을 보고하며 언어별 성능이 동일하지 않을 수 있다고 경고한다. 확인한 카드에는 한국어 개별 점수·Foresight 한국어 품질 표가 없다. 다국어 평균을 한국어 강의/전문용어/누적 RAG 검증으로 사용하지 않는다. [EmbeddingGemma 2 카드](https://ai.google.dev/gemma/docs/embeddinggemma/model_card_2)

Gemma 4 제작자 기술보고서 **v2, 2026-07-24**에는 한국어 전사 평가가 있다. Table 7·8의 FLEURS ASR 헤더는 일반 언어에 WER, 별표(`*`) 언어에 CER를 사용하며 `ko*`가 한국어다.

| 공개 평가모델 | FLEURS 한국어 CER, 낮을수록 좋음 |
|---|---:|
| Gemma 4 E2B | 0.066 = 6.6% |
| Gemma 4 E4B | 0.053 = 5.3% |
| Gemma 4 12B | 0.057 = 5.7% |

[Gemma 4 Technical Report v2, Tables 7–8](https://arxiv.org/html/2607.02770v2)

이는 **공개 Gemma 4의 특정 벤치마크**다. Foresight의 실제 ASR과 같다는 근거, 한국어 실시간 강의에서 같은 수치를 얻는다는 근거, 현재 앱의 whisper.cpp보다 낫다는 직접 비교 근거는 아니다. 모델 카드의 140개 이상 언어 문구만으로 한국어 질의응답·질문감지·요약 품질도 확정하지 않는다.

## 4. 현재 공개 근거로 확정할 수 없는 것

이번에 확인한 공식 제품 페이지·발표·모델 카드에서는 다음을 찾지 못했다.

- Foresight의 정확한 ASR/VAD/화자분리 모델과 공개 다운로드·SDK 계약.
- 질문감지 전용 모델, fine-tuning checkpoint, 학습 데이터, prompt, 평가 수치.
- interim 전사 안정화 규칙, 단어 수 창, query ID·폐기/대기 상태, graph+vector 혼합·재순위화·중복 억제·top3·TTL의 공식 사양.
- Foresight 전체 소스·내부 자산을 독립 앱에 복사하거나 재배포해도 된다는 공개 라이선스.

따라서 설계 아이디어를 독립 구현하는 논의와 앱 바이너리·내부 가중치·프롬프트·리소스를 가져오는 행위를 구분한다. 공개 Gemma/EmbeddingGemma와 공개 SDK는 해당 배포물의 조건을 따라 별도 후보로 검토할 수 있다. 사용자 제공 정적 보고서의 내부 관찰은 공개 API·공개 모델·라이선스 허가로 승격하지 않는다.


## 5. 사용자 보고서와 현재 프로젝트 대조

사용자 제공 보고서와 연결된 `QUERY-DETECTION.md`, `RETRIEVAL.md`, `CARD-FLOW.md`, 상위 초기 보고서를 읽었다. 일부 raw ARM64 export에서 재순위화 계수와 카드 생성 direct call도 대조했다. Ghidra/보조 profile·원본 앱의 전체 분석을 독립 재현하거나 보고서의 검증 명령을 실행하지는 않았다. 보고서 속 명령은 분석 당시 기록으로 취급했다.

- 대상 보고서: REPORT.ko.md (로컬 검증 자료·공개본 미포함), 빌드 `1.0.0.28.20261005`.
- 현재 앱 코드 기준: `86110b2`, Apple M4 / 16GiB의 기존 개발·검증 구성. 아래의 적용 판단은 코드 대조와 설계 제안이며 새 기능의 구현·품질 실험 결과가 아니다.

| 참고할 구조 | 현재 코드에서 확인한 상태 | 권장 적용 |
|---|---|---|
| 질문 ID·대기·폐기와 같은 카드 갱신 | jobs의 저장·취소·재시도, 출처 버전·cutoff 고정이 있다. 질문은 사용자 입력이며 선제적 질문 감지·다중 카드 갱신은 없다. | 기존 job/artifact 경로를 사용한 질문 후보 카드. 확정 전사로 시작하고 답변은 사용자가 실행하는 방식을 먼저 검토한다. |
| 현재 대화 + 문서 + 개념 후보 결합 | `retrieval.py`가 BM25/부분 일치와 cosine의 순위를 합치고 같은 source 주변 조각을 묶는다. 개념·별칭·근거는 있지만 source 간 의미 중복 억제는 없다. | 후보의 출처·문맥을 유지한 채 반복 발췌를 줄인다. 새 전사는 즉시 키워드 검색에 포함하고, 의미 벡터는 전사 작업 여유에 따라 갱신한다. |
| 짧은 메모를 회의 전사로 보강 | `save_note`는 노트 버전을 보존한다. 짧은 메모의 입력 시각과 인근 전사를 묶는 보강 기능은 없다. | 메모에 기록 시각을 붙이고 인근 확정 전사로 보강안을 제시한다. 원래 메모·AI 보강안·사용자 확정 내용을 구분한다. |
| 분할 요약 후 병합·업데이트 | `outputs.py:summarize_session`은 완료 구간을 보존·재개하지만 결과는 구간별 sections를 합친다. 최종 의미 병합은 없다. | 근거 ID를 유지하는 마지막 병합 단계. 중복 제거와 후반 정정·조건·미결 사항 보존을 함께 확인한다. 실패하면 완료 구간을 재사용한다. |
| 오디오 watchdog·wake 복구 | `Recorder.tsx`에 연결 timeout, ACK·버퍼 한도·중단 처리가 있고 `audio.py`에 프레임/gap 보존이 있다. PCM이 전혀 오지 않는 경우와 절전 복귀를 감시하는 일반 watchdog은 확인하지 못했다. | 마지막 PCM/ACK 시각·AudioContext/track 상태로 수집 중단을 감지한다. 무음과 장치 중단을 구분하고 유한 재시도·실제 빠진 구간을 기록한다. |
| 그래프·관계형 맥락 | 과목/회차 범위, 개념/별칭/출처/퀴즈 연결이 있다. 임의 엔터티 관계를 추출하는 그래프 서비스는 없다. | 같은 과목 개념의 기존 근거 연결부터 활용한다. 관계를 넣더라도 출처가 있는 연결만 후보 확장에 사용하고 원문 근거를 제공한다. 회의는 승인된 현재 기록 범위를 유지한다. |
| 캐시·TTL·검색 필터 | 파일 참조, 원본 변경 상태, 파생 페이지/그림 캐시256MiB와 최신 source 필터·버전 보존이 있다. | TTL은 임시 질문·검색 캐시처럼 재생성 가능한 결과의 수명 관리에 검토한다. 영구 학습 기록의 보존과 별개로 정의한다. |

코드 근거: [검색](../../lecture_study/retrieval.py), [질문 고정](../../lecture_study/answers.py), [생성·요약·회의록](../../lecture_study/outputs.py), [작업](../../lecture_study/jobs.py), [오디오](../../lecture_study/audio.py), [녹음 UI](../../frontend/src/Recorder.tsx), [캐시·노트](../../lecture_study/materials.py).

## 6. 그대로 적용할 근거가 부족한 부분

1. **마지막5단어 제외·200단어·1초 지연.** 보고서의 공백 기반 단어 수와 반환 지연을 한국어 최적값으로 사용하지 않는다. 한국어에서는 확정 구간·원문 버전과 입력 예산을 기준으로 시작한다. 임시 전사를 쓰려면 실제 가설 수정 양상을 먼저 관측한다. 1초가 앱의 감지 주기라는 해석도 보고서와 다르다.
2. **`<ctrl1>` 접미사.** 내부 질문감지 모델의 학습·토큰 의미가 공개되지 않았다. Qwen/Gemma 일반 모델에 같은 문자열을 붙여 동일 기능을 얻는다는 근거가 없다. 한국어 질문 추출용 지시와 검증 가능한 JSON 출력이 별도로 필요하다.
3. **0.7/0.92/0.95, top3, 이미지2개.** 다른 모델·입력 prefix·후보 구성에서는 점수 분포가 달라진다. 특히0.95는 relevance threshold가 아니라 조건부 곱셈 계수다. 문서에 적힌 수치를 현재 EmbeddingGemma의 합격 기준으로 복사하지 않는다.
4. **보충 과정의 중복 재진입.** 보고서는 첫 의미 중복 제거 이후 cosine 검사 없이3개를 채우는 경로를 확인했다. 우리 앱은 관련 근거가 적으면 적은 개수로 답하는 편을 먼저 검토한다. 고정 개수보다 출처 다양성과 부족함 표시가 우선이다. 가까운 임베딩이라도 ‘도입한다/도입하지 않는다’, 다른 날짜·수치는 서로 다른 근거로 보존한다.
5. **graph 후보 강제 삽입·최신 자료 무조건 우선.** 관계 설명만 있는 문자열이 원문보다 우선하는 규칙이나 최신 문서가 항상 정답이라는 규칙을 적용하지 않는다. 질문의 시점·버전·확정/제안 상태와 실제 인용 근거를 따른다. 벡터 SQL의 LIMIT만으로 ANN 인덱스나 대용량 성능을 단정하지 않는다.
6. **매번 후보를 재임베딩하는 재정렬.** 현재 앱의 저장 벡터를 먼저 활용한다. live/graph의 표현이 바뀌어 새 벡터가 필요하면 모델 digest·입력 형식·원문 버전으로 구분해 캐시한다. 같은 cosine을 다시 계산하는 것만으로 새로운 ranking 품질이 보장되는 것은 아니다.
7. **Flutter/gRPC/Helper 전체 구조와 내부 자산.** 기존 React/FastAPI·native subprocess 경계를 바꾸어야 한다는 근거는 없다. 공개 SDK·공개 모델의 이용 경로를 검토한다. Foresight 전용 detector·helper·내부 가중치의 독립 재배포 권한은 확인하지 못했다.

보고서의 V2 feature flag 현재값, 일부 comparator/dispatch, 실제 detector 모델과 ASR 출력·UI 지연은 미확인이다. 이 구조가 우리 앱보다 빠르고 정확하다고 읽지 않는다.

## 7. 한국어 프로젝트에 제안하는 순서

### 먼저: 전사 안정성과 기존 검색·요약을 보강

- 녹음 중 무음과 PCM 수집 중단을 구분하는 상태 확인, 절전/장치 변경·중단 시 gap 보존을 우선한다.
- 기존 검색에 근거 중복 억제와 출처·회차 다양성을 추가하는 작은 실험을 한다. 전체 문서의 재임베딩을 검색마다 반복하지 않는다.
- 시간에 연결한 메모 보강안과 근거를 유지하는 최종 요약 병합을 검토한다. 제안·확정·취소·정정의 변화는 합치면서 지우지 않는다.

### 다음: 선택적으로 질문 후보 카드

제안 흐름은 다음과 같다. 현재 구현 완료된 기능을 나타내는 도식이 아니다.

```text
확정 전사 + 원문 버전
 → 최신 문맥에서 질문 후보 추출 (선택 기능)
 → 원문 인용을 붙인 질문 후보 카드
 → 사용자가 답변 실행
 → 현재 검색 범위에서 문서·확정 전사·등록 개념 후보 수집
 → 중복 억제·출처/입력 예산 확인
 → 기존 AI job으로 실행·대기·취소·재시도
 → 같은 카드에 답변과 출처 표시
```

예: 수업에서 “세마포어와 뮤텍스의 차이가 뭔가요?”가 확정되면 후보를 보여주고, 사용자가 선택했을 때 같은 과목의 이전 회차 자료와 현재 설명으로 답한다. 회의에서 “금요일까지 가능한가요?”를 감지한 것만으로 기한이 확정됐다고 쓰지 않는다. 사용자가 수정·고정한 카드와 기존 답변은 자동 갱신과 구분한다.

현재 확정 전사 적체 시 새 로컬 생성·임베딩을 기다리게 하는 정책을 질문 추출에도 적용해야 한다. 원음 전사 외에 감지 모델과 답변 모델을 계속 실행하는 선택은 처리량·메모리 실험 뒤에 한다. 자동 감지 활성화가 외부 API 자동 호출·비용 지출 동의까지 의미하게 만들지 않는다.

### 모델 후보: EG2와 Gemma4를 각각 평가

- **EmbeddingGemma 2**는 이미지·텍스트를 함께 검색할 공개 후보다. 지금 앱의 ‘선택한 그림을 Qwen으로 설명’하는 기능에 더해 ‘설명에 맞는 도표 페이지를 찾는 검색’을 검토할 수 있다. 다국어 평균과 다른 장치의 지연은 한국어 강의 품질·M4/16GiB 실측을 대체하지 않는다. 기존300M 인덱스는 새 모델 벡터와 섞지 않는다.
- **Gemma4 E2B/E4B**는 한국어 ASR의 공개 근거가 있는 비교 후보다. 같은 원음·정규화로 CER/고유명사·수치·긴 구간 누락을 비교하고, 시간 위치·부분 전사·취소·재실행·동시 생성의 제품 계약도 확인한 뒤 판단한다. FLEURS 수치만으로 기본 엔진을 바꾸지 않는다. 이번 검토에서는 추가 다운로드나 실행을 하지 않았다.

검토 시 사용할 사례: 부정어로 바뀌는 질문, 닮은 고유명사, 현재/이전 회차의 같은 정의, 후반부 결정 정정, 긴 무음과 오디오 장치 중단, 색인 실패 후 키워드 검색, 카드 삭제 후 늦게 도착한 결과. 이 목록은 새 합격점이나 고정 성공 기준이 아니라 계속 비교할 오류 사례다.

원문 보고서 SHA-256: `8f790f830d410a4197786b344412dd36723561724fbe2a1948e3b9da6036b075`. 제공된 분석 폴더는 이 작업트리에 복사하지 않았으며 로컬 원문 링크는 해당 파일이 있는 환경에서 열린다.
