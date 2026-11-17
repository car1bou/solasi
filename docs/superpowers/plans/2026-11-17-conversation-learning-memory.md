# Conversation and Learning Memory Implementation Plan

> **For agentic workers:** Use superpowers:executing-plans to implement this plan task by task in this session.

**Goal:** Persist resumable study conversations and evidence-linked course learning memories without losing existing records.
**Architecture:** Add compatible SQLite tables and a focused study-memory service/router. Reuse existing jobs, generation locks, source retrieval, source validation, and export verification. Keep original source-excerpt Q&A accessible.
**Tech Stack:** Existing Python/FastAPI/SQLite, React/TypeScript and native Mac host; no new dependency.
**Spec:** `docs/superpowers/specs/2026-11-17-conversation-learning-memory-design.md` (user approved 2026-11-17).

## Global Constraints

- Preserve all existing notes, ink, recordings, results, settings and installed models.
- No automatic external API calls or model download for memory maintenance.
- External chat defaults to excluding both previous conversation and course memory.
- Deletion, pause and edits invalidate pending snapshots and cannot resurrect removed memory.
- Existing worktree contains unrelated changes; do not revert them or commit them as this task.
- User authorized implementation and actual-app verification; execute inline without another approval gate.
- Work-state plugin writes were rejected in the preceding turn; do not retransmit repository metadata there.

## Review Focus

- Retry after forget/edit/pause: obsolete snapshots must fail before sending or saving.
- Interrupted generation: user text survives and retries do not duplicate turns.
- Course/session/page ownership: neither history retrieval nor source lookup widens the selected scope.
- Tiny input budget and long Korean messages: report omitted history and never silently discard current input.
- Existing export/reset and session deletion: newly persisted conversations and memories are preserved or deliberately scrubbed.

### Task 1: Persistent conversations and memory controls

**Files:** `lecture_study/schema.sql`, new `lecture_study/study_memory.py`, new `tests/test_study_memory.py`.
**Interfaces:** `owner(db, session_id=None, course_id=None)`, `create_thread(db, owner)`, `read_thread(db, id, owner, before=None)`, `memory_list(db, course_id)`, `invalidate(db, owner)`, `delete_thread(db, id, owner)`, `clear_memories(db, course_id)`.

- [ ] Write failing tests for additive persistence/reopen, owner mismatch, partial-turn durability, edits/deletes/cutoff and invalidated snapshots.
- [ ] Run ` .venv/bin/python -m unittest tests.test_study_memory -v`; observe missing implementation failure.
- [ ] Add tables and ownership-checked persistence operations; one provenance record per learned item, generation epochs and source deletion cleanup.
- [ ] Run the same tests; expect all pass and old fixture rows unchanged.

### Task 2: Conversational generation and idle local learning

**Files:** `lecture_study/study_memory.py`, new `lecture_study/study_memory_api.py`, `lecture_study/server.py`, new `tests/test_study_memory_api.py`.
**Interfaces:** `attach_study_memory(app, db, config, provider_config, generation_slot, local_embedding_client)` returns `background_tick`; request prefix `/api/study/`.

- [ ] Test with mock providers: follow-up context, no-evidence recall, scoped source citations, external exclusion, cancellation/retry and delete/forget race.
- [ ] Add explicit `study_chat` jobs and structured answer validation; reserve context for recent/older related history, memory and checked source evidence.
- [ ] Add idle local-only structured extraction and summaries with verified user quotes, quiz observations and processing cursors.
- [ ] Run memory/API tests plus answers, retrieval and source-grounding suites.

### Task 3: Conversation and course-memory UI

**Files:** new `frontend/src/StudyChat.tsx`, `QuestionView.tsx`, `KnowledgeSettings.tsx`, `styles.css`, new `frontend/tests/study-chat.test.ts`.
**Interfaces:** StudyChat accepts existing session/course/scope props; existing source Q&A remains available.

- [ ] Add failing SSR/interaction-helper tests for history, pending/errors, memory source/edit/delete, external opt-in and accessible controls.
- [ ] Build using existing cards/buttons/forms; no new UI dependency. Restore last conversation, paginate history, preserve drafts/close guards.
- [ ] Run frontend tests and production build.

### Task 4: Lifecycle, portable exports and packaging

**Files:** `lifecycle.py`, `uninstall_export.py`, `mobile_bridge.py`, packaging patch helper, `tests/test_uninstall_export.py`, memory tests, `docs/guide.md`.

- [ ] Add regression tests for source-session deletion, portable result export completeness, pause during reset preparation, and mobile capability boundaries.
- [ ] Include independent readable conversation/memory exports and content validation. Keep native reset/uninstall code intact.
- [ ] Run targeted regressions, then full Python/frontend checks. Build candidate engine without reverting deployed security/runtime changes.

### Task 5: Real Mac validation and preservation

**Files:** `docs/conversation-learning-memory-macos-validation-20261117.md`, task-specific output directory.

- [ ] Capture existing installed launch settings, per-table old-row baseline, managed file/model hashes and a SQLite-consistent backup.
- [ ] Use a separate QA app/vault first: real local-model dialogue, restart/resume, new-conversation course recall, correction/forget and export.
- [ ] Obtain fresh independent code review and fix important findings with regressions.
- [ ] Install approved feature into actual app with previous bundle retained; verify signatures, actual UI/local generation and existing record/file preservation.
- [ ] Report exact evidence, limits and untested platforms; do not run actual reset or uninstall.
