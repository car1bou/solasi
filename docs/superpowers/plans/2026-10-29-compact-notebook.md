# Compact Notebook Implementation Plan

> **For agentic workers:** Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Keep document navigation and drawing in two compact rows and fit the PDF to the actual remaining workspace.

**Architecture:** Retain MaterialLibrary and the active PageNotebook portals. Send document actions through ContinuousPage to the existing popup menu, and portal the save/menu controls into the document row. Measure the PDF frame against the viewport after layout changes; keep the existing measured page-fit calculation.

**Tech Stack:** React, TypeScript, CSS, existing native WebKit host.

**Spec:** User approved two compact rows, secondary actions in More, always visible save/zoom and error warnings. PDF fit must use the enlarged actual workspace.

## Global Constraints

- Keep saved PDF coordinates, source files, ink versions, approval and drafts unchanged.
- Keep errors, pending saves and conflicts visible; keep export validation and download links.
- No dependencies or backend changes. Preserve unrelated Windows/mobile work.

## Review Focus

- Short/narrow windows: controls and menus must remain reachable without horizontal page overflow.
- Hidden tab to visible: recompute available space without a window resize.
- Zoom/rotation/page changes: fit uses actual inner frame bounds and retains the current page.
- More actions: selection works before closing, outside click/Escape close, keyboard focus returns.
- Save failures and export guards remain visible even when secondary actions move.

### Task 1: Compact document and drawing controls

Files: MaterialLibrary.tsx, ContinuousPage.tsx, PageNotebook.tsx, styles.css, frontend/tests/notebook-toolbar.test.ts.

- [x] Move secondary actions into the existing More menu, pass menu content and header portal through ContinuousPage.
- [x] Retain tool icons/settings; remove duplicated page title, redundant fit button, persistent shortcut help and page jump submit label.
- [x] Check type/build and toolbar/menu tests.

### Task 2: Use remaining space and verify

Files: MaterialLibrary.tsx, styles.css, frontend/tests/continuous-pages.test.ts (if pure geometry helper is needed).

- [x] Observe layout, scroll/resize and navigation visibility; update PDF frame from actual available height.
- [x] Browser-test real components at 680×480, wider windows, both themes, page-fit/rotation, menu dismissal and keyboard use.
- [x] Build a Mac-only tested snapshot, preserve the actual vault baseline, install and check the saved QA PDF without changing ink.
- [x] Commit scoped files, push main and verify remote SHA.

Ruling: While a document is visible, tighten existing course/session title and tab margins as well. Native680×480 retained the180px minimum frame with old header spacing; reducing margins preserves all navigation and increases usable PDF height. Keep the compact styling out of hidden notebook tabs.

Independent review: restored the original retry icon when metadata is unavailable; no other blocker reported.

Verification: isolated Mac frontend128/128; native draft/PDF tests22/22; type/build successful. Actual installed0.3.32/build42:680×480 light/dark, resize880×760, four rotations, Enter navigation, More export disclosure and Escape focus return; original QA pagev3 unchanged. Release receipt is stored in the task-local verification folder.
