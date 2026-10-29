# Annotated PDF Export Implementation Plan

> **For agentic workers:** Use superpowers:executing-plans to implement this plan task-by-task, with a final independent review.

**Goal:** Export every original PDF page with saved text boxes, pen and highlighter, and verify the installed Mac app.
**Architecture:** A dedicated Swift PDFKit/CoreGraphics/CoreText helper draws original PDF pages and saved vector overlays. A checked saved-revision snapshot is streamed through the existing native exclusive export path; OCR rendering is unchanged.
**Tech Stack:** Python/FastAPI, Swift/PDFKit/CoreText, React/TypeScript; no added dependency.
**Spec:** docs/superpowers/specs/2026-10-29-annotated-pdf-export-design.md (approved)

## Global Constraints
- Include all original pages, saved T text, pen and highlighter; exclude sidebar memo and OCR review.
- Block pending/failed/conflicting drafts; preserve originals, history and editable app records.
- Never overwrite existing files. Cancel safely. Reject changed originals.
- Commit only this feature and the required preceding notebook/T changes; exclude concurrent Windows/mobile/AI changes.

## Review Focus
- Intrinsic rotation and nonzero crop origin: overlay positions match the viewer.
- Korean, symbols and explicit blank lines: preserve literal text and clip to its saved box.
- Translucent intersecting strokes: apply alpha once per filled polygon.
- Unsaved hidden pages and generation failure: no misleading old or partial PDF.
- Existing destinations and original changes: no overwrite or export from mismatched originals.

### Task 1: Saved snapshot and vector PDF helper
**Files:** Create macos/NotebookPDF.swift, lecture_study/notebook_pdf.py, tests/test_notebook_pdf.py.
**Interfaces:** `saved_pages(db,course_id,asset_id,digest)` returns original path, asset and immutable saved page ink; `export_pdf(source,destination,pages)` asynchronously runs the Mac helper.
- [x] Write tests for saved multi-page snapshots, changed originals and unchanged histories; run and observe failure.
- [x] Write native rendering tests for text/pressure/alpha, crop and rotated pages; observe missing-helper failure.
- [x] Implement the helper with original PDF page drawing, normalized polygon paths and literal wrapped/clipped text.
- [x] Run tests and inspect rendered PDF pages.

### Task 2: Safe export action and packaging
**Files:** Modify lecture_study/server.py, frontend/src/PageNotebook.tsx, frontend/src/page-drafts.ts, macos/AppResources.swift, macos/Solasi.swift, macos/BridgeFixture.swift, scripts/freeze_macos_engine.py, scripts/install_macos_app.py; add frontend export guard tests.
**Interfaces:** GET `/api/courses/{course}/assets/{asset}/notebook.pdf?document_sha256={sha}` streams a temporary PDF, with cleanup. `notebookExportIssue(course,asset,sha)` returns a blocking page message or empty string.
- [x] Pin narrow resource whitelist, .pdf suffix and draft guards in regression checks.
- [x] Add separate PDF export action beside JSON, reusing native user-click and exclusive save handling.
- [x] Package the helper in the frozen Mac engine; bump app to 0.3.30/build40.
- [x] Run frontend tests/build, Mac bridge tests and isolated Mac backend suite.

### Task 3: Installed validation and scoped main commit
**Files:** Update docs/guide.md and a scoped verification report.
- [x] Build from a reviewed Mac-only source snapshot; preserve current vault and app backup.
- [x] In a separate QA course, save Korean/math/multiline text, pen and highlighter; quit/restart and export.
- [x] Check original hash, restored ink, PDF page count/text/positions and rendered output; exercise no-overwrite/cancel.
- [x] Independent review complete; stage only tested files/hunks, commit and push main; compare remote full SHA.

Execution: user explicitly requested direct implementation and installed validation after design approval. No further design decisions are pending.
