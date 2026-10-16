# Mac 내부 화면·오디오 연결 검증

2026-10-16, Apple Silicon Mac. 제품 앱과 사용자 보관함은 교체하지 않았으며 임시 보관함에서 실행했다.

## 구현 범위

- `WorkerBridge.swift`: 크기를 제한한 파이프 프레임, 응답 조각별 소비 ACK, 요청 취소, 엔진 종료 통지. Python HTTP 서버를 시작하지 않는다.
- `AppResources.swift`: 번들 화면·문서 자산, HEAD/Range 전달, 중단된 요청 취소, 경로 검사, 기존 파일을 덮어쓰지 않는 내보내기.
- `Solasi.swift`: 번들 엔진 실행, 신뢰한 주 화면의 API 요청, NSOpenPanel/NSSavePanel, 같은 보관함의 원음 링크, 앱별 추가 기록 로그.
- `AudioCapture.swift`: AVAudioEngine의 입력을 mono PCM16으로 변환하고 저장 ACK를 받는다. 연결 대기 30초, 정상 무음 보존, 종료 시 복사한 입력 버퍼를 먼저 전달, 입력 복귀를 확인한 뒤 최대 한 번 새 구간 복구를 구현했다.
- `AudioPlayback.swift` / `PlaybackAudio.tsx`: AVPlayer가 필요한 원음 바이트를 Range로 요청한다. 전사 선택 구간과 기존 재생 제어를 연결하며 WAV 전체를 Blob으로 적재하지 않는다.

## 실제 발견한 문제와 확인 결과

1. Swift `FileHandle.read(upToCount: 65536)`로 파이프를 읽을 때 작은 `ready` 프레임이 전달되지 않아 기동 검사가 20초 후 실패했다. `availableData`로 변경한 뒤 같은 Swift→Python 작업 엔진 검사가 통과했다.
2. `solasi-app://app/` 화면에서 ES module과 `crypto.getRandomValues`, `crypto.randomUUID`, `crypto.subtle`이 동작했다. 현재 Mac의 `isSecureContext`는 `true`였다. 모듈 실행은 WebKit의 `didFinish` 직후보다 늦게 완료될 수 있어 fixture가 실제 실행 결과를 기다린다.
3. 같은 scheme의 `<audio>`는 10분 합성 WAV에서 20초 동안 `readyState=0`, `duration=null`로 남았다. 따라서 실제 앱의 원음은 AVPlayer와 제한된 리소스 로더로 재생한다.
4. 실제 Swift 파이프와 Python ASGI 작업 엔진에 1초당 8,000프레임인 합성 무음을 600회 가속 입력했다. 모든 저장 ACK 후 WAV 9,600,044바이트와 PCM 4,800,000프레임을 확인했다. AVPlayer가 같은 원음을 600초 길이로 읽고 599초로 탐색했으며 엔진이 정상 종료했다. 이는 10분 실제 마이크 녹음이 아닌 합성 데이터의 저장·범위 탐색 검사다.
5. 프런트엔드 관련 검사 34개, 대본 내보내기 검사 9개, TypeScript 확인·Vite 빌드, Swift 앱 컴파일, 네이티브 정책·PCM fixture가 통과했다.

## 재실행 명령

앱 소스는 `WorkerBridge.swift AppResources.swift AudioCapture.swift AudioPlayback.swift Solasi.swift`다. `*Fixture.swift`는 각각 별도로 컴파일한다.

```sh
xcrun swiftc -target arm64-apple-macosx13.0 -module-cache-path .local-state/swift-cache \
  macos/WorkerBridge.swift macos/AppResources.swift macos/BridgeFixture.swift \
  -o /tmp/solasi-bridge-fixture
/tmp/solasi-bridge-fixture

xcrun swiftc -target arm64-apple-macosx13.0 -module-cache-path .local-state/swift-cache \
  macos/WorkerBridge.swift macos/AudioCapture.swift macos/AudioFixture.swift \
  -o /tmp/solasi-audio-fixture
/tmp/solasi-audio-fixture

xcrun swiftc -target arm64-apple-macosx13.0 -module-cache-path .local-state/swift-cache \
  macos/WorkerBridge.swift macos/AudioCapture.swift macos/AudioPlayback.swift macos/WorkerPipeFixture.swift \
  -o /tmp/solasi-worker-pipe-fixture
/tmp/solasi-worker-pipe-fixture "$PWD/.venv/bin/python" "$PWD"

xcrun swiftc -target arm64-apple-macosx13.0 -module-cache-path .local-state/swift-cache \
  macos/WorkerBridge.swift macos/AppResources.swift macos/WebViewFixture.swift \
  -o /tmp/solasi-webview-fixture
/tmp/solasi-webview-fixture

.venv/bin/python -m unittest tests.test_transcript_script -q
npm --prefix frontend run check
npm --prefix frontend run build
```

WebKit·AVPlayer fixture는 macOS 그래픽·미디어 서비스에 접근해야 한다. 제한된 실행 환경에서 연결 오류가 나면 별도 검증 앱과 임시 보관함으로 실행한다.

## 이 검사로 확인하지 못한 범위

실제 마이크 권한 창의 지연, 장시간 실제 입력, 물리적인 절전·복귀·장치 교체, 새 패키지의 PDF 창 렌더링, 기존 앱의 IndexedDB 초안 이전은 이 문서의 fixture만으로 확인되지 않는다. 별도 앱의 전체 사용 흐름 검증과 이전 확인을 통과하기 전에는 현재 제품 앱을 교체하지 않는다.
