# v0.5.0 — LLM 기반 라우터 (Plan, 코덱스 리뷰 반영 보강)

> **Status**: Approved — 개발 대기
> **Milestone**: `v0.5.0: LLM Router & Context-Aware Retrieval` (신규)
> **Branch base**: `develop`
> **해결 대상 이슈**: #76 (가설 질문), #77 (history-blind routing), 메타-요청 케이스

---

## Context — 왜 v0.5.0 이고, 왜 LLM Router 만 남는가

키워드 라우터의 한계가 실사용에서 드러남:
- **대명사**: "비싼거" → 엉뚱한 답
- **메타-요청**: "이거 말고 더 있을건데?" → 자료 없음
- **가설 질문** (#76): "만약 ~라면" 패턴 처리 부족

**코덱스 리뷰 후 코드 검증 결과**, v0.5.0 1차 초안의 절반이 이미 운영 중인 것으로 확인:

| 항목 | 1차 플랜 | 실제 코드 상태 | 결론 |
|---|---|---|---|
| Query rewriter | "신규 구현" | `chat/services/query_rewriter.py` (152줄) 이미 존재 | ❌ 제거 |
| TokenUsage.purpose | "마이그레이션 추가" | `chat/models.py:117` + `token_purpose.py` (7 상수) 이미 운영 | ❌ 제거 (값만 추가) |
| `/bo/llm-usage/` | "신규 페이지" | `bo/views/dashboard.py:65-85` 에 purpose 집계 + 한국어 라벨 이미 존재 | ❌ 제거 (라벨만 추가) |
| `router_node` 가 history 받음 | 가정 | `chat/graph/nodes/router.py:28` 은 `route_question(state['question'])` 만 호출 | ✅ **수정 필요** |
| `run_chat_completion()` model 주입 | 가정 | `chat/services/single_shot/llm.py:19-41` 은 env 변수만 읽음 | ✅ **시그니처 확장 필요** |
| `workflow_key=''` → single_shot 폴백 | 가정 | `chat/graph/nodes/workflow.py:44-49` 정확히 그렇게 동작 | ✅ 회귀 0 보장 |

**v0.5.0 실질 신규 가치 = LLM Router 한 덩어리**. 나머지는 정비·연결 작업.

> Rewriter 가 이미 들어와 있다는 사실은 **#77 의 메인 효과 (follow-up/메타-요청/대명사) 가 사실상 이미 해결됐을 가능성** 을 의미. v0.5.0 의 첫 작업은 **현재 rewriter 동작이 의도대로 가는지 실사용 검증** 부터.

---

## Scope

### 포함
- **LLM Router** — `chat/services/llm_router.py` 신규
- `route_question()` 시그니처 확장: `(question, history)` — `question_router.py`
- `router_node` 호출부 수정 — `chat/graph/nodes/router.py:28` 에서 history 전달
- `run_chat_completion()` 시그니처 확장: `(messages, model=None)` — `single_shot/llm.py`
- `PURPOSE_LLM_ROUTER = 'llm_router'` 추가 — `token_purpose.py` (known 6 → 7, `ALL_PURPOSES` 전체 7 → 8: known 7 + unknown 1)
- `_PURPOSE_LABELS` 한국어 라벨 매핑 — `bo/views/dashboard.py:30-38`
- `OPENAI_AUX_MODEL` 환경변수 (미설정 시 `OPENAI_MODEL` 폴백)
- `assets/prompts/chat/llm_router.md` 신규 + `prompt_registry` 등록 (`relative_path='chat/llm_router.md'`)
- e2e 검증 시나리오 (S1~S7, S2 가 1순위)
- 단위 테스트 + 회귀 보호 (DATE_CONDITION 보호 / LLM 출력 검증 계약 포함)

### 제외 (out of scope)
- Query rewriter 신규 (이미 존재)
- TokenUsage 마이그레이션 (이미 운영)
- `/bo/llm-usage/` 신규 페이지 (기존 dashboard 활용)
- ReRank / 하이브리드 검색 → **v0.6.0 후보 (메모리 기록됨)**
- Combined router+rewriter call → v0.5.x
- Streaming, prompt caching, 멀티 LLM provider → 항구 제외

---

## 핵심 설계 결정 (사용자 확정)

### 1. LLM Router 책임 범위 = **route 만**

```python
# llm_router 가 반환하는 것
{"route": "single_shot|workflow|agent", "reason": "..."}
# workflow_key 는 항상 ''
```

- **workflow_key 는 DB RouterRule 전담** — 운영자가 BO 에서 명시 등록
- LLM hallucination 위험 0, 정책 일관성 확보
- LLM 이 `route=workflow` 를 줘도 `workflow_key=''` → `workflow_node` 가 `single_shot_node` 로 자동 폴백 (`workflow.py:44-49`)
- 즉 **운영자가 workflow_key 매핑한 패턴만 정형 계산**, 나머지는 단발 응답

### 2. 4-tier 라우팅 (우선순위)

```
Tier 1: DB RouterRule (운영자 명시)               — workflow_key 가능
Tier 2: DATE_CONDITION_KEYWORDS (v0.4.2 보호)     — agent route (calendar 도구)
Tier 3: LLM 분류 (신규)                           — route 만, workflow_key=''
Tier 4: 나머지 키워드 fallback (WORKFLOW/AGENT/default)
```

- **Tier 2 가 LLM 보다 먼저인 이유**: v0.4.2 (#73) 에서 확립한 "`급여 지급일`,
  `정산일`, `만료일`, `마감일` 같은 합성 질문은 반드시 agent + calendar 도구로
  보낸다" 는 회귀 보호 계약을 LLM 오분류로부터 지키기 위함. LLM 이 같은 질문을
  `workflow` / `single_shot` 으로 분류하면 calendar 도구 호출이 끊어져
  `급여 지급일이 토요일이면 익일` 같은 조건절을 그대로 답에 흘려보낸다.
- DATE_CONDITION 단순/충돌 케이스 (`급여 지급일은?`, `퇴직금 정산일 알려줘`)
  에서는 **LLM 호출 자체가 일어나지 않아야 한다** (비용 0, 회귀 0).
- Tier 3 LLM 실패 시 Tier 4 로 폴백 (회귀 0 보장).
- DB rule 우선 → 운영자가 DATE_CONDITION/LLM 결정을 모두 override 할 수 있음.

### 3. Phase 분할 = **2 Phase**

| Phase | 범위 |
|---|---|
| **9-1 LLM Router + 인프라** | run_chat_completion 시그니처 / PURPOSE / dashboard 라벨 / llm_router.py / route_question 시그니처 / router_node 수정 / 프롬프트 / env / 단위 테스트 |
| **9-2 검증 + Polish** | e2e 시나리오 / 회귀 테스트 / 운영 로그 정비 / dev log / README |

---

## 파일 변경 요약

### 신규 (4)
```
chat/services/llm_router.py
chat/tests/test_llm_router.py
assets/prompts/chat/llm_router.md
resources/documents/YYYY-MM-DD-v0_5_0-llm-router.md
```

### 수정 (10)
```
chat/services/question_router.py            # route_question(question, history) 시그니처 + 4-tier 통합
chat/graph/nodes/router.py:28               # history 전달
chat/services/single_shot/llm.py:19-41      # run_chat_completion(messages, model=None)
chat/services/token_purpose.py:25-67        # PURPOSE_LLM_ROUTER 추가 (ALL_PURPOSES frozenset 7 → 8)
chat/services/prompt_registry.py            # PromptEntry(key='chat-llm-router',
                                            #             relative_path='chat/llm_router.md')
bo/views/dashboard.py:30-38                 # _PURPOSE_LABELS 매핑
chat/tests/test_token_purpose.py            # 7 → 8 (test_total_count_is_seven → eight,
                                            #         test_known_six_purposes_are_members → seven),
                                            #         llm_router membership 단언 추가
chat/tests/test_routing_e2e.py              # `_llm_classify` mock 도입 (네트워크/API key 없이 그린)
bo/tests.py (또는 기존 dashboard test)        # 라벨 매핑 / observed-only 노출에 llm_router 포함
README.md                                   # §3, §11
```

> `chat/tests/test_token_purpose.py` 는 현재 `test_total_count_is_seven` 와
> `test_known_six_purposes_are_members` 가 known 상수 수를 박아두고 있어
> `PURPOSE_LLM_ROUTER` 추가 시 테스트명까지 함께 갱신
> (`test_total_count_is_eight`, `test_known_seven_purposes_are_members`) 해야
> 의미가 맞는다. 실제 코드의 멤버십 집합은 `ALL_PURPOSES` frozenset.
> dashboard 라벨/observed-only 노출 테스트도 `llm_router` 가 한국어 라벨로
> 렌더링되는지 새 단언을 1줄 추가한다.
>
> `chat/tests/test_routing_e2e.py` 는 현재 `route_question()` 을 **직접 호출** 하므로,
> Tier 3 LLM 분기가 들어가면 기존 default/keyword fallback 케이스가 실제 LLM
> 네트워크 호출을 시도할 위험이 있다. 본 PR 에서 해당 파일에 `_llm_classify`
> 를 `None` 반환으로 고정하는 mock (per-test 또는 모듈 fixture) 을 도입한다.
> 자세한 계약은 §검증 > 회귀 보호 참조.

---

## 핵심 코드 변경 스케치

### A. `run_chat_completion()` 시그니처 확장 — `chat/services/single_shot/llm.py`

```python
# Before (line 19)
def run_chat_completion(messages):
    model = os.environ.get('OPENAI_MODEL', DEFAULT_MODEL)
    ...

# After
def run_chat_completion(messages, model=None):
    if model is None:
        model = os.environ.get('OPENAI_MODEL', DEFAULT_MODEL)
    ...
```

- 기존 호출처는 인자 없이 호출 그대로 동작 (회귀 0)
- LLM Router 는 `run_chat_completion(messages, model=os.environ.get('OPENAI_AUX_MODEL') or os.environ.get('OPENAI_MODEL'))` 으로 호출

### B. `route_question()` 시그니처 확장 — `chat/services/question_router.py`

```python
from chat.services.llm_router import LlmRouteResult, _llm_classify


def route_question(question: str, history: Optional[List[Dict]] = None) -> RouteDecision:
    history = history or []

    # Tier 1: DB RouterRule
    db_decision = _match_db_rules(question)
    if db_decision is not None:
        return db_decision

    # Tier 2: DATE_CONDITION_KEYWORDS — v0.4.2 (#73) 회귀 보호.
    # LLM 보다 먼저 평가해서 `급여 지급일` 류가 workflow/single_shot 으로
    # 오분류되어 calendar 도구 호출이 끊기는 사고를 차단.
    hits = _matches(question, DATE_CONDITION_KEYWORDS)
    if hits:
        return RouteDecision(
            route=ROUTE_AGENT,
            reason='date_condition_keyword',
            matched_rules=hits,
        )

    # Tier 3: LLM 분류 (신규). llm_router 는 RouteDecision 을 모르고
    # `LlmRouteResult` (route + reason) 만 반환 — 순환 import 차단 계약.
    try:
        llm_result: Optional[LlmRouteResult] = _llm_classify(question, history)
    except Exception as exc:
        logger.warning('LLM 라우터 실패, 키워드 fallback: %s', exc)
        llm_result = None
    if llm_result is not None:
        return RouteDecision(
            route=llm_result.route,
            reason=llm_result.reason,
            workflow_key='',  # DB RouterRule 전담 — LLM 출력은 항상 무시
        )

    # Tier 4: 나머지 키워드 fallback (WORKFLOW / AGENT / default).
    # 기존 inline 키워드 분기는 그대로 두고, 위 DATE_CONDITION 블록만
    # `_match_db_rules` 다음으로 끌어올린다 — 새 helper 추출은 하지 않는다.
    hits = _matches(question, WORKFLOW_KEYWORDS)
    if hits:
        return RouteDecision(
            route=ROUTE_WORKFLOW, reason='workflow_keyword', matched_rules=hits,
        )
    hits = _matches(question, AGENT_KEYWORDS)
    if hits:
        return RouteDecision(
            route=ROUTE_AGENT, reason='agent_keyword', matched_rules=hits,
        )
    return RouteDecision(route=ROUTE_SINGLE_SHOT, reason='default')
```

> 현재 `question_router.py` 에는 `_keyword_route()` helper 가 없다. 위 스케치는
> 기존 inline 키워드 블록을 helper 로 추출하지 않고, DATE_CONDITION 블록만
> LLM 호출 위로 이동시키는 최소 변경만 한다. 향후 v0.5.x 에서 LLM 호출 이후
> fallback 만 묶어 `_keyword_route()` 로 추출하는 정리는 별도 작업.

#### 순환 import 회피 계약 (필독)

`RouteDecision` 은 `chat/services/question_router.py` 에 정의되어 있고,
`question_router.py` 는 Tier 3 에서 `llm_router._llm_classify` 를 호출해야
한다. 만약 `llm_router.py` 가 `RouteDecision` 을 직접 만들어 반환하려고
`from chat.services.question_router import RouteDecision` 을 추가하면,
`question_router → llm_router → question_router` 순환 import 가 발생한다
(Django 앱 로딩 시점 / 모듈 초기화 시점에 ImportError 또는 부분 초기화 모듈
참조로 깨질 수 있음).

**계약**:
- `llm_router.py` 는 `RouteDecision` 을 **런타임/모듈-탑 어디에서도 import
  하지 않는다**. 함수 안 지연 import 도 금지 (실수 차단).
- `llm_router.py` 는 자체 neutral dataclass `LlmRouteResult` (또는 동등한
  plain dict / tuple) 만 반환한다. `LlmRouteResult` 는 `route`, `reason`
  두 필드만 가지며 `ALL_ROUTES` 검증을 통과한 결과.
- `question_router.py` 가 `LlmRouteResult` → `RouteDecision` 변환을 전담
  하면서 `workflow_key=''` 를 강제한다 (`RouteDecision` 의 정책 책임이
  llm_router 로 새지 않게).
- 향후 `RouteDecision` 을 별도 모듈로 분리 (`chat/services/route_types.py`
  등) 한다면 그쪽으로 import 옮기는 것도 가능하지만, **v0.5.0 의 기본
  권장안은 neutral result 반환 방식** (변경 면적 최소).
- 단위 테스트로 `from chat.services import llm_router` import smoke 케이스
  (`test_module_imports_without_route_decision`) 1건 추가 — 모듈 단독
  import 시 `RouteDecision` 참조 없이도 로딩되는지 확인.

### C. `router_node` 호출부 — `chat/graph/nodes/router.py:28`

```python
# Before
decision = route_question(state['question'])

# After
decision = route_question(state['question'], state.get('history', []))
```

### D. `llm_router.py` 신규 (`_llm_classify` + `LlmRouteResult`)

```python
import json
import logging
import os
from dataclasses import dataclass
from typing import Optional

from chat.graph.routes import ALL_ROUTES  # ('single_shot', 'workflow', 'agent')
from chat.services.prompt_loader import load_prompt
from chat.services.single_shot.llm import run_chat_completion
from chat.services.single_shot.postprocess import record_token_usage
from chat.services.token_purpose import PURPOSE_LLM_ROUTER
# ⚠️ `RouteDecision` 은 절대 import 하지 않는다 — 순환 import 차단 계약 (§B 참조).

logger = logging.getLogger(__name__)

_REASON_MAX_LEN = 120  # 로그/DB 가독성 보호 (한 줄)


@dataclass(frozen=True)
class LlmRouteResult:
    """LLM 라우터의 neutral 결과 — `RouteDecision` 의존 없음.

    `question_router.route_question()` 이 이 결과를 받아 `RouteDecision` 으로
    변환하며 `workflow_key=''` 를 강제한다. 분리 이유는 §B 의 순환 import
    회피 계약 참조.
    """

    route: str    # ALL_ROUTES 멤버 (검증 완료된 값만 들어옴)
    reason: str   # 'llm:<짧은 근거>' 또는 'llm'


def _llm_classify(question: str, history: list[dict]) -> Optional[LlmRouteResult]:
    system_prompt = load_prompt('chat/llm_router.md')
    user_payload = _format_user_payload(question, history[-3:])
    messages = [
        {'role': 'system', 'content': system_prompt},
        {'role': 'user', 'content': user_payload},
    ]
    text, usage, model = run_chat_completion(
        messages,
        model=os.environ.get('OPENAI_AUX_MODEL') or os.environ.get('OPENAI_MODEL'),
    )
    record_token_usage(model, usage, purpose=PURPOSE_LLM_ROUTER)

    return _parse_and_validate(text)


def _parse_and_validate(text: str) -> Optional[LlmRouteResult]:
    """LLM 출력 → LlmRouteResult. 계약을 못 지키면 None → keyword fallback."""
    try:
        parsed = json.loads(text)
    except (ValueError, TypeError):
        return None
    if not isinstance(parsed, dict):
        return None

    route = parsed.get('route')
    if not isinstance(route, str) or route not in ALL_ROUTES:
        return None

    reason_raw = parsed.get('reason', '')
    reason = reason_raw.strip() if isinstance(reason_raw, str) else ''
    if len(reason) > _REASON_MAX_LEN:
        reason = reason[:_REASON_MAX_LEN]

    # workflow_key 가 출력에 있어도 무시 — `RouteDecision` 으로의 변환을
    # question_router 가 전담하고, 거기서 `workflow_key=''` 가 강제된다.
    return LlmRouteResult(
        route=route,
        reason=f'llm:{reason}' if reason else 'llm',
    )
```

> **API 정합**: 현재 코드베이스에는 `render_prompt` / `prompt_to_messages` 가
> 없고, 모든 호출처가 `prompt_loader.load_prompt(relative_path)` 패턴을 쓴다
> (`chat/services/prompt_loader.py` 참조). 신규 스케치도 같은 패턴을 따른다.

#### LLM 출력 검증 계약

| 단계 | 통과 조건 | 위반 시 |
|---|---|---|
| 1. JSON 파싱 | `json.loads(text)` 성공 | None → fallback |
| 2. 객체 형태 | `isinstance(parsed, dict)` | None → fallback |
| 3. route 멤버십 | `parsed['route'] in ALL_ROUTES` | None → fallback |
| 4. reason 정제 | str → `.strip()`, 길이 ≤ 120 (초과 시 절단) | 통과 (정제만) |
| 5. workflow_key | LLM 출력에 있어도 **무시** — `LlmRouteResult` 가 필드를 안 가져 자연 드롭, `route_question` 이 변환 시 `RouteDecision.workflow_key=''` 강제 | 통과 (드롭) |

- `ALL_ROUTES` 는 `chat.graph.routes` 에 이미 정의된 상수 튜플을 그대로 사용
  (LangGraph conditional edge 가 분기하는 값과 일치). 새 route 가 추가될 때
  자동 동기화되도록 LLM 측은 이 상수를 import 한다.
- 위 1~3 어디서든 실패하면 `_llm_classify` 는 `None` 을 반환하고, 호출자인
  `route_question` 은 Tier 4 키워드 fallback 으로 떨어진다 — LangGraph
  conditional edge 가 알 수 없는 라벨로 깨지는 사고를 원천 차단.

### E. `PURPOSE_LLM_ROUTER` 추가 — `chat/services/token_purpose.py`

```python
# 신규 상수. 현재 known 6 + unknown 1 = 7, v0.5.0 이후 known 7 + unknown 1 = 8.
PURPOSE_LLM_ROUTER = 'llm_router'

ALL_PURPOSES: FrozenSet[str] = frozenset({
    PURPOSE_SINGLE_SHOT_ANSWER,
    PURPOSE_QUERY_REWRITER,
    PURPOSE_WORKFLOW_EXTRACTOR,
    PURPOSE_WORKFLOW_TABLE_LOOKUP,
    PURPOSE_AGENT_STEP,
    PURPOSE_AGENT_FINAL,
    PURPOSE_LLM_ROUTER,   # 신규
    PURPOSE_UNKNOWN,
})
```

> 실제 코드의 멤버십 집합 이름은 `ALL_PURPOSES` (frozenset). 다른 모듈에서
> 멤버십 검사할 일이 생기면 `validate_purpose(...)` helper 가 표준 진입점이다.

### F. Dashboard 라벨 — `bo/views/dashboard.py:30-38`

```python
_PURPOSE_LABELS = {
    'single_shot_answer': '단발 응답',
    'query_rewriter': '쿼리 재작성',
    'workflow_extractor': '워크플로 추출',
    'workflow_table_lookup': '워크플로 표 조회',
    'agent_step': '에이전트 단계',
    'agent_final': '에이전트 최종',
    'llm_router': 'LLM 라우터',   # 신규
    'unknown': '알 수 없음',
}
```

---

## 프롬프트 초안 — `assets/prompts/chat/llm_router.md`

```
사용자 질문을 3가지 의도 중 하나로 분류하세요.

- single_shot: 사실/정의/조회 질문. 자료 검색 후 단발 답변으로 충분.
- workflow: 정형 계산·산정. 날짜 차이, 금액 합계, 표 조회 등 결정적 절차.
- agent: 비교·추천·예외·가설 시뮬레이션. 탐색 또는 도구 호출 필요.

JSON 으로만 출력:
{"route": "single_shot|workflow|agent", "reason": "한 줄 근거"}

workflow_key 는 출력하지 마세요. 운영자가 BO RouterRule 로 매핑합니다.
이전 대화가 주어지면 의도 판단에만 참고하세요.
```

---

## 검증

### 단위 테스트 (`chat/tests/test_llm_router.py`)

**분류 정상 경로** (반환 타입은 `LlmRouteResult`)
- `test_llm_classify_returns_single_shot_for_definition`
- `test_llm_classify_returns_workflow_for_calculation`
- `test_llm_classify_returns_agent_for_comparison`

**LLM 출력 검증 계약 (각 케이스 모두 `None` 반환 → keyword fallback)**
- `test_llm_classify_handles_invalid_json` — `text="not json"` → None
- `test_llm_classify_rejects_non_object_json` — `text="[1,2,3]"`, `"null"`, `"\"x\""` → None
- `test_llm_classify_rejects_unknown_route` — `{"route":"chitchat"}` 등 `ALL_ROUTES` 밖 값 → None
- `test_llm_classify_rejects_missing_route` — `{}` / `{"reason":"x"}` → None
- `test_llm_classify_trims_reason` — 양옆 공백 strip
- `test_llm_classify_truncates_long_reason` — 길이 > 120 → 120 으로 잘림
- `test_llm_classify_drops_workflow_key_from_llm` — LLM 출력에 `workflow_key='date_calculation'` 가 와도 반환되는 `LlmRouteResult` 는 해당 필드를 안 가지며, `route_question` 이 변환한 `RouteDecision.workflow_key == ''`
- `test_llm_classify_accepts_non_string_reason` — `reason=null/123` → 빈 reason, 그래도 `LlmRouteResult` 반환

**순환 import 회피 smoke**
- `test_module_imports_without_route_decision` — `from chat.services import llm_router`
  단독으로 import 가능하고, 모듈 어디에도 `RouteDecision` 심볼이 노출되어
  있지 않음 (`assert not hasattr(llm_router, 'RouteDecision')`).

**Token usage 기록 계약**
- `test_llm_classify_records_token_usage_with_llm_router_purpose` —
  `run_chat_completion` 과 `record_token_usage` 를 mock 한 상태에서
  `_llm_classify('...', [])` 를 호출하면, `record_token_usage` 가 정확히
  1회 호출되고 호출 인자가 `(<mock_model>, <mock_usage>,
  purpose=PURPOSE_LLM_ROUTER)` 임을 단언 (call-site purpose 회귀 보호).

**라우터 통합** (`LlmRouteResult` → `RouteDecision` 변환 확인 포함)
- `test_route_question_falls_back_to_keyword_on_llm_failure` — LLM 예외 mock → 키워드 라우팅 진행
- `test_route_question_falls_back_when_llm_returns_none` — `_llm_classify` 가 None 반환 시 키워드 fallback
- `test_route_question_db_rule_overrides_llm` — DB rule 매치 시 LLM 호출 X (mock 호출 카운트 0)
- `test_route_question_passes_history_through` — history 가 LLM 에 전달되는지
- `test_route_question_converts_llm_result_to_route_decision` — `_llm_classify` 가 `LlmRouteResult(route='agent', reason='llm:hypothesis')` 를 반환하면 `RouteDecision(route='agent', reason='llm:hypothesis', workflow_key='')` 로 변환되는지

**DATE_CONDITION 우선순위 보호 (LLM 호출 0 보장)**
- `test_date_condition_keyword_skips_llm_call` — `'급여 지급일은?'` 입력 시 LLM mock 호출 카운트 == 0 + `route == agent`, `reason == 'date_condition_keyword'`
- `test_date_condition_skips_llm_even_when_llm_would_return_workflow` — LLM mock 이 `workflow` 를 돌려주도록 stub 해도 `route == agent` 유지 (Tier 2 가 Tier 3 보다 먼저)
- `test_date_condition_keywords_each_skip_llm` — `지급일`/`만료일`/`정산일`/`마감일` 4개 키워드 각각에 대해 LLM 미호출
- `test_db_rule_still_overrides_date_condition` — DB rule (`pattern='지급일', route='workflow'`) 이 있으면 Tier 1 이 먼저 (회귀 보호 계약이 DB override 를 막지 않음 확인)

### e2e 시나리오 (브라우저)

| # | 시나리오 | 현재 | v0.5.0 목표 |
|---|---|---|---|
| S1 | "경조사" → "비싼거" | 회귀 가능성 | 본인 상 500만 (rewriter 효과 검증) |
| **S2** | "경조사" → "이거 말고 더 있을건데?" | 자료 없음 | "보여드린 게 전부입니다" |
| S3 | "본인 결혼?" → "자녀는?" | 무관 검색 | 자녀 결혼 경조금 |
| S4 | "퇴직금 계산식?" (자립) | 정상 | 정상 (NOOP) |
| S5 | 첫 질문 (history=[]) | 정상 | 정상 (rewriter skip) |
| **S6** | "퇴직금 비교 vs 계산 vs 정의" | 키워드 우연 | LLM route 별 분기 (reason=llm:...) |
| **S7** | "만약 5년 근무하면?" (#76) | ❌ | LLM 이 agent 로 분류 |

> S1~S5 는 rewriter 이미 동작 중이라 **v0.5.0 시작 전 baseline 확인**.
> S6~S7 가 v0.5.0 LLM Router 의 신규 검증 포인트.

### 회귀 보호
- 기존 라우팅 e2e 테스트 (`chat/tests/test_routing_e2e.py`) 전부 통과.
  **계약**: 이 파일은 `route_question()` 을 직접 호출하므로 Tier 3 LLM 분기
  추가 후에는 default/keyword fallback 케이스가 실제 LLM 네트워크 호출을
  시도할 수 있다. 본 PR 에서 다음을 적용:
  - `chat.services.llm_router._llm_classify` 를 `None` 반환으로 고정하는
    mock (모듈 fixture / `setUp` patch / context manager 중 택일). 기본
    권장은 모듈 단위 `patch('chat.services.question_router._llm_classify',
    return_value=None)` — 기존 단언이 키워드/DB rule/DATE_CONDITION/default
    중 하나로 떨어지도록 그대로 두고, LLM tier 만 비활성.
  - 특정 케이스에서 LLM 분기 자체를 검증해야 한다면 mock 의 `return_value`
    를 해당 케이스에 한해 `LlmRouteResult(route=..., reason='llm:...')` 로
    바꾸는 `with patch(...)` 블록을 사용.
  - **네트워크/`OPENAI_API_KEY` 없이 그린이어야 함** — CI 와 로컬 모두
    오프라인에서 `python manage.py test chat.tests.test_routing_e2e` 통과가
    합격선. 환경변수 미설정 상태로 회귀 확인.
- DATE_CONDITION (v0.4.2 / #73) 단순·충돌 케이스에서 **LLM 호출 0** 보장
  (위 단위 테스트의 `test_date_condition_keyword_skips_llm_call` 계열)
- WORKFLOW / AGENT 키워드 fallback 동작 유지
- LLM 호출 mock 으로 막은 상태에서 모든 기존 라우팅 결정 동일
- `chat/tests/test_token_purpose.py` — `ALL_PURPOSES` 크기 7 → 8 갱신 +
  `PURPOSE_LLM_ROUTER` 멤버십 단언 추가, 테스트 이름도
  `test_total_count_is_seven` → `test_total_count_is_eight`,
  `test_known_six_purposes_are_members` → `test_known_seven_purposes_are_members`
  로 함께 변경 후 그린
- BO dashboard 라벨/observed-only 노출 테스트에 `llm_router` → `LLM 라우터` 매핑
  검증 1줄 추가 후 그린
- `_llm_classify` 호출 시 `record_token_usage` 가 `purpose=PURPOSE_LLM_ROUTER`
  로 정확히 1회 호출되는지 검증 (단위 테스트의
  `test_llm_classify_records_token_usage_with_llm_router_purpose`) — purpose
  타이핑/누락 회귀 차단

---

## 비용

| 항목 | 회당 비용 (gpt-4o-mini) |
|---|---|
| 메인 응답 (기존) | $0.0007 |
| Query rewriter (기존, history 비면 skip) | $0.00012 |
| **LLM Router (신규, DB rule 매치 시 skip)** | **$0.00012** |
| 질문당 증가 | +$0.00012 (DB rule 미매치 시) |

- Skip 조건: DB rule 매치 시 LLM 호출 0
- Aux model 분리로 메인 응답 비용 영향 0
- BO dashboard 에서 일자별 실측 (이미 운영 중)

---

## 리스크 & 대응

| 리스크 | 대응 |
|---|---|
| LLM 이 DATE_CONDITION 케이스를 workflow/single_shot 으로 오분류 → calendar 도구 라우팅 깨짐 (#73 회귀) | **Tier 2 에서 DATE_CONDITION_KEYWORDS 가 LLM 보다 먼저 매치**, 단위 테스트로 LLM 호출 0 보장 |
| LLM 라우터 일반 오분류 | DB RouterRule 우선 + 키워드 fallback |
| LLM 이 `ALL_ROUTES` 밖 라벨 (`"chitchat"`) 반환 → LangGraph conditional edge 가 깨짐 | `_parse_and_validate` 가 `route in ALL_ROUTES` 검사 → 위반 시 None → 키워드 fallback |
| LLM 이 workflow_key 를 들고 옴 (hallucination) | 출력에서 workflow_key 필드 무시, `LlmRouteResult` 에 해당 필드 없음 → `route_question` 변환 단계에서 `RouteDecision.workflow_key=''` 강제 |
| `llm_router.py` ↔ `question_router.py` 순환 import (`RouteDecision` 양방향 참조) | llm_router 는 `RouteDecision` 을 import 하지 않고 neutral `LlmRouteResult` 만 반환, 변환 책임을 question_router 가 전담. import smoke 테스트로 회귀 차단 |
| 기존 `test_routing_e2e.py` 가 실제 LLM 네트워크 호출 시도 (API key 없는 환경에서 빨강) | 해당 파일에서 `_llm_classify` 를 `None` 반환 mock 으로 고정 — 네트워크/API key 없이 그린 합격선 |
| `run_chat_completion()` 시그니처 변경 → 호출처 회귀 | grep 으로 호출처 전수 확인 + 기존 호출 인자 없이 동작 보장 |
| `OPENAI_AUX_MODEL` 미설정 | `OPENAI_MODEL` 폴백, 별도 설정 강제 X |
| LLM 출력 JSON 파싱 실패 / 비-object | None 반환 → 키워드 fallback |
| LLM 응답 시간 +500ms | aux model 은 mini 고정 |
| `route_question` 시그니처 변경 → 기존 테스트 회귀 | history 디폴트 `None`/`[]` 로 호환 |
| 운영 중 비용 폭증 | 기존 dashboard 의 purpose 별 집계로 1주 관측 후 튜닝 |
| Rewriter 가 이미 있는데 메타-요청 (S2) 가 여전히 깨지는 경우 | rewriter 프롬프트 BO 편집으로 1차 대응 → 부족하면 v0.5.x 에서 logic 보강 |

---

## git-flow

- **Milestone**: `v0.5.0: LLM Router & Context-Aware Retrieval` (신규 생성)
- **Issue 이동**: 기존 #76 / #77 을 `0.x Maintenance` → `v0.5.0` 으로
- **신규 트래킹 이슈**: Phase 9-1 / 9-2 (각각 1개)
- **Branch**: `feature/#<issue>-llm-router` (9-1), `chore/#<issue>-v0_5_0-polish` (9-2)
- **PR 순서**: 9-1 → 9-2, 각 PR develop 머지
- **Release**: 두 Phase 완료 + e2e 검증 통과 후 develop → main 단발 머지 + `v0.5.0` 태그
- **Hotfix**: 운영 중 발견 시 `0.x Maintenance` 마일스톤에 별도 등록 (v0.5.0 마일스톤 오염 방지)

---

## 실행 순서

### Pre-flight
1. `chat/services/query_rewriter.py` 가 의도대로 동작하는지 baseline 확인
   - S1, S2, S3 브라우저 시나리오 먼저 돌려보기
   - 이미 잘 되면 v0.5.0 가치는 S6, S7 (LLM Router) 에 집중

### Phase 9-1 검증
1. `python manage.py check`
2. `python manage.py test chat.tests.test_llm_router` (정상 경로 + 검증 계약 + import smoke + token usage `purpose=PURPOSE_LLM_ROUTER` 호출 검증)
3. `python manage.py test chat.tests.test_token_purpose`
   (`ALL_PURPOSES` 크기 7 → 8, 테스트명 `eight`/`seven` 으로 리네임된 케이스 그린)
4. `unset OPENAI_API_KEY && python manage.py test chat.tests.test_routing_e2e`
   — `_llm_classify` mock 으로 네트워크/API key 없이 그린 (회귀)
5. `python manage.py test bo` (dashboard 라벨/observed-only 노출 테스트 그린)
6. 브라우저 S6, S7 시나리오 + 로그에 `llm:...` reason 확인
7. 브라우저로 `급여 지급일은?` 재확인 — `reason == 'date_condition_keyword'`,
   BO dashboard 의 `LLM 라우터` purpose 카운트 증가 없음

### Phase 9-2 검증
1. 전체 시나리오 (S1~S7) 통과
2. BO dashboard 에서 `llm_router` 라인 노출 + 토큰/비용 집계
3. dev log 작성
4. README §3, §11 업데이트

---

## Out of Scope (명시)

- **v0.5.x 후보** (운영 데이터 보고 결정):
  - Rewriter 가 메타-요청에 부족할 시 logic 보강
  - Combined router + rewriter 단일 호출
  - 페이지네이션 / 이미 본 청크 제외
  - 청킹 전략 재검토
- **v0.6.0 후보** (메모리 기록): ReRank, 하이브리드 검색 (Postgres FTS or OpenSearch 이관)
- **항구 제외**: Streaming, prompt caching, 멀티 LLM provider 추상화

---

## 참조

- `chat/services/query_rewriter.py` — 이미 존재 (152줄), `rewrite_query_with_history()` 동작 중
- `chat/services/question_router.py:120` — `route_question()` 진입점
- `chat/services/question_router.py:46-48` — `DATE_CONDITION_KEYWORDS` (v0.4.2 회귀 보호 대상)
- `chat/graph/routes.py` — `ALL_ROUTES` (LLM 출력 검증에 사용)
- `chat/graph/nodes/router.py:28` — 호출부 (history 미전달 — 수정 대상)
- `chat/graph/nodes/workflow.py:44-49` — `workflow_key=''` → single_shot 폴백 (회귀 0 근거)
- `chat/services/single_shot/llm.py:19-41` — `run_chat_completion()` (시그니처 확장 대상)
- `chat/services/single_shot/postprocess.py` — `record_token_usage(model, usage, purpose=...)` (LLM Router 호출 사이트의 purpose 기록 진입점)
- `chat/services/prompt_loader.py` — `load_prompt(relative_path)` API (코드에 실제로 존재하는 진입점)
- `chat/services/prompt_registry.py` — `PromptEntry` 등록 패턴 (`relative_path='chat/...'`)
- `chat/services/token_purpose.py:25-67` — `PURPOSE_*` 상수 + `validate_purpose()`
- `chat/tests/test_token_purpose.py` — `ALL_PURPOSES` 크기/멤버십 박힌 단언 (수정 대상: count + 테스트명 리네임)
- `chat/tests/test_routing_e2e.py` — `route_question()` 직접 호출 (수정 대상: `_llm_classify` mock 도입, 오프라인 그린)
- `chat/models.py:117` — `TokenUsage.purpose` 필드 (이미 운영)
- `bo/views/dashboard.py:30-85` — purpose 별 집계 + 한국어 라벨 (이미 운영)
- 메모리: `project_v0_5_0_llm_router.md` — 작업 전제
- 메모리: `project_v0_6_0_search_quality.md` — 다음 후보
