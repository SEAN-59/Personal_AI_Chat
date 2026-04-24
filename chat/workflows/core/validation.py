"""workflow 입력 검증 헬퍼 (Phase 5).

`ValidationResult` 만 import 한다. dates/numbers/formatting 은 사용하지 않음
— 의존 방향(`result ← validation ← ... ← base`) 유지.

정책 (Phase 5 §3):
- 사용자 입력 문제는 `ValidationResult.fail(...)` 로 반환
- 프로그래밍 오류(인자 자료형이 mapping 이 아닌 등)는 `TypeError` / `ValueError`
"""

from __future__ import annotations

from typing import Any, Iterable, Mapping

from chat.workflows.core.result import ValidationResult


# ---------------------------------------------------------------------------
# 공개 API
# ---------------------------------------------------------------------------

def require_fields(data: Mapping[str, Any], fields: Iterable[str]) -> ValidationResult:
    """`data` 에 `fields` 가 모두 있고 값이 비어 있지 않은지 검사.

    빠진 필드나 '비어 있다고 간주되는 값' 을 가진 필드를 모두 모아
    `missing_fields` 에 담아 반환. 모두 OK 면 `.success()`.

    '비어 있다' 의 기준:
    - key 자체가 없음
    - 값이 `None`
    - 값이 문자열이고 양쪽 공백 제거 후 길이 0
    """
    if not isinstance(data, Mapping):
        raise TypeError(
            f'require_fields: data 는 Mapping 이어야 합니다 (got {type(data).__name__})'
        )

    missing: list[str] = []
    for field_name in fields:
        if field_name not in data:
            missing.append(field_name)
            continue
        if _is_empty(data[field_name]):
            missing.append(field_name)

    if missing:
        return ValidationResult.fail(missing=missing)
    return ValidationResult.success()


def require_non_empty(value: Any, field_name: str) -> ValidationResult:
    """단일 값이 비어 있지 않은지 검사."""
    if not field_name:
        raise ValueError('require_non_empty: field_name 이 비어 있습니다.')
    if _is_empty(value):
        return ValidationResult.fail(missing=[field_name])
    return ValidationResult.success()


def combine_validations(*results: ValidationResult) -> ValidationResult:
    """여러 `ValidationResult` 를 하나로 합친다.

    - 모두 ok → success
    - 하나라도 실패 → missing_fields / errors 를 순서대로 이어 붙여 fail
    - 같은 missing 필드가 중복되면 첫 출현만 남긴다 (순서 보존)
    """
    if not results:
        return ValidationResult.success()

    if all(r.ok for r in results):
        return ValidationResult.success()

    missing: list[str] = []
    errors: list[str] = []
    for r in results:
        for m in r.missing_fields:
            if m not in missing:
                missing.append(m)
        for e in r.errors:
            if e not in errors:
                errors.append(e)

    if not missing and not errors:
        # 모든 실패가 빈 missing/errors 인 건 상위 실수지만 방어.
        return ValidationResult.fail(errors=['validation failed'])

    return ValidationResult.fail(missing=missing, errors=errors)


# ---------------------------------------------------------------------------
# 내부
# ---------------------------------------------------------------------------

def _is_empty(value: Any) -> bool:
    if value is None:
        return True
    if isinstance(value, str) and not value.strip():
        return True
    return False
