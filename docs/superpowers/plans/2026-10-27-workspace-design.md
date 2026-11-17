# Solasi workspace design implementation plan

> **For agentic workers:** Implement inline with superpowers:executing-plans. User has approved the four mockups and requested execution, with flat course navigation and a separate lecture-recordings tab.

**Goal:** Apply the approved dark/light workspace design to the existing app while keeping course navigation flat.
**Architecture:** Reuse existing API, theme tokens, icons, recording lifecycle and page drafts. Keep course names in the sidebar; expose materials and recordings in course tabs. Share a chronological session list between home and course recordings. Create records in a native dialog without starting the microphone.
**Tech Stack:** Existing React, TypeScript, CSS and macOS WebKit; no dependencies.
**Spec:** User-approved `output/solasi-design-flow-20261027/01-home.png` through `04-workspace.png`, amended by the latest user message: sidebar contains no materials or lecture children; main course screen has a separate 강의 기록 tab.

## Constraints and review focus

- Preserve concurrent model/handwriting edits, API contracts, data, native audio and ink geometry.
- Retain close guards, saving errors, source-state warnings and light/dark support.
- Flat navigation must keep long course names and many courses usable without session rows pushing courses down.
- All records remain reachable, including meetings and lectures without a course.
- Opening/cancelling creation must preserve course, recording and dirty editors; never start audio implicitly.
- Keep page notes mounted across session tabs and maintain access to secondary features.
- Use the existing checkout because user has requested this app updated alongside ongoing local changes; do not commit or push unrelated work.

## Tasks

- [x] Add regression checks for flat course navigation, dedicated recording tab and chronological record access; observe expected failures.
- [x] Update App/CourseView and reuse a SessionList; add compact home form and accessible creation dialog, preserve navigation guards.
- [x] Apply approved chrome and workspace layout to SessionView/Recorder/MaterialLibrary/CSS without changing audio or ink logic.
- [x] Run frontend tests and production build; exercise home, course tabs, creation/cancel, material/notes and narrow/dark/light layouts using isolated data.
- [x] Compare rendered screens to the approved images with the sidebar amendment; record `design-qa.md`, prepare the app update and verify installed UI where permitted.

## Progress

Complete. Frontend108 tests, TypeScript and production build passed. Independent review findings corrected and exercised. Visual comparison and native0.3.26 checks passed. User saved and quit normally, then UI-only update was atomically installed with a backup. Native code, engine manifest and launch settings preserved; existing page-document rows matched across replacement. Installed app relaunched and home/course/history/PDF-ink views checked. See design-qa.md and installation-receipt.json.
