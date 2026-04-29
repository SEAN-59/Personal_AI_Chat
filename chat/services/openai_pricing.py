"""OpenAI 모델 단가 매핑 + cost 계산 (Phase 8-5).

`record_token_usage` 가 호출 시점에 `compute_cost_usd` 를 불러 cost 를 USD Decimal
로 산정해 `TokenUsage.cost_usd` 에 저장한다. 단가는 코드 상수 (`MODEL_PRICING`).

본 모듈의 cost 는 **`TokenUsage` 에 기록된 채팅 LLM 호출 비용의 추정치**:
- Phase 8-2 의 7 호출 사이트 (single_shot_answer / query_rewriter ×3 /
  workflow_extractor / workflow_table_lookup / agent_step / agent_final) 에 한정.
- 모델 단가 매핑 × 토큰 수 (단순 곱). 할인 / 리베이트 / 캐시 hit 환급 미반영.
- **embedding (`files/services/embedder.py`) / reranker (`chat/services/reranker.py`)
  호출 비용은 미포함** — 두 사이트가 record_token_usage 를 부르지 않아 TokenUsage
  에 row 없음. Phase 8-7 후보로 별 plan.

Phase 4-4 OpenAI Admin API widget (`bo/views/openai_usage.py`) 의 cost 와 별 데이터
소스라 두 값이 다른 게 정상 — Admin API 는 외부 청구 (모든 API 호출 + 할인 반영),
본 모듈은 자체 추정 (채팅 LLM 만, 단순 곱).

단가 변경 시 검토 항목:
1. `MODEL_PRICING` 의 새 단가로 교체. 변경 시점은 git history 에 남음.
2. 과거 row 의 cost 는 옛 단가 기준 그대로 (시점 cost 보존 정책).
3. 새 모델 추가 시 `MODEL_PRICING` 에 등록 + 단위 테스트.
"""

from __future__ import annotations

import logging
from decimal import Decimal
from typing import Mapping, Tuple


logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# 모델 단가 (USD per 1K tokens) — 2026-04 기준 OpenAI 공식 가격표.
# `record_token_usage` 가 실제 호출하는 모델만 등록.
# ---------------------------------------------------------------------------

MODEL_PRICING: Mapping[str, Tuple[Decimal, Decimal]] = {
    # gpt-4o-mini — single_shot 답변 / agent ReAct / rewriter / table_lookup
    # 의 default 모델 (chat/services/single_shot/llm.py 의 OPENAI_MODEL).
    'gpt-4o-mini': (Decimal('0.00015'), Decimal('0.00060')),
    # gpt-4o — 환경변수로 명시 적용 시.
    'gpt-4o': (Decimal('0.0025'), Decimal('0.0100')),
}


def compute_cost_usd(
    model: str,
    prompt_tokens: int,
    completion_tokens: int,
) -> Decimal:
    """USD 비용 계산. 미등록 모델은 0 + warning (fail-silent).

    공식: `(prompt × input_price + completion × output_price) / 1000`.

    Decimal 사용 — float 누적 오차 방지. 단위 1K tokens 라 `/ Decimal(1000)`.
    """
    pricing = MODEL_PRICING.get(model)
    if pricing is None:
        logger.warning(
            'compute_cost_usd: 미등록 모델 %r — cost=0 으로 처리 (단가 추가 필요)',
            model,
        )
        return Decimal('0')

    input_per_1k, output_per_1k = pricing
    prompt_cost = (Decimal(prompt_tokens) * input_per_1k) / Decimal(1000)
    completion_cost = (Decimal(completion_tokens) * output_per_1k) / Decimal(1000)
    return prompt_cost + completion_cost
