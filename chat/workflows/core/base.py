"""Workflow 공통 실행 계약 (Phase 5).

`BaseWorkflow` 는 `typing.Protocol` 로만 정의한다 — 도메인 구현이 상속할
필요가 없고, 클래스 기반이든 함수 기반이든 네 단계 메서드를 갖추기만 하면
된다. `run_workflow(workflow, raw)` 는 네 단계를 엮어주는 레퍼런스 러너:

    prepare  → 입력 정규화
    validate → 검증 (ValidationResult)
    execute  → 실제 계산 (WorkflowResult)

validate 가 실패하면 `execute` 를 돌리지 않고 검증 결과를 그대로
`WorkflowResult` 로 번역해 반환한다. 도메인 workflow 가 이 러너를 직접
쓰면 검증 스타일(fail 은 missing vs errors)이 자동으로 일관화된다.

import 는 result 모듈만. dates/numbers/validation/formatting 은 base 의
계약 밖이라 여기서 건드리지 않는다 (필요하면 도메인 workflow 가 직접 import).
"""

from __future__ import annotations

from typing import Any, Mapping, Protocol, runtime_checkable

from chat.workflows.core.result import (
    ValidationResult,
    WorkflowResult,
    WorkflowStatus,
)


@runtime_checkable
class BaseWorkflow(Protocol):
    """4단계 계약을 만족하는 모든 객체.

    상속은 필요 없다 — 아래 세 메서드만 존재하면 도메인 workflow 로 인정.
    """

    def prepare(self, raw: Mapping[str, Any]) -> Mapping[str, Any]:
        """raw 입력을 정규화된 dict 로 바꿔 반환."""
        ...

    def validate(self, normalized: Mapping[str, Any]) -> ValidationResult:
        """정규화된 입력이 계산하기에 충분한지 검사."""
        ...

    def execute(self, normalized: Mapping[str, Any]) -> WorkflowResult:
        """검증을 통과한 입력으로 실제 계산."""
        ...


def run_workflow(
    workflow: BaseWorkflow,
    raw: Mapping[str, Any],
) -> WorkflowResult:
    """prepare → validate → execute 순서를 엮는 레퍼런스 러너.

    동작:
    - `validate` 가 fail 이면 `missing_fields` 가 있으면 MISSING_INPUT,
      아니면 INVALID_INPUT 으로 번역해 반환. execute 는 호출하지 않는다.
    - `validate` 가 success 면 `execute` 결과를 그대로 돌려준다.
    """
    if not isinstance(workflow, BaseWorkflow):
        raise TypeError(
            'run_workflow: prepare / validate / execute 세 메서드가 필요합니다.'
        )

    normalized = workflow.prepare(raw)
    if not isinstance(normalized, Mapping):
        raise TypeError(
            'run_workflow: prepare 는 Mapping 을 반환해야 합니다 '
            f'(got {type(normalized).__name__}).'
        )

    validation = workflow.validate(normalized)
    if not isinstance(validation, ValidationResult):
        raise TypeError(
            'run_workflow: validate 는 ValidationResult 를 반환해야 합니다 '
            f'(got {type(validation).__name__}).'
        )

    if not validation.ok:
        if validation.missing_fields:
            return WorkflowResult.missing_input(
                missing_fields=validation.missing_fields,
            )
        return WorkflowResult.invalid_input(
            errors=validation.errors or ('validation failed',),
        )

    result = workflow.execute(normalized)
    if not isinstance(result, WorkflowResult):
        raise TypeError(
            'run_workflow: execute 는 WorkflowResult 를 반환해야 합니다 '
            f'(got {type(result).__name__}).'
        )
    return result


__all__ = [
    'BaseWorkflow',
    'run_workflow',
    # result 모듈에서 올라온 API 를 base 를 통해서도 한 눈에 볼 수 있게 re-export.
    'ValidationResult',
    'WorkflowResult',
    'WorkflowStatus',
]
