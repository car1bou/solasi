# Solasi Mac 설치 삭제 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans for inline execution or superpowers:subagent-driven-development for delegated execution. Canonical task status is recorded with claude-mem work_state_write.

**Goal:** 선택한 사용자 기록을 앱 없이 읽는 파일로 내보내고 검증한 뒤, 명시적인 마지막 확인을 거쳐 Mac 앱·원래 보관함·전용 모델과 엔진을 실제 삭제한다.

**Architecture:** Python 엔진이 일관된 기록 목록과 독립 보존 파일·검증 영수증을 만든다. macOS 네이티브 코드가 저장 위치 선택과 최종 확인을 소유한다. 앱 밖에서 실행되는 작은 네이티브 도우미가 엔진 종료·보관함 배타 접근·보존 영수증·대상 식별자를 다시 확인한 후 허용 목록만 삭제한다.

**Tech Stack:** 기존 React/TypeScript, Python 3.12/FastAPI/SQLite, Swift/AppKit/PDFKit/CryptoKit 및 기존 패키징. 새 프런트엔드 의존성 없음.

**Spec:** `docs/superpowers/specs/2026-11-17-uninstall-design.md`

## Global Constraints

- Mac만 구현한다. 기록 세 범주의 기본값은 모두 보존이다.
- 앱 전용 모델·엔진·환경설정·기기에 저장된 API 키·캐시·로그는 자동 제거한다.
- 검증된 내보내기와 `솔라시 삭제` 입력 및 최종 버튼 확인 전에는 원본을 삭제하지 않는다.
- 실패한 보존을 성공으로 간주하지 않고, 실제 삭제 전 실패/취소 시 앱과 원래 기록을 유지한다.
- 외부 원본·별도 백업·공유 도구·개발 소스·보존 폴더는 삭제하지 않는다.
- 실제 사용자 보관함에서 파괴적 실행을 시험하지 않는다. 무관한 작업을 되돌리거나 섞어 커밋하지 않는다.
- 기존 최신 설치의 보안/기능을 보존할 수 있는 소스를 확인하기 전에는 설치 앱을 교체하지 않는다.

## Review Focus

- 기존 PDF 내보내기에서 빠지는 비PDF 자료 필기·옆 메모·인식문·세션 메모를 누락하면 안 된다.
- AI 결과 종류·퀴즈/응답과 원음 링크는 앱 없이 읽을 수 있는 최종 내용으로 보존되어야 한다.
- 내보내기 이후 원본/보존 파일 변경, 심볼릭 링크 치환, 동시 실행은 삭제를 차단해야 한다.
- 혼재한 런타임 실험 자료와 보관함 내부의 별도 백업은 폴더 전체 삭제로 손실되면 안 된다.
- 앱 종료 후 도우미가 실패해도 결과를 볼 수 있고, 부분 삭제를 전체 성공으로 표시하면 안 된다.

## Task 1: 보존 목록과 검증 가능한 독립 내보내기

**Files:** Create `lecture_study/uninstall_export.py`, `tests/test_uninstall_export.py`; modify `lecture_study/notebook_pdf.py`, `macos/NotebookPDF.swift`, `lecture_study/transcription.py`, `lecture_study/outputs.py`; extend `tests/test_notebook_pdf.py`.

**Interfaces:** `ExportSelection(documents: bool, audio: bool, results: bool)`; `async prepare_export(db, config, destination: Path, selection: ExportSelection) -> ExportReceipt`; `verify_export(receipt: ExportReceipt) -> None`. Receipt is JSON format 1 containing selection, source inventory/fingerprint, relative file paths, size/hash, record-to-file mapping, format checks and destination identity. Never include secrets. Existing regular export behavior stays compatible; uninstall-specific content/link rules are separate entry points or optional internal arguments.

- Write failing fixture tests for each category and all 8 category combinations. Assert documents/ink/memos/recognitions/session notes/audio/current transcript/current AI and quiz content are mapped once, omitted categories are absent, and originals remain byte-identical.
- Run `.venv/bin/python -m unittest discover -s tests -p 'test_uninstall_export.py' -v`; confirm failures are the missing production behavior.
- Implement inventory from owning tables and existing public helpers; preserve document/record identity and meaningful titles; copy external originals into a new exclusive export folder. Explicitly handle records already marked deleted separately from unexpectedly missing originals.
- Implement standalone exports. Reuse PDF ink drawing and existing page rendering; support nonPDF notebook pages. Add memo/recognition text files with document/page context. Preserve current quiz/questions/answers/grades without claiming full history restoration. Replace app-only links with relative retained-file links or an explicit audio-not-included label.
- Implement semantic and integrity checks: copied-file hash/size/source-change checks; reopen PDF and verify count/geometry plus ink/text rendering; read exported text and compare with inventory; verify audio format/length and hash. Complete receipt only after all checks pass. Reject paths within any deletion target and never overwrite prior outputs.
- Add failures for missing/changed source, malformed/unhandled record, nonPDF ink, original PDF with crop/rotation, text/highlighter/pen, zero-length legitimate memo vs corrupt audio, disk/write error, duplicate titles and traversal-like titles.
- Run new tests plus `.venv/bin/python -m unittest discover -s tests -p 'test_notebook_pdf.py' -v`; assert original source/export contracts remain compatible.

## Task 2: 네이티브 전용 준비·쓰기 차단·재검증

**Files:** Modify `lecture_study/native_worker.py`, `tests/test_native_worker.py`; create `tests/test_uninstall_protocol.py`.

**Interfaces:** Private pipe operations `uninstall_prepare`, `uninstall_verify`, `uninstall_cancel`. Prepare accepts native-selected absolute destination and three exact booleans, produces receipt ID/status/progress. Verify consumes the active receipt ID and revalidates selection, source state and output hashes. Cancel invalidates readiness and releases maintenance state. These are not general HTTP deletion routes.

- Write failing native-pipe tests for unsupported field types, untrusted/relative paths, wrong receipt, changed source/output and cancellation. Assert no delete operation exists on this preparation surface.
- Run `.venv/bin/python -m unittest discover -s tests -p 'test_uninstall_protocol.py' -v` and observe expected failures.
- Extend strict frame parsing/dispatch. Enter maintenance only when jobs/recordings/downloads and conflicting requests are idle; reject new mutations/audio while prepared. Maintain ACK/cancel support and existing frame size bounds.
- Take a consistent SQLite snapshot after existing draft flush; compare source inventory before final verification. Keep output generation off the UI thread. If preparation fails, release maintenance state and preserve app/database. Never delete keys or original data during preparation.
- Run protocol tests and `.venv/bin/python -m unittest discover -s tests -p 'test_native_worker.py' -v`; verify ordinary worker requests and shutdown are unaffected.

## Task 3: 종료 후 삭제 도우미와 대상 검증

**Files:** Create `macos/UninstallPlan.swift`, `macos/UninstallHelper.swift`, `macos/UninstallFixture.swift`, `tests/test_native_uninstall.py`; modify `scripts/install_macos_app.py` for helper packaging.

**Interfaces:** Codable `UninstallPlan` format 1 contains app identity, vault identity, explicitly enumerated owned targets and their filesystem identity, export receipt location/digest, parent/worker IDs and app identifier. `UninstallHelper PLAN_PATH` accepts a private locally staged plan; no shell commands or caller-supplied arbitrary deletion list from web content.

- Write Swift fixture tests that create fake app/vault/runtime/export roots. App-only ownership fixtures use a validation bundle ID. Test deletion only of enumerated targets; retained files/external originals/shared tools/backups stay byte-identical.
- Run `.venv/bin/python -m unittest discover -s tests -p 'test_native_uninstall.py' -v`; confirm missing helper behavior fails.
- Validate target ownership using launch configuration, vault marker, known managed paths/receipts, uid, canonical path, filesystem identity and no-follow traversal. Protect root/home/parent/shared/development paths. Preserve unknown mixed-runtime items, report them and do not claim a full cleanup.
- Stage helper and plan in a new private temporary directory outside deletion roots; verify executable availability before asking final consent. Helper waits for application/owned worker shutdown, acquires the existing vault lock, verifies receipt/files and plan identities again, then removes only planned files. Hold safe handles/locks through deletion and reject replacement races.
- Remove the current vault's local provider credentials using its exact service/account scope and the OS credential API. Do not enumerate or delete other apps' credentials. Remove app last. Do not use elevated permissions, kill unrelated processes, follow external symlinks or silently leave skipped targets.
- Add tests for symlinked parent/child, replaced inode, overlapping export root, active lock/process, missing permission, corrupt receipt, changed export, shared/unknown runtime files and injected failure after some targets were deleted. Assert no success result on partial failure and no modification of retained output.
- Verify helper build/signature and that native completion/error display works after the source app has exited. Clean only helper-owned temporary files.

## Task 4: 앱 안의 범위 선택·저장 위치·최종 확인

**Files:** Create `frontend/src/UninstallSettings.tsx`, `frontend/tests/uninstall.test.ts`; modify `frontend/src/SettingsView.tsx`, `macos/Solasi.swift`, `macos/WorkerBridge.swift` only as needed for current lifecycle integration.

**Interfaces:** Native commands `uninstall_info` (capability/read-only), `uninstall_begin` (trusted click, native folder selection), `uninstall_cancel`. Native owns the final typed confirmation and any plan/receipt; browser code never sends removal paths. Unsupported platforms do not display a working uninstall action.

- Add failing tests for all-preserve default, category choices, unsupported platform, busy/error/cancel state, progress and no execute-before-verification path. Use existing components/style and lifecycle patterns.
- Render automatic removal summary plus three record-retention checkboxes and native destination selection. Display export progress and actionable errors accessibly. Use native confirmation with `솔라시 삭제`, cancel as default, preservation summary/folder-open and delete summary/estimated unique size.
- Reuse multiwindow prepareClose/draft guards. Prevent duplicate flows and block new work while prepared. Invalidate confirmation after any selection/destination/receipt change. For all-unchecked case show no-export plus explicit loss warning instead of claiming export success.
- After final user action, request last verification, stage validated helper and authorize it, then quit through the existing worker/child shutdown path. On cancellation or pre-delete failure, resume all original windows and drafts. Expose helper readiness/launch errors before teardown.
- Run `npm test` and `npm run build` in `frontend`; run native worker shutdown/window tests and compile/sign a candidate app using current-source packaging. Confirm normal close guards, recording and exports remain intact.

## Task 5: 통합 검증·후보 빌드·설치

**Files:** Modify `scripts/freeze_macos_engine.py`, `tests/test_mac_install.py` only if the new code/assets require collection; create `docs/uninstall-macos-validation-20261117.md` with evidence and exact limits.

- Verify the active repo/branch and latest installed 0.3.41+ source compatibility. Locate/reconcile newer deployed functionality before rebuilding; do not deploy a lower-version or security-regressed engine. Reuse verified installed runtime/model assets without downloading new models.
- Run relevant Python/native suites, frontend suite/build, engine self-check and candidate signature. Record passed/skipped/failed checks precisely; do not call skipped tests passed.
- In an isolated fake install, run all-preserve, each single-category, mixed and zero-preserve workflows; verify cancel, missing original, corrupt/changed output, no free space, active work, key-store error and partial removal failure. Final deletion operates on fake targets/fixture credentials only.
- Exit the fake app and open retained PDFs/text/audio using standard readers/tools. Compare expected contents and integrity against the fixture inventory and assert all external originals/backups/unknown files unchanged.
- Obtain a fresh whole-change review against the spec, fix material issues and rerun the affected checks. Do not merge/push without a separate task requirement.
- Prepare an app replacement with an existing-app backup and data preservation inventory. Validate only preparation/cancel/folder/error UI on the real installed app; do not press its final destructive action. Replace only when newer functionality is preserved and required filesystem permission allows it.
- Attach candidate/report to canonical work-state items and state whether the installed app was actually updated. Do not mark the user task complete if only source/candidate is ready.

## Execution result

User chose inline implementation with a separate final review. Tasks 1–5 were implemented and the installed Mac app is now 0.3.42/build52. The original checklist above records planned intent; the canonical completed status and exact evidence are in claude-mem work state and `docs/uninstall-macos-validation-20261117.md`.

Plan adaptations: protocol cases share `test_native_worker.py`; native fixture code is compiled from the Python test rather than stored as a shipped fixture source. The user correction replaced ambiguous checkboxes with native **보존 / 삭제** controls plus **선택 변경** and receipt invalidation. Because deployed code is newer than checkout, the engine was patched with bytecode compatibility proofs instead of fully freezing stale source.

Final verification: 840 Python/native tests, 831 pass and 9 environment-dependent skips; frontend156 pass/build; native focused9 and UI2 pass (included in the full count). Independent review findings were fixed and tested. Installed app/helper signatures pass; actual86files and listed record counts are unchanged. Destructive tests used temporary fixtures only. No real uninstall, commit or push was performed. Remaining verification limits are stated in the validation report.
