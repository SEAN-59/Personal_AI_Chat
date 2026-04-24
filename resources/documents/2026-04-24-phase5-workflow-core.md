# 2026-04-24 개발 로그 — 2.0.0 Phase 5: Workflow Core

## 배경

Phase 3 에서 `chat/workflows/{core,domains}/__init__.py` 뼈대만 만들고 비워뒀다. Phase 4(라우팅 Core → BO Router Rule → Retrieval Contextualization → OpenAI 사용량 위젯) 를 마친 지금, 실제 도메인 workflow 를 올리기 전에 **범용 계산·정규화·검증·포맷팅 엔진** 을 먼저 깔아둔다.

공용 엔진 없이 도메인부터 쓰면 곧바로 "함수 안에 회사 규정이 섞이는" 오염 패턴이 나타난다. Phase 5 는 이걸 원천 차단하는 단계 — 서비스 레이어 라이브러리 추가만 하고 graph / view / BO / DB 는 건드리지 않는다 (회귀 0).

---

## 1. 패키지 구조

```
chat/workflows/core/
  __init__.py        # 공개 API 재노출
  result.py          # ValidationResult / WorkflowResult / WorkflowStatus
  validation.py      # require_fields / require_non_empty / combine_validations
  dates.py           # parse_date / days·months·years_between / ensure_date_order
  numbers.py         # parse_int_like / parse_money / sum_amounts / average_amount
  formatting.py      # format_currency / format_date / format_duration
  base.py            # BaseWorkflow (Protocol) + run_workflow

chat/tests/
  test_workflows_result.py
  test_workflows_validation.py
  test_workflows_dates.py
  test_workflows_numbers.py
  test_workflows_formatting.py
  test_workflows_base.py
```

**의존 방향(엄격 일방향)**

```
result ← validation / dates / numbers / formatting ← base
```

- `result.py` 는 다른 core 모듈 import 금지 (순환 차단 · 재사용성 확보)
- `validation.py` 는 `result.ValidationResult` 만 import
- `dates.py` / `numbers.py` / `formatting.py` 는 서로 import 하지 않음 — 조합이 필요하면 호출부에서
- `base.py` 는 네 모듈 위에서 4단계 계약을 엮음

---

## 2. 공통 반환 타입

### 2-1. `ValidationResult` (입력 단계, 내부용)

```python
@dataclass(frozen=True)
class ValidationResult:
    ok: bool
    missing_fields: tuple[str, ...] = ()
    errors: tuple[str, ...] = ()

    @classmethod
    def success(cls): ...
    @classmethod
    def fail(cls, *, missing=(), errors=()): ...  # 둘 다 비면 ValueError
```

`frozen=True` · tuple 필드로 **불변·해시 가능**. 합성·로그·DB 저장 안전.

### 2-2. `WorkflowStatus` + `WorkflowResult` (최종 반환형)

```python
class WorkflowStatus(str, Enum):
    OK = 'ok'
    MISSING_INPUT = 'missing_input'
    INVALID_INPUT = 'invalid_input'
    UNSUPPORTED = 'unsupported'


@dataclass(frozen=True)
class WorkflowResult:
    status: WorkflowStatus
    value: Any = None
    details: Mapping[str, Any] = ...   # MappingProxyType 으로 read-only 고정
    missing_fields: tuple[str, ...] = ()
    warnings: tuple[str, ...] = ()
```

팩토리 4개(`ok` / `missing_input` / `invalid_input` / `unsupported`) 가 각 상태의 "자연스러운 모양" 을 강제한다. 문자열 enum 상속이라 JSON / 로그 / DB 어디든 `"ok"` 값 그대로 쓰인다.

---

## 3. 검증 정책 (경계선)

| 상황 | 처리 방식 | 예 |
|---|---|---|
| 사용자 입력 부족·형식 오류 | `ValidationResult.fail(...)` | 입사일 누락 |
| 도메인 규칙 어긋남 (시작일 > 종료일) | `ValidationResult.fail(errors=[...])` | 계약 날짜 역순 |
| 프로그래밍 오류 (타입 깨짐, 구조 손상) | `raise TypeError` / `ValueError` | `parse_date(None)`, `require_fields(list, ...)` |

즉 **사용자가 고칠 수 있는 문제 → 검증 결과 객체**, **코드가 틀린 문제 → 예외**. `base.run_workflow` 가 이 규약을 받아 `ValidationResult` 를 `WorkflowResult` 로 자동 번역한다:

- `missing_fields` 가 있음 → `WorkflowResult.missing_input(...)`
- `errors` 만 있음 → `WorkflowResult.invalid_input(...)`

---

## 4. 날짜 파싱 범위

지원:
- `2025-01-31`, `2025.01.31`, `2025/01/31`
- 2자리 연도: `25-01-31` → 2025-01-31
- 한국어 자연어: `2025년 1월 31일` / `2025년 01월 31일`
- `date` / `datetime` 인스턴스 그대로

미지원 (Phase 6 이후):
- 상대 표현(`오늘`, `어제`)
- 타임존 포함 문자열
- 한자 연월 표기

기간 계산(`months_between`, `years_between`)은 **anchor day** 규칙 — 하루라도 모자라면 한 단위 덜 카운트. 예: 2020-05-10 → 2025-05-09 은 4년.

---

## 5. 숫자 파싱 범위

지원:
- 콤마 제거: `"1,234,567"` → 1234567
- 단위 접미어 하나: `"1,234원"`, `"3개월"`, `"5년"`, `"30일"`
- 부호: `"+42"`, `"-42"`
- `int` 그대로 통과

거부:
- `bool` → `TypeError` (int 서브클래스지만 의미상 숫자 아님)
- `3.14` 같은 실수
- 빈 문자열 / 비숫자 문자열
- 한글 수사(`천만`), 통화 접두어(`$`, `₩`)

`parse_money` 는 현재 `parse_int_like` 의 얇은 alias. Phase 6 에서 돈 전용 규칙(예: 음수 거부) 이 붙을 자리.

`average_amount` 는 **항상 `float`** 반환 — 정수 나눗셈 절삭으로 발생하는 계산 오차를 피하려는 의도.

---

## 6. BaseWorkflow — Protocol + run_workflow

```python
@runtime_checkable
class BaseWorkflow(Protocol):
    def prepare(self, raw): ...
    def validate(self, normalized): ...
    def execute(self, normalized): ...


def run_workflow(workflow, raw) -> WorkflowResult:
    normalized = workflow.prepare(raw)
    validation = workflow.validate(normalized)
    if not validation.ok:
        if validation.missing_fields:
            return WorkflowResult.missing_input(...)
        return WorkflowResult.invalid_input(...)
    return workflow.execute(normalized)
```

`typing.Protocol` 로 정의했기 때문에 **상속 불필요** — 도메인 workflow 는 세 메서드만 갖추면 `isinstance(obj, BaseWorkflow)` 가 True 다 (`@runtime_checkable`). 함수 조합형 workflow 도 허용.

러너는 타입 계약 위반(`prepare` 가 Mapping 이 아닌 걸 반환 등)을 `TypeError` 로 즉시 드러낸다. 도메인 구현이 실수로 잘못된 타입을 반환해도 디버깅이 쉬움.

---

## 7. 공개 API (재노출)

`chat/workflows/core/__init__.py` 에서 모든 helper·타입을 한 지점에 모았다:

```python
from chat.workflows.core import (
    ValidationResult, WorkflowResult, WorkflowStatus,
    combine_validations, require_fields, require_non_empty,
    parse_date, days_between, months_between, years_between, ensure_date_order,
    parse_int_like, parse_money, sum_amounts, average_amount,
    format_currency, format_date, format_duration,
    BaseWorkflow, run_workflow,
)
```

Phase 6 도메인 구현이 내부 모듈을 직접 import 해도 동작은 하지만, 위 re-export 를 쓰는 게 안정적(향후 core 내부 구조 변경에 영향받지 않음).

---

## 8. 테스트

총 **85 케이스** / 6 파일. 모두 `SimpleTestCase` (DB 불필요 · 빠름).

| 파일 | 케이스 | 주요 커버 |
|---|---|---|
| `test_workflows_result.py` | 12 | factory / 불변성 / 해시 / Mapping read-only |
| `test_workflows_validation.py` | 15 | missing 누적 / errors 누적 / 중복 제거 / 0·False 처리 |
| `test_workflows_dates.py` | 29 | 3 구분자 × 2자리 연도 × 한국어 / anchor day / 역순 |
| `test_workflows_numbers.py` | 23 | 콤마 / 단위 4종 / 부호 / bool 거부 / 평균 |
| `test_workflows_formatting.py` | 17 | 천단위 / ISO 날짜 / `0` 스킵 / 음수 |
| `test_workflows_base.py` | 9 | Protocol 검사 / 4단계 러너 / 각 단계 타입 계약 |

```
Ran 114 tests in 0.028s   # 기존 tests 포함 전체
OK
```

---

## 9. 검증

### 자동
- `docker compose exec -T web python manage.py check` — 이슈 없음
- `docker compose exec -T web python manage.py test chat.tests` — 전체 114 건 통과

### 수동
- `python -c "from chat.workflows.core import ValidationResult, WorkflowResult, parse_date, format_currency, run_workflow"` 성공
- REPL: `parse_date("2025년 1월 31일")` → `date(2025, 1, 31)`
- REPL: `format_duration(years=1, months=2, days=3)` → `"1년 2개월 3일"`

### 회귀 민감 포인트
- `chat/services/single_shot/*`, `chat/graph/*`, BO, migration **무변경** → 기존 채팅 경로 동작 동일
- 마이그레이션 신규 없음

---

## 10. 남은 작업 / Out of Scope (Phase 6 이후)

- 도메인 workflow 실체화 (퇴직금 / 연차 / 근속 / 평균 급여 / 수당)
- LangGraph `workflow_node` 를 single_shot 포워딩에서 실제 디스패처로 교체
- BO 에 workflow 실행 로그 · 실패 케이스 뷰어
- agent ReAct / tool calling 루프
- 한글 수사(`천만`), 통화 변환, 세금 · 공제 계산
- 상대 날짜(`오늘`, `어제`) / 타임존 처리
- LLM 을 끼우는 helper (core 는 순수 함수 원칙)
- `WorkflowInput` 포괄 타입 — 도메인 요구가 나온 뒤 정의

---

## 11. 완료 정의 (Definition of Done) 충족 여부

- [x] `chat/workflows/core/` 6 모듈 전부 구현
- [x] 공개 API 가 `__init__.py` 에서 재노출
- [x] 테스트 85 케이스 green (전체 114/114 통과)
- [x] `ValidationResult` / `WorkflowResult` / `BaseWorkflow` 가 README §3-1 에 명시
- [x] 의존 방향(§1) · 검증 경계선(§3) 이 dev log 에 기록
- [x] single-shot 파이프라인 / graph / BO 무변경 (회귀 0)
