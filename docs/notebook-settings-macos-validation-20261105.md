# Notebook tool settings and menu polish — Mac validation

Release: **0.3.37 / build 47**. Implemented on November 4; final installation and preservation checks on November 5, 2026.

## Changes

- Tool settings show a preview of the applied pen/highlighter color, width and opacity, a text sample for the text tool, and a size circle for the eraser. The preview uses the existing `InkMark` renderer and does not write page data.
- Width/text size are shown as CSS pixels at the app's existing **100% view** reference width of 680px. Eraser size is the diameter; its stored radius and behavior are unchanged. These values are not PDF points or physical millimeters.
- Current slider values are visible and exposed through `aria-valuetext`. Existing color picker, color-code validation, tool-specific persistence and active text-box editing remain in their original paths.
- Notebook More groups **자료 AI**, **원본**, and **내보내기·보기**. Action handlers, dirty-data/export checks, page layout controls, Escape/outside dismissal and trigger focus remain unchanged.
- No backend, model, database schema or native executable change. Existing SVG icon family and light/dark theme tokens are reused. Preview paper remains white like the PDF page.

## Validation

The final frontend passed **132 tests**, TypeScript checking and a production build. A separate reviewer checked the scoped changes and final preview simplification without finding an actionable issue.

The installed Mac app was exercised at **680 × 480** in both light and dark modes:

| Check | Observed result |
| --- | --- |
| Preview | Final straight pen/highlighter sample and tool-specific caption displayed in both themes. |
| Eraser value | Keyboard adjustment changed radius `.014` to `.015`, showing diameter `19 px` to `20.4 px`; the original value was restored. |
| Highlighter value | Keyboard adjustment changed opacity `35%` to `40%`; the original value was restored. |
| Short popup | Tab reached the lower width/opacity controls and scrolled them into view. Tab exit closed the popup, and Escape returned to the tool. |
| More menu | AI/source groups displayed; page-view and JSON/PDF export controls were reachable through the bounded menu scroll area. Escape and outside click closed it. No new AI job or export was started by selecting a menu heading. |
| Preservation | All **4,147 existing rows across 11 protected tables** matched the fresh pre-install snapshot. SHA256 matched for **71 original/audio files**. Existing ink, transcripts, recognition drafts and source history were preserved. |
| Preferences | Tool values/selected eraser and course-navigation preference were restored to their pre-test values. System theme was restored through the UI. |
| Package | Installed frontend matched the tested build; engine integrity and strict code signing passed. A rollback copy of the previous app and a fresh SQLite snapshot were retained. |

Private screenshots, accessibility snapshots, file-hash receipts and backups are under `.local-state/notebook-polish-20261104/`, excluded from Git. They contain user workspace information and are not included in this public report.

## Boundaries and remaining observations

No new model inference, microphone recording, or generated PDF-file comparison was performed for this presentation change. Existing export guards remain covered by the regression suite.

During resumed native verification, the tool sometimes captured an empty/background window and could not target it. Resizing or using macOS **Window → Center** restored the home screen and operable notebook at the same 680 × 480 size. This does not establish the internal cause or prove a startup defect was fixed; no speculative cache, database or native-window code change was applied.

Original-file relinking remains separate work: selecting a moved file through the current generic file picker can create a new asset identity and does not safely reattach existing page ink. This release does not label that behavior as recovery.
