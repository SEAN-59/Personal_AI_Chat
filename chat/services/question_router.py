"""규칙 기반 질문 분류기.

graph 의 router_node 가 부른다. Phase 4-1 에서는 단순 `substring contains` 기반:

    1. workflow 키워드 매치 → 'workflow'
    2. agent 키워드 매치 → 'agent'
    3. 그 외          → 'single_shot'

workflow 가 agent 보다 먼저인 이유: 정형 계산은 저렴·안정적이므로 애매할 때
workflow 쪽이 안전. agent 는 탐색·비교가 명확할 때만 사용.

Phase 4-2 (BO RouterRule) 이후 구조는 이렇게 바뀐다:
    DB RouterRule 조회  ──매치 있음──▶ 해당 route
          │
          └매치 없음──▶ 이 모듈의 키워드 상수 (fallback)
          │
          └그래도 없음──▶ 'single_shot' (default)

즉 이 모듈의 키워드 상수는 장기적으로 fallback 계층 역할을 맡는다.
"""

from dataclasses import dataclass, field
from typing import List

from chat.graph.routes import ROUTE_AGENT, ROUTE_SINGLE_SHOT, ROUTE_WORKFLOW


# 정형 계산·산정 성격 질문 신호.
# 단순히 단어 하나만 보고 판단하지만, 오분류 사례(예: '복지포인트는 얼마야?')는
# Phase 4-2 의 BO rule priority / negative pattern 으로 조정할 예정.
WORKFLOW_KEYWORDS: tuple[str, ...] = (
    '계산', '산정', '얼마', '몇 일', '몇 년', '평균', '합계', '차감',
    '근속', '퇴직금', '연차 계산', '잔여 연차', '급여', '수당',
    '입사일', '퇴사일', '최근 3개월',
)

# 비교·추천·상황판단 성격 질문 신호.
# agent 는 비용·불확실성이 커 마지막 수단 — 신호가 명확할 때만 쓰인다.
AGENT_KEYWORDS: tuple[str, ...] = (
    '비교', '추천', '유리', '불리', '종합', '예외', '케이스',
    '해석', '충돌', '만약', '내 상황', '어떤 게 나아',
)


@dataclass(frozen=True)
class RouteDecision:
    """라우터 결정. Phase 4-1 은 route/reason/matched_rules 만 채운다.

    confidence 같은 추가 필드는 LLM 보조 분류가 들어오는 Phase 4-2 이후 도입.
    """
    route: str                                          # ROUTE_* 중 하나
    reason: str                                         # 'workflow_keyword' / 'agent_keyword' / 'default'
    matched_rules: List[str] = field(default_factory=list)  # 매치된 키워드(들)


def _matches(question: str, keywords: tuple[str, ...]) -> List[str]:
    """question 안에 포함된 모든 키워드를 순서대로 반환. 없으면 빈 리스트."""
    return [kw for kw in keywords if kw in question]


def route_question(question: str) -> RouteDecision:
    """질문을 3 route 중 하나로 분류."""
    hits = _matches(question, WORKFLOW_KEYWORDS)
    if hits:
        return RouteDecision(
            route=ROUTE_WORKFLOW,
            reason='workflow_keyword',
            matched_rules=hits,
        )

    hits = _matches(question, AGENT_KEYWORDS)
    if hits:
        return RouteDecision(
            route=ROUTE_AGENT,
            reason='agent_keyword',
            matched_rules=hits,
        )

    return RouteDecision(route=ROUTE_SINGLE_SHOT, reason='default')
