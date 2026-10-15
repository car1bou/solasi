# 사용자별 여러 기기 연결과 배포 조사

확인일: 2026-10-15 (Asia/Seoul)

## 현재 결정 — 아래 동기화 제안은 채택하지 않음

2026-10-15 사용자 최종 정정: **각 기기에서 독립적으로 사용하는 로컬 앱**으로 진행한다. 드라이브·NAS 연결, Solasi 계정 서비스, 기기 등록·동기화, PC 원격 작업함은 구현 범위에서 제외한다. 다른 기기판에도 같은 로컬 저장 원칙을 적용한다. 기존에 사용자가 선택할 수 있게 한 AI 실행 방식과 자료 저장 위치는 별개의 설정이다.

이 문서의 서비스 계정·사용자 저장소 연결 비교는 이전 검토 기록이다. 현재 구현 설계로 사용하지 않는다. 현재 기준은 [과목·PDF·페이지 필기 로컬 설계](superpowers/specs/2026-10-15-local-course-notes-design.md)다.

상태: 공식 문서에 근거한 조사와 설계 제안이다. 제품 코드·계정·클라우드 인프라를 변경하거나 배포하지 않았다. 아래의 권장 구조는 구현·기기 검증이 끝난 제품 기능이 아니다.

## 반영할 사용자 요구

- 다른 사람에게 앱을 배포하며, 각 사용자는 자신의 Mac·PC·iPad·Galaxy Tab·휴대폰을 연결한다.
- 같은 사용자의 과목 공용 PDF에 페이지 메모·필기를 누적한다. 회차별 녹음·전사·일반 노트는 별도로 둔다.
- PDF 추출 결과를 주 화면으로 노출하지 않고, 원본 페이지와 메모·필기를 중심으로 구성한다.
- 기존 로컬 원본 파일 연결과 설치된 로컬 AI를 보존한다. 모델 파일까지 클라우드 동기화할 필요는 없다.
- Samsung Notes는 공식 문서로 우선 설계하며, REA 내부 분석은 APK·설치 파일을 확보한 후 진행한다.

## 요약 제안 — 조사에 근거한 판단

여러 사용자에게 배포하려면 **사용자 계정에 각 기기를 연결하고, 각 기기에 로컬 작업본을 둔 다음 계정 범위에서 동기화**하는 구조가 적합하다. 특정 개발자의 Mac에 접속하는 구조로는 사용자의 요구를 충족하지 못한다.

먼저 **Supabase Auth·Postgres·private Storage + 로컬 영구 변경 큐**로 필요한 페이지 메모·필기 작업을 안전하게 재전송하는 작은 구성을 비교한다. 온라인 인증·계정 격리는 서비스가 제공하지만, 영구 큐·멱등 쓰기·다운로드 차이 계산·충돌 보존은 이 앱에서 구현해야 한다. 단순한 최초 구현도 원격 저장 성공을 기다려야 획이 그려지거나, 끊기면 필기를 잃는 방식이어서는 안 된다.

요구가 여러 문서·회차의 넓은 오프라인 읽기·쓰기로 확장되고 직접 구현할 동기화 책임이 커진다면, **Supabase + PowerSync 기반 로컬 SQLite 동기화**를 우선 비교 후보로 삼는다. 인증·서버 데이터·파일 저장과 오프라인 변경 전송을 분리해 제공하는 공식 경로가 있고, 현재 React 클라이언트와 SQLite 개념을 이어갈 수 있기 때문이다. 단, 기존 FastAPI가 사용하는 SQLite 파일을 그대로 연결하면 모든 것이 자동 동기화되는 방식은 아니다. 동기화할 데이터 모델, 클라이언트 DB 경계, 쓰기 API, 충돌 처리, 사용자별 다운로드 범위를 구현해야 한다. [Supabase 통합 공식 가이드](https://docs.powersync.com/integrations/supabase/guide)

이 선택은 제품 요구와 문서에 근거한 **설계 판단**이며, 이 앱에서 안정성·성능·비용 우위를 측정한 결과는 아니다. PowerSync 서버의 FSL 조건을 배포 방식에 맞게 확인하고, 작은 기기 간 동기화 비교로 채택을 결정할 필요가 있다.

## 공식 문서로 확인한 선택지

| 구성 | 확인한 기능 | 앱에서 추가로 해결할 부분 | 판단 |
|---|---|---|---|
| Supabase Auth·Postgres·Storage + 앱의 영구 변경 큐 | 사용자 식별, SQL 행 권한, private 객체 저장소·서명 URL을 제공한다. | 오프라인 변경 큐·재전송·기기 간 충돌·로컬 저장·변경 다운로드는 별도 구성이다. | 좁은 필기·메모 작업부터 비교할 가장 작은 후보다. 동기화 범위가 커지면 직접 유지할 책임도 커진다. |
| Supabase + PowerSync | 선택한 Postgres 데이터를 로컬 SQLite로 내려받는다. 로컬 쓰기를 큐에 보존하고 `uploadData`가 백엔드로 전송한다. 오프라인 읽기·쓰기를 제공하는 공식 통합 경로가 있다. | 쓰기 검증·권한·충돌 정책, Sync Streams 권한, 파일 전송 어댑터, 기존 DB 마이그레이션을 앱에서 구현한다. | 오프라인 필기를 포함하는 요구의 우선 비교 후보다. |
| Postgres + Electric | HTTP Shape로 Postgres의 선택한 데이터를 내려보내는 read-path sync engine이다. | 쓰기는 자체 API를 거친다. 공식 예제도 optimistic state·영구 로컬 변경·rollback·충돌 처리를 앱에서 구성한다. Shape 인증 프록시도 필요하다. | 불가능하거나 읽기 전용 앱만 가능한 도구는 아니다. 다만 이번 요구에서 쓰기 경로를 직접 구성할 책임이 더 크다. |

근거: [Supabase RLS](https://supabase.com/docs/guides/database/postgres/row-level-security), [private Storage](https://supabase.com/docs/guides/storage/buckets/fundamentals), [PowerSync 통합](https://docs.powersync.com/integrations/supabase/guide), [PowerSync 충돌 처리](https://docs.powersync.com/handling-writes/handling-update-conflicts), [Electric 쓰기 패턴](https://electric.ax/docs/sync/guides/writes), [Electric 인증](https://electric.ax/docs/sync/guides/auth).

## 사용자별 격리

Supabase RLS는 요청 사용자의 `auth.uid()`와 행의 소유자를 비교하는 등의 정책으로 접근 가능한 행을 제한한다. 테이블 grants와 각 읽기·삽입·수정·삭제 정책을 함께 구성해야 한다. 클라이언트가 보낸 `owner_id`만 신뢰해서는 안 된다. 서비스용 비밀 키는 RLS를 우회할 수 있으므로 배포 앱·브라우저에 포함하면 안 된다. [공식 RLS 문서](https://supabase.com/docs/guides/database/postgres/row-level-security)

PowerSync의 다운로드 권한은 **Sync Streams가 별도로 결정**한다. Supabase 쓰기·API RLS가 있어도 PowerSync를 통해 다른 사용자의 데이터를 내려주면 격리가 깨진다. 공식 통합 예제는 인증된 사용자 ID로 소유 목록과 하위 항목을 선택한다. [공식 통합 가이드](https://docs.powersync.com/integrations/supabase/guide)

이 앱의 권장 기본 단위는 개인 사용자다. `owner_id`에 연결한 과목·자료 버전·페이지 주석·회차 기록을 같은 사용자에게만 동기화한다. 현재 요청에 없는 공동 편집용 조직·수업 멤버십은 먼저 만들지 않는다. 사용자 A가 B의 과목 ID·첨부 ID·작업 ID를 보내더라도 DB 조회, 파일 URL 발급, AI 작업 모두 거절해야 한다. 이는 제안하는 구현 기준이다.

기기 로그인과 기기 폐기는 별도로 추적한다. 로그아웃한 기기에서 다운로드했던 로컬 데이터는 토큰을 폐기했다고 자동으로 사라지지 않는다. 계정 전환 시 로컬 DB·파일 캐시·메모리의 사용자 구분과 삭제 정책을 구현해야 한다. 이미 오프라인인 기기의 파일을 원격 삭제했다고 보장할 수는 없다.

## PDF·녹음의 용량과 원본 연결

**로컬 파일 경로는 다른 기기에서 읽을 수 있는 자료 자체가 아니다.** Mac의 `/Users/.../lecture.pdf` 문자열을 iPad에 동기화해도 PDF 내용이 생기지 않는다. 다른 기기에서 보려면 원본을 가진 기기가 전송하거나, 접근 가능한 저장소에서 내려받아야 한다. 오프라인 보기에는 그 기기의 저장 공간에 PDF 바이트가 있어야 한다.

파일 본문을 DB 행의 base64·BLOB으로 동기화하는 대신, 파일 ID·크기·버전·참조만 DB로 동기화하고 실제 PDF·음성은 객체 저장소로 전송하는 방식이 공식 권장이다. PowerSync도 metadata + storage provider 패턴을 사용하며 파일 큐·캐시를 별도로 관리한다. 다만 현재 공식 built-in attachment helpers는 **alpha**로 표시되어 있어 바로 완성된 안정 기능으로 가정할 수 없다. JavaScript 어댑터는 전체 파일 버퍼를 받는 경로도 있어 큰 녹음의 메모리 부담을 확인해야 한다. [공식 파일 문서](https://docs.powersync.com/client-sdks/advanced/attachments)

권장 제품 정책은 다음과 같다. 아직 사용자가 승인한 저장 정책은 아니다.

| 자료 종류 | 권장 저장·전송 |
|---|---|
| Mac에 연결한 PDF | 로컬에서는 기존 원본을 참조한다. 사용자가 기기 동기화를 켠 PDF만 계정 저장소에 전송한다. 앱 안의 강의 회차마다 PDF를 복사하지 않는다. |
| 다른 기기의 PDF 보기 | 기본은 필요할 때 열고 제한된 캐시만 유지한다. 사용자가 ‘오프라인 보관’을 고른 자료만 고정한다. |
| 필기·페이지 메모 | 원본 PDF와 별도 저장하고 동기화한다. 필기할 때마다 PDF 전체를 다시 쓰거나 업로드하지 않는다. |
| 녹음 | 녹음한 기기에 먼저 보존한다. 원음 동기화 여부·용량·전송 대기 상태를 별도로 표시한다. |
| 추출·임베딩·모델 | 모델 가중치는 기기별 설치한다. 다시 만들 수 있는 캐시와 사용자 작성 원본을 분리한다. 추출·임베딩의 동기화 범위는 실제 용량·재계산 비용으로 판단한다. |

PDF는 사용자 범위에서 파일 내용 해시·버전으로 식별하고, 페이지 주석은 특정 문서 버전에 고정하는 것을 권장한다. 다른 버전의 PDF를 같은 이름으로 덮어써도 예전 필기가 새 페이지에 조용히 붙으면 안 된다. 삭제 역시 ‘기기 캐시 비우기’와 ‘계정 자료 삭제’를 구분해야 한다. 사용자 간 전역 중복 제거는 이번 범위에 넣지 않는다.

private Storage는 다운로드까지 RLS를 적용하며, JWT 인증 또는 만료되는 서명 URL로 접근한다. 반대로 public bucket의 파일 URL은 다운로드 권한을 우회할 수 있으므로 강의자료·녹음의 기본값으로 쓰지 않는다. [공식 bucket 문서](https://supabase.com/docs/guides/storage/buckets/fundamentals)

## 필기·메모 충돌

PowerSync가 모든 충돌을 자동으로 의미 있게 병합하지는 않는다. 공식 문서는 백엔드가 충돌 정책을 정하며, 가장 단순한 구현에서는 필드별 최종 쓰기 우선이 된다고 설명한다. 같은 작업이 재전송될 수 있으므로 백엔드 처리는 멱등해야 한다. CRDT를 저장·동기화하는 구성도 가능하지만 앱의 편집 모델을 대신 설계해 주지는 않는다. [기본 충돌 문서](https://docs.powersync.com/handling-writes/handling-update-conflicts), [맞춤 충돌 처리](https://docs.powersync.com/handling-writes/custom-conflict-resolution)

필기 전체를 한 JSON 행으로 덮어쓰는 것보다, 완료한 획마다 고유 ID를 부여하고 추가·삭제·변형 작업을 기록하는 구조를 먼저 비교한다. 서로 다른 기기가 별개 획을 추가하는 흔한 상황에서 전체 페이지 덮어쓰기를 피할 수 있다. 같은 획을 수정·삭제하거나 텍스트를 동시에 바꾸는 경우는 별도의 버전 대조가 필요하다. 초기 권장 정책은 충돌한 텍스트 두 버전을 남겨 사용자가 고르게 하는 것이며, 말없이 한쪽을 잃는 최종 쓰기 우선을 기본으로 삼지 않는다. 이는 필기 저장 모델 제안이며 구현 결과가 아니다.

실시간 펜 점마다 원격 응답을 기다리면 안 된다. 화면에는 로컬 입력을 즉시 그리고, 완료한 획을 로컬 영구 저장한 뒤 동기화한다. ‘기기 저장 완료’와 ‘계정 동기화 완료’ 상태를 구분한다. 전원 종료 직전 진행 중 획의 보존 범위는 후속 기기 시험으로 정한다.

## 암호화의 경계

Supabase는 저장 시 AES-256, 전송 시 TLS를 사용한다고 명시한다. 이것과 RLS는 서버 운영자도 원문을 볼 수 없는 종단간 암호화(E2EE)를 뜻하지 않는다. [Supabase 보안 문서](https://supabase.com/security)

Electric도 클라이언트에서 암호화한 ciphertext를 동기화할 수 있지만 키 관리·복구·기기 간 키 공유를 제공하거나 특정 방식으로 정하지는 않는다고 설명한다. 따라서 E2EE는 동기화 엔진을 택했다고 저절로 생기지 않는다. [Electric 보안 문서](https://electric.ax/docs/sync/guides/security)

E2EE를 채택하면 복호화 가능한 사용자의 기기에서 자료 추출·검색·로컬 AI를 실행하는 구성이 자연스럽다. 서버가 원문을 읽어야 하는 검색·외부 AI 작업은 별도 사용자 전송이 된다. 계정 복구와 자료 복호화 키 복구도 같은 문제가 아니므로 구현 전에 정책 결정이 필요하다. 이 문서는 E2EE를 구현하거나 채택 확정하지 않았다.

## 배포 모델 비교와 사용자 자신의 저장소

| 모델 | 각 사용자의 기기 연결 | PC가 꺼진 경우 | 운영·사용 부담 |
|---|---|---|---|
| 개인 PC를 자료 서버로만 사용 | 사용자의 PC에 다른 기기를 연결한다. | 그 PC의 원본 파일·AI 작업은 사용할 수 없다. 기기별 캐시·오프라인 편집은 별도 구현해야 한다. | 서버 파일 저장비는 줄지만 PC 가동·연결·중계가 사용 조건이 된다. |
| 서비스 계정 동기화 + 개인 PC AI | 같은 계정에 속한 기기를 연결하고, 자료 동기화와 PC 작업을 분리한다. | 동기화되거나 내려받은 PDF·메모·필기는 이용할 수 있게 설계한다. 해당 PC의 로컬 AI만 대기한다. | 일반 사용자에게 권장하는 제안. 계정·동기화·저장·전송 서비스를 운영해야 한다. |
| 사용자 자신의 저장소로 동기화 | 각자가 OneDrive·WebDAV·S3 등 선택한 저장소를 연결한다. | 접근 가능한 동기화 저장소와 기기 캐시를 통해 PC와 독립적으로 작업할 수 있다. | 운영자가 모든 파일 용량을 부담하는 것을 줄일 수 있지만, 저장소 인증·오류·충돌·서로 다른 API 지원은 앱의 책임이다. |

Joplin은 실제로 로컬 우선 데스크톱·모바일 클라이언트와 동기화 대상 드라이버를 분리하며 OneDrive·WebDAV·S3 등을 지원한다. 이는 사용자 자신의 저장소를 이용하는 구조의 공개 구현 근거다. Joplin 전체가 Solasi에 바로 삽입할 수 있는 라이브러리라는 의미는 아니며, 코드를 복사하거나 채택하지 않았다. [지원 동기화 대상](https://joplinapp.org/help/apps/sync/), [동기화 구조](https://joplinapp.org/help/dev/spec/sync/)

Google Drive의 `appDataFolder`도 앱 전용 데이터를 저장하는 공식 경로지만 사용자가 Drive UI에서 볼 수 없는 숨김 폴더이고, 공유·공간 간 이동·휴지통 동작 등에 제약이 있다. 기존 강의 PDF를 보통의 Drive 폴더처럼 관리하는 기능과 동일하지 않다. 단순히 Google 로그인을 추가한다고 충돌 해결·파일 버전·오프라인 전송이 완성되지는 않는다. [Google Drive 앱 데이터 문서](https://developers.google.com/workspace/drive/api/guides/appdata)

이 조사에서는 사용 편의성을 우선하면 서비스 계정 동기화를 추천한다. 운영자의 서버 비용 최소화가 더 중요하면 사용자 저장소 연결형을 먼저 선택할 수 있다. 두 모델을 처음부터 모두 구현하기보다 사용자에게 운영 방식을 먼저 확인해야 한다.

## 개인 PC의 AI 실행과 계정 동기화 분리

아래는 구현 결과가 아니라 권장하는 역할 분리다.

1. 각 사용자는 자신의 계정에 PC·태블릿·휴대폰을 등록한다. 다른 사용자의 자료·PC 작업으로 연결하지 않는다.
2. PDF 열람·페이지 메모·필기 저장은 해당 기기에서 먼저 처리한다. 펜을 움직일 때 서버나 모델의 응답을 기다리지 않는다.
3. 무거운 전사·추출·임베딩·로컬 생성은 그 사용자가 등록한 PC 실행기에 요청한다. 사용자별로 지원하는 모델·메모리·준비 상태를 확인한다.
4. PC 실행기는 인증된 작업 서비스에 자신이 먼저 연결해 대기한다. 일반 사용자에게 공유기 포트 개방을 요구하거나 현재의 localhost API를 그대로 공개하는 구조로 만들지 않는다.
5. PC가 꺼지면 로컬 AI 작업만 대기한다. 기기에 저장한 PDF와 필기는 계속 이용할 수 있도록 구성한다. 내려받지 않은 자료·동기화하지 않은 원본까지 오프라인으로 열 수 있다고 표시하지 않는다.
6. 외부 생성 API는 사용자가 선택한 경우에만 해당 제공자로 요청한다. 원음 전송은 별도의 선택이며 PC 오프라인을 이유로 자동 전환하지 않는다. API 키는 일반 과목 데이터와 함께 동기화하지 않는 것을 권장한다.

외부에서 시작한 연결을 이용해 내부 서비스에 통신하는 패턴은 Cloudflare Tunnel의 공식 구조에서도 확인된다. 이것은 패턴의 가능성을 뒷받침하며 Solasi가 사용자마다 Cloudflare Tunnel 계정을 요구해야 한다는 뜻은 아니다. 작업 ID·기기 ID·로그인 주체를 검증하고 허용된 전사·생성 작업만 실행하는 앱 전용 프로토콜이 별도로 필요하다. [Cloudflare Tunnel 구조](https://developers.cloudflare.com/cloudflare-one/networks/connectors/cloudflare-tunnel/)

Tailscale은 직접 연결과 중계, 기기 인증을 이미 제공하는 대안이지만 모든 기기에 별도 VPN을 설치·운영하는 절차가 생긴다. 공개 제품 전체를 개발자의 하나의 tailnet에 넣는 것을 기본값으로 정하지 않는다. 상업 서비스에서는 Personal 요금 조건을 그대로 적용한다고 가정할 수 없다. [연결 유형](https://tailscale.com/docs/reference/connection-types), [공유와 초대](https://tailscale.com/docs/reference/inviting-vs-sharing), [이용 구간](https://tailscale.com/pricing)

## 공통 화면과 기기별 실행 패키지

- 현재 React 화면과 Python 전사·검색 코드는 재사용할 수 있다. 현재 설치한 `Solasi.app`은 이 Mac의 경로·Python·자료를 참조하는 실행기이므로, 다른 사람에게 그대로 전달하는 독립 설치판은 아니다.
- Tauri 2는 데스크톱과 iOS·Android를 지원하며 Swift·Kotlin 모바일 플러그인을 작성할 수 있다. 데스크톱 Python API 서버는 sidecar 패턴으로 묶을 수 있지만 OS·CPU별 바이너리와 의존성을 준비해야 한다. [Tauri 시작 문서](https://v2.tauri.app/start/), [sidecar](https://v2.tauri.app/develop/sidecar/), [모바일 플러그인](https://v2.tauri.app/develop/plugins/develop-mobile/)
- Tauri의 공식 Shell 플러그인은 모바일에서 URL 열기만 지원한다. 따라서 현재 Python/FastAPI·MLX 환경을 모바일에서 `spawn`해 그대로 실행하는 구성으로 해석하면 안 된다. [Shell 지원 범위](https://v2.tauri.app/plugin/shell/)
- Electron 데스크톱 + Capacitor 모바일도 React를 재사용하는 대안이다. Electron과 모바일 셸을 별도로 관리하는 비용이 있으므로 이 앱에서 어느 쪽이 더 작고 빠른지 측정하지 않은 상태로 확정하지 않는다. [Electron](https://www.electronjs.org/docs/latest/), [Capacitor FAQ](https://capacitorjs.com/docs/getting-started/faqs), [Capacitor 플러그인](https://capacitorjs.com/docs/plugins)
- PWA는 읽기·필기 화면과 빠른 접근 경로에 유용하다. 하지만 브라우저 저장소는 용량 제한·퇴거·사이트 데이터 삭제의 영향을 받으며, 영구 저장 요청도 브라우저마다 처리 방식이 다르다. 브라우저에만 원음·필기를 보관하고 무조건 영구 보존된다고 안내하지 않는다. [MDN 저장 한계](https://developer.mozilla.org/en-US/docs/Web/API/Storage_API/Storage_quotas_and_eviction_criteria), [OPFS](https://developer.mozilla.org/en-US/docs/Web/API/File_System_API/Origin_private_file_system)

장시간 모바일 녹음은 별도 네이티브 경로를 검토한다. Android는 microphone foreground service·마이크 권한과 백그라운드 시작 제한을, iOS는 오디오 세션·background mode와 중단·오디오 경로 변경을 처리해야 한다. Apple의 아래 지침은 archived 문서이므로 실제 구현 시 현재 SDK도 대조해야 한다. PWA의 화면 잠금·앱 전환 중 무중단 녹음은 이번 조사에서 공식 보장으로 확인하지 못했다. [Android 서비스 유형](https://developer.android.com/develop/background-work/services/fgs/service-types), [Apple 녹음 앱 지침](https://developer.apple.com/library/archive/documentation/Audio/Conceptual/AudioSessionProgrammingGuide/AudioGuidelinesByAppType/AudioGuidelinesByAppType.html)

브라우저 안에서 AI를 실행하는 경로도 있다. Transformers.js는 WebGPU ASR 예제를 제공하지만 브라우저·모델별 지원과 실행 오류의 차이가 있고, 모델 다운로드·RAM·기기 부하 문제도 있다. 이 사실을 근거로 모든 태블릿에서 현재 Mac과 같은 한국어 전사·로컬 생성 품질을 보장할 수는 없다. 모바일 자체 모델은 별도 비교 대상으로 남기고 사용자 PC·선택 API 경로부터 이어가는 것을 권장한다. [Transformers.js WebGPU](https://huggingface.co/docs/transformers.js/guides/webgpu), [Google의 클라이언트 AI 성능 지침](https://web.dev/articles/client-side-ai-performance)

Yjs의 IndexedDB provider는 노트 편집 상태를 로컬에 보존하고 네트워크 provider와 함께 사용할 수 있다. 하지만 계정 권한·파일 전송·복구 정책을 자동 제공하는 동기화 서비스는 아니다. 우선 고유 획 작업·텍스트 버전·영구 전송 큐를 좁은 범위에서 비교하고, 동시 편집 요구가 그보다 크면 Yjs 같은 CRDT를 비교한다. [Yjs 오프라인 문서](https://docs.yjs.dev/getting-started/allowing-offline-editing)

## 라이선스·운영비

- PowerSync 클라이언트 SDK·관련 클라이언트 패키지는 Apache-2.0 또는 MIT이며, 서버 Service와 CLI는 FSL이다. 앱에서 SDK를 사용하는 것과 동기화 서비스를 재호스팅·재판매하는 것은 같은 라이선스 검토가 아니다. 선택한 버전의 실제 라이선스를 배포 전에 확인한다. [공식 라이선스 구분](https://powersync.com/open-source), [서버 소스](https://github.com/powersync-ja/powersync-service)
- Electric 공식 저장소는 Apache-2.0으로 표기되어 있다. 관리형 서비스의 요금·약관까지 Apache 라이선스로 대체되는 것은 아니다. [공식 저장소](https://github.com/electric-sql/electric)
- Supabase와 PowerSync Cloud 모두 무료·유료 구간과 사용량·용량 제한이 있다. Supabase는 DB compute·파일 보관·전송량 등을, PowerSync는 동기화량·보관량·동시 클라이언트 등을 따로 계산한다. 같은 PDF를 여러 기기에 보내면 전송량이 늘며, DB 동기화 요금만 계산해서는 안 된다. [Supabase 가격표](https://supabase.com/pricing), [PowerSync 가격표](https://www.powersync.com/pricing)
- 조사 당시 PowerSync 가격표 안에서도 무료 인스턴스 비활성 기간의 설명이 일치하지 않는 부분이 있어 정확한 기간은 확정하지 않았다. 무료 플랜의 무기한 상시 가동을 전제로 배포하지 않는다.
- 외부 AI 호출 비용과 사용자의 로컬 하드웨어 비용은 위 동기화 서비스 요금과 별개다. 이 문서에서는 사용자 수·자료량이 정해지지 않아 월 운영비를 확정하지 않았다.

## 채택 전 확인할 작은 비교

아래는 실행한 시험이 아니라 다음 구현의 검증 기준이다.

1. 사용자 A의 두 기기에서 같은 과목·PDF를 열고, 사용자 B는 ID·URL을 알아도 접근할 수 없는지 확인한다. DB API·Sync Streams·객체 URL 발급을 모두 검사한다.
2. 두 기기를 오프라인으로 만들고 같은 PDF에 서로 다른 획·페이지 메모를 쓴 뒤 다시 연결한다. 양쪽 입력을 잃지 않고 동기화 대기·실패·충돌 상태를 표시한다.
3. 업로드 성공 응답 직전 연결을 끊어 같은 작업을 재전송한다. 획·노트·파일이 중복 생성되지 않아야 한다.
4. 큰 PDF·긴 녹음에서 전송 재시도·부분 실패·메모리·기기 캐시 한도를 확인한다. PDF 바이트와 주석의 동기화 완료 상태를 혼동하지 않는다.
5. 계정 전환·로그아웃·기기 폐기 후 이전 계정 DB·캐시가 다음 사용자에게 보이지 않는지 확인한다. 오프라인 기기의 원격 삭제 한계를 문서화한다.
6. PDF 원본 교체·삭제·회전·페이지 삽입 후 예전 주석이 잘못된 문서 버전·좌표에 붙지 않는지 확인한다.

## 조사 기록

전체 조사는 세 흐름에서 Exa 검색 **12회 × 요청 결과 5개 = 60건**을 사용했다. 이는 중복을 포함한 요청 결과 수이며, 60개의 고유 문서를 정독했다는 뜻은 아니다. 검색 결과의 동일 URL을 합치고 판단에 필요한 공식 문서·공식 저장소를 직접 읽었다. 일부 작업자의 검색 출력이 잘려 전체 검색 결과의 고유 URL 수는 집계하지 않았다.

계정·DB 동기화 흐름은 검색 4회에서 요청 결과 **20건**, 직접 fetch한 URL은 중복 제외 **16개** 중 정상 응답 **15개**였다. 로그아웃 경로로 추정한 공식 URL 1개는 `CRAWL_NOT_FOUND`여서 근거로 사용하지 않았다. 클라이언트·PC 연결 흐름은 검색 **20건**, 로컬 편집·브라우저 AI·권한·사용자 저장소 흐름은 검색 **20건**이었다.

계정·DB 흐름의 검색 각도:

1. Supabase 사용자 인증·RLS·private Storage의 사용자별 격리.
2. PowerSync의 Supabase·로컬 SQLite·오프라인 쓰기·첨부·라이선스.
3. Electric의 쓰기 패턴·Shape 인증·보안·오프라인 책임.
4. PowerSync의 충돌·파일·라이선스 경계를 재확인.

출처 품질: 기능·제약은 해당 제품의 공식 문서와 원저장소로 확인했다. 공급자의 지원 범위·API 설명 근거로 사용했으며, 공급자의 성능·편의성 홍보를 이 앱의 비교 실험 결과로 취급하지 않았다. 블로그 순위·제휴 추천글은 근거에서 제외했다.

미확인: 이 앱의 동기화 프로토타입, 서버 RLS·기기 격리 실행 검증, 실제 비용, E2EE 키 관리, 모든 대상 기기의 펜·오프라인 입력, 실제 사용자 배포·업데이트 경로. 제품 코드·의존성·계정·테스트·배포는 변경하지 않았다.
