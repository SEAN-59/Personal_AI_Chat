# 2026-04-28 개발 로그 — 2.0.0 Phase 8-4: Polish — Retrieval Relevance & BO Shared Partials

## 배경

Phase 8-1 / 8-2 / 8-3 머지 완료 후 polish phase. 두 backlog 항목을 묶어 처리:

### #1 — retrieve_documents false positive (8-1 backlog, 사용자 가시 잡음)

Phase 8-1 smoke 시나리오 A''' 에서 발견:
- 질문: `2025년 1월 1일부터 100일 후 날짜는?`
- agent → retrieve_documents 호출 → `2025년` / `100일` / `1일부터` 같은 시간 토큰이 longest meaningful tier 가 됨 → 임의 PDF (개인정보 / 취업규칙 등) 가 false positive 매치 → `is_failure=False` → `hits[0]` 이 evidence → 무관 PDF 가 `QueryResult.sources` 로 노출.

근본 원인: `_LOW_SIGNAL_TOKENS` 에 시간 표현 미포함 + `_tokenize_query` 가 한국어 조사 분리 안 함.

### #3 — BO 인라인 JS / CSS 분산 (8-3 carry-over, refactor)

Phase 8-3 에서 agent.html / router_rules.html / router_rule_form.html / qa pages 각자 shake / auto-dismiss / bulk-action 인라인 구현. `_qa_bulk_script.html` 만 partial 인데 마크업 클래스가 `qa-*` 로 고정돼 router-rules 에 재사용 불가 — 결국 router 용으로 같은 코드를 다시 인라인.

향후 BO 페이지 추가 시 또 같은 코드를 인라인할 가능성 ↑.

---

## 1. 패키지 구조 변화

```
chat/services/agent/
  tools_builtin.py          ← _LOW_SIGNAL_TOKENS 시간 단어 추가 + _PARTICLE_SUFFIX +
                              _LOW_SIGNAL_PATTERNS regex tuple + _is_low_signal helper

chat/tests/
  test_agent_tools_builtin.py  ← HasMeaningfulMatchTests 보강 9 + IsLowSignalTests 4

bo/static/bo/
  bo.js                     ← 신규 — initFormShake / initAlertAutoDismiss / initBulkActions

bo/templates/bo/
  base.html                 ← <script src="bo/bo.js" defer>
  agent.html                ← 인라인 <script> / shake CSS 제거
  router_rules.html         ← 인라인 <script> 제거 + data-bulk-* 마크업 통일
  router_rule_form.html     ← 인라인 shake <script> 제거 (required 자동 감지)
  qa_logs.html              ← qa-* → data-bulk-* + data-auto-dismiss + include 제거
  qa_feedback.html          ← 동일
  qa_canonical.html         ← 동일
  _qa_styles.html           ← bulk-mode 셀렉터 [data-bulk-page] 기반 일반화
  _qa_bulk_script.html      ← 삭제 (bo.js 가 일반화)

bo/views/agent.py           ← AgentSettingsForm widget attrs 에 data-shake-input

bo/tests.py                 ← 2 cases — bulk attribute / bo.js 로드 회귀 가드
```

---

## 2. 핵심 결정

### Decision 1 — Retrieval relevance: regex 일반화 (LLM judge X)

옵션 검토:
- (A) `_LOW_SIGNAL_TOKENS` enumeration 확장 → `2025년` / `1년` / `100년` 모두 등록 불가능.
- **(B) regex 패턴 (숫자+단위) → 채택**.
- (C) LLM-based relevance judge → retrieve 호출당 LLM 추가 → 비용 폭증, 8-2 의 비용 분리 의도와 충돌.
- (D) embedding cosine similarity threshold → retrieval layer 큰 변경.

**(B)** 가 비용 0, 의존성 0, 회귀 위험 낮음.

### Decision 2 — `_PARTICLE_SUFFIX` 한국어 조사/접미 그룹

`_tokenize_query` 가 조사 분리 안 함이라 `1일부터` / `100일까지` / `날짜는` 같은 토큰이 그대로 남음. 패턴 차원에서 흡수:

```python
_PARTICLE_SUFFIX = r'(은|는|이|가|을|를|에|의|도|만|로|으로|부터|까지)?'
```

모든 시간·수량 regex 에 부착. `날짜` / `기간` 도 같은 suffix 패턴으로 일반화.

### Decision 3 — `^...$` anchor 로 부분 매치 차단

`30년근속` 같은 도메인 명사가 `\d+년` 패턴으로 잘못 절감되지 않게 `^...$` anchor 강제. 도메인 명사는 의미 토큰 그대로 인정.

### Decision 4 — `bo.js` 단일 파일 + `data-bulk-*` 규약

옵션:
- (A) 페이지별 인라인 — 8-3 까지 상태.
- (B) 여러 partial template — 페이지마다 include boilerplate.
- **(C) 단일 `bo.js` + base.html 한 번 로드 → 채택**.

`bo.js` 가 `DOMContentLoaded` 시점에 `data-*` attribute 기반으로 자동 동작. 페이지 작성자는 마크업 규약만 따르면 됨 (별도 호출 / include 불필요). fail-silent 정책 — selector 없으면 즉시 return, 콘솔 에러 0.

### Decision 5 — `data-bulk-edit-toggle data-bulk-target` 짝 매칭

기존 인라인 마크업: `<button data-router-edit-toggle>` 가 page 컨테이너 (`.router-page`) **밖** header 에 위치. JS 가 page 안에서 querySelector 하면 못 찾음.

채택: `<button data-bulk-edit-toggle data-bulk-target="router">` ↔ `<div data-bulk-page="router">` 의 식별자 매칭. JS 는 `document.querySelector` 로 두 attribute 짝지어 매칭. 토글이 page 외부에 위치해도 OK.

### Decision 6 — `alert-danger` 자동 제거 제외

`initAlertAutoDismiss` 가 모든 `data-auto-dismiss` 를 3초 후 fade-out 하지만 `alert-danger` 는 자동 제거 대상에서 제외. 사용자가 에러 메시지 읽고 조치해야 하므로. 인라인 스크립트의 기존 동작을 공용 JS 계약에도 보존.

### Decision 7 — `initFormShake` 가 두 hook 모두 지원

- **opt-in**: `data-shake-input` (HTML5 `required` 미적용 input — agent.html 의 number input 같은 케이스).
- **자동 감지**: `input.input[required]` / `select.input[required]` / `textarea.input[required]` (router_rule_form 의 required 필드).

두 hook 합집합으로 어느 쪽 마크업이든 회귀 0.

---

## 3. 사용자-가시 변화

### 시나리오 A''' 잡음 해소

| | Before | After |
|---|---|---|
| 질문 | `2025년 1월 1일부터 100일 후 날짜는?` | (동일) |
| 답변 | 정상 (single_shot 또는 workflow) | 정상 (동일) |
| Sources 패널 | 무관 PDF 3건 (개인정보 / 취업규칙 / 포상규정) | **0건** (low-signal 토큰만 매치 → low_relevance failure → evidence 제외) |

### 운영자-가시 변화 (회귀 0)

| BO 페이지 | 동작 변화 |
|---|---|
| `/bo/agent/` | shake / auto-dismiss 동일 동작. 인라인 JS 제거 / 공용 bo.js 로 |
| `/bo/router-rules/` | 일괄 액션 / `수정` 토글 / 페이지네이션 동일 동작 |
| `/bo/qa/logs/`, `/qa/feedback/`, `/qa/canonical/` | 일괄 승격 / 삭제 동일 동작 |
| `/bo/router-rules/new/`, `/<id>/edit/` | shake 동일 동작 |

---

## 4. 검증

### 단위 테스트

| 모듈 | 신규 케이스 |
|---|---|
| `test_agent_tools_builtin.py` (`HasMeaningfulMatchTests`) | 9 (시간 토큰 3 + 조사 붙은 토큰 3 + 화폐 1 + 도메인 명사 통과 1 + A''' exact query 회귀 1) |
| `test_agent_tools_builtin.py` (`IsLowSignalTests`) | 4 (단어 / 단순 regex / 조사 붙은 regex / 정상 도메인 토큰) |
| `bo/tests.py` (`BoSharedPartialsMarkupTests`) | 2 (router_rules data-bulk-* attribute / base.html bo.js 로드) |
| **총합** | **15** |

총 469/469 그린 (Phase 8-3 종료 실측 454 → +15).

### 운영 환경 smoke

5 운영 시나리오 + Phase 8-4 신규 검증:

1. **시나리오 A''' 직접 검증** — `2025년 1월 1일부터 100일 후 날짜는?` → 무관 PDF 가 sources 에 없음.
2. 시나리오 1~5 (8-3 그대로) → 회귀 0.
3. BO `/bo/agent/` 폼 invalid 입력 → 빨간 테두리 + shake (공용 bo.js 동작).
4. BO `/bo/router-rules/` `수정` → 행 클릭 → 일괄 액션 (공용 bo.js 동작).
5. BO `/bo/qa/logs/` `수정` → 카드 클릭 → 일괄 승격/삭제.
6. 어떤 페이지든 success 토스트 → 3초 후 자동 사라짐. 에러 토스트는 그대로.

---

## 5. 후속 (Phase 8-5 / 8-6)

본 plan 분할 (1+3 / 2+6 / 4+5) 의 다음 두 단계:

- **Phase 8-5** — BO 대시보드 purpose 분해 컬럼 / 차트 (#2) + TokenUsage `cost_usd` 환산 (#6).
- **Phase 8-6** — `MAX_CONSECUTIVE_FAILURES` / `MAX_REPEATED_CALL` BO 노출 (#4) + AgentSettings audit log (#5).

8-1 backlog #1 은 본 PR 머지로 처리 완료 — 사용자 memory `project_phase_8_polish_backlog.md` 의 #1 항목에 노트.
