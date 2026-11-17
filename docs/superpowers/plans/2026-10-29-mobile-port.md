# Android Tablet and iPad Port Implementation Plan

> **For agentic workers:** Use superpowers:subagent-driven-development for scoped implementation and review; use superpowers:dispatching-parallel-agents only for independent investigations. Never commit the user's dirty changes.

**Goal:** Run the existing Solasi workflows in standalone Android tablet and iPad apps, verified in official emulators/simulators before real-device acceptance.

**Architecture:** Existing React + embedded Python ASGI/SQLite, native protected resource/message transport, native file/audio/material/inference adapters. No mobile subprocess or remote product mode.

**Tech Stack:** Kotlin/Android WebView/embedded CPython, UIKit/WKWebView/CPython XCFramework, existing React/TypeScript and Python domain modules, linked native model libraries.

**Spec:** docs/superpowers/specs/2026-10-29-mobile-port-design.md

## Global Constraints

- Preserve current screens/domain/data behavior and unrelated concurrent changes.
- No desktop vault/user data as fixtures, listener, silent external API fallback, arbitrary JS paths, mobile subprocess execution or fake capability success.
- Model files verified and separate from app binaries; simulator results are not real-device performance evidence.
- Tools installed only from official sources; stop only dependent steps for user authentication/contract acceptance or environment failure, continue independent work.
- No commits, push, account changes, security weakening or cleanup of unrelated files.

## Review Focus

- Foreign frames/navigation and encoded traversal must not obtain the native bridge or private files.
- Provider URI loss, Korean/spaced filenames, changed originals and app-managed copies must be explicit without data loss.
- App interruption, microphone denial or packet overflow must never produce a falsely complete recording.
- Wrong CPU ABI/Python wheel/model/projector/vector identity must fail before execution/indexing.
- An emulator-only or unavailable feature must not be presented as a tested tablet feature.

### Task 1: Official simulation environments

**Files:** `.local-state/mobile-tools/`, `output/mobile-environment.json`, `docs/mobile.md`.
- [ ] Verify official Studio checksum/signature and install Android Studio; prepare SDK and tablet AVD after license approval.
- [ ] Complete Xcode App Store installation, SDK/runtime selection and create an iPad simulator after user authentication/license acceptance.
- [ ] Run tool/version/device inventory and record success or the actual blocking condition.

### Task 2: Embedded runtime and application bridge

**Files:** new `lecture_study/mobile_bridge.py`, `tests/test_mobile_bridge.py`, mobile-specific locked requirements/staging script; smallest necessary hooks in existing adapters.
**Interfaces:** Consume AppConfig/ASGI lifespan/native request validation and PCM ACK; produce a JSON-command/resource boundary suitable for JNI and CPython C API without a listener or child process.
- [ ] Resolve mobile wheels for both Python/ABI sets from official package sources; record hashes.
- [ ] Write and run failing integration tests for API create/reopen, origin/path/header limits, file picker injection denial and bounded PCM acknowledgement.
- [ ] Implement the in-process host, preserving one owner thread for SQLite and proper close/cancel.
- [ ] Run new and existing native bridge/domain tests.

### Task 3: Native Android host

**Files:** new `mobile/android/`, shared staging/build scripts, focused bridge tests; only transport detection in existing frontend.
**Interfaces:** Consume Task2 JSON commands/resources and emit existing native audio/playback events.
- [ ] Implement WebView trusted origin/message isolation, asset/resource delivery, durable picker/export and app sandbox paths.
- [ ] Embed Python and native microphone PCM delivery with ACK/backpressure; preserve errors and interruption state.
- [ ] Build debug APK and run on tablet AVD; verify actual UI create/reopen and local resource flows.

### Task 4: Native iPad host

**Files:** new `mobile/ios/` and reproducible project/build specification, focused bridge tests.
**Interfaces:** Same Task2 contract as Android; existing WKWebView native message and media semantics.
- [ ] Implement iPad host, bridge replies/custom resource scheme, document provider/export and embedded Python initialization.
- [ ] Implement microphone capture lifecycle/ACK and playback without spawning workers.
- [ ] Build simulator app with Xcode; run create/reopen/material/recording workflows on iPad simulator.

### Task 5: In-process native engines and complete simulator acceptance

**Files:** mobile native library adapters/build manifests plus focused material, ASR and model dispatch tests.
- [ ] Replace material/OCR, ASR/audio decoding and generation/embedding subprocess boundaries with platform/linked-library calls.
- [ ] Validate pinned assets, schema/image/source evidence, token budget and embedding identity on each runtime.
- [ ] Exercise file/page/ink, transcription, playback/seek/export, local AI and normal/interrupted persistence in simulators.
- [ ] Produce debug APK/simulator app, exact evidence, final independent review and clearly bounded remaining real-device checks.
