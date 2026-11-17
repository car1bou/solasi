# Windows Port Implementation Plan

> **For agentic workers:** Use superpowers:subagent-driven-development for independent implementation and review. Work on this existing isolated worktree; do not commit the user's dirty changes.

**Goal:** Preserve Solasi's existing functionality/screens while replacing OS-dependent implementations for Windows 11 x64.

**Architecture:** Existing React UI and Python ASGI/domain logic, Windows WebView2 host with in-process API/resource transport, portable material/ink renderer, pinned CPU inference workers. Mac paths unchanged.

**Tech Stack:** Python 3.12, current React/TypeScript, pywebview EdgeChromium, Pillow/PDFium, llama.cpp/whisper.cpp, frozen Windows bundle.

**Spec:** docs/superpowers/specs/2026-10-27-windows-port-design.md

## Global Constraints

Preserve all current features/screens and dirty work. No remote listener, silent API fallback, original duplication, model auto-download or unverifiable support claims. CPU16GB is a test target. Windows real-device results are separate from platform mocks. Do not change signing, accounts, sync, existing vaults or installed Mac app.

## Review Focus

- Korean/spaces/Unicode paths and original movement; no path traversal or unintended file disclosure.
- PDF rotations/crop boxes and EXIF orientation; normalized ink remains aligned.
- Microphone removal, pending ACK, sleep and close; preserve received audio.
- Model/digest/projector/embedding identity mismatch; refuse rather than mislabel results.
- Frozen Windows startup without developer tools; no orphan workers or hidden server.

## Task 1: Portable materials and handwriting

Files: new Windows/portable material and handwriting adapters, material_worker.py, handwriting.py dispatch, focused tests.
- [x] Write/run failing tests for metadata/rendering, orientation/geometry, recognition output and platform dispatch.
- [x] Implement portable backend; preserve Mac code path and common approval/search flow.
- [x] Run focused tests including existing handwriting/material tests.

## Task 2: Windows host and native contract

Files: new lecture_study/windows_app.py and host support modules, tests/test_windows_app.py. Parent owns frontend/src/api.ts and frontend native playback bridge injection.
- [x] Test API/resource path boundaries, body limits, cancellation, ranges, file selection and close/recording behavior.
- [x] Implement in-process ASGI loop, WebView2 resource handling and native commands/events; no listener.
- [x] Implement sounddevice capture with bounded queue and existing saved-audio ACK contract; preserve browser/native playback features.
- [x] Verify helper tests on Mac and actual Windows after transfer.

## Task 3: CPU inference and model compatibility

Files: new Windows generation worker/build support, direct_models.py platform dispatch, macos embedding portability guards, focused tests.
- [x] Test Windows asset acceptance vs Mac formats and model/projector/schema bounds.
- [x] Implement pinned native CPU generation+vision and portable embedding worker, preserving framed contracts/identity.
- [x] Run focused old/new direct-model and embedding tests; compile native code where available.

## Task 4: Runtime preparation and packaging

Files: runtime.py, Windows runtime/build/freeze scripts, Windows requirements, docs/windows.md, frontend/src/api.ts and tests.
- [x] Test OS manifest/binary suffix/preparation routing and archive integrity/extraction.
- [x] Build per-user standalone Windows package with engine/assets/runtime dependencies; models/vault excluded.
- [x] Preserve API/screen components by adding Windows transport detection only.
- [x] Run Python suite, frontend tests/check/build; review the complete diff.

## Task 5: Windows acceptance

- [x] Connect to existing RustDesk Windows PC without altering security/access settings.
- [x] Inspect CPU/RAM/OS, installed build tools and available input devices using read-only commands.
- [x] Build/run in a new task directory and disposable vault; leave existing projects/data untouched.
- [x] Exercise existing workflows and record exact evidence. If access/build dependencies block this, state the specific condition and do not claim device support.

## Execution outcome — 2026-10-28

The implementation/build tasks and the connected-PC trial workflow above were exercised. The delivered trial artifact is `output/Solasi-Windows-x64-20261028-r2.zip`; exact evidence and remaining release acceptance items are in `docs/windows.md` and `TASK_STATE.md`. Checked tasks do not establish clean-machine installation, 16GB performance, live/realtime recovery or general AI accuracy. Those require the additional environments and measurements listed in the acceptance record. No commit or push was made; concurrent user UI changes remain intact.
