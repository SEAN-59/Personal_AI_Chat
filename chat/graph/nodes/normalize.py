"""Normalize node — graph 입구에서 BO 규칙으로 question 을 정규화.

플랜 §7.1 결정: START → normalize → router 사이에 1회만 적용. 노드 내부의
추가 normalize 는 금지. raw 는 `question_raw`, normalized 는
`question_normalized` 로 분리해 state 에 싣는다. `question` 자체는 raw 의미
그대로 유지(호환).

규칙 0건 / 매치 0건이면 normalized = raw 로 둔다 (downstream 헬퍼가 그대로 동작).
"""

import logging

from chat.graph.state import GraphState
from chat.services.input_normalizer import normalize


logger = logging.getLogger(__name__)


def normalize_node(state: GraphState) -> dict:
    raw = state.get('question') or ''
    result = normalize(raw)

    if result.changed:
        logger.info(
            'input_normalize raw=%r normalized=%r rules=%s',
            result.raw,
            result.normalized,
            [a.id for a in result.applied],
        )

    return {
        'question_raw': result.raw,
        'question_normalized': result.normalized,
        'normalization_applied': result.applied_as_dicts(),
    }
