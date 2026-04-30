# v0.4.2 — fix #73: Agent Calendar Tool 개발 플랜

## Context

v0.4.1 운영 중 사용자 발견 회귀:

```
사용자: 26년 6월 임금 지급일은?
봇:    6월 21일입니다. 다만, 토요일 또는 공휴일인 경우 익일에 지급됩니다.
실제: 2026-06-21 = 일요일 → 정답은 6월 22일
```

규정 텍스트는 정확히 인용되지만, 자료 안에 들어있는 **조건절 (`토/공휴일이면 익일`) 을 현재 달력에 적용해 추론하는 능력** 이 없음. 같은 패턴이 사규 곳곳에 반복 (만료일 / 정산일 / 신청 마감 / 분기 마감) 이라 패턴별 workflow 구현은 ROI 가 나쁨.

이슈 #73 (`fix:` / `type: bug` / `0.x Maintenance` milestone) 의 결정 사항:

> **Option A — agent 에 calendar tool 추가**. 임금/만료/정산 등 모든 conditional date 패턴을 한 도구로 흡수.

본 plan 은 v0.4.2 patch release 단위로 처리 — `fix` 만 포함 → SemVer PATCH 상승.

---

## Scope

**포함**
- `chat/services/agent/tools_builtin.py` — 3개 도구 신규 등록:
  - `weekday_of(date) -> '월'/'화'/.../'일'`
  - `is_business_day(date) -> bool` (주말 + 한국 공휴일)
  - `next_business_day(date) -> 'YYYY-MM-DD'`
- `requirements.txt` — `holidays` PyPI 의존성 추가
- `assets/prompts/chat/agent_react.md` — conditional date clause 인식 시 calendar tool 호출 가이드 추가
- `chat/services/question_router.py` — `DATE_CONDITION_KEYWORDS` 신설 (`지급일` / `만료일` / `정산일` / `마감일`) + `route_question` 의 평가 순서를 `DB rule → DATE_CONDITION → WORKFLOW → AGENT → default` 로 확장. WORKFLOW 보다 먼저 평가해 `급여 지급일` 같은 합성 질문이 `급여` (WORKFLOW_KEYWORDS) 에 가로채지지 않도록.
- `bo/views/router_rules.py` + `bo/templates/bo/router_rules.html` — 코드 fallback 키워드 박스에 `DATE_CONDITION_KEYWORDS` 섹션 신설 (운영자가 새 tier 의 존재를 BO 에서 인지 가능하도록).
- 단위 테스트 (`chat/tests/test_agent_tools_calendar.py`) — 3 도구 각 1~2건
- 통합 테스트 — agent E2E 시나리오 (임금 지급일 query → calendar tool 호출 → 정답)
- Dev log `resources/documents/2026-04-XX-fix-73-agent-calendar.md`
- 본 plan 문서 자체 (`resources/plans/v_0_x/v_0_4_2/fix_73_plan.md`)

**제외 (이번 patch 범위 밖)**
- 회사별 custom 공휴일 / 임시공휴일 추가 (PyPI `holidays` 의 standard Korean public holidays 만)
- 결정론적 workflow 도메인 (option B — 충분히 안 쓰이면 영원히 도입 안 함)
- 시스템 프롬프트 (`system.md`) 수정 — single_shot 경로엔 calendar 능력 없음, agent 만 처리
- LLM router (Phase 10 / v0.5.0) — 별 milestone
- 도구의 BO 노출 (`/bo/agent/` tool catalog 는 자동 반영되니 코드 변경 0)

---

## git-flow 계획

- **Milestone**: `0.x Maintenance` (이미 #9 로 존재)
- **Issue**: #73 (이미 존재 — Step 0 에서 타이틀/라벨만 `fix:` / `type: bug` 로 재분류)
- **Branch**: `fix/#73-agent-calendar-tool`, `develop` 에서 분기
- **PR 단위**: **단일 PR**. 도구 / 프롬프트 / 라우터 키워드 / 테스트 / 문서가 하나의 fix unit. 커밋은 아래 6 단계로 쪼개 히스토리 가독성 확보.
- **Conventional Commits**: 모든 커밋 prefix `fix:` (단 `test:` / `docs:` 는 그 자체로 fix 의 부속이라 PR 전체 머지 결과는 PATCH 로 정합).
- **Release**: develop merge → develop → main 정기 배포 PR → tag `v0.4.2` → main 백머지

> 사용자 명시 정책: 이 patch 는 v0.4.2 로 즉시 cut. v0.5.0 (LLM router) 와 분리.

---

## 핵심 설계 결정

### 1. 도구 시그니처 (3개)

| 이름 | 입력 | 출력 | 비고 |
|---|---|---|---|
| `weekday_of` | `date: 'YYYY-MM-DD'` | `'월'/'화'/'수'/'목'/'금'/'토'/'일'` | 단순 요일 |
| `is_business_day` | `date: 'YYYY-MM-DD'` | `true / false` | 주말 또는 한국 공휴일이면 `false` |
| `next_business_day` | `date: 'YYYY-MM-DD'` | `'YYYY-MM-DD'` | `date` 가 영업일이면 그대로, 아니면 다음 영업일 |

세 도구 모두 schema 모드 (`Tool.input_schema` 명시). 입력은 단일 string `date` 필드로 통일 — agent 가 `arguments={"date": "2026-06-21"}` 형태로 호출. 잘못된 형식은 callable 에서 `ValueError` 를 던져 현행 `tools.call()` 의 `failure_kind='callable_error'` 분기에 흡수 (별 enum 추가 X — agent 동작상 callable_error 면 ReAct loop 가 다음 iteration 에 다른 입력 시도하므로 충분).

### 2. `holidays` PyPI 사용

- `pip install holidays` (BSD-3, 활발히 유지보수, 한국 공휴일 정확)
- 사용 예: `import holidays; KR = holidays.KR(); date(2026,6,6) in KR  # True (현충일)`
- 매년 update 필요 — `holidays` 패키지가 자체적으로 업데이트되므로 운영 부담 0
- 임시공휴일은 한국 행정안전부 발표를 PyPI 가 잡아주지만 발표 직후엔 lag 가능 — 발견 시 패키지 업그레이드로 해결

### 3. agent prompt 변경 최소

`agent_react.md` 끝에 한 문단 추가:

> **조건절 처리 (Phase 0.4.2)**: retrieve 결과에 "토요일/일요일/공휴일이면 익일" 같은 조건절이 보이고 사용자 질문이 특정 날짜를 묻고 있다면, `is_business_day` 또는 `next_business_day` 도구로 실제 적용 결과를 계산해 답변에 반영. 도구 없이 LLM 이 직접 요일을 판단하지 말 것.

`build_messages` 의 tool catalog 에는 자동 노출되므로 별 변경 X.

### 4. 라우팅 키워드 — `DATE_CONDITION_KEYWORDS` 신설 + 평가 우선순위 변경

#### 4-1. 단순 `AGENT_KEYWORDS` 확장이 안 되는 이유 (Codex 검토 P2)

`route_question()` 의 현행 평가 순서 (`chat/services/question_router.py:107-129`):

```
1. DB RouterRule
2. WORKFLOW_KEYWORDS (코드 fallback)   ← 먼저
3. AGENT_KEYWORDS (코드 fallback)
4. default → single_shot
```

`AGENT_KEYWORDS` 에 `지급일` 만 추가하면 `급여 지급일은?` 같은 **합성 질문** 이 `WORKFLOW_KEYWORDS` 의 `급여` 에 먼저 가로채짐 → `route='workflow', workflow_key=''` → workflow_node 가 single_shot 으로 폴백 → calendar 도구 호출 안 됨. 동일 충돌: `퇴직금 지급일`, `수당 지급일`.

#### 4-2. 해결 — 전용 tier 신설

`chat/services/question_router.py` 에 **`DATE_CONDITION_KEYWORDS`** 상수 신설하고 평가 순서에 끼워넣음:

```python
# 조건절 (토/공휴일 익일 등) 적용이 필요한 질문 신호.
# WORKFLOW_KEYWORDS 보다 먼저 평가 — `급여 지급일` 같은 합성 질문이 `급여`
# (WORKFLOW) 에 먼저 가로채지지 않도록. v0.4.2 신규 (이슈 #73).
DATE_CONDITION_KEYWORDS: tuple[str, ...] = (
    '지급일', '만료일', '정산일', '마감일',
)
```

`route_question` 평가 순서 (변경 후):

```
1. DB RouterRule
2. DATE_CONDITION_KEYWORDS  → route='agent', reason='date_condition_keyword'   ← 신규
3. WORKFLOW_KEYWORDS         → route='workflow'
4. AGENT_KEYWORDS            → route='agent', reason='agent_keyword'
5. default                   → route='single_shot'
```

#### 4-3. 왜 `AGENT_KEYWORDS` 와 분리하는가

- **시멘틱 분리**: `비교/추천/유리` 같은 "추론 의도" 와 `지급일/만료일` 같은 "조건절 적용 필요" 는 의미가 다름 — 한 통에 섞으면 후속 추가/제거 시 의도 혼동
- **다른 우선순위**: WORKFLOW_KEYWORDS 와 충돌 시 어느 쪽이 이겨야 하는지가 두 카테고리 다름 — DATE_CONDITION 은 이겨야 하고, AGENT_KEYWORDS 는 그대로 (기존 정책 유지)
- **로그 가독성**: `reason='date_condition_keyword'` 가 `reason='agent_keyword'` 보다 진단 정보가 풍부 — 운영자가 이 라우팅이 calendar 의도였음을 즉시 식별
- **확장성**: 향후 다른 "조건 적용 필요" 패턴 (예: `시효`, `유효기간`) 도 같은 tier 에 자연스럽게 추가

#### 4-4. 운영자 override 경로

- 운영자가 `pattern=급여 지급일`, `route=workflow` 같이 명시 등록하면 DB RouterRule 이 코드 fallback 보다 먼저 평가되므로 즉시 우선
- DATE_CONDITION 으로 보내고 싶지 않은 케이스도 BO 에서 explicit override 가능
- 운영 데이터 / dev log 에 이 관계 명시

### 5. 도구 실패 정책

- 잘못된 date 문자열 (parsing 불가) → callable 에서 `ValueError('invalid date format: ...')` raise → 현행 `tools.call()` 의 `failure_kind='callable_error'` 로 흡수 (Phase 7-4 분기 4종: `unknown_tool` / `schema_invalid` / `callable_error` / `low_relevance` 그대로 사용 — 새 enum 추가 X)
- 누적 가드는 `low_relevance` 만 카운트 (Phase 7-4 정책) 이라 callable_error 는 max_iter 안에서 자유롭게 재시도 가능 — agent 가 다른 형식 (`2026.06.21` → `2026-06-21`) 으로 retry
- `holidays` 라이브러리 자체 실패 (네트워크 X, 순수 in-memory 라 거의 없음) → fallback: 주말 판단만 하고 공휴일은 "확인 필요" 안내
- `is_business_day` / `next_business_day` 의 결과는 agent 의 final answer 에 직접 반영

### 6. 테스트 전략

- 단위 테스트 (`test_agent_tools_calendar.py`) — 3 도구 입력/출력 + 잘못된 입력 → `tools.call()` Observation 에서 `failure_kind='callable_error'` 확인 + 한국 공휴일 정확성 (현충일 / 어린이날 / 광복절)
- 라우팅 테스트 — `chat/tests/test_routing_e2e.py` 에:
  - 단순 케이스 4건: `지급일은?` / `만료일은?` / `정산일은?` / `마감일은?` → 모두 `route=agent`, `reason='date_condition_keyword'`
  - **충돌 케이스** 4건: `급여 지급일은?` (WORKFLOW `급여` 와 DATE_CONDITION `지급일` 동시 매치 — agent 가 이겨야 함), `퇴직금 만료일은?`, `수당 정산일은?`, `연차 마감일은?` — `DATE_CONDITION_KEYWORDS` 우선 평가 검증
  - 음성 케이스: `급여는 얼마야?` → `route=workflow` (DATE_CONDITION 미매치, WORKFLOW `얼마` 매치 — 기존 동작 유지)
- 통합 테스트 — 임금 지급일 시나리오를 mock retrieve 결과 + LLM stub 으로 ReAct loop 한 번 돌려 calendar tool 호출 추적
- E2E (수동) — 운영 PDF 환경에서 `2026년 6월 임금 지급일은?` 실제 답변 확인

---

## 구현 순서 (커밋 6개)

### Step 0 — Issue 재분류 (코드 변경 X)
- `gh issue edit 73 --title "fix: ..."` + label `type: bug`
- 메모리 / plan 변경 없음

### Step 1 — 의존성 + plan 문서 커밋
- `requirements.txt` 에 `holidays` 추가 (latest minor pin: `holidays>=0.50,<1.0`)
- 본 plan 문서 자체 add

**커밋**: `fix: Add holidays dependency and plan doc for #73 (#73)`

### Step 2 — 3 calendar 도구 구현 + 등록
- `chat/services/agent/tools_builtin.py` 에 3 callable + `register(Tool(...))` 3 블록 추가
- 입력 검증 + 한국 공휴일 처리

**커밋**: `fix: Add weekday_of / is_business_day / next_business_day tools (#73)`

### Step 3 — agent prompt 가이드 추가
- `assets/prompts/chat/agent_react.md` 끝에 conditional clause 처리 문단 추가

**커밋**: `fix: Guide agent to use calendar tools for conditional date clauses (#73)`

### Step 4 — `DATE_CONDITION_KEYWORDS` 신설 + 평가 우선순위 변경 + BO 노출
- `chat/services/question_router.py` 변경:
  - `DATE_CONDITION_KEYWORDS` 상수 신설 (`지급일 / 만료일 / 정산일 / 마감일`)
  - `route_question()` 평가 순서: DB rule → **DATE_CONDITION** → WORKFLOW → AGENT → default
  - `RouteDecision.reason` 신규 값: `'date_condition_keyword'`
- BO 노출:
  - `bo/views/router_rules.py` — `DATE_CONDITION_KEYWORDS` import + context 에 `date_condition_keywords` 키로 전달
  - `bo/templates/bo/router_rules.html` — 코드 fallback 박스에 `DATE_CONDITION` 섹션 신설 (`workflow_keywords` / `agent_keywords` 섹션과 동일 패턴)
- 마이그레이션 / DB 변경 0 — 코드 상수 + 함수 흐름 + BO 표시만 수정

**커밋**: `fix: Add DATE_CONDITION_KEYWORDS tier to route calendar queries to agent (#73)`

### Step 5 — 테스트
- `chat/tests/test_agent_tools_calendar.py` 신규 (단위)
- `chat/tests/test_agent_calendar_e2e.py` 신규 (통합 — 임금 지급일 시나리오)

**커밋**: `test: Cover calendar tools and conditional date e2e (#73)`

### Step 6 — Dev log
- `resources/documents/2026-04-XX-fix-73-agent-calendar.md`
- 사용자 회귀 사례 / 설계 결정 / 구현 / 검증 / 한계

**커밋**: `docs: Document agent calendar tool fix (#73)`

---

## 파일 변경 요약

### 신규 (4)
```
chat/tests/test_agent_tools_calendar.py
chat/tests/test_agent_calendar_e2e.py
resources/documents/2026-04-XX-fix-73-agent-calendar.md
resources/plans/v_0_x/v_0_4_2/fix_73_plan.md   # 본 문서
```

### 수정 (7)
```
chat/services/agent/tools_builtin.py        # 3 도구 callable + register
assets/prompts/chat/agent_react.md          # conditional clause 가이드
chat/services/question_router.py            # DATE_CONDITION_KEYWORDS 신설 + 평가 순서 변경
chat/tests/test_routing_e2e.py              # 단순 키워드 4건 + 합성 충돌 케이스 + 음성 케이스 (총 9 case 추가)
bo/views/router_rules.py                    # DATE_CONDITION_KEYWORDS context 전달
bo/templates/bo/router_rules.html           # 코드 fallback 박스에 DATE_CONDITION 섹션 추가
requirements.txt                             # +holidays
```

### 삭제 (없음)

---

## 주요 파일 경로 (reference)

**현 상태 (v0.4.1)**
- `chat/services/agent/tools_builtin.py:364-403` — 기존 3 도구 register 위치. 새 도구 3개 같은 컨벤션 추가
- `chat/services/agent/tools.py` — `Tool` dataclass + `register()` API
- `chat/services/agent/react.py` — ReAct loop. 도구 추가만 하면 자동 활용 (catalog 자동 빌드)
- `chat/services/agent/state.py` — `Observation` / `failure_kind` 정의. 현행 4분기 (`unknown_tool` / `schema_invalid` / `callable_error` / `low_relevance`) 그대로 사용
- `chat/services/question_router.py:38-51` — `WORKFLOW_KEYWORDS` / `AGENT_KEYWORDS` 코드 상수. 본 fix 에서 `DATE_CONDITION_KEYWORDS` 신설을 같은 영역에 추가
- `chat/services/question_router.py:107-129` — `route_question()` 본체. 평가 순서 변경 위치
- `assets/prompts/chat/agent_react.md` — agent system prompt
- `requirements.txt` — `chat/` 패키지 의존성

**재사용**
- `chat.services.agent.tools.register` / `Tool` / `FieldSpec` — 도구 등록 인프라
- 한국 공휴일은 `holidays.KR` 인스턴스 캐싱 (전역 1회 생성, thread-safe)

---

## 검증

### 자동 (CI)
```bash
docker compose exec -T web python manage.py check
docker compose exec -T web python manage.py test --verbosity 0
```
- 기존 523 + 신규 ~14 → 537 전후 그린 기대 (calendar 단위 + 라우팅 e2e 8~9 (단순 4 + 충돌 4 + 음성 1) + 통합 e2e)

### 수동 (E2E)
1. 채팅 페이지에서 `26년 6월 임금 지급일은?` 입력
2. 서버 로그 확인:
   - `라우팅: route=agent reason=date_condition_keyword matched_rules=['지급일']` (코드 fallback 매치)
     - 운영자가 BO 에 명시 rule 을 등록한 환경이면 `reason=db_rule:<name>` 로 표시
   - `ReAct iteration 1/6 ...` retrieve_documents 호출
   - `ReAct iteration 2/6 ...` `is_business_day` 또는 `next_business_day` 호출 (date='2026-06-21')
   - `final_answer` 에 "6월 22일" 포함
3. BO `/bo/agent/` 의 최근 7일 호출 통계에 새 tool 등장
4. BO `/bo/` 대시보드 Purpose 별 사용량에 `agent_step` row 증가
5. BO `/bo/router-rules/` — 코드 fallback 키워드 박스 안에 `DATE_CONDITION_KEYWORDS` 4건 visible 확인 (별 섹션 또는 AGENT 섹션 위에 표시)
6. **충돌 검증**: `급여 지급일은?` 입력 → 로그에 `route=agent reason=date_condition_keyword matched_rules=['지급일']` (WORKFLOW `급여` 가 가로채지 않음을 확인)

### 회귀 민감 포인트
- [ ] 기존 agent E2E (`본인 결혼 경조금 비교`) 변경 없음 — calendar 도구 미호출 confirm
- [ ] `holidays` import 실패 시 (테스트 환경) graceful fallback 동작
- [ ] 운영자가 등록한 기존 RouterRule 과 충돌 0 (DB 변경 0)
- [ ] `routing_e2e` 의 기존 9 case 그대로 통과 — **신규 9 case 추가** (단순 4 + 합성 충돌 4 + 음성 1)
- [ ] BO `/bo/router-rules/` 코드 fallback 박스에 `DATE_CONDITION` 섹션 4 키워드 visible (view + template 함께 수정)

---

## 리스크 & 대응

| 리스크 | 대응 |
|---|---|
| `holidays` 패키지 임시공휴일 lag | 운영자가 BO 에서 사후 보정 안내 + 패키지 업그레이드 정책 (분기 1회) |
| agent 가 calendar 도구를 안 쓰고 LLM 직접 요일 판단 | 프롬프트 가이드 강화 (Step 3) + 회귀 시 `agent_react.md` BO 편집으로 즉시 보강 |
| `DATE_CONDITION_KEYWORDS` 가 WORKFLOW 보다 먼저 평가됨 — 기존 의도와 충돌 가능 | (a) routing_e2e 회귀로 기존 9 case 보호, (b) 신규 키워드 4개 (`지급일/만료일/정산일/마감일`) 는 단독으로 등장 시 거의 항상 calendar 의도라 false positive 낮음, (c) BO RouterRule 로 explicit override 가능 — DB rule 이 모든 코드 fallback 보다 먼저 평가됨 |
| 운영자가 합성 질문 (`급여 지급일`) 을 workflow 로 보내고 싶을 때 | BO `/bo/router-rules/new/` 에서 `pattern=급여 지급일`, `route=workflow`, `workflow_key=...` 로 명시 등록 — DB rule 이 즉시 우선 |
| 운영자가 calendar 키워드를 single_shot 으로 보내고 싶을 때 | BO `/bo/router-rules/new/` 에서 `pattern=지급일`, `route=single_shot` 으로 명시 rule 등록 — 코드 fallback 보다 우선 평가 |
| 도구 추가로 agent token 비용 ↑ | 도구 catalog 1 줄씩 추가 — 호출당 +50~100 token. 1000 q/day → +$0.005/day. 무시 가능 |
| date 문자열 형식 불일치 (`2026.06.21` vs `2026-06-21`) | 도구 callable 진입부에서 `dateutil.parser.parse` 로 normalize. 실패 시 `ValueError` → `callable_error` 로 ReAct loop 재시도 |
| 한국 공휴일 데이터 정확성 (현충일/광복절/추석/설) | PyPI `holidays` 의 KR 검증 + 단위 테스트로 매년 변동 공휴일 (추석/설) 1~2건 픽스 |

---

## Out of Scope (별도 이슈로 처리)

- 회사별 custom 휴무일 (창립기념일 등) BO 등록 UI
- 다국가 공휴일 (`holidays` 는 멀티국가 지원하지만 KR 만 사용)
- `payday_calculation` 결정론적 workflow (option B) — calendar tool 사용량 보고 6개월 후 재검토
- BO `/bo/agent/` 의 tool catalog 에 도구 설명 한국어화 (현재 영문 description 그대로) — UX 개선 별 이슈
- Phase 10 LLM router 와의 통합 — calendar tool 은 agent 도구라 router 변경과 직교

---

## 참고 — v0.5.0 와의 관계

본 fix 는 v0.5.0 (LLM router) 와 **독립적**.

- calendar tool 은 agent 도구 확장 — router 변경과 무관
- v0.5.0 에서 LLM router 가 도입돼도 본 도구는 그대로 활용
- 본 patch 가 먼저 나가도 v0.5.0 개발에 영향 0

따라서 v0.5.0 일정과 무관하게 v0.4.2 cut.
