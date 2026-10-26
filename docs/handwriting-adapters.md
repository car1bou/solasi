# 필기 이미지·인식 엔진 연결

필기 입력 검증·후보 저장·승인은 공통으로 사용하고, **이미지 생성기와 이미지 인식기만 교체**할 수 있다. Mac 기본 구현은 CoreGraphics/PDFKit과 Apple Vision이다. Windows·Android용 생성기·인식기와 앱은 아직 구현하지 않았다. 현재 로컬 모델 manager는 Mac MLX 경로이며, 함수 분리가 다른 OS에서의 모델 실행을 보장하지 않는다.

## 호출 경계

| 함수 | 역할 |
| --- | --- |
| `handwriting.ink_payload(snapshot)` | 페이지 크기·획을 검증하고 pen 획을 추린다. |
| `handwriting_macos.render_ink(payload, image_path, *, page_source=None, page=1)` | 원본 페이지와 pen 획을 PNG로 합성한다. OCR을 실행하지 않는다. |
| `handwriting_macos.recognize_image(image_path)` | 준비된 PNG를 Vision으로 인식한다. 렌더링하지 않는다. |
| `handwriting.recognize_ink(snapshot, image_path=None, *, renderer=None, recognizer=None)` | 생성기·인식기를 연결해 기존 후보 결과를 반환한다. 기본값은 Mac adapter다. |
| `handwriting.recognize_local_image(image_path, manager, before_local=None, model='qwen3.5:4b')` | 준비된 이미지를 Qwen/Gemma에 전달한다. 렌더러·Vision을 호출하지 않는다. |
| `handwriting.recognize_local_ink(..., renderer=None, diagnostic_recognizer=None)` | 이미지 준비·로컬 인식·좌표를 연결한다. 기본 Mac 경로에서는 Vision 잘림 진단을 별도로 유지한다. |

`image_path`는 `Path`다. 생성기는 지정한 파일에 PNG를 저장하고 `renderer / width / height` metadata를 반환한다. 원본 페이지는 1부터 시작한다. 인식기는 `engine / regions`를 반환한다. `regions`는 `bbox / text / candidates`를 가지며, bbox는 왼쪽 위 기준 정규화된 `[x, y, width, height]`다. 기존 `save_recognition`이 좌표·문자열 길이·페이지 현재성을 검사한다.

공통 함수가 만든 임시 이미지는 성공·실패·취소 때 제거한다. 호출자가 `recognize_ink`의 `image_path`를 지정했다면 그 출력은 호출자가 소유한다. 이미지 입력 함수에 직접 넘긴 파일도 삭제하거나 수정하지 않는다. 생성기·인식기 자체의 자식 프로세스는 각 구현이 종료·취소 처리해야 한다.

## 대체 구현 연결

플랫폼 구현의 두 async 함수를 다음과 같이 연결한다. `device_renderer`와 `device_ocr`는 위 계약에 맞춰 구현한 함수다.

```python
from lecture_study.handwriting import recognize_ink, save_recognition

result = await recognize_ink(
    snapshot,
    renderer=device_renderer,
    recognizer=device_ocr,
)
candidate = save_recognition(db, snapshot, result)
```

두 함수를 모두 지정하면 Mac adapter를 호출하지 않는다. 원본 페이지를 읽은 결과의 engine에는 공통 단계에서 `/page`를 붙인다. 이 값은 같은 페이지의 자동 재인식 중복 방지에도 쓰이므로 임의로 바꾸지 않는다. 빈 대체 입력은 실행하지 않은 Apple 엔진을 표시하지 않고 `empty-ink`를 반환한다.

후보는 검색 근거가 아니다. 기존 `approve_recognition`에서 사용자가 확인한 문장부터 색인하며, 필기를 바꾸면 현재 검색에서 제외하고 과거 출처는 보존한다.

## 로컬 비전 모델과 진단

준비된 이미지에 현재 Mac manager를 직접 연결할 수 있다.

```python
from pathlib import Path
from lecture_study.handwriting import recognize_local_image

result = await recognize_local_image(
    Path('/absolute/path/to/prepared.png'),
    manager,
    model='qwen3.5:4b',  # 또는 gemma4:12b
)
```

이 함수는 PNG 생성이나 원본 사진 선택·확대를 하지 않는다. 이미지 준비까지 기존 앱과 동일하게 처리하려면 `recognize_local_ink`를 사용한다. 기본 Mac 조합에서는 기존 사진·EXIF 처리, Qwen 확대, 모델 digest, 원문 전사 프롬프트와 Vision 잘림 경고를 보존한다.

대체 renderer를 지정하면 Vision 진단을 암묵적으로 실행하지 않는다. 필요하면 `diagnostic_recognizer=device_diagnostic`을 함께 지정한다. 진단을 생략한 결과에는 `edge_touching`을 만들지 않으며, 이를 '잘림 없음'으로 해석하면 안 된다. 현재 Mac 기본 진단이 실패하면 기존처럼 요청을 실패시킨다. 외부 API나 다른 엔진으로 자동 전환하지 않는다.

## 빌드·검사

`HandwritingRecognition`의 기존 결합 CLI와 `--recognize-image`를 유지하고 `--render-only --image OUTPUT`만 추가했다. 기존 엔진 빌드 스크립트가 같은 Swift 파일을 컴파일하며 새 Python adapter를 수집한다. 새 의존성이나 DB 마이그레이션은 없다.

```sh
python -m unittest discover -s tests -p 'test_handwriting*.py' -v
python -m unittest discover -s tests -p 'test_native_handwriting.py' -v
```

Mac의 실제 픽셀·Vision·모델·네이티브 흐름 검증 범위는 [분리 검증 기록](handwriting-adapters-validation-20261027.md)을 참고한다. 비Mac 플랫폼을 흉내 낸 주입 검사는 인터페이스 계약 검사이며 실제 Windows·Android 실행 시험과 다르다.
