# v0.5.6 개발 틀 — Chunk Editing & Problem Reporting

## Summary

v0.5.6은 문서 운영자가 실제 답변 품질 문제를 더 빠르게 발견하고, 원인 chunk를 더 적은 비용으로 수정할 수 있게 만드는 운영 흐름 보강 버전이다.

현재 방향은 PDF → MD 자동 변환 품질을 무리하게 완성하는 것이 아니라, 사람이 BO에서 검수·수정하는 흐름을 전제로 한다. 따라서 v0.5.6의 핵심은 다음 두 가지다.

1. BO에서 chunk 단위로 확인·수정하고, 변경된 chunk만 재임베딩할 수 있게 한다.
2. 채팅 화면에서 사용자가 문제를 제보하면, 현재 세션 전체 대화 스냅샷을 DB에 저장하고 BO에서 관리자가 확인할 수 있게 한다.

## GitHub

- Milestone: `v0.5.6: Chunk Editing and Issue Reporting`
- Issue #93: `feat: Add chunk-level editing and re-embedding`
- Issue #94: `feat: Add chat problem reports with session snapshots`

## Phase 1 — Chunk 확인·수정 + chunk 단위 재임베딩 (#93)

### 목표

문서 전체 MD를 다시 저장하고 전체 재임베딩하는 대신, 이미 분리된 특정 chunk 하나의 내용만 수정하고 해당 chunk embedding만 갱신할 수 있게 한다.

### 사용자 흐름

1. BO 파일 관리에서 문서의 `청크 확인`으로 이동한다.
2. 관리자가 문제 있는 chunk를 확인한다.
3. 해당 chunk의 `수정` 버튼을 누른다.
4. chunk 내용만 수정한다.
5. 저장 시 안내 문구를 확인한다.
   - 이 수정은 해당 chunk만 재임베딩합니다.
   - 문서 구조나 표 행 추가/삭제처럼 chunk 경계를 바꾸는 수정은 문서 전체 수정/재임베딩을 사용해야 합니다.
6. 저장 후 해당 chunk의 `content`, `embedding`, `updated_at`류 메타가 갱신된다.

### 핵심 계약

- chunk 단위 수정은 `DocumentChunk` 하나의 content와 embedding만 갱신한다.
- `chunk_index`, `document_id`는 유지한다.
- chunk 경계가 바뀔 수 있는 구조 수정은 지원하지 않는다. 이 경우 기존 문서 전체 수정/재임베딩 흐름을 사용한다.
- 재임베딩 실패 시 기존 chunk content/embedding이 깨지면 안 된다.
- 사용자가 chunk 수정과 문서 전체 수정의 차이를 UI에서 이해할 수 있어야 한다.

### 주요 검토 포인트

- embedding 실패 시 transaction/rollback 안전성.
- 기존 `Document.edited_text`와 chunk content의 동기화 정책.
- chunk만 수정했을 때 BO 문서 수정 화면의 MD와 불일치가 생길 수 있는지.
- 수정 이력/audit 필요 여부.
- 검색 결과가 수정된 chunk를 즉시 반영하는지.

## Phase 2 — 채팅 문제 제보 + BO 확인 (#94)

### 목표

채팅 화면에서 사용자가 답변 오류를 발견했을 때, 별도 설명 자료를 만들지 않아도 현재 세션 전체 대화와 출처를 함께 관리자에게 전달할 수 있게 한다.

### 채팅 화면 사용자 흐름

1. 채팅 상단 초기화 버튼 좌측에 `문제 제보` 버튼을 추가한다.
2. 버튼 클릭 시 모달을 연다.
3. 모달 안내 문구를 노출한다.
   - `문제 제보를 제출하면 현재 채팅 세션의 대화 내용과 답변 출처 정보가 함께 관리자에게 전달됩니다.`
4. 사용자는 `제목`, `내용`만 입력한다.
5. 제출 시 현재 세션 전체 대화 스냅샷을 함께 DB에 저장한다.

### DB 저장 계약

새 모델 이름은 세부 플랜에서 확정하되, `QA` 기존 도메인과 혼동되지 않도록 `ProblemReport`, `ChatIssueReport` 류 명칭을 우선 검토한다.

저장 후보 필드:

- `title`
- `description`
- `session_key` 또는 session id
- `conversation_snapshot` JSON
- `status`: `open / reviewing / resolved / ignored`
- `admin_note`
- `created_at`, `updated_at`

`conversation_snapshot`에는 현재 세션의 모든 turn을 저장한다.

- 사용자 질문
- 챗봇 답변
- 답변 sources
- chat_log_id가 있으면 함께 저장
- created_at 또는 turn 순서

### BO 관리자 흐름

1. BO 사이드바에 `문제 제보` 메뉴를 추가한다.
2. 목록에서 제목, 상태, 생성일, 세션 id, 마지막 질문 미리보기를 확인한다.
3. 상세 화면에서 사용자가 입력한 제목/내용과 세션 전체 대화 타임라인을 확인한다.
4. 각 답변의 sources를 확인해 문제 문서/chunk 추적이 가능해야 한다.
5. 관리자는 상태와 관리자 메모를 수정할 수 있다.

### 핵심 계약

- DB에는 세션 전체 스냅샷을 저장한다.
- BO 목록에는 관리 편의를 위해 마지막 질문만 미리보기로 보여준다.
- BO 상세에는 전체 대화 타임라인을 보여준다.
- 사용자는 현재 세션 정보가 함께 전달된다는 사실을 모달에서 명확히 안내받는다.
- 기존 엄지 피드백/QA Pair/CanonicalQA와 의미가 섞이지 않도록 모델·URL·메뉴 명칭을 분리한다.

## 권장 진행 순서

1. Issue #93 세부 개발 플랜을 Claude가 작성한다.
2. Codex가 실제 코드와 대조해 검토·보강 요청을 반복한다.
3. Codex 승인 후 Claude가 구현한다.
4. Claude 테스트 후 Codex가 검증한다.
5. 사용자가 chunk 수정/재임베딩 수동 QA를 한다.
6. PR/merge/후처리.
7. 같은 방식으로 Issue #94를 진행한다.

## Manual QA 초안

### #93 Chunk 수정

- BO에서 문서의 청크 확인 화면에 진입한다.
- 특정 chunk의 오타 또는 금액 값을 수정한다.
- 저장 시 해당 chunk만 재임베딩된다는 안내를 확인한다.
- 같은 질문으로 채팅을 실행해 수정된 값이 반영되는지 확인한다.
- 문서 전체 수정/재임베딩 버튼은 기존대로 동작해야 한다.

### #94 문제 제보

- 채팅에서 여러 turn 대화를 진행한다.
- `문제 제보` 버튼을 누른다.
- 모달에서 세션 정보 전달 안내 문구를 확인한다.
- 제목/내용 입력 후 제출한다.
- BO 문제 제보 목록에서 제보가 보이는지 확인한다.
- 상세 화면에서 전체 대화와 sources가 보이는지 확인한다.
- 상태와 관리자 메모를 변경해 저장한다.

## Out of Scope

- PDF → MD 자동 변환 품질 자체 개선.
- chunk 경계 재계산이 필요한 구조적 편집을 부분 재임베딩으로 처리하는 것.
- 문제 제보를 자동으로 CanonicalQA나 운영 QA 케이스로 승격하는 기능.
- 알림/메일/슬랙 연동.
