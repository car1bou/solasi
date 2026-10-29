# Unified PDF Notebook Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:dispatching-parallel-agents for independent playback/backend work, then integrate and review.

**Goal:** 삼성노트 방식의 통합 PDF 필기와 T 입력, 화면 이동 시 재생 중단을 구현한다.
**Architecture:** 페이지별 저장을 유지하며 공통 도구 UI와 문서 뷰포트를 만든다. text annotation은 기존 잉크·초안·버전에 포함하되 손글씨 OCR과 구분한다.
**Tech Stack:** React, TypeScript, Python, 기존 Mac 내장 worker.
**Spec:** docs/superpowers/specs/2026-10-29-unified-notebook-design.md

## Global Constraints

기존 자료·회차 노트·필기·승인·출처·미저장 초안은 보존한다. 별도 Windows/mobile 작업을 덮어쓰지 않는다. 기존 원음 삭제 작업은 새로 실행하지 않는다.

## Tasks

- [x] 재생 lifecycle과 늦은 자동 재생을 회귀 검사 후 수정한다.
- [x] text annotation 검증·버전 저장·직접 입력 검색·초안·OCR 구분을 구현·검증한다.
- [x] 페이지 편집기 chrome을 공통 영역으로 올리고 한 문서 뷰포트에서 페이지를 다룬다.
- [x] 회차 노트 통합·상시 검색 탭·세로 더보기·삭제 설명을 반영한다.
- [x] T 도구의 생성·수정·이동·삭제·색·크기·실행 취소·복구·내보내기를 검증한다.
- [x] 빌드·관련/전체 회귀와 브라우저의 실제 UI·IndexedDB를 검증하고 발견된 문제를 수정한다.
- [x] 실제 설치 Mac 앱의 분리된 검증 과목에서 PDF·T·메모·보기 선택·두 테마·Tab·재실행·JSON 내보내기를 확인한다.

추가 요청: 연속/한 쪽 선택을 ⋮ → 페이지 보기의 아이콘 하위 메뉴로 옮긴다. 노트 더보기·기록 더보기·자료 선택·도구 설정의 바깥 클릭/Esc/항목 선택 닫힘을 검증한다.
