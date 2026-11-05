# 진행 중 필기 복구 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 그리는 중의 부분 획을 사용자 적용 복구 후보로 보존하고 작은 초안의 기록 전 공백을 줄인다.
**Architecture:** 기존 PageDraft에 writer별 별도 부분 journal을 추가한다. 현재 편집·페이지 저장·undo는 그대로 두고, 제한된 단일 실행과 최신 요청 합치기로 중간 상태를 보존한다. native의 동일 검증·원자적 쓰기를 작은 직접 요청과 큰 분할 요청에서 재사용한다.
**Tech Stack:** React/TypeScript, native WKWebView bridge, Python/FastAPI, SQLite.
**Spec:** `docs/superpowers/specs/2026-11-05-early-ink-recovery-design.md`

## Global Constraints

- 기존 기록·필기·초안·출처·원음·연결 원본을 보존한다.
- 첫 durable journal 전 입력과 마지막 기록 이후의 점은 무손실로 보장하지 않는다.
- 미완성 후보는 사용자 적용 전 확정 페이지·인식·검색에 편입하지 않는다.
- 기존 다른 OS 변경은 빌드·커밋에서 제외한다. 새 모델·의존성은 추가하지 않는다.

## Review Focus

- 느린 전송에서 무제한 queue 또는 오래된 partial의 재등장.
- 정상 완료·취소·다른 창 갱신과 partial 정리의 경합.
- 후보 적용이 이미 저장된 최신 내용이나 기존 회복 사본을 덮는 경우.
- 부분 획으로 page PUT·자동 OCR이 실행되는 경우.
- 크기 제한·실패에서 마지막 durable 복구 사본을 잃는 경우.

### Task 1: 원자적 native 초안 쓰기

Files: `lecture_study/native_drafts.py`, `tests/test_native_drafts.py`, `frontend/src/draft-migration.ts`, `frontend/tests/draft-migration.test.ts`.

- [ ] 먼저 작은 직접 쓰기, journal-only checkpoint, 실패 rollback·크기/키 검증·큰 입력 fallback 검사를 추가하고 실패를 확인한다.
- [ ] NativeDrafts의 공통 쓰기를 기존 write와 새 checkpoint에서 재사용한다. 작은 요청은 64KiB까지 단일 요청, 큰 요청은 기존 multipart ACK·commit을 유지한다.
- [ ] `.venv/bin/python -m unittest tests.test_native_drafts` 및 `node --test frontend/tests/draft-migration.test.ts` 통과.

### Task 2: 부분 획 수명·사용자 복구

Files: `frontend/src/page-drafts.ts`, `frontend/src/PageNotebook.tsx`, `frontend/tests/page-drafts.test.ts`, 필요 시 기존 필기 fixture.

- [ ] 부분 journal 격리·서버 미반영·단일 실행/최신 값·완료·취소·실패·conflict·후보 적용 검사를 먼저 추가하고 실패를 확인한다.
- [ ] 첫 점 즉시, 이후 250ms 기준으로 최신 값만 보낸다. 정상 완료의 durable 쓰기 이후 해당 진행 journal만 정리하며 기존 undo 한 번을 유지한다.
- [ ] 후보에 ‘그리던 획 복구 후보’, 미리보기, 적용 버튼을 표시한다. 다른 revision은 기존 conflict로 보호한다.
- [ ] 전체 frontend 검사·TypeScript/build, native draft 검사 통과. 별도 snapshot에서 동일 검사를 확인한다.

### Task 3: 실제 설치 앱 검증·게시

Files: `scripts/install_macos_app.py` 버전, 검증 보고서.

- [ ] 승인 범위의 파일만 clean HEAD snapshot에 덧씌워 엔진·UI 빌드. 앱·보관함 백업 뒤 안전하게 설치한다.
- [ ] 실제 680×480 라이트·다크에서 펜·형광펜의 partial journal을 관측한 뒤 정확한 앱 PID만 강제 종료한다. 재실행 후보·적용·최종 geometry·정상 완료·단일 undo를 확인한다.
- [ ] 기존 행/파일 해시·원본·설정 대조, 앱 서명 검사. 전송 전 종료의 실제 유실/살아남은 입력을 과장 없이 기록한다.
- [ ] fresh 독립 검토 후 이번 파일만 main 커밋·푸시하고 원격 SHA를 확인한다.
