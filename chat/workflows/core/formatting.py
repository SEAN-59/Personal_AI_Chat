"""workflow 결과를 표시용 문자열로 바꾸는 helper (Phase 5).

의존 없음 (core 다른 모듈 import 안 함). 순수 함수.

범위 (Phase 5 §6):
- 개별 값(금액 / 날짜 / 기간)을 자연스러운 표시 문자열로.
- 자연어 답변 조립("평균 급여는 ~원 입니다") 은 response layer 책임.
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Optional, Union


DateLike = Union[str, date, datetime]


# ---------------------------------------------------------------------------
# 공개 API
# ---------------------------------------------------------------------------

def format_currency(value: int) -> str:
    """`1234567` → `"1,234,567원"`.

    정수만 허용. 실수·문자열은 호출측이 `parse_money` 로 먼저 정규화.
    """
    if isinstance(value, bool):
        raise TypeError('format_currency: bool 은 받지 않습니다.')
    if not isinstance(value, int):
        raise TypeError(
            f'format_currency: int 이어야 합니다 (got {type(value).__name__})'
        )
    return f'{value:,}원'


def format_date(value: DateLike) -> str:
    """`date`/`datetime` 또는 ISO 문자열을 `YYYY-MM-DD` 로 정규화해 반환.

    문자열 입력의 경우 내부 파서를 쓰지 않고 ISO 형식만 안전하게 받는다.
    parse_date 의 다양한 포맷을 지원받고 싶으면 호출측이 먼저 date 로 바꿔서
    넘기는 게 원칙 (core 모듈 간 의존 방향 유지).
    """
    if isinstance(value, datetime):
        return value.date().isoformat()
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, str):
        # 이미 'YYYY-MM-DD' 로 정돈된 문자열만 통과. 그 외는 호출측 책임.
        try:
            parsed = date.fromisoformat(value)
        except ValueError as exc:
            raise ValueError(
                f'format_date: ISO 형식이 아닙니다 ({value!r})'
            ) from exc
        return parsed.isoformat()
    raise TypeError(
        f'format_date: date / datetime / ISO str 중 하나여야 합니다 (got {type(value).__name__})'
    )


def format_duration(
    *,
    years: Optional[int] = None,
    months: Optional[int] = None,
    days: Optional[int] = None,
) -> str:
    """년·월·일 단위를 "1년 2개월 3일" 같은 문자열로 합침.

    - 모두 `None` 이면 빈 문자열.
    - `0` 은 명시적으로 표기하지 않는다 (의미 없는 "0일" 제거).
    - 음수는 허용 — 호출측이 부호가 필요하면 그대로 반영된다.
    """
    parts: list[str] = []
    if years not in (None, 0):
        parts.append(f'{years}년')
    if months not in (None, 0):
        parts.append(f'{months}개월')
    if days not in (None, 0):
        parts.append(f'{days}일')
    return ' '.join(parts)
