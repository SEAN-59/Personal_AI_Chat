"""중립 텍스트 정규화 helper.

v0.5.2 input normalization 의 비교/저장 키 정규화 단일 진실 소스.
`chat.models` 와 `chat.services.input_normalizer` 가 둘 다 이 모듈만 import 한다.
service → models → service 순환 import 회피를 위해 중립 위치에 둔다.
"""

import unicodedata


def canonicalize(text: str) -> str:
    """비교/저장 키용 canonical 형태.

    NFKC + strip + casefold. 한글은 NFKC/casefold 에서 사실상 무영향이고,
    전각/반각 라틴, 대소문자, 양옆 공백 차이만 흡수한다.
    """
    return unicodedata.normalize('NFKC', text or '').strip().casefold()
