# Windows port

The Windows implementation preserves the existing React screens and domain workflows. It replaces the desktop host, local resource transport, microphone capture, material/ink rendering and model runtime. The Mac entry points remain available. Windows support is not established by platform mocks or by compiling a CPU worker on Mac; the acceptance record below distinguishes actual Windows checks from the remaining release checks.

## Build machine and end-user machine

Build on Windows 11 x64 with Python 3.12, Git and the Visual Studio C++ workload. CMake 4.4.4 and the Python build dependencies are installed in an isolated build environment. The end user receives the frozen app, Python dependencies and native CPU engines; no Python, Node, compiler or Ollama installation is required. The installer includes Microsoft's signature-verified Evergreen WebView2 Runtime installer. Models and user records are not included in the app bundle.

Build the current frontend on the development machine with `cd frontend; npm ci; npm run build`, or use a prepared source snapshot that includes the matching `frontend/dist`.

```powershell
# Developer build; change this Python path to a Python 3.12 executable.
.\windows\Build-Windows.ps1 -Python C:\Python312\python.exe
```

The script builds pinned llama.cpp ModelWorker/EmbeddingWorker, whisper.cpp CLI/VAD and Tesseract. Generation, embedding and ASR include baseline and AVX2/FMA/F16C variants; a baseline CPUID/XGETBV helper selects a compatible variant only after receipt/hash verification. FFmpeg/ffprobe use a pinned LGPL shared Windows build. Source revisions, input checksums and notices are retained in receipts. Build output defaults to `.local-state\windows-build\Solasi` and refuses to overwrite an existing app output. Model files remain outside the bundle.

The equivalent Python build steps are `scripts/build_windows_models.py`, `scripts/build_windows_runtime.py` and `scripts/freeze_windows_app.py`; each has `--help`. Build scripts can use an already prepared private CMake/vcpkg environment without installing tools globally.

## Install and run

Extract and retain the complete app folder, then run `Solasi.exe`. If WebView2 is absent, run the included Microsoft-signed `setup/MicrosoftEdgeWebView2RuntimeInstallerX64.exe` first. This portable route does not require PowerShell policy changes and does not register an external audio protocol or Start menu shortcut.

For environments already permitted to run local scripts, `Install-Solasi.ps1` provides per-user installation. It verifies bundled hashes and Microsoft's Runtime installer signature, installs the Runtime per user, copies the app to `%LOCALAPPDATA%\Solasi\app`, and creates a Start menu shortcut. It preserves existing app versions when replacing and refuses replacement while Solasi is running. It registers `solasi://audio` only if that protocol is not owned by another application.

User data lives in `%LOCALAPPDATA%\Solasi\data`; models/runtime data live in `%LOCALAPPDATA%\Solasi\runtime`. Original PDFs, images and imported audio remain linked to their chosen source paths. Moving the app folder does not migrate or delete these records. App-created recordings and drafts use the existing durable storage/recovery paths.

For development acceptance with a new disposable vault:

```powershell
python -m lecture_study.windows_app `
  --data-dir C:\SolasiTest\vault `
  --runtime-dir C:\SolasiTest\runtime `
  --frontend-dir frontend\dist
```

Do not use the installed Mac vault as a Windows test fixture. App packaging and model preparation are separate steps. In development, direct native model workers are expected under `<runtime>\direct-engines`; frozen apps use `<app>\engines`.

## Runtime boundary

- All app resources come from `https://solasi.invalid` via WebView2 resource interception. That hostname is an internal origin, not a web service. There is no application HTTP listener.
- One asyncio thread owns ASGI/SQLite. The existing native request validation, source/version checks and audio packet/ACK contracts are reused.
- Native microphone capture is independent of WebView visibility. Minimize, close confirmation, device loss, interrupted recordings and re-entry must be checked with the actual input device.
- Windows local generation uses Qwen3.5 4B GGUF plus its matched vision projector. Downloads are explicit, pinned and verified before publication. No API fallback is automatic.
- Initial CPU generation has an **8192-token per-call execution limit**. Long summary/minutes inputs use the existing source-preserving split workflow. This does not claim Mac's larger per-call context or equal performance.
- Embeddings preserve the existing EmbeddingGemma v1 tokenizer/prefix, 768 dimensions, mean pooling and L2 normalization. Other model/vector versions are not mixed into that index.
- Windows fast OCR uses Tesseract with pinned Korean/English data. The engine differs from Apple Vision; Korean handwriting accuracy must be measured separately.

## Verification record

2026-10-27: the full Python suite on Mac passed 746 tests (7 conditional skips), including compiled CPU-worker protocol checks. Frontend checks, 113 tests and the production build passed. These checks do not establish Windows runtime support.

Actual remote Windows smoke opened the existing Solasi UI, created a new lecture record, closed the window and reopened the saved record. A stale initial NavigationCompleted error was reproduced, fixed by tracking the app root's navigation ID, and verified absent on the second Windows run. The first Windows automated run exposed a real CP949 manifest-decoding error, a missing VAD `.exe` suffix and test-fixture portability problems. These were fixed; 65 Windows boundary tests passed with 5 conditional skips on the real PC. ZIP validation now examines the original archive name before Windows normalizes separators. Native generation and embedding workers were built with MSVC using Microsoft SDK files in an isolated build folder, then the generation worker passed 3 compiled protocol/Korean-path checks. Actual Qwen text, image and JSON-schema inference passed. The integrated inference check also returned finite, L2-normalized 768-dimensional EmbeddingGemma vectors with the pinned identity. The runtime build and verified ASR/VAD/OCR asset preparation completed on Windows. The frozen worker self-check passed, and `Solasi.exe` opened the existing UI and saved lecture without a separately installed Python runtime. Initial build logs are retained in `output/windows-diagnostics-1`; later reports are retained in `output/windows-diagnostics-2` and `output/windows-diagnostics-3`.

A generated Korean printed-font OCR fixture passed its expected-text check (agreement 0.963, about 0.26 seconds). This is one synthetic printed fixture, not evidence of general or handwriting accuracy. The initial scalar Whisper build exceeded the product's 120-second timeout on an 8.744-second Korean TTS fixture. A separate diagnostic completed in about 135 seconds, including about 127 seconds of encode time. The corrected build includes hash-verified baseline and AVX2/FMA/F16C executables plus a conservative CPUID/XGETBV probe. On this PC the accelerated Korean TTS check passed: ASR plus VAD took 15.314 seconds, normalized expected-text agreement was 1.0, and the combined TTS/ASR/VAD/printed-OCR run took 18.568 seconds. The product timeout remained 120 seconds. This is one synthetic fixture, not a real-time or general lecture-quality claim. The report is `output/windows-diagnostics-3/runtime-acceptance/smoke-20261027T042348727684Z-41572/report.json`.

The first frozen build failed at final folder rename with Windows access denied. A diagnostic rebuild using a normalized destination published on its first attempt without retries. That result does not establish the earlier error's cause. Destination normalization now happens after the existing-output and symlink refusal checks.

Remote test PC: Windows 11 Home x64 build 10.0.26200, Ryzen 7 9800X3D, about 64GB RAM. This machine does **not** establish 16GB laptop performance or a clean end-user environment: it already contains developer tools.

The final `Solasi-release` frozen app was published on 2026-10-28. Its console worker passed PDF crop/rotation rendering across four pages, EXIF JPEG orientation, Korean UTF-8 text parsing, four-page PDF extraction through frozen LiteParse, and ink composition. The original fixture hashes remained unchanged. Evidence: `output/windows-diagnostics-4/release-acceptance/report.json`.

**Current trial package:** `output/Solasi-Windows-x64-20261028-r2.zip` (156,066,920 bytes), SHA256 `5edeab20e386e005e80c162fd556a38b8e7a0abede174e989263823d4f949127`. The manifest covers 1,489 files totaling 353,756,600 bytes; manifest SHA256 is `1473d12a7c2b13a61e90e4fa5e090dde11080914f6782baf3317876740741f7f`. After transfer to Mac, the archive SHA256, CRC and every manifest file hash passed again. Models and vaults remain external. The frontend is the source snapshot prepared October 27; the final bundle also includes the October 28 Windows/runtime and image-explanation fixes. Concurrent later workspace UI edits are not automatically included.

Earlier packages `Solasi-Windows-x64-20261027.zip` and `Solasi-Windows-x64-20261028.zip` are superseded diagnostics. Real GUI testing exposed two image-explanation defects: a generation-only `before_local` callback reached `model_status`, and the output schema allowed citations that omitted the selected image. The current package forwards the callback only to generation and requires the selected image citation. Regression checks reproduced the defects before the fixes. Related Mac vision tests passed 22; the actual Windows vision/model/build group passed 22 with 4 conditional skips. CPU dispatch/build tests and independent code review also passed; no automatic API fallback was introduced.

Actual GUI acceptance used only owned synthetic fixtures and a separate vault:

- Native file selection linked four Korean/spaced PDF, PNG, JPEG and TXT names. EXIF orientation and four PDF pages displayed correctly. Two ink strokes saved at revision 2 survived a normal process exit and reopening.
- File import of the 8.745-second Korean TTS fixture produced the expected Korean transcript. Source and stored PCM frame counts were both 139,920 at 16kHz. Paragraph playback started, pause worked and seeking changed the displayed playback position. The TXT export was saved through the native dialog and its Korean UTF-8 content was inspected. This establishes the interaction and data path, not audible playback quality or fine-grained alignment accuracy. Native Whisper output with the product's 1000ms padding contained two segments (0–4880ms and 5840–7900ms); the first end time was not the duration of the entire recording.
- An intentionally non-text ink stroke produced an empty Tesseract candidate. Manual review text `line` was approved and shown as confirmed handwriting. This checks the approval workflow, not recognition accuracy.
- Final-package image explanation saved with the selected image citation in 45,781ms. The actual `ModelWorker-avx2` process was observed. A course question saved with `retrieval_mode=hybrid` in 28,578ms, exercising keyword/semantic retrieval and generation. One answer made an unsupported negative claim about whether a word appeared in the fixture; execution success is not a quality pass.
- Course summary completed and saved in 23,657ms, using the existing two-part, source-preserving `excerpts-v1` workflow with eight sections. The body displayed in the GUI. The app warned that AI-selected excerpts can omit important content and that source selection needs review. No general summary-quality claim is made.

Final GUI metadata is retained in `output/windows-diagnostics-4/gui-artifacts-final.log` (UTF-16 JSON with escaped Korean text). Its transfer archive `output/windows-gui-final.zip` passed CRC and SHA256 `37900d55bed0d51a4a57aa561e9d63608bb9cba39c91a6ac7b4d788813087139`. Native accelerated text/image/schema and finite, normalized 768-dimensional embedding checks passed in 32.611 seconds in `output/windows-diagnostics-4/ai-acceptance/inference-20261028T091835461396Z-49364.json`. These are synthetic contract checks. The main diagnostic archive `output/windows-diagnostics-4.zip` matched the remote SHA256 `62731dd3b70c0d84d288b714ceb9648d9c5142a36640386460a55ead3a69f040` after transfer.

Remaining acceptance checks:

- [x] Native worker build and PE dependency inspection; frozen worker and GUI startup.
- [x] Accelerated ASR rebuild, synthetic ASR/VAD/OCR and final frozen-worker material checks.
- [x] GUI material/audio import, file transcription, summary, image explanation, handwriting approval, hybrid question and TXT export.
- [x] Frozen-worker PDF crop/rotation/EXIF, Korean text/PDF extraction and ink rendering; unchanged fixture originals.
- [x] GUI original linking and ink save/normal restart/reopen.
- [x] Earlier frozen GUI microphone start, minimize and stop: saved mono PCM16/44.1kHz WAV, source/stored/file frame counts all 22,826,160.
- [x] Imported audio playback start/pause/seek interactions; audible quality remains unchecked.
- [x] Real Qwen text/image/schema outputs and 768-dimensional normalized embedding inference; hybrid retrieval through the GUI.
- [ ] General lecture transcription, summary/answer and Korean handwriting quality; vector equivalence across platforms.
- [ ] WebView2 absent/present installation and a Windows user-profile path containing Korean and spaces.
- [ ] Final accelerated GUI live capture, realtime ASR, device loss, real sleep/resume and interrupted recovery.
- [ ] exFAT export, external audio protocol link and second-instance handoff on the actual PC.
- [ ] Clean Windows installation without developer tools and CPU-only 16GB performance.

Primary-source runtime investigation: [Windows runtime research](research/2026-10-27-windows-runtime.md). Automated Windows boundary checks: `python -m unittest discover -s tests -p "test_windows_*.py" -v`. Native model protocol checks additionally use `SOLASI_GENERATION_WORKER=<absolute ModelWorker path>`; real model tests require `SOLASI_GENERATION_MODEL_DIR=<verified model directory>`.
