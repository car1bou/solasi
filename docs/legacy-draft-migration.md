# 이전 Mac 앱의 필기 초안 보존

`macos/LegacyDraftExport.swift`는 이전 WKWebView 저장소를 읽는 별도 도구다. HTTP 서버를 열지 않고 `loadHTMLString`의 `baseURL`을 이전 앱의 정확한 `http://127.0.0.1:<port>/`로 지정한다. 원래 앱과 같은 bundle ID의 기본 `WKWebsiteDataStore`를 사용한다.

## 실행 전

1. 기존 앱과 SQLite/WAL/SHM, 원음 및 WebKit 저장소를 별도 보존한다.
2. 모든 기존 창에서 일반 노트·대본 수정 등 메모리에만 있는 입력을 저장하거나 별도로 보존하고 앱을 종료한다. 초안 내보내기는 **살아 있는 편집기의 메모리를 읽지 않는다**.
3. 이전 앱의 `launch.json`에서 사용하던 포트를 확인한다. 내장 앱의 실제 대상 보관함에서 확인한 `native_vault_id`를 사용한다.
4. 새 출력 폴더를 지정한다. 기존 출력은 덮어쓰지 않는다.

준비된 도구만 빌드하려면 다음과 같이 실행한다. `--build-only`는 WebKit 저장소를 열지 않는다.

```sh
python3 scripts/export_legacy_drafts.py \
  --origin http://127.0.0.1:62434 \
  --vault-id VERIFIED_32_HEX_VAULT_ID \
  --output /absolute/path/to/new-draft-export \
  --build-dir /absolute/path/to/new-helper-build \
  --build-only
```

출력된 `command`는 기존 입력 보존과 종료가 확인된 뒤 실행한다. 빌드와 실행을 함께 하려면 `--build-only` 대신 `--quiescent`를 전달한다. 도구는 실제 `Bundle.main.bundleIdentifier`가 `local.solasi.launcher`인지 확인하고, 같은 ID의 다른 앱이 실행 중이면 저장소 접근 전에 중단한다. 검증 전용 ID `local.solasi.migration-fixture-<hex>`도 허용한다.

작은 진행 창에는 항목 수만 표시한다. 이 창이 없는 긴 실행은 WebKit에 의해 정지되는 현상이 실제로 관찰됐으므로 창과 실행 활동을 유지한다. 창을 닫으면 취소하며 원본과 미완성 출력은 보존한다.

## 출력 형식

- `drafts.jsonl`: `solasi-page-drafts` / `drafts`의 모든 raw row를 한 행씩 저장한다. main, 다른 writer의 journal, `dirty:false`의 backup 및 추가 JSON 필드를 유지한다.
- `manifest.json`: `version:1`, `format:solasi-legacy-drafts-jsonl`, `vault_id`, `origin`, 실제 `source_bundle_id`, 원래 `theme` 문자열 또는 null, `database_present`, `rows`, `row_count`, `total_bytes`, `rows_sha256`, `verified:true`를 포함한다.
- 각 `rows` 항목은 `key`, `offset`, `bytes`, `sha256`, `undefined_paths`, `undefined_paths_sha256`을 가진다. 행의 `bytes`와 SHA256은 UTF-8 JSON만 대상으로 하며 뒤의 LF는 제외한다. 다음 offset은 `offset + bytes + 1`이다. 전체 파일의 `rows_sha256`과 `total_bytes`에는 LF를 포함한다.
- 정상적인 `backup:undefined` 등은 JSON에서 객체 속성이 빠지거나 배열 위치가 null로 표현된다. 해당 위치를 `undefined_paths`에 경로 배열로 보존한다. 객체 키는 문자열, 배열 위치는 정수다. 예: `[["backup"],["values",0],["nested","optional"]]`. 실제 null이나 속성 자체가 없는 경우에는 경로를 추가하지 않는다. 가져오기는 이 목록도 함께 보존해야 한다.
- `undefined_paths_sha256`은 공백 없는 UTF-8 JSON 경로 목록의 SHA256이다. 비ASCII 문자를 그대로 쓰고 slash를 escape하지 않는다. Python 기준 `json.dumps(paths,ensure_ascii=False,separators=(',',':')).encode('utf-8')`과 일치한다. 경로 목록이 비어도 `[]`와 해당 해시를 기록한다.
- `unsaved_inputs:[]`, `unsaved_inputs_captured:false`는 이 도구가 현재 편집 메모리를 캡처하지 않았다는 뜻이다. 별도의 사용자 확인·창 상태 기록을 대체하지 않는다.

한 번에 128KiB까지 전달하고 파일 기록 후 다음 조각을 받는다. 한 행의 JSON과 경로 메타데이터는 각각 최대 64MiB이며 합계 64MiB 제한은 없다. 전체 행을 두 번 읽어 키·길이·JSON SHA256·경로 목록 SHA256과 화면 모드, DB 존재 여부를 대조한다. JSON 본문만 같고 `undefined`가 사라진 경우에도 실패한다. 이 대조는 실행 전 입력 중지 확인과 함께 사용해야 한다.

예상하지 못한 structured-clone 값(예: Date, Map, 순환 값, sparse array)은 JSON 변환으로 유실시키지 않고 실패시킨다. DB가 없으면 새 DB를 만들지 않는다. 실패 시 `.partial-<UUID>` 폴더를 남기고, 완료 시에만 최종 폴더로 배타적 이름 변경을 수행한다. 이후 가져오기는 manifest를 신뢰하기 전에 각 행과 전체 파일·경로 목록 해시를 독립적으로 검사해야 한다.

## 2026-10-16 격리 검증

실제 사용자 저장소 대신 고유 fixture bundle ID를 사용했다.

| 항목 | 관찰 결과 |
|---|---|
| 서버 없는 origin | JS `location.origin`과 WK frame origin 모두 `http://127.0.0.1:62434` |
| 프로세스 재실행 | raw main·writer, backup·추가 필드와 `solasi.theme=dark` 유지 |
| 작은 export | 2행, 221 bytes; 독립 JSON·키·SHA 대조 통과 |
| 합계 64MiB 초과 | 5행, 72,352,115 bytes; 각 offset·bytes·키·SHA와 전체 SHA 대조 통과 |
| 별도 이름의 서명된 helper 앱 | 같은 fixture bundle ID로 동일한 큰 저장소를 읽고 두 차례 대조 완료 |
| 창 없는 긴 실행 | WebKit `ProcessSuspension`으로 멈춤 관찰; 진행 창 추가 후 완료 |
| 빈 origin | DB 생성 없이 0행·`database_present:false`·`theme:null` 완료 |
| 기존 출력 경로 | 저장소 접근 전 오류, 기존 결과 유지 |
| 같은 bundle ID 중복 실행 | 저장소 접근 전 오류 |
| 정상 `backup:undefined`·중첩 객체·배열 | 별도 fixture 3행·307bytes export, JSON+경로 목록으로 정확한 객체 복원, 원본 필드 유지 확인 |
| 경로 목록 해시 | 실제 manifest를 Python의 별도 SHA256 계산과 대조 |
| JSON으로 보존 못 하는 Date | 실패 후 원래 Date 필드와 모든 fixture 행이 여전히 존재함을 재조회 |
| Python 실행기 | source snapshot→Swift 컴파일→별도 앱 서명→빌드 전용 명령 출력 통과 |

작은 자동 검사는 `python3 -m unittest tests.test_legacy_draft_export -v`로 실행한다. 실제 Swift에 포함된 JavaScript codec을 Node로 검사하는 roundtrip 시험도 포함한다. WebKit fixture는 `macos/LegacyStoreFixture.swift`를 별도 고유 ID 앱으로 빌드해 `seed`, `seed-large`, `seed-undefined`, `seed-invalid`, `read`를 실행했다. 사용자 저장소를 fixture로 시드하면 안 된다.

원래 앱의 실제 저장소 읽기·새 보관함 가져오기·재시작 확인은 상위 마이그레이션 단계에서 따로 검증한다.
