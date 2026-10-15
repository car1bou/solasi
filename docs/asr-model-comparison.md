# 한국어 전사 모델 비교와 앱 적용

2026-10-13~14. Apple M4 · 16GiB · macOS27.0.1. 공개 사람 음성을 내려받아 이 PC에서 처리했다. 외부 전사 API로 보내지 않았다.

## 현재 결정

앱 기본 전사는 **whisper.cpp1.9.5 + Whisper large-v3-turbo + SileroVAD6.2.0**이다. M4에서 native Metal 실행을 사용한다. 기존의 문장 구간·원음 시각·실패 복구 계약을 유지하면서 base보다 적은 오류를 확인했다. 모델 누락·손상은 준비되지 않은 상태이며 base로 몰래 바꾸지 않는다.

Qwen3-ASR1.7B의 커뮤니티 MLX4bit판은 유력한 다음 후보다. 이번 표본에서는 더 적은 문자 오류와 짧은 처리 시간이 관찰됐지만, 현재 반환 시각은 입력 조각 범위다. 문장/단어 정렬과 실제 강의·회의 입력을 확인한 뒤 기본 엔진 교체를 판단한다. 작은 점수 차이만으로 최종 우열을 확정하지 않는다.

## 음성과 측정 조건

[Google FLEURS](https://huggingface.co/datasets/google/fleurs), `ko_kr/test`, revision `70bb2e84b976b7e960aa89f1c648e09c59f894dd`, CC-BY4.0. 원어민 낭독·검수 절차는 [논문2.1절](https://arxiv.org/abs/2205.12446)에 기술돼 있다. 익숙한5개(rows0·2·3·5·7)와 ASR 전에 선택한 추가20개(rows8–27)를 분리했다. 합계312.36초, 원음19,992,490bytes(19.07MiB). 모든 원음과 모델 해시는 처리 전후 같다.

추가20개는19개 고유 문장이다. rows9·18은 같은 문장, row25는 익숙한row5와 같은 문장의 다른 녹음이다. speaker_id가 없어 서로 다른25명이라고 표현하지 않는다. 어떤 모델의 학습 음성과 겹치는지는 확인되지 않았다.

**CER은 낮을수록 좋다.** NFKC·소문자·Unicode 문자/숫자만 남겨 문자 편집 수를 기준 문자 수로 나눈 진단값이다. 띄어쓰기·문장부호는 제외하지만 `일만/1만`, `미터/m`, 기준의 괄호 로마자도 센다. `아순시온`을 맞게 읽어도 `(Asunción)`이 없으면8글자 오류다. 공식 FLEURS 점수나 순수한 발화 오류율이 아니다.

| 실제 실행 구성 | 익숙한5개 CER | 추가20개 CER | 추가20개 전사 시간 | 메모리 관찰 |
|---|---:|---:|---:|---|
| Whisper base · CPU | 11.63%(25/215) | 10.35%(98/947) | 19.03초 | RSS364MiB |
| Whisper small · CPU | 3.26%(7/215) | 6.97%(66/947) | 50.53초 | RSS839MiB |
| whisper-medium-komixv2 · CPU | 4.19%(9/215) | 5.60%(53/947) | 71.43초 | RSS2.12GiB |
| large-v3-turbo · Metal | 3.72%(8/215) | 2.96%(28/947) | 36.87초 | RSS1.88GiB |
| Qwen3-ASR1.7B · MLX4bit Metal | 3.26%(7/215) | 2.53%(24/947) | 17.90초 | MLX allocator peak2.50GiB / process RSS1.25GiB |
| Raon-Speech9B | 실측 없음 | 실측 없음 | 실측 없음 | 현재 Mac 경로 미검증 |

Whisper는 한국어·기본 beam/best-of5·VAD기본값·명칭 힌트 없음이며, 매 음성마다 프로세스와 모델을 새로 읽었다. Qwen은 temperature0·한국어·힌트 없음이며 한 번 로드해 재사용했다. Qwen의 import0.200초·모델 로드2.478초는 전사 합계 밖이다. CPU/Metal·정밀도·로딩 방식이 달라 위 시간을 통제된 모델 구조 성능 순위로 쓰지 않는다. MLX allocator와 RSS는 범위가 다른 계측으로 더하지 않는다.

별도 turbo CPU 결과는 같은 CER, 추가20개105.67초였다. 같은 M4의 Metal36.87초가 약2.9배 짧았다. 1회씩의 순차 실행이며 다운로드·설치와 긴 수업의 대기는 포함하지 않는다.

## 고유명사

| 표기 | base의 오류 | turbo의 관찰 | Qwen의 관찰 |
|---|---|---|---|
| 이란·자그로스산맥 | 1안·자그러스3맥 | 두 이름 일치 | 두 이름 일치 |
| 북발트해 | 북바이트애 | 일치 | 북바이트해 |
| 카탈로니아어 | 카카로니아어 | 일치 | 일치 |
| TMZ·세풀베다 | TMG·세풀배다 | TMZ 일치, 새풀베다 오류 | 두 이름 일치 |
| 깁슨 | 깊스 | 깁스 오류 | 깁스 오류 |

이름을 일괄 정답으로 교체하지 않는다. 수업/회의별로 짧은 이름·전문용어를 저장하는 힌트 기능은 유지한다. 기존 base 실험에서는 관련 지명이 개선됐지만 관계없는 단어는 악화되기도 했다. 힌트는 해당 구간의 ASR 입력으로 기록하고 원음·원래 인식문·사용자 수정을 보존한다. 자료에서 자동으로 이름을 뽑는 기능은 아직 구현하지 않았다.

## 앱 경로의 별도 검증

모델 단독 full-clip 점수와 실제20초 분할 경로는 구분한다.

- turbo CPU로 익숙한5개를 파일/48kPCM replay: 양쪽8/215=3.72%. 원음 보존·빈틈 없음·원음 범위 안의 확정 시각 확인.
- turbo Metal로 추가20개를 파일/48kPCM replay: 파일32/947=3.38%, PCM30/947=3.17%. 처리40.60초/40.05초. 22.38초와24.06초 음성도 포함하며, 후자는20초 경계에서 full-clip보다 오류가 증가했다.
- 12.54초 사람 음성을250ms 속도로 인증된 ASGI WebSocket에 보내 동시 ASR 실행:51ACK,601920frames,48kHz,누락0,잠정 전사 관찰,최대 관찰 대기 구간1,종료 후3.37초에done. 확정2/50=4.00%. 브라우저·실제 네트워크·마이크 재녹음 시험은 아니다.
- turbo에서 선행 무음의 원음 시각, 거의 무음인 꼬리의 빈 전사, 재시도·취소·중단 복구·이전 출처 보존 테스트 통과.
- DBv7은 기존 완료 구간의base와 당시 힌트를 유지한다. 새 추론 구간은large-v3-turbo,zeroPCM으로 추론하지 않은 구간은모델없음으로 기록한다. 준비 화면은PATH가 아닌 앱 runtime파일과 모델/VAD SHA검사 결과를 표시한다.

## 후보별 실행·라이선스

Whisper small(487,601,967bytes)·turbo(1,624,555,275bytes)는 공식 whisper.cpp 모델 파일, MIT다. turbo revision은`5359861c739e955e79d9a303bcbc70fb988958b1`, SHA256은`1fc70f774d38eb169993ac391eea357ef47c88757ef72ee5943879b7e8e2bc69`다. [공식 파일](https://huggingface.co/ggerganov/whisper.cpp/blob/5359861c739e955e79d9a303bcbc70fb988958b1/ggml-large-v3-turbo.bin)

Komix는 저자 원본 safetensors3,055,544,304bytes에서947개 텐서·763,857,920개 파라미터를 확인하고, 고정 whisper.cpp 변환 이름/정밀도 규칙에 따라 직접 GGML1,533,763,076bytes로 변환했다. 모델을 실행해 비교했지만 원저자 카드에 가중치 라이선스가 없어 앱 배포물에는 포함하지 않는다. [원저자 카드](https://huggingface.co/seastar105/whisper-medium-komixv2), [조사 문서](research/2026-10-13-komix-stt.md)

Qwen은 고정 커뮤니티 MLX4bit 가중치1,603,081,617bytes, revision `78a389c776a5483b2d0d4ea5494e11012e0d6159`다. Apache2.0이며 MLX-Audio 코드는MIT. 제품과 분리된 평가 venv의35개 hashlocked wheel116.3MiB로 실제 Metal 추론했다. 모델의 입력 조각 시각과 token 비율 추정치를 문장 원음 시각으로 사용하지 않는다. [변환 카드](https://huggingface.co/mlx-community/Qwen3-ASR-1.7B-4bit), [정렬 조사](research/2026-10-13-qwen-asr.md)

Raon 원본은 가중치18,105,967,634bytes(16.86GiB), officialAWQINT4는7,823,034,274bytes(7.29GiB)다. 공식 경로는CUDA/vLLM-Omni이며 M4에서 검증된 MPS/MLX 양자화 경로를 찾지 못해 전체 가중치 다운로드·추론을 수행하지 않았다. 가중치는CC-BY-NC4.0,코드는Apache2.0이다. 저자 FLEURSko CER1.81은 저자 조건의 값이며 위 자체 점수와 직접 순위를 매기지 않는다. GPU 장비에서 검토할 후보로 유지한다. [공식 카드](https://huggingface.co/KRAFTON/Raon-Speech-9B), [조사 문서](research/2026-10-13-raon-stt.md)

## 재현 자료와 다음 확인

전체25개 기준·인식문·시간·CER JSON (로컬 검증 자료·공개본 미포함)에CPU/Metal 및VAD조건을 모두 보관했다. VAD padding250ms는 추가20개24/947로 개선됐으나 익숙한5개9/215로 악화됐다. VADoff도 결과가 섞였으므로 현재 VAD기본값을 유지했다. 표본에 맞춘 유리한 조건만 기본으로 고르지 않았다.

```sh
.venv/bin/python -m experiments.compare_cpp_models turbo --backend metal
.venv/bin/python -m experiments.compare_cpp_models komixv2
HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1 .local-state/runtime/qwen-eval-venv/bin/python experiments/evaluate_qwen_asr.py
.venv/bin/python -m experiments.build_comparison_report
.venv/bin/python -m tests.evaluate_human_audio --additional
.venv/bin/python -m tests.evaluate_live_audio
```

모델·원음·평가 venv는 별도 runtime에 준비해야 하며 저장소에는 큰 바이너리와 원음을 넣지 않는다. Qwen 평가용 패키지는 `experiments/qwen-requirements.lock`이며 제품 의존성이 아니다.

다음 확인은 실제 강의·회의/겹치는 발화/멀리 있는 마이크/전문용어·이름의 오인식,20초 분할 경계 문맥,연속30–60분의 대기와RAM/swap,LLM동시실행이다. Qwen한국어 forced alignment와Raon의GPU추론도 남아 있다. 현재 결과는 전사 개선의 근거이며 전체 서비스 품질의 보장은 아니다.

## 추가 자료·30초 분할 갱신 — 2026-10-14

[추가82개 원음·4모델·분할 비교](diverse-audio-test.md)를 완료했다. 실제 강연 발췌24개와 세 방 녹음18개를 포함한다. 이번 강연 표본에서는turbo, 세 방 표본에서는Qwen이 더 적은 오류였다. 기본 모델은turbo를 유지하며 새 구간 상한을30초로 조정했다. 위25개 및20초 결과는 당시 측정으로 보존한다. 잠정3초와 원음 시각·기존 수정은 유지한다. Raon은5070Ti16GB 조건만 확인하고 사용자의 Mac 개발 우선 요청에 따라 GPU 시험을 보류한다.
