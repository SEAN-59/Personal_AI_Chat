"""단계 3~4: 공식 Q&A 검색 + 캐시 히트 판정.

`find_canonical_qa` 는 임베딩 유사도 기준으로 과거 승격된 Q&A 를 top-K 조회한다.
`resolve_cache_hit` 은 top 1 유사도가 임계치 이상이면 OpenAI 호출을 건너뛰고
바로 QueryResult 를 돌려준다 (캐시 히트).

캐시 히트 시에는 ChatLog / TokenUsage 를 저장하지 않는다 (기존 규칙 유지).
"""

import logging
from typing import Dict, List, Optional

from chat.models import CanonicalQA
from chat.services.qa_retriever import QAHit, search_canonical_qa
from chat.services.single_shot.types import QueryResult


logger = logging.getLogger(__name__)


# QA 검색 top-K 와 후보 유사도 하한. 둘 다 '어느 과거 Q&A 를 참고 자료로 붙일지' 기준.
QA_TOP_K = 3
QA_SIMILARITY_THRESHOLD = 0.80

# 캐시 히트 기준 — top 1 유사도가 이 이상이면 그 답변을 재사용.
# 낮출수록 캐시 적중률↑ (속도·비용↑) / 너무 낮추면 유사한 다른 질문에도 같은 답 나갈 위험.
QA_CACHE_HIT_THRESHOLD = 0.88


def find_canonical_qa(question: str) -> List[QAHit]:
    """과거 공식 Q&A 에서 유사 질문 top-K 를 반환."""
    qa_hits = search_canonical_qa(
        question,
        top_k=QA_TOP_K,
        similarity_threshold=QA_SIMILARITY_THRESHOLD,
    )
    logger.info('CanonicalQA 검색: %d개', len(qa_hits))
    return qa_hits


def resolve_cache_hit(qa_hits: List[QAHit]) -> Optional[QueryResult]:
    """캐시 히트면 완성된 QueryResult 를 반환, 아니면 None.

    히트 조건: 리스트가 비지 않고 top 1 유사도가 `QA_CACHE_HIT_THRESHOLD` 이상,
    그리고 매칭된 CanonicalQA 의 `sources` 가 비어있어야 함.

    v0.5.4 — sources(=Document id 목록) 가 비어있지 않은 row 는 BO 재임베딩으로
    참조 문서의 내용이 바뀌었을 가능성이 있으므로 immediate-cache 로 답을 단락
    시키지 않는다. 옛 답을 그대로 돌려주는 stale 응답 회귀 차단. `find_canonical_qa`
    가 만든 QAHit 은 prompt builder 의 "과거 참고 답변" 섹션에 그대로 흐른다.
    """
    if not qa_hits or qa_hits[0].similarity < QA_CACHE_HIT_THRESHOLD:
        return None

    hit = qa_hits[0]
    canonical = CanonicalQA.objects.filter(pk=hit.qa_id).first()

    # sources 가 있는 row 는 cache hit 대상에서 제외 (v0.5.4).
    if canonical is None or canonical.sources:
        logger.info(
            'CanonicalQA cache skip (sourced row, qa_id=%s)',
            hit.qa_id,
        )
        return None

    logger.info('CanonicalQA 캐시 히트 (sim=%.3f, qa_id=%d)', hit.similarity, hit.qa_id)

    cached_sources: List[Dict] = []

    return QueryResult(
        reply=hit.answer,
        sources=cached_sources,
        total_tokens=0,        # OpenAI 호출 없음
        chat_log_id=None,      # 재사용 응답은 ChatLog 생성 X
    )
