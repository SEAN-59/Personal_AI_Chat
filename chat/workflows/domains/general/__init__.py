"""Generic (질문 유형 중심) workflow 도메인들.

각 모듈이 자신을 `chat.workflows.domains.registry` 에 register 하는 부작용을
갖는다. 이 패키지가 import 되는 시점에 전 workflow 가 등록된 상태가 된다.

Phase 6-1 은 `date_calculation` 하나만 등록. Phase 6-2 에서
`amount_calculation`, 6-3 에서 `table_lookup` 이 차례로 추가된다.
"""

from chat.workflows.domains.general import date_calculation  # noqa: F401  (register 부작용)


__all__: list[str] = []
