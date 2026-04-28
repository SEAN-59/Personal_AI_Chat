"""Agent runtime 설정 로더 (Phase 8-3).

`AgentSettings` 모델의 BO 조정값을 frozen dataclass 로 freeze 해 ReAct loop 가
사용한다. **default 의 single source of truth** 이며, `react.py` 가 본 모듈을
import 하지만 본 모듈은 `react.py` 를 import 하지 않는다 (단방향 — 순환 import
회피).

설계 결정:

- **per-call DB SELECT** — 캐시 없음. agent 호출 빈도 (분당 1~2 회) 대비 SELECT
  비용은 무시 가능. BO 변경 → 즉시 반영 (incident 대응 우선).
- **3단 폴백**:
    1. AgentSettings 조회 성공 + sanity 통과 → DB 값.
    2. 조회 실패 (마이그레이션 누락 / DB 손상) → `_DEFAULTS` + warning 로그.
    3. 조회 성공 but 비정상 값 (CheckConstraint 우회 / 외부 dump) → `_DEFAULTS` + warning.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass


logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Default constants — react.py 가 alias 로 import (단방향).
# ---------------------------------------------------------------------------

DEFAULT_MAX_ITERATIONS = 6
DEFAULT_MAX_LOW_RELEVANCE_RETRIEVES = 3


@dataclass(frozen=True)
class AgentRuntimeSettings:
    """ReAct loop 가 한 호출 동안 사용하는 동결 설정.

    `enabled=False` 이면 `agent_node` 가 single_shot 폴백 — `react.run_agent` 는
    아예 호출되지 않는다. enabled 분기는 호출자 (agent_node) 책임.
    """

    enabled: bool
    max_iterations: int
    max_low_relevance_retrieves: int


_DEFAULTS = AgentRuntimeSettings(
    enabled=True,
    max_iterations=DEFAULT_MAX_ITERATIONS,
    max_low_relevance_retrieves=DEFAULT_MAX_LOW_RELEVANCE_RETRIEVES,
)


# ---------------------------------------------------------------------------
# 한도 sanity check — CheckConstraint 우회 대비 마지막 안전망.
# ---------------------------------------------------------------------------

_MAX_ITERATIONS_RANGE = (1, 12)
_MAX_LOW_RELEVANCE_RANGE = (1, 10)


def _is_sane(settings: AgentRuntimeSettings) -> bool:
    mi_lo, mi_hi = _MAX_ITERATIONS_RANGE
    lr_lo, lr_hi = _MAX_LOW_RELEVANCE_RANGE
    return (
        mi_lo <= settings.max_iterations <= mi_hi
        and lr_lo <= settings.max_low_relevance_retrieves <= lr_hi
    )


def load_runtime_settings() -> AgentRuntimeSettings:
    """현재 BO 설정을 freeze 한 `AgentRuntimeSettings` 반환.

    DB 조회 실패 / 비정상 값 → `_DEFAULTS` 폴백 + warning 로그. 절대 fail-loud
    하지 않음 — agent 호출 자체가 깨지면 운영 incident.
    """
    try:
        from chat.models import AgentSettings  # lazy import — Django app loading
        row = AgentSettings.objects.get_solo()
    except Exception as exc:                                          # noqa: BLE001
        logger.warning(
            'AgentSettings 조회 실패 — _DEFAULTS 폴백: %s', exc,
        )
        return _DEFAULTS

    candidate = AgentRuntimeSettings(
        enabled=bool(row.enabled),
        max_iterations=int(row.max_iterations),
        max_low_relevance_retrieves=int(row.max_low_relevance_retrieves),
    )

    if not _is_sane(candidate):
        logger.warning(
            'AgentSettings 값이 범위 밖 — _DEFAULTS 폴백: %r', candidate,
        )
        return _DEFAULTS

    return candidate
