# Gemma 4 변형과 M4 비교 후보

후속 실측: [E2B QAT·E4B QAT·12B 실제 Mac 비교](gemma4-actual-comparison.md). 아래 내용은 가중치 다운로드 **전**에 수행한 후보 조사 기록이며, 미실측 표시는 당시의 상태다.

확인일: 2026-10-14. Apple M4 · 16GiB의 한국어 강의·회의 앱을 기준으로 공식 Google 카드·컬렉션·Ollama v0.40.3 소스와 공개 registry의 작은 manifest/config를 읽었다. 이 조사는 추가 가중치 다운로드·추론·코드 변경을 하지 않았다.

사용자가 승인한 E2B MLX 7.477GB는 실제 비교 대상으로 이미 준비되어 있다. 해당 모델의 실행·품질·장기 녹음 결과는 별도 검증 기록을 따른다. 아래 E4B·12B·QAT·대형 모델의 순위는 공개 구성에 따른 **미실측 후보 판단**이다. 현재 기본 모델을 교체한 결과가 아니다.

## 1. 기본 계열

| 계열 | 구조·파라미터 | 입력 | 공개 컨텍스트 |
|---|---|---|---|
| E2B | dense, 2.3B effective / 임베딩 포함5.1B | 텍스트·이미지·음성 | 128K |
| E4B | dense, 4.5B effective / 임베딩 포함8B | 텍스트·이미지·음성 | 128K |
| 12B Unified | dense, 11.95B, encoder 없는 통합 구조 | 텍스트·이미지·음성 | 256K |
| 26B-A4B | MoE, 총25.2B / 활성3.8B | 텍스트·이미지 | 256K |
| 31B | dense, 30.7B | 텍스트·이미지 | 256K |

E의 effective는 큰 Per-Layer Embedding(PLE) 테이블을 제외한 연산 규모이며 MoE의 활성 파라미터와 다르다. 26B-A4B는 활성3.8B만 저장·로딩하면 되는 모델이 아니다. 12B는 이미지·오디오 encoder 대신 원시 패치·파형을 가벼운 projection으로 decoder에 전달한다. 영상은 프레임으로 처리하며, 음성 지원 모델의 공식 입력 상한은30초다. 긴 강의의 분할·시간 정렬·누락 방지는 앱 계약으로 확인해야 한다. [Google 모델 카드](https://ai.google.dev/gemma/docs/core/model_card_4)

각 크기에 PT와 지시 수행 IT가 공개되어 있다. 현재 요약·메모 보강·질문 후보에는 IT를 비교한다. 공식 모델의 라이선스는 Apache2.0이다. [Google 공개 모델 목록](https://huggingface.co/collections/google/gemma-4)

## 2. 실제 배포 크기와 실행 태그

단위는 decimal GB다. **config+layers의 byte 합**이며 manifest·bookkeeping·실행 캐시 공간은 별도다. 로컬 RAM이나 KV cache 요구량을 뜻하지 않는다. 기본 태그는 runner별 manifest를 선택하며 `-mlx` 고정 태그와 digest가 다를 수 있다. 아래 값은 확인 당시 기본 태그의 배포물이다.

| 계열 | 기본 태그 | GGUF Q4_K_M / llama.cpp | 기본 MLX | QAT GGUF Q4_0 정확한 태그 | QAT 크기 |
|---|---|---:|---:|---|---:|
| E2B | `gemma4:e2b` | 4,587,156,505B / 4.587GB | 7,476,595,162B / 7.477GB | `gemma4:e2b-it-qat` | 4,336,358,185B / 4.336GB |
| E4B | `gemma4:e4b` | 6,583,656,505B / 6.584GB | 9,461,576,343B / 9.462GB | `gemma4:e4b-it-qat` | 6,146,501,801B / 6.147GB |
| 12B | `gemma4:12b` | 8,021,618,941B / 8.022GB | 7,714,091,504B / 7.714GB | `gemma4:12b-it-qat` | 7,151,003,754B / 7.151GB |
| 26B-A4B | `gemma4:26b` | 18,731,025,629B / 18.731GB | 16,146,867,483B / 16.147GB | `gemma4:26b-a4b-it-qat` | 15,634,199,946B / 15.634GB |
| 31B | `gemma4:31b` | 20,385,458,234B / 20.385GB | 19,424,434,885B / 19.424GB | `gemma4:31b-it-qat` | 18,851,736,234B / 18.852GB |

배포 출처: [태그 목록](https://ollama.com/library/gemma4/tags), 기본 manifest [E2B](https://registry.ollama.ai/v2/library/gemma4/manifests/e2b)·[E4B](https://registry.ollama.ai/v2/library/gemma4/manifests/e4b)·[12B](https://registry.ollama.ai/v2/library/gemma4/manifests/12b)·[26B](https://registry.ollama.ai/v2/library/gemma4/manifests/26b)·[31B](https://registry.ollama.ai/v2/library/gemma4/manifests/31b).

QAT 출처: [E2B](https://registry.ollama.ai/v2/library/gemma4/manifests/e2b-it-qat)·[E4B](https://registry.ollama.ai/v2/library/gemma4/manifests/e4b-it-qat)·[12B](https://registry.ollama.ai/v2/library/gemma4/manifests/12b-it-qat)·[26B-A4B](https://registry.ollama.ai/v2/library/gemma4/manifests/26b-a4b-it-qat)·[31B](https://registry.ollama.ai/v2/library/gemma4/manifests/31b-it-qat).

### 「12B가 E4B보다 작다」의 정확한 범위

확인한 **기본 MLX 배포물**은12B가 E4B보다1,747,484,839B 작다. 반대로 GGUF Q4_K_M과 QAT Q4_0에서는12B가 더 크다. 이 비교는 원본 모델의 파라미터 수 순위가 아니라 서로 다른 구조·양자화·포함 자산을 가진 artifact의 저장량이다. 12B의 실제 RAM·전사 병행 지연이 더 작다는 결론은 나오지 않는다.

재조회할 MLX manifest SHA-256:

| 계열 | 기본 MLX manifest |
|---|---|
| E2B | `45d11505b91d888e353859f5deeeeff3ffc9b3aa42263c00904120c53851ef96` |
| E4B | `eb2177adf7646d15faead94fdad6d3e170dc8015653418a3b7d5d52a6380be5b` |
| 12B | `c7597fc90b86aff6965317f37dd5465402284e26382d9b4bf2dfe3ef1491f4b6` |
| 26B-A4B | `48eb98ec778c163d87f69d735fcdd79e345063af9af4685613fd018ae5debf5e` |
| 31B | `92808281a855666acf35743d49004bb30c810152cd004baf78f31b4578920e49` |

### 기본 MLX의 양자화 config

| 계열 | 직접 확인한 선언 |
|---|---|
| E2B | container `file_type=nvfp4`. `config.json`의 `quantization`·`quantization_config`는 없음. |
| E4B | `MIXED_PRECISION`, 하위 모듈 `NVFP4`·`W4A16_NVFP4` |
| 12B | `MIXED_PRECISION`, 하위 모듈 `NVFP4`·`W4A16_NVFP4` |
| 26B-A4B | `MIXED_PRECISION`, 하위 모듈 `NVFP4`·`MXFP8` |
| 31B | `MIXED_PRECISION`, 하위 모듈 `NVFP4`·`W4A16_NVFP4` |

이름에4bit가 있어도 모든 텐서가 같은 정밀도라는 뜻은 아니다. 위 manifest의 `config` blob과 이름이 `config.json`인 layer를 읽어 확인했다. 기본 GGUF는 Q4_K_M, QAT 태그는 Q4_0이다. 기본 MLX의 최소 엔진 요구는 대체로0.31.0, 26B는0.34.1이며 현재 앱의 고정 Ollama0.40.3보다 낮다. 이는 배포 metadata 호환 조건이며 실제 실행 성공을 대신하지 않는다.

## 3. QAT·MTP·다른 변형

- **QAT Q4_0**: Google의 양자화 고려 학습 변형.5개 크기에 unquantized 연구용·GGUF 배포물이 있다.
- **QAT Mobile wNa8o8**: E2B·E4B 전용 schema, 일부 decoder2bit·정적 activation 등을 사용한다. 현재 Ollama의 `*-it-qat` GGUF와 다르다.
- **Compressed Tensors w4a16**: E2B·E4B·12B·31B의 vLLM용 배포. 현재 Mac 앱의 직접 교체 경로로 확인하지 않았다.
- **Q8_0·BF16·MXFP8**: 별도 정밀도 후보. 파일 크기·품질·메모리 조건이 다르므로 기본 모델과 같은 실행 구성으로 합산하지 않는다.
- **`*-assistant`**: MTP에서 다음 토큰을 제안하는 보조 모델. 독립적인 질의응답 모델이 아니다. QAT target에는 같은 정밀도의 대응 QAT assistant가 필요하다.

[Google QAT 설명](https://huggingface.co/google/gemma-4-E2B-it-qat-q4_0-gguf), [QAT Mobile 목록](https://huggingface.co/collections/google/gemma-4-qat-mobile), [QAT 전체 목록](https://huggingface.co/collections/google/gemma-4-qat-q4-0), [공식 MTP assistant 설명](https://huggingface.co/google/gemma-4-12B-it-assistant).

E2B 기본 MLX manifest에는 약157.6MB의 `draft.*` 텐서가 있으나 container config에 `draft` 선언이 없다. E4B·12B·26B·31B 기본 MLX에는 draft architecture/config가 명시되어 있다. E2B 실측에서 MTP 활성화를 이름만 보고 가정하지 않는다.

공식 관련 모델 **DiffusionGemma26B-A4B**도 있다. 총25.2B/활성3.8B, 텍스트·이미지·영상 프레임 입력, 음성 미지원이며 block diffusion을 사용한다.1100tok/s 이상 주장은H100/FP8/작은 batch 조건이다. 현재 M4/16GiB의 우선 후보로 볼 근거가 없다. [Google 카드](https://huggingface.co/google/diffusiongemma-26B-A4B-it)

## 4. M5 주장과 M4 적용의 경계

Ollama의 약90% 생성 가속은 **Gemma4 12B NVFP4·M5 Max·Aider polyglot 코딩 에이전트** 조건이다. 큰 행렬연산2~2.5배 가속도 같은 하드웨어 조건이다. M4의 한국어 요약·ASR 병행 수치로 사용하지 않는다. MLX는 Apple Silicon 전반을 대상으로 하며 M5의 GPU Neural Accelerator가 추가 가속을 제공한다. M5 가속 수치를 적용할 수 없는 것과 M4 실행 불가는 별개다. [MTP 실험](https://ollama.com/blog/faster-gemma-4-mlx-mtp), [Apple Silicon 지원 설명](https://ollama.com/blog/mlx)

## 5. M4/16GiB의 미실측 후보 순서

1. **이미 승인·준비한 E2B MLX 대 Qwen3.5 4B 비교를 완료한다.** 동일 근거·JSON 계약과 전사 적체를 포함한 전체 완료 시간·RAM/swap을 따른다.
2. **E2B QAT GGUF4.336GB**: 녹음 중 생성의 다음 후보. 같은 계열에서 메모리·지연·품질 차이를 확인한다. 현재 MLX가 더 빠르거나 정확할 수도 있으며 QAT와 MTP 구성을 함께 기록한다.
3. **E4B QAT GGUF6.147GB**: 전사에 여유가 있을 때 한국어·고유명사·요약 품질을 비교한다. E4B MLX9.462GB보다 저장량이 작은 후보이나 실제 RAM 절약 폭은 미측정이다.
4. **12B QAT7.151GB 또는 MLX7.714GB**: 녹음 종료 후 메모 보강·요약 병합의 품질 후보. 파일 크기가 E4B MLX보다 작다는 이유로 동시 실행 기본값으로 고르지 않는다.
5. **26B-A4B·31B·DiffusionGemma**: 현재16GiB의 ASR 병행 후보에서 제외한다. 기본 가중치만16~20GB급이고 OS·앱·ASR·KV cache가 추가된다. 더 큰 Mac/원격 장치에서의 실행 적합성은 별도다.

위 순서는 공개 구성에 따른 추론이다. 한국어 FLEURS CER 공개 값은 E2B6.6%·E4B5.3%·12B5.7%여서 큰 모델이 항상 전사에서 우세하지도 않다. 현재 앱의 강의 음성·정규화·고유명사 표본과 직접 비교한 수치가 아니다. [제작자 보고서v2 Tables7~8](https://arxiv.org/html/2607.02770v2)

추가 다운로드가 필요하면 정확한 artifact·용량·저장 위치를 사용자에게 먼저 알린다. 승인된 E2B 외 가중치는 이 조사에서 받지 않았다. 새 후보의 실제 RAM·한국어 품질·전사/생성 병행·긴 음성 누락은 미검증이다.
