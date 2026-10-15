# 추가 한국어 사람 음성 검증

2026-10-14 · Apple M4/16GiB/macOS27.0.1. 공개 원음을 로컬에서 처리했고 외부 전사 API를 사용하지 않았다.

## 표본

| 입력 | 개수 | 길이 | 확인 범위 |
|---|---:|---:|---|
| 추가 FLEURS 낭독 | 40 | 485.82초 | 새40문장, 화자ID 없음 |
| Pansori 실제 TEDx 발췌 | 24 | 107.80초 | 12 단독화자 출처, 자막 경계 발췌 |
| Deeply 세 방 녹음 | 18 | 85.02초 | 화자2명/정답5종/6paired groups, iPhoneX·0.4m |
| FLEURS 음량0.1 파생 | 5 | 65.28초 | 독립된 새 녹음이 아님 |
| FLEURS Gaussian SNR10dB 파생 | 5 | 65.28초 | 독립된 새 녹음이 아님 |
| FLEURS 연결 파생 | 1 | 600.96초 | 600.96초, 기존 발화를 연결·일부 반복; 실제 긴 강의 아님 |

새 원음82개678.64초(11.31분), 파생11개를 구분한다. 앞선25개와 합계107개 원음 파일이며 모두 독립 화자·정답 문장인 것은 아니다. 총 시험 파일93개59,160,736bytes(56.42MiB). 원음 SHA를 처리 전후 확인했다. 표본은 모델 결과를 보기 전에 고정했다.

[Pansori 제작자](https://github.com/yc9701/pansori-tedxkr-corpus)와 [Deeply 제작자](https://github.com/deeplyinc/Korean-Read-Speech-Corpus)의 원본은CC-BY-NC-ND4.0, [FLEURS](https://huggingface.co/datasets/google/fleurs)는CC-BY4.0이다. NC-ND 원음을 제품에 동봉하거나 가공·재배포하지 않는다. 잡음/음량/연결 파생은FLEURS로만 만들었다. 원음은 저장소에 넣지 않는다.

## 같은 새 원음의 진단 CER

NFKC·소문자·Unicode 문자/숫자, 띄어쓰기·문장부호 제외. 숫자 표기·괄호 로마자 차이도 오류로 센다. 낮을수록 좋다. 공식 코퍼스 벤치마크 점수나 모델 우열의 통계 검정이 아니다.

| 실제 실행 | 낭독40 | 강연24 | 세 방18 |
|---|---:|---:|---:|
| Whisper small · native GPU | 6.86%(120/1748) | 9.96%(53/532) | 8.78%(39/444) |
| medium-komixv2 · native GPU | 8.70%(152/1748) | 10.53%(56/532) | 11.49%(51/444) |
| large-v3-turbo · native GPU | 5.66%(99/1748) | 4.32%(23/532) | 6.53%(29/444) |
| Qwen3-ASR1.7B · MLX4bit | 5.49%(96/1748) | 7.52%(40/532) | 2.48%(11/444) |

Whisper는 매 파일 모델 로딩, Qwen은 한 번 로딩·재사용이며 정밀도와 입력 방식이 다르다. 시간은 통제된 모델 구조 비교가 아니다. 이번 표본에서 turbo는 강연 발췌, Qwen은 세 방 표본에서 더 적은 오류를 보였다. Qwen의 정확한 문장/단어 시각은 미검증이므로 기본은turbo를 유지한다. Komix 가중치 라이선스는 원저자 확인이 없어 평가에만 사용한다. Raon은 사용자의 요청에 따라 GPU 실행을 보류했다.

## 긴 입력의 분할 비교

| 같은600.96초 파생 음성 | 진단 CER | 처리 |
|---|---:|---:|
| 기존20초 제품 경로 | 17.68%(380/2149) | 76.49초 |
| 30초 제품 경로 | 11.21%(241/2149) | 46.38초 |
| 단일 파일 native 경로 | 11.35%(244/2149) | 34.65초 |

분할 외에도 독립CLI 문맥·VAD 경계·자막 조각의 인공 연결이 섞여 있다. 30초가 모든 강의에 최적이라는 결론은 내리지 않는다. 이번 개선과 Whisper30초 입력 창, 사용자의 정확도 우선 요청에 따라 새 구간 상한을30초로 조정했다. 잠정3초·digital silence800ms·원음 시각·기존 확정 전사/수정은 유지한다. 연속 발화의 확정 대기는 구간 길이가 기존보다최대10초 늘어난다. 긴 입력의11% 오류도 남아 있어 완성된 장시간 회의 정확도로 표현하지 않는다.

## 재현

```sh
.venv/bin/python -m experiments.collect_diverse_audio
.venv/bin/python -m experiments.evaluate_diverse_audio --engine turbo
HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1 .local-state/runtime/qwen-eval-venv/bin/python experiments/evaluate_diverse_audio.py --engine qwen
.venv/bin/python -m experiments.evaluate_diverse_audio --engine komix --groups fleurs40,pansori24,deeply18
.venv/bin/python -m experiments.evaluate_diverse_audio --engine small --groups fleurs40,pansori24,deeply18
.venv/bin/python -m experiments.evaluate_diverse_audio --engine turbo --route product --chunk-seconds 30
.venv/bin/python -m tests.evaluate_live_audio --repeat 3
```

전체 원음 기준·인식문·시간·모델 해시·실패 여부 (로컬 검증 자료·공개본 미포함). 원본은 고정다운로드 목록으로 받고 평가 모델/engine는 별도 runtime에 준비해야 한다. 실제 회의·겹침 발화·원거리 마이크·전문용어의 대표성·학습 효과는 아직 확인하지 않았다.
