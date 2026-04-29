"""workflow 용 숫자·금액 정규화 및 집계 (Phase 5).

의존 없음 (core 다른 모듈 import 안 함). 순수 함수.

파싱 규칙 (Phase 5 §5):
- 콤마 / 공백 제거
- 한국어 단위 접미어 중 하나(`원` / `개월` / `년` / `일`) 뒤에 붙은 건 제거
- 부호(`-`, `+`)는 허용
- 실수·한글 수사(천만, 3억)·통화 접두어는 out-of-scope

오류는 `ValueError` — 도메인에서 `ValidationResult.fail` 로 번역한다.
"""

from __future__ import annotations

import re
from typing import Iterable, Union


Number = Union[int, str]


# 후행 단위 접미어 하나를 잘라내는 정규식. 다중 단위("5년3개월")는 지원하지 않음.
_TRAILING_UNIT = re.compile(r'(원|개월|년|일)$')


# ---------------------------------------------------------------------------
# 공개 API
# ---------------------------------------------------------------------------

def parse_int_like(value: Number) -> int:
    """정수처럼 생긴 입력을 `int` 로 정규화.

    지원: `int`, `"123"`, `"1,234"`, `"1,234원"`, `" -50 "`, `"3개월"`, `"+42"`.
    실패: `ValueError`.
    """
    if isinstance(value, bool):
        # bool 은 int 서브클래스지만 의미상 "숫자" 가 아님 — 프로그래밍 오류로 취급.
        raise TypeError('parse_int_like: bool 은 숫자로 받지 않습니다.')
    if isinstance(value, int):
        return value
    if not isinstance(value, str):
        raise TypeError(
            f'parse_int_like: int 또는 str 이어야 합니다 (got {type(value).__name__})'
        )

    text = value.strip()
    if not text:
        raise ValueError('parse_int_like: 빈 문자열은 숫자가 아닙니다.')

    # 단위 접미어 하나 제거
    text = _TRAILING_UNIT.sub('', text.rstrip()).rstrip()

    # 콤마·공백 제거
    text = text.replace(',', '').replace(' ', '')

    if not text:
        raise ValueError('parse_int_like: 숫자 부분이 없습니다.')

    try:
        return int(text)
    except ValueError as exc:
        raise ValueError(f'parse_int_like: 정수로 변환 실패: {value!r}') from exc


def parse_money(value: Number) -> int:
    """돈 단위(원) 값을 정수로 정규화.

    지금은 `parse_int_like` 의 얇은 alias — "의도를 드러내는" 구분용.
    향후 음수 금액 거부 같은 규칙이 생길 자리.
    """
    return parse_int_like(value)


def sum_amounts(values: Iterable[Number]) -> int:
    """각 원소를 `parse_int_like` 로 정규화한 뒤 합계 반환."""
    total = 0
    for v in values:
        total += parse_int_like(v)
    return total


def average_amount(values: Iterable[Number]) -> float:
    """각 원소를 정규화한 뒤 산술 평균 반환. 빈 입력은 `ValueError`.

    반환이 항상 float 인 이유: 금액 평균은 정수 나눗셈으로 절삭되면
    근속·평균급여 계산에서 눈에 띄는 오차가 생긴다. 호출측에서 반올림·절삭을
    판단하도록 float 그대로 돌려준다.
    """
    normalized = [parse_int_like(v) for v in values]
    if not normalized:
        raise ValueError('average_amount: 빈 목록의 평균은 정의되지 않습니다.')
    return sum(normalized) / len(normalized)
