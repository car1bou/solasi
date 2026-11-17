# Windows port: preserve Solasi

User authorization: keep the current features, screens and data rules; change OS-specific implementations, starting with Windows. Technical choices are delegated. Earlier proposals to defer existing features (including realtime transcription) do not apply.

## Requirements

- Windows 11 x64, independent local application. No account, sync or remote-host product mode.
- Preserve the current React components, all workflows, source references, approval rules, hashes, revisions, recovery, and Mac behavior.
- Preserve after-stop and realtime transcription, local text/image generation, semantic retrieval, fast OCR, file linking, native drafts, playback, exports and close protection.
- End users do not install Python, Node, compilers or Ollama. Model downloads remain explicit and verified. External APIs stay optional; no silent remote fallback.
- CPU-only 16GB is an evaluation target, not a measured minimum or performance promise.
- Existing dirty UI work belongs to the user and must not be reverted or reformatted.
- Actual Windows verification is required before claiming support. User has a RustDesk-connected Windows PC; connection access is being checked.

## Implementation decisions

Reuse the existing Python ASGI app and native command contracts. Windows uses pywebview EdgeChromium with all local HTTPS resources intercepted by WebView2, without an HTTP listener. A single application asyncio thread owns the ASGI app/SQLite; API bridge threads marshal calls onto that thread. Audio capture lives outside the webview, and commits through the existing recording protocol. Local page/OCR processing is isolated in the material worker; Mac adapters remain the default on Mac.

Windows generation uses a pinned llama.cpp worker and GGUF plus a matched vision projector. Preserve model request/schema/digest validation. Preserve the existing EmbeddingGemma preprocessing, pooling, normalization and index identity; do not substitute incompatible vectors. Build Windows dependencies on Windows, verify asset hashes, bundle dependencies separately from model weights and user data.

Alternatives considered: a C# WebView2 host adds a second pipe client and language; Tauri adds Rust and IPC. pywebview reuses the existing Python engine and exposes documented WebView2 hooks. A loopback server is simpler but changes the installed Mac app's local, listener-free execution model. Native Windows OCR requires package identity according to Microsoft; do not claim an unpackaged Preview supports it without validation. Choose a bundled portable OCR implementation instead.

## Verification

Focused tests for platform dispatch, safe paths, API auth/cancellation, range responses, renderer pixels/coordinates, CPU model contracts, subprocess cleanup and native recording ACKs. Full Python/TypeScript regression checks after integration. Windows build and real GUI acceptance must cover file linking, PDF/image orientation, pen/drafts, audio minimize/stop/playback, ASR both modes, OCR, generation, semantic retrieval and close/crash recovery. Record tested and untested boundaries; no mocks counted as device evidence.
