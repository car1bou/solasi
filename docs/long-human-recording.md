# 사람 음성 장기 녹음·전사·생성 동시 실행

2026-10-14, Apple M4·16GiB, macOS 27.0.1. 원시 집계 (로컬 검증 자료·공개본 미포함).

실제 성인 인터뷰·생활 소음의 후속 TCP 동시 실행과 브라우저 실패는 [다화자 검증](conversation-robustness.md)에 기록했다.

후속 모델별 동시 실행은 [E2B QAT·E4B QAT·12B 실제 비교](gemma4-actual-comparison.md)를 따른다. 아래는 이전 Qwen 실행의 기록이며 후속 모델의 지연과 격리된 A/B 개선율로 비교하지 않는다.

## 입력과 실행 방법

- [LibriVox 『술 권하는 사회』 Part 1](https://librivox.org/short-stories-by-jin-geon-hyun/), 현진건, 낭독 Jessie Yun. [배포 메타데이터](https://archive.org/metadata/short_stories_hyun_1411_librivox), [원본 MP3](https://archive.org/download/short_stories_hyun_1411_librivox/short_stories_02_hyun_128kb.mp3).
- Public Domain Mark 1.0 / LibriVox public-domain dedication. MP3 14,058,564B, SHA256 `68f07d5ca8677317590af0fc1dd5b8634ae0749ba1bbddc3965962f73086f1fc`.
- 디코딩한 연속 한국어 사람 음성 **878.3035초(14분 38초)**. 합성 음성이나 짧은 클립 반복이 아니다. 단일 화자의 문학 낭독이며 강의·회의·겹침 발화 검증과 구분한다.
- 실제 브라우저 AudioWorklet → WebSocket → 원음 WAV → Whisper large-v3-turbo와 Qwen3.5 4B를 사용했다. 전사·생성 모델 대역은 없다. 실제 마이크·스피커 대신 소프트웨어로 음성을 주입했다.
- 초기 fixture는 미디어 플레이어와 별도 AudioContext 사이 MediaStream bridge를 사용했다. 수정 fixture는 수집 AudioContext와 같은 렌더 시계를 쓰는 BufferSource로 주입한다. 부하가 걸리면 렌더 시계가 실제 시간보다 느려질 수 있다.
- 생성은 녹음 중 약 1분 간격으로 15건 제출하고 종료 뒤 모든 작업이 끝날 때까지 기다렸다. 기존 정책대로 이미 실행 중인 생성은 유지하며, 확정 전사가 밀리면 새 로컬 요청이 대기한다.

## 발견한 손실과 수정

초기 동시 실행에서는 입력 878.3035초 중 WAV가 **843.792초**였는데 gap은 빈 배열이었다. 전사만 실행해도 **864.208초**였다. 파형의 시간 오차가 누적되어, ACK 성공과 작업 완료만으로 원음 보존을 판정할 수 없다는 점을 확인했다. 서로 다른 시계를 거치는 주입 경로 자체의 손실도 포함될 수 있어 실제 마이크 결함으로 단정하지 않는다.

수집 worklet은 처리 프레임 번호의 공백을 시간축에 반영하고, 입력이 없을 때 부분 버퍼를 먼저 저장한다. 정상 무음은 PCM으로 보존한다. 종료 시에는 마지막 worklet 프레임을 받은 후 마이크 트랙을 닫으며, ACK·API 응답을 기다리는 동안 마이크를 계속 열어 두지 않는다.

수정 fixture의 실제 실행 결과:

| 항목 | 결과 |
|---|---:|
| 저장 PCM | 42,158,592 프레임 / **878.304초**, 48kHz |
| 원음 시간축 | 42,159,360 프레임 / 878.320초 |
| 명시한 공백 | 시작 512프레임 + 종료 256프레임 = **16ms** |
| 녹음 상태 | **중단됨(interrupted)**, error 없음 |
| 파형 대조 | 1kHz 변환 후 전역 상관 0.999999999957, 30초 간격 대조 지점의 시간 오차 0초 |
| 확정 전사 범위 | 34개, 모두 done |
| 녹음 중 생성 | 15건, 모두 done |
| 전체 fixture 작업 | 준비 작업 포함 17건 완료 |

공백이 남았으므로 정상 종료·gap 0으로 보고하지 않는다. 파형 대조는 샘플링 진단이며 48kHz 비트 단위 동일성이나 단어 정확도 검증은 아니다. 최종 버전의 마이크 종료 순서는 회귀 검사로 확인했으며, 이 장기 실행은 해당 종료 순서의 마지막 개인정보 보완 직전 코드로 실행했다.

## 지연 결과와 해석

| 지표 | 초기 동시 실행 A | 수정 fixture 동시 실행 B |
|---|---:|---:|
| 재생·수집 실제 경과 | 878.450초 | 905.339초 |
| 확정 ASR 호출 중앙값 / P95 | 24.987 / 38.927초 | 21.838 / 34.045초 |
| 확정 전사 시간축 지연 중앙값 / P95 | 42.930 / 63.660초 | 39.790 / 59.090초 |
| ACK 중앙값 / P95 | 6.9 / 174.9ms | 5.7 / 102.8ms |
| 정지 뒤 마지막 확정 ASR 완료 | 36.208초 | 22.637초 |
| 정지 뒤 생성 포함 전체 작업 완료 | 171.419초 | 149.966초 |
| 답변 제출→완료 중앙값 / 최대 | 49.410 / 76.592초 | 43.020 / 156.644초 |

지연은 해결되지 않았다. 16GB에서 전사와 생성이 경쟁했고, B의 호스트 전체 swap 사용량은 중앙값 약 7.96GiB였다. 이미 시작한 생성을 끝까지 유지하는 정책상 GPU 경쟁이 남는다. 입력 경로·부하·호스트 상태가 달라 A/B 수치를 제품 성능 개선율로 해석하지 않는다. 초기 ASR 단독 실행의 호출 중앙값은 15.017초였으나, 이 실행에도 원음 길이 손실이 있어 정상적인 동시 실행 기준선으로 사용하지 않는다.

승인된 모델 다운로드와 짧은 회귀 검사가 일부 겹쳤다. 격리된 벤치마크와 모델별 최대 GPU 메모리 측정이 아니다. 같은 하드웨어의 깨끗한 상태에서 반복한 분포가 필요하다.

## 재현·남은 범위

```sh
npm --prefix frontend run build
.venv/bin/python experiments/serve_long_recording_fixture.py /tmp/long-human-check .local-state/runtime/long-human-20261014/sul-part1.mp3 single
# 출력한 URL에서 fixture 실행 후 ready=true 확인
.local-state/runtime/qwen-eval-venv/bin/python experiments/build_long_recording_report.py --align /tmp/long-human-check
```

새 임시 폴더를 사용한다. 위 비교 결과를 다시 집계하려면 A/B 두 폴더를 인수로 전달한다. `--align`은 기존 평가 환경의 numpy/scipy를 사용한다. 앱 사용에 이 평가 환경을 추가할 필요는 없다.

[원작 텍스트](https://ko.wikisource.org/w/index.php?title=술_권하는_사회&oldid=425047)는 낭독 도입부·파트 경계·시각이 정렬된 정답이 아니다. 전체 낭독 CER을 보고하지 않는다. 실제 마이크 장시간 녹음, 여러 화자·소음·겹침 발화, 시간 정렬된 강의/회의 전사 정답, M5·Windows·원격 NVIDIA 실행은 이번 검증 범위에 없다. 고유명사 비교는 별도 짧은 사람 음성 [모델 비교](new-local-models.md)에 기록한다.
