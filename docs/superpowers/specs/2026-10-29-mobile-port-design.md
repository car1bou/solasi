# Solasi Android tablet and iPad port

## Intent and authority

The user changed priority to Android tablets and iPad, requested development using simulators, and authorized installing the missing official tools. Preserve the existing screens and workflows; replace OS-dependent code. Technical decisions are delegated and only unavoidable user actions should be requested. The earlier Windows trial remains intact.

## Architecture decision

Reuse the React frontend and Python ASGI/SQLite/domain implementation inside each native app. Android uses a Kotlin WebView host with embedded CPython; iPad uses UIKit/WKWebView with embedded CPython. No remote backend, sync service, or desktop companion is required. Serve resources through native interception and invoke ASGI in process. Use the existing native HTTP/PCM/ACK/source-version contracts.

A desktop subprocess cannot be the mobile execution boundary: iOS requires embedded Python and does not support subprocess execution. Native model, transcription, PDF/OCR and audio operations must execute as linked libraries/platform APIs within the app. Do not route unsupported operations to the desktop, a public server, or an unrequested external AI service.

## Approaches considered (agent decisions)

1. Embedded Python plus native WebView/platform adapters: selected, preserves the domain/data implementation and existing screen components.
2. Rewrite the backend in Kotlin and Swift: duplicates the substantial Python domain logic and risks divergent data semantics; rejected.
3. Web-only/remote API wrapper: does not meet standalone local operation or native durable capture/file access requirements; rejected.

## Required boundaries

- Separate sandbox storage and test vaults. Never migrate, copy or modify the installed Mac vault or models as fixtures.
- No arbitrary paths from JavaScript, external navigation with a native bridge, open listener, untrusted frames, or silent model/API fallback.
- Android document URI grants and iOS security-scoped files must remain durable and distinguish originals from app-managed working copies. Do not falsely claim desktop path linking where the mobile provider cannot offer it.
- Microphone native capture, bounded PCM delivery, save acknowledgement, interruptions and recovery reuse the app's durable recording contract. Permission denial must preserve state.
- Generated answers keep source references, model identity, explicit limits, model preparation and cancellation. A missing library/model is an explicit unavailable state, never a simulated success.
- Models are separate verified data assets. A simulator smoke does not establish real tablet AI speed, memory headroom, battery or pen behavior.
- Native binary wheels require the correct Android/iOS ABI and Python minor. Mobile dependency versions may differ only with explicit locks/hashes and compatibility verification.
- Build/install tools from official sources only. User authentication and legally binding acceptance are requested at the actual gate. No account secrets in chat or logs.
- Preserve concurrent dirty user UI/domain changes. Work in existing linked worktree `codex/serverless-mac`; no blanket commit, reset or push.

## Work order and completion evidence

1. Install official Android Studio/SDK/emulator and Xcode/iPad Simulator. Record exact versions, receipts and concrete blockers.
2. Prove compatible embedded dependencies and in-process application lifespan/API transport with real domain tests.
3. Build native Android and iPad hosts using the same frontend; exercise create/reopen, material selection/page/ink, capture/playback/export and protected resource routing.
4. Replace native worker subprocesses with in-process platform/library adapters and prove local inference/model identity on each available runtime.
5. Build installable debug artifacts and run simulator workflows; report exact tested vs pending boundaries and maintain a resumable task record.

The task is not complete with a launcher, mock API, static screenshot or project skeleton. Missing Xcode/SDK, dependency ABIs, linked inference implementations and unrun simulators remain named blockers until verified.

## Current environment evidence

2026-10-29: macOS 27.0.1 arm64; only `/Library/Developer/CommandLineTools` selected; `xcrun simctl` unavailable. No Xcode/Simulator/Android Studio in Spotlight or standard application locations, no Android SDK/.android/CoreSimulator, no Java runtime. About 29GiB free before downloads. Google official Studio DMG download started; Xcode App Store account sheet requires user completion. No product code changed at this point.

## Primary sources

- https://docs.python.org/3.14/using/ios.html — embed Python; platform and extension packaging.
- https://docs.python.org/3.14/using/android.html — embedded Android runtime.
- https://chaquo.com/chaquopy/doc/current/android.html — Android embedding, ABI and SDK constraints.
- https://github.com/beeware/Python-Apple-support — iOS CPython XCFramework.
- https://developer.android.com/studio — official tool downloads and published checksums.
- https://developer.apple.com/xcode/resources/ — official Xcode distribution.
