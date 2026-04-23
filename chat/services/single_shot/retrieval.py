"""단계 1~2: DocumentChunk 하이브리드 검색 + 재정렬.

외부에 노출되는 API 는 `retrieve_documents(question)` 한 개.
내부는 기존 구현(files.services.retriever.search_chunks + chat.services.reranker.rerank)을
그대로 호출한다. 상수는 single_shot 안에 모아 향후 workflow 가 같은 값을 참조하게 한다.
"""

import logging
from typing import List

from chat.services.reranker import rerank
from files.services.retriever import ChunkHit, search_chunks


logger = logging.getLogger(__name__)


# 1차 후보 개수 — rerank 이전. 너무 많으면 LLM 재정렬 비용·지연 증가.
CHUNK_CANDIDATES = 10
# rerank 후 프롬프트에 넣을 최종 개수.
CHUNK_TOP_K = 5


def retrieve_documents(question: str) -> List[ChunkHit]:
    """회사 자료 청크를 검색·재정렬해 상위 N 개 반환.

    벡터 + 키워드 하이브리드로 CHUNK_CANDIDATES 개를 뽑고, LLM 기반 rerank 로
    CHUNK_TOP_K 개만 남긴다.
    """
    candidates = search_chunks(question, top_k=CHUNK_CANDIDATES)
    logger.info('후보 검색: %d개 (질문: %s)', len(candidates), question[:30])
    hits = rerank(question, candidates, top_k=CHUNK_TOP_K)
    logger.info('재정렬 후 선택: %d개', len(hits))
    return hits
