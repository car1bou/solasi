# 단일 로컬 AI Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** 사용자 승인대로 Qwen 4B 단일 로컬 생성 경로를 제공하고 Gemma 두 모델만 안전하게 정리한다.
**Architecture:** 기존 공통 제공자 설정·허용 목록을 좁히고 UI를 단순화한다. 과거 작업을 변조하지 않으며 명시적인 현재 로컬 AI 재시도만 새 작업으로 만든다.
**Tech Stack:** 기존 Python/FastAPI·React/TypeScript·MLX·Swift. 새 의존성 없음.
**Spec:** [승인 범위](../specs/2026-10-27-single-local-model-design.md)

## Global Constraints

기록·원음·획·초안·승인 출처·과거 모델 metadata 보존. ASR/임베딩/Vision/API 유지. 모델 삭제는 승인한 Gemma12B/E2B의 고정 목록만. 사용자 deliverables/output/.DS_Store는 제외. 기존 linked worktree 재사용.

## Review Focus

기존 Gemma 설정의 부팅/생성, 예전 실패 작업의 재시도와 원본 요청, API 모델 선택의 보존, 로컬 다운로드/직접 호출 우회, 공유 blob·symlink의 오삭제.

### Task 1: 공통 모델 정책·재시도·OCR

- [x] RED: Qwen 단일 카탈로그/직접 지원, 기존 로컬 설정 정규화·다른 로컬 설정 거절·과거 Gemma 작업 불변과 새 Qwen 재실행, Gemma OCR 거절 검사.
- [x] local_models/mlx_direct/providers/server/handwriting에서 공통 정책을 적용하고 기존 Qwen·임베딩·Vision 계약을 유지한다. 미사용 Gemma 제품 분기와 테스트는 정리하되 역사적 실험 기록은 유지한다.
- [x] 해당 집중 검사 GREEN.

### Task 2: 사용자 화면과 Mac 검증

- [x] RED: 로컬 모델 ID 선택·Gemma OCR 버튼 제거와 현재 로컬 AI 재시도의 UI 검사.
- [x] SettingsView/QuestionView/HandwritingReview를 변경하고 외부 API 입력은 유지한다. 로컬 준비는 역할별 표시로 정리한다.
- [x] frontend 105개·빌드, 전체 Python 679개(675 통과·4 선택 생략), 실제 Qwen 입력/출력과 승인·검색·초안 회귀를 확인했다. frozen 빌드/설치 앱 교체·실행과 실제 보관함 fingerprint 보존도 확인했다.
- [ ] 추가 native GUI 시나리오의 필기 편집·승인·검색·재실행 전체 통과: 응답 대기 중 검증 프로그램이 시간 초과했다. 제품 오류로 확정하지 않았으며 이 추가 시나리오를 통과로 보고하지 않는다. 설치 화면 관찰·별도 native 순차 추론·기존 회귀 검사와 구분한다.

### Task 3: 승인한 파일 정리·검토·main

- [x] 기존 manifest 전체의 참조 집합과 삭제 고정 목록·보호 기준·사용 중 여부를 기록한다. 변경 전후 유지 모델·원음·보관함 무결성을 대조한다.
- [x] 기능 검증 후 승인한 Gemma 두 모델 전용 blob/manifest/view만 정리하고 실제 공간 변화·보존 결과를 남긴다.
- [x] 독립 검토와 문서. 삭제 도구의 symlink 감지 누락은 RED/GREEN으로 수정 후 실행했다.
- [x] 정확한 파일 25개만 커밋·main 일반 푸시·원격 SHA 확인: `719a592424f1f721b7a808c29d17ef55bc1c0bc1`.

검증 결과와 실행 한계는 [검증 기록](../../single-local-model-validation-20261027.md)에 남겼다. 다른 작업의 미커밋 화면 변경은 보존하며 이 커밋에서 제외한다.

## 실행 승인

사용자가 ‘추천대로: Qwen 4B 단일화·Gemma 두 모델 정리’로 위 단일화·수식 대조 제거·파일 영구 삭제·과거 기록 보존을 승인했다. 현재 세션에서 직접 실행하며 새 정책을 임의로 확대하지 않는다.
