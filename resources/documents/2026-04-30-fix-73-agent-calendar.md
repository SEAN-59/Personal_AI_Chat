# 2026-04-30 개발 로그 — v0.4.2 fix #73: Agent Calendar Tool

## 배경

v0.4.1 운영 중 사용자 발견 회귀:

```
사용자: 26년 6월 임금 지급일은?
봇:    6월 21일입니다. 다만, 토요일 또는 공휴일인 경우 익일에 지급됩니다.
실제: 2026-06-21 = 일요일 → 정답은 6월 22일
```

규정 텍스트는 정확히 인용되지만 자료 안에 들어있는 **조건절 (`토/공휴일이면 익일`) 을 현재 달력에 적용해 추론하는 능력** 이 없음. 같은 패턴이 사규 곳곳에 반복 (만료일 / 정산일 / 신청 마감 / 분기 마감) 이라 패턴별 workflow 구현은 ROI 가 나쁨.

이슈 #73 의 결정 (option A): **agent 에 calendar tool 추가**. 한 도구가 모든 conditional date 패턴을 흡수.

플랜: `resources/plans/v_0_x/v_0_4_2/fix_73_plan.md`

---

## 1. 설계 결정

### 1.1. 도구 시그니처 (3개)

| 이름 | 입력 | 출력 (callable raw) | summary |
|---|---|---|---|
| `weekday_of` | `{date: str}` | `{date, weekday}` | `2026-06-21 = 일요일` |
| `is_business_day` | `{date: str}` | `{date, weekday, is_business_day, holiday_name}` | `2026-06-06 (토요일) = 휴일 — 현충일` |
| `next_business_day` | `{date: str}` | `{input_date, next_business_day, weekday, shifted}` | `2026-06-21 → 2026-06-22 (월요일, 다음 영업일)` |

세 도구 모두 schema 모드 (`Tool.input_schema` 명시) — 단일 string `date` 필드. 입력 변형 4종 허용: `YYYY-MM-DD` / `YYYY/MM/DD` / `YYYY.MM.DD` / `YYYYMMDD`.

### 1.2. `holidays` PyPI

- `holidays>=0.50,<1.0` (BSD-3, 활발 유지보수)
- `holidays.KR(language='ko')` 전역 1회 캐싱 — thread-safe, 매년 PyPI 업그레이드만으로 데이터 갱신
- 한국어 공휴일명 (`현충일` / `삼일절` / `광복절` / `어린이날` / `추석` / `설`)

### 1.3. 도구 실패 정책

**`failure_kind` 분기 추가 0** — 현행 `tools.call()` 의 4분기 (`unknown_tool` / `schema_invalid` / `callable_error` / `low_relevance`) 그대로 활용:

- 잘못된 date 형식 → callable 에서 `ValueError` raise → **`callable_error`**
- 빈 문자열 / 키 누락 → schema `require_fields` 에서 차단 → **`schema_invalid`**
- callable_error 는 `MAX_LOW_RELEVANCE_RETRIEVES` 누적 가드 미카운트 → ReAct loop 가 다른 형식으로 자유 retry

이는 Codex 검토 P2-1 의 가이드 — "별 enum 추가하지 말고 현행 4분기 충분히 활용". 플랜의 가설 (`invalid_input` 신설) 은 폐기.

### 1.4. 라우팅 — `DATE_CONDITION_KEYWORDS` tier 신설

#### 단순 `AGENT_KEYWORDS` 확장이 안 되는 이유 (Codex P2-2)

기존 `route_question()` 평가 순서:
```
1. DB RouterRule
2. WORKFLOW_KEYWORDS  ← 먼저
3. AGENT_KEYWORDS
4. default → single_shot
```

`AGENT_KEYWORDS` 에 `지급일` 만 추가하면 `급여 지급일은?` 같은 합성 질문이 `WORKFLOW` 의 `급여` 에 가로채짐 → `route='workflow', workflow_key=''` → workflow_node 가 single_shot 으로 폴백 → calendar 도구 호출 안 됨. 동일 충돌: `퇴직금 지급일`, `수당 지급일`.

#### 해결 — 전용 tier

`chat/services/question_router.py` 에 `DATE_CONDITION_KEYWORDS` 신설:

```python
DATE_CONDITION_KEYWORDS: tuple[str, ...] = (
    '지급일', '만료일', '정산일', '마감일',
)
```

`route_question` 평가 순서:
```
1. DB RouterRule
2. DATE_CONDITION_KEYWORDS → route='agent', reason='date_condition_keyword'  ← 신규
3. WORKFLOW_KEYWORDS         → route='workflow'
4. AGENT_KEYWORDS            → route='agent', reason='agent_keyword'
5. default                   → route='single_shot'
```

### 1.5. 운영자 override 경로

- 합성 질문을 workflow 로 보내고 싶은 경우: BO `/bo/router-rules/new/` 에서 `pattern=급여 지급일`, `route=workflow` 로 명시 등록 — DB rule 이 코드 fallback 보다 먼저 평가
- DATE_CONDITION 키워드를 single_shot 으로 보내고 싶은 경우: 같은 방식으로 `pattern=지급일`, `route=single_shot` 등록

### 1.6. BO 노출

`/bo/router-rules/` 의 코드 fallback 박스에 `agent (조건절)` 카드 추가 — 운영자가 새 tier 의 존재와 4 키워드를 즉시 인지 가능. WORKFLOW / AGENT 카드와 같은 패턴.

### 1.7. agent 프롬프트 가이드

`assets/prompts/chat/agent_react.md` 끝에 **조건절 처리 (v0.4.2)** 문단 추가. 도구만으로는 부족 — agent 에게 "토/공휴일이면 익일" 류 발견 시 `is_business_day` / `next_business_day` 호출하라고 명시. LLM 이 자체적으로 요일 추측하지 않도록 차단.

---

## 2. 구현

### 신규 (3)
- `resources/plans/v_0_x/v_0_4_2/fix_73_plan.md` — 본 fix 의 detail plan
- `chat/tests/test_agent_tools_calendar.py` — 22 cases
- `resources/documents/2026-04-30-fix-73-agent-calendar.md` — 본 dev log

### 수정 (5)
- `requirements.txt` — `holidays>=0.50,<1.0` 추가
- `chat/services/agent/tools_builtin.py` — 3 callable + summarize + register 블록 (181 lines 추가)
- `assets/prompts/chat/agent_react.md` — 조건절 처리 가이드 7줄
- `chat/services/question_router.py` — `DATE_CONDITION_KEYWORDS` 상수 + `route_question` 평가 순서 확장
- `bo/views/router_rules.py` + `bo/templates/bo/router_rules.html` — DATE_CONDITION 카드 노출
- `chat/tests/test_routing_e2e.py` — 9 cases 추가 (단순 4 + 충돌 4 + 음성 1)

### 마이그레이션 / DB 변경
**0건.** 코드 상수 + 도구 등록만으로 해결.

---

## 3. 검증

### 자동 (CI)
```
$ docker compose exec -T web python manage.py test
Ran 551 tests in 1.147s
OK
```

523 (v0.4.1) → 551 (+28 신규: calendar 22 + 라우팅 9 ⊃ 기존 통과 그대로).

### 수동 (도구 smoke)
```
weekday_of({'date': '2026-06-21'}) → 2026-06-21 = 일요일
is_business_day({'date': '2026-06-21'}) → 2026-06-21 (일요일) = 휴일 (주말)
is_business_day({'date': '2026-06-06'}) → 2026-06-06 (토요일) = 휴일 — 현충일
next_business_day({'date': '2026-06-21'}) → 2026-06-21 → 2026-06-22 (월요일, 다음 영업일)
weekday_of({'date': '2026.06.21'}) → 2026-06-21 = 일요일  (alt 형식 OK)
weekday_of({'date': 'invalid'}) → callable_error: ValueError ...
```

### 수동 (라우팅 smoke)
```
'지급일은?'         → route=agent reason=date_condition_keyword matched=['지급일']
'급여 지급일은?'    → route=agent reason=date_condition_keyword matched=['지급일']  ← WORKFLOW '급여' 가 가로채지 못함
'급여는 얼마야?'    → route=workflow reason=workflow_keyword matched=['얼마','급여']  ← 음성 케이스 보호
```

### 수동 (BO 페이지)
- `http://localhost:8001/bo/router-rules/` HTTP 200
- "기본 키워드" 박스 안에 `agent (조건절)` 카드 + 4 키워드 (`지급일/만료일/정산일/마감일`) + "WORKFLOW 보다 먼저 평가 (v0.4.2)" 노트 visible

---

## 4. 한계 / 후속

### 한계
- `holidays` PyPI 의 임시공휴일은 행정안전부 발표 직후엔 lag 가능 — 발견 시 패키지 업그레이드로 해결
- 회사별 custom 휴일 (창립기념일 등) 미지원 — 사규에 자체 명시되어 있어도 calendar tool 은 표준 한국 공휴일만 봄
- agent 가 calendar 도구를 안 쓰고 LLM 직접 요일 판단할 위험 → 프롬프트 가이드로 차단, 회귀 시 BO Prompt 관리에서 즉시 보강
- 이번 fix 는 agent 경로 한정 — single_shot 으로 가는 동일 질문엔 calendar reasoning 없음. 운영자가 BO 에서 RouterRule 명시 등록하면 우회 가능

### 후속 (out of scope, 별 이슈)
- 회사별 custom 휴무일 BO 등록 UI
- 결정론적 `payday_calculation` workflow (option B) — calendar tool 사용량 6개월 관찰 후 재검토
- v0.5.0 LLM 기반 라우터 — keyword 기반 routing 의 본질적 한계 해결 (별 milestone)

---

## 5. 릴리즈

본 fix 는 v0.4.2 패치 릴리즈 (PATCH bump):

```
v0.4.1 → v0.4.2
```

흐름:
1. fix/#73 → develop merge
2. develop → main release PR (chore: Release v0.4.2)
3. tag v0.4.2 + push → GHCR 운영 배포
4. 사용자가 운영에서 `26년 6월 임금 지급일은?` 시 정답 (6월 22일) 답변 확인

---

## 6. 참고

- 이슈: https://github.com/SEAN-59/Personal_AI_Chat/issues/73
- 플랜: `resources/plans/v_0_x/v_0_4_2/fix_73_plan.md`
- Codex 검토 (3 라운드): P2 invalid_input / P2 RouterRule seed / P3 정산일 / P3 신규 file count / P2 routing precedence / P3 BO visibility / P3 test count — 모두 plan 단계에서 반영 후 구현
