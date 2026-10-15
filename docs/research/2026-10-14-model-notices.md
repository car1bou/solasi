# C4 Whisper·Silero 모델 고지 원본

확인일: 2026-10-14 (Asia/Seoul). 공개 GitHub ref/commit metadata, 고정 커밋의 LICENSE 텍스트, 공식 라이선스 설명을 확인했다. 모델·미디어 가중치 다운로드, 제품 코드·manifest·테스트 수정, 모델 실행은 하지 않았다. 기존 [runtime 자산 인벤토리](2026-10-14-runtime-assets.md)는 수정하지 않았다.

## 고정 LICENSE 자산

아래 bytes와 SHA-256은 raw URL에서 받은 **원본 텍스트 bytes**를 대상으로 계산했다. 줄바꿈 변환이나 텍스트 재직렬화를 하지 않았다. 모델 가중치의 크기·SHA와 다른 값이다.

| 고지 | 고정 commit | bytes | SHA-256 |
|---|---|---:|---|
| OpenAI Whisper 모델 고지 | `86098128c0b4f24f0e2aa2994de830614b474227` | 1,063 | `b5d65a59060e68c4ff940e1eddfa6f94b2d68fdf58ed7f4dd57721c997e35e9d` |
| Silero VAD v6.2 고지 | `be95df9152c0d7618fa1edfeb296fc3dae32376f` | 1,075 | `2e63e9a38b6e8fc0c7bc37ce174caca1862870856c6daf5697cfb785e925520b` |

### OpenAI Whisper / large-v3-turbo

- 고정 다운로드: [OpenAI Whisper LICENSE 원본](https://raw.githubusercontent.com/openai/whisper/86098128c0b4f24f0e2aa2994de830614b474227/LICENSE).
- 사람이 확인할 페이지: [고정 LICENSE](https://github.com/openai/whisper/blob/86098128c0b4f24f0e2aa2994de830614b474227/LICENSE).
- 조회 시점 main commit은 위 `860981...`, commit 시간은 2026-08-31T17:19:19Z였다. [GitHub commit metadata](https://api.github.com/repos/openai/whisper/commits/main)
- **LICENSE 파일 마지막 변경 commit**은 `6e3be77e1a105e59086e3e21ff5f609fd6fa89a5`(2022-09-21T16:09:43Z)였다. [파일 commit 기록](https://api.github.com/repos/openai/whisper/commits?path=LICENSE&per_page=1), [마지막 변경 commit의 원본](https://raw.githubusercontent.com/openai/whisper/6e3be77e1a105e59086e3e21ff5f609fd6fa89a5/LICENSE). 두 고정 커밋의 LICENSE는 byte 단위로 동일했고 bytes/SHA도 같다.
- 내용 성격: MIT 전체 라이선스, 저작권자는 `Copyright (c) 2022 OpenAI`. 복사·수정·배포 등의 허용과 저작권/허가 고지 포함 조건, 보증 부인이 들어 있다. 이 문서는 고지의 성격을 기록한 것이며 배포물 전체의 준수 판정은 아니다.
- 모델 가중치 적용 근거: [같은 고정 commit README의 License 절](https://github.com/openai/whisper/blob/86098128c0b4f24f0e2aa2994de830614b474227/README.md#license)은 Whisper 코드와 모델 가중치를 MIT로 공개한다고 명시한다. [OpenAI의 large-v3-turbo 모델 카드](https://huggingface.co/openai/whisper-large-v3-turbo)도 license=mit이다.
- OpenAI 모델 고지는 ggml-org/whisper.cpp 엔진 LICENSE와 저작권자가 다르다. C4에서 모델 고지를 엔진 고지로 대체하지 않는다.

### Silero VAD v6.2 / 앱의 v6.2.0 표기

- 공식 GitHub ref는 **`refs/tags/v6.2`**이며 object type=commit, resolved SHA는 `be95df9152c0d7618fa1edfeb296fc3dae32376f`였다. [태그 ref metadata](https://api.github.com/repos/snakers4/silero-vad/git/ref/tags/v6.2)
- `refs/tags/v6.2.0` 조회는 404였다. 앱의 파일명/버전 표기가 v6.2.0이어도 LICENSE 출처를 존재하지 않는 v6.2.0 GitHub ref로 만들지 않는다. source tag=v6.2와 resolved SHA를 별도로 기록한다.
- 고정 다운로드: [Silero v6.2 LICENSE 원본](https://raw.githubusercontent.com/snakers4/silero-vad/be95df9152c0d7618fa1edfeb296fc3dae32376f/LICENSE).
- 사람이 확인할 페이지: [고정 LICENSE](https://github.com/snakers4/silero-vad/blob/be95df9152c0d7618fa1edfeb296fc3dae32376f/LICENSE).
- 내용 성격: MIT 전체 라이선스, 저작권자는 `Copyright (c) 2020-present Silero Team`. 고지 포함 조건과 보증 부인이 들어 있다. [같은 commit의 공식 README](https://github.com/snakers4/silero-vad/tree/be95df9152c0d7618fa1edfeb296fc3dae32376f#key-features)는 배포된 Silero VAD가 MIT임을 설명한다.
- **미확인:** 앱이 준비하는 GGML/ONNX/JIT 가중치가 이 tag와 byte/변환 provenance로 연결되는지, 모델 파일의 현재 bytes/SHA. 이번에는 라이선스 텍스트만 확인했고 가중치를 받지 않았다. 엔진·변환 도구 고지는 별도 보존 대상이다.

## C4 고지 등록 체크 예

1. notice 자산 URL은 위 raw **commit** URL로 고정한다.
2. 받은 원본 bytes의 길이와 SHA-256을 위 값과 비교한다.
3. 파일을 Whisper 모델 고지와 Silero 모델 고지로 각각 보존하고 기존 엔진 고지를 유지한다.
4. 모델 가중치의 source revision·bytes·SHA·변환 기록과 LICENSE 텍스트의 revision·bytes·SHA를 구분한다.
5. 전체 MIT 원문은 다운로드된 notice 파일에 보존한다. 이 Markdown 요약을 원문 고지 대신 배포하지 않는다.

확인 경계: 작은 공개 LICENSE 3회 수신(Whisper current/last-change와 Silero tag), SHA/bytes 계산, Whisper 두 원문 byte 일치, 공개 ref 확인까지 수행했다. 실제 모델 준비·실행·배포 검증은 수행하지 않았다.
