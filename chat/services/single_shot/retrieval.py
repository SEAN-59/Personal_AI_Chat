"""단계 1~2: DocumentChunk 하이브리드 검색 + 재정렬.

외부에 노출되는 API 는 `retrieve_documents(question, *, expand_neighbors=True)`.
내부는 기존 구현(files.services.retriever.search_chunks + chat.services.reranker.rerank)을
그대로 호출하고, v0.5.5 부터 document-local neighbor 청크 확장을 후처리로 추가한다.
상수는 single_shot 안에 모아 향후 workflow 가 같은 값을 참조하게 한다.
"""

from __future__ import annotations

import logging
import re
from typing import Iterable, List, Sequence

from chat.services.reranker import rerank
from files.models import Document, DocumentChunk
from files.services.retriever import ChunkHit, search_chunks


logger = logging.getLogger(__name__)


# 1차 후보 개수 — rerank 이전. 너무 많으면 LLM 재정렬 비용·지연 증가.
CHUNK_CANDIDATES = 10
# rerank 후 프롬프트에 넣을 최종 개수.
CHUNK_TOP_K = 5

# v0.5.5 — document-local neighbor expansion 상수.
# hit 청크 앞/뒤 각각 몇 개 chunk_index 까지 추가로 끌어올지.
NEIGHBOR_RADIUS = 2
# 한 document 안에서 확장된 후 유지 가능한 chunk 최대 수 (원본 hit 포함).
MAX_NEIGHBOR_CHUNKS_PER_DOC = 8
# 전체 expansion 결과 chunk 수 상한.
MAX_TOTAL_CHUNKS_AFTER_EXPANSION = 12
# 최종 expanded hits 전체 content 합 상한 (문자 기준).
MAX_EXPANSION_CHARS = 8000

# Enumeration 단서. v0.5.5 §4.1: generic 한국어 단어만, `항목` 은 의도적으로 제외
# (monetary rewrite 출력에 우연히 trigger 되는 회귀 방지).
_ENUMERATION_TOKENS: tuple[str, ...] = (
    '모든', '전부', '전체', '종류', '목록', '리스트', '다 알려줘', '전부 다',
)

# Monetary/ordinal/comparative marker — 조건 3 발동 후보 query 감지.
_COMPARATIVE_TOKENS: tuple[str, ...] = (
    '비싼', '싼', '큰', '작은', '높은', '낮은', '많은', '적은',
    '최대', '최소', '가장', '제일',
    '첫 번째', '첫번째', '두 번째', '두번째', '세 번째', '세번째',
    '번째',
)

# 명시적 표/금액 metric 어휘.
_METRIC_TOKENS: tuple[str, ...] = (
    '금액', '지급금액', '지급액', '비용', '기준',
)


# 표/목록 marker 정규식.
# - markdown table: `|` 가 한 줄에 2개 이상 + 다음 줄에 `---` 구분자.
_TABLE_PATTERN = re.compile(
    r'(^|\n)[^\n]*\|[^\n]*\|[^\n]*\n[ \t]*\|?[ \t:\-|]*-{3,}[ \t:\-|]*',
)
# - 목록 마커 (`-` `*` `1.` `①` 등) 3줄 이상 연속.
_LIST_LINE = re.compile(r'^[ \t]*(?:[-*•]|\d+[.)]|[①②③④⑤⑥⑦⑧⑨⑩])\s+')


def _has_table_or_list_marker(content: str) -> bool:
    if not content:
        return False
    if _TABLE_PATTERN.search(content):
        return True
    streak = 0
    for line in content.splitlines():
        if _LIST_LINE.match(line):
            streak += 1
            if streak >= 3:
                return True
        else:
            streak = 0
    return False


def _has_enumeration_intent(question: str) -> bool:
    if not question:
        return False
    return any(token in question for token in _ENUMERATION_TOKENS)


def _has_comparative_intent(question: str) -> bool:
    return any(token in question for token in _COMPARATIVE_TOKENS) if question else False


def _has_explicit_metric(question: str) -> bool:
    return any(token in question for token in _METRIC_TOKENS) if question else False


def _should_expand(
    question: str,
    hits: Sequence[ChunkHit],
) -> bool:
    """§4.1 적용 조건 평가."""
    if not hits:
        return False

    enum = _has_enumeration_intent(question)
    if enum:
        return True

    # 같은 document hit ≥ 2 + 표/목록 marker 검출 (조건 2).
    doc_counts: dict[int, int] = {}
    for h in hits:
        doc_counts[h.document_id] = doc_counts.get(h.document_id, 0) + 1
    has_multi_doc_hit = any(c >= 2 for c in doc_counts.values())
    has_marker = any(_has_table_or_list_marker(h.content or '') for h in hits)

    if has_multi_doc_hit and has_marker:
        return True

    # 조건 3: monetary/ordinal/comparative + 명시적 metric + table/list marker.
    if (
        _has_comparative_intent(question)
        and _has_explicit_metric(question)
        and has_marker
    ):
        return True

    return False


def _merge_windows(
    chunk_indices: Iterable[int],
    radius: int,
) -> list[tuple[int, int]]:
    """hit chunk_index 들을 radius 만큼 확장 후 인접 윈도우 병합."""
    # 각 hit 의 (start, end) 페어를 정렬해 병합.
    intervals: list[tuple[int, int]] = []
    pairs = sorted((max(0, i - radius), i + radius) for i in chunk_indices)
    for start, end in pairs:
        if intervals and start <= intervals[-1][1] + 1:
            prev_start, prev_end = intervals[-1]
            intervals[-1] = (prev_start, max(prev_end, end))
        else:
            intervals.append((start, end))
    return intervals


def _hit_to_chunk_hit(chunk: DocumentChunk) -> ChunkHit:
    """`DocumentChunk` ORM 객체 → `ChunkHit`. neighbor 부착용."""
    doc = chunk.document
    return ChunkHit(
        chunk_id=chunk.id,
        document_id=doc.id,
        document_name=getattr(doc, 'original_name', '') or '',
        document_url=(doc.file.url if getattr(doc, 'file', None) else ''),
        content=chunk.content or '',
        score=0.0,
        chunk_index=chunk.chunk_index,
    )


def _expand_neighbors(
    question: str,
    hits: Sequence[ChunkHit],
) -> List[ChunkHit]:
    """hits 에 document-local neighbor 청크를 부착해 새 리스트 반환.

    §4.1 budget cap, document-local chunk_index 오름차순 정렬, 중복 제거 포함.
    """
    if not hits or not _should_expand(question, hits):
        return list(hits)

    # document 단위 그룹화 + group 순서는 첫 등장 hit 순.
    group_order: list[int] = []
    grouped: dict[int, list[ChunkHit]] = {}
    for h in hits:
        if h.document_id not in grouped:
            grouped[h.document_id] = []
            group_order.append(h.document_id)
        grouped[h.document_id].append(h)

    # document 별 neighbor 청크 조회.
    expansion_by_doc: dict[int, list[ChunkHit]] = {did: [] for did in group_order}
    for did in group_order:
        hit_chunks = grouped[did]
        intervals = _merge_windows(
            [h.chunk_index for h in hit_chunks],
            NEIGHBOR_RADIUS,
        )
        original_indices = {h.chunk_index for h in hit_chunks}
        wanted_indices: set[int] = set()
        for start, end in intervals:
            for idx in range(start, end + 1):
                if idx in original_indices:
                    continue
                wanted_indices.add(idx)
        if not wanted_indices:
            continue
        # 같은 document 안에서만 추가 조회. status=READY 일관성 유지.
        qs = (
            DocumentChunk.objects
            .filter(
                document_id=did,
                document__status=Document.Status.READY,
                chunk_index__in=wanted_indices,
            )
            .select_related('document')
        )
        expansion_by_doc[did] = [_hit_to_chunk_hit(c) for c in qs]

    # document 그룹별 정렬 + budget 적용.
    total_chars = sum(len(h.content or '') for h in hits)
    total_chunks = len(hits)
    final_hits: list[ChunkHit] = []
    seen_chunk_ids: set[int] = set()

    for did in group_order:
        originals = grouped[did]
        extras = expansion_by_doc.get(did, [])
        # 원본 hit 은 무조건 포함.
        # 같은 document 안에서 chunk_index 오름차순.
        combined_originals = sorted(originals, key=lambda h: h.chunk_index)
        for h in combined_originals:
            if h.chunk_id in seen_chunk_ids:
                continue
            seen_chunk_ids.add(h.chunk_id)
            final_hits.append(h)

        # 이 document 의 doc-local 캡 — 원본 hit + extras 합쳐서 MAX_NEIGHBOR_CHUNKS_PER_DOC.
        used_for_doc = sum(1 for h in final_hits if h.document_id == did)
        for extra in sorted(extras, key=lambda h: h.chunk_index):
            if extra.chunk_id in seen_chunk_ids:
                continue
            if used_for_doc >= MAX_NEIGHBOR_CHUNKS_PER_DOC:
                break
            if total_chunks >= MAX_TOTAL_CHUNKS_AFTER_EXPANSION:
                break
            extra_len = len(extra.content or '')
            if total_chars + extra_len > MAX_EXPANSION_CHARS:
                # 더 큰 extra 가 뒤에 더 있을 수 있으나 보수적으로 cap 도달 시 중단.
                break
            seen_chunk_ids.add(extra.chunk_id)
            final_hits.append(extra)
            total_chars += extra_len
            total_chunks += 1
            used_for_doc += 1

    # 마지막으로 document 그룹 내부 chunk_index 오름차순 재정렬 (extras 가 sorted insert
    # 였지만 원본 hit 사이에 끼워 넣지 않았으므로 한 번 더 정렬).
    final_sorted: list[ChunkHit] = []
    placed_docs: set[int] = set()
    for did in group_order:
        if did in placed_docs:
            continue
        placed_docs.add(did)
        doc_hits = [h for h in final_hits if h.document_id == did]
        doc_hits.sort(key=lambda h: h.chunk_index)
        final_sorted.extend(doc_hits)
    return final_sorted


def retrieve_documents(
    question: str,
    *,
    expand_neighbors: bool = True,
) -> List[ChunkHit]:
    """회사 자료 청크를 검색·재정렬해 상위 N 개 반환.

    벡터 + 키워드 하이브리드로 CHUNK_CANDIDATES 개를 뽑고, LLM 기반 rerank 로
    CHUNK_TOP_K 개만 남긴다. v0.5.5 부터 `expand_neighbors=True` (기본) 일 때
    document-local neighbor 청크를 §4.1 조건/budget 에 맞춰 추가 부착한다.
    table_lookup workflow 와 agent path 는 `expand_neighbors=False` 로 호출해
    이번 phase 의 영향 범위를 single_shot 으로 한정한다.
    """
    candidates = search_chunks(question, top_k=CHUNK_CANDIDATES)
    logger.info('후보 검색: %d개 (질문: %s)', len(candidates), question[:30])
    hits = rerank(question, candidates, top_k=CHUNK_TOP_K)
    logger.info('재정렬 후 선택: %d개', len(hits))
    if not expand_neighbors:
        return hits
    expanded = _expand_neighbors(question, hits)
    if len(expanded) != len(hits):
        logger.info(
            'neighbor expansion: %d → %d (질문: %s)',
            len(hits),
            len(expanded),
            question[:30],
        )
    return expanded
