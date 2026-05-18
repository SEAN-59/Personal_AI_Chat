"""질문 → DocumentChunk 하이브리드 검색.

- 벡터 검색: pgvector 코사인 거리 (의미 유사도)
- 키워드 검색: 질문에서 뽑은 단어들로 ILIKE 매칭 + 매칭 수 기반 랭킹

두 결과를 Reciprocal Rank Fusion(RRF)으로 병합해 top-K 반환.

v0.5.4:
- 후보 풀에는 `Document.status == READY` 인 chunk 만 포함.
- 다중 키워드 동시 적중 / 질문 phrase 통째 매치는 RRF 점수에 boost 가산.
- 최종 정렬은 score desc + chunk_id asc 로 결정적.
"""

import re
from dataclasses import dataclass
from typing import Dict, List

from django.db.models import Case, IntegerField, Q, Value, When
from pgvector.django import CosineDistance

from files.models import Document, DocumentChunk
from files.services.embedder import embed_text


# RRF 점수 상수 (표준 값)
RRF_K = 60

# 각 단일 검색에서 뽑을 후보 수
VECTOR_POOL_SIZE = 20
KEYWORD_POOL_SIZE = 20

# 최종 기본 반환 개수
DEFAULT_TOP_K = 5

# v0.5.4 — RRF 한 칸(≈1/(60+1)≈0.0164) 보다 큰 가산. 두 신호 모두 결정적.
MULTI_KEYWORD_BOOST = 0.02   # hit_total 당 가산
EXACT_PHRASE_BOOST = 0.05    # 질문 phrase 가 chunk 안에 통째로 들어있을 때 가산

# 질문 토큰에서 제외할 조사·어미·의문사·범용 enumeration 단서.
_STOPWORDS = {
    '뭐야', '뭔가요', '뭐예요', '어디', '어디야', '언제', '누가', '얼마나',
    '어떻게', '왜', '어떤', '무엇', '뭔지', '알려줘', '알려주세요',
    '입니까', '입니다', '있나요', '있어요', '이야', '야',
    '은', '는', '이', '가', '을', '를', '의', '에', '와', '과', '로',
    '해', '해줘', '해주세요', '그럼',
    # v0.5.5 — 범용 enumeration / 질문 보조어. 도메인 어휘는 제외하지 않음.
    '모든', '전부', '전체', '종류', '목록', '리스트', '각각', '여러',
    '말해줘', '말해', '보여줘', '보여',
}

# v0.5.5 — generic 한국어 접미사 (조사/어미). 토큰 끝에서 가장 긴 것부터 1회 제거.
# 도메인 어휘 하드코딩 금지 — 어디까지나 generic suffix.
_TOKEN_SUFFIXES = (
    # 어미 4글자
    '하시나요', '드립니다', '드리나요', '입니다만',
    # 어미/조사 3글자
    '하나요', '합니까', '합니다', '했어요', '했나요', '하려고', '한다면',
    '에서는', '에서도', '에서만', '에게서', '에서의', '으로서', '으로써',
    '이라고', '이라는',
    # 어미/조사 2글자
    '하는', '한다', '했다', '하고', '해서', '하며', '하면', '하기', '하지',
    '하나', '했어', '하다', '되는', '된다', '됐다', '되어', '되고',
    '에서', '에게', '에는', '에도', '으로', '에서', '까지', '부터', '마다',
    '처럼', '보다', '같이', '라는', '라고', '이나', '이란', '이든', '이다',
    '께서', '에게', '한테',
    # 1글자 조사
    '은', '는', '이', '가', '을', '를', '의', '에', '와', '과', '로',
    '도', '만', '나', '랑', '며',
)


def _normalize_token(tok: str) -> str:
    """토큰 끝의 조사/어미를 보수적으로 한 번 제거. 한국어 토큰만 적용.

    제거 후 최소 2글자 이상 + 한글이 남아야 정규화 적용. 그 외에는 원본 유지.
    """
    if not tok or not re.fullmatch(r'[가-힣]+', tok):
        return tok
    for suf in _TOKEN_SUFFIXES:
        if len(tok) > len(suf) and tok.endswith(suf):
            stem = tok[: -len(suf)]
            if len(stem) >= 2 and re.fullmatch(r'[가-힣]+', stem):
                return stem
    return tok


@dataclass
class ChunkHit:
    chunk_id: int
    document_id: int
    document_name: str
    document_url: str   # 원본 파일 서빙 URL (/media/origin/xxx)
    content: str
    score: float        # RRF 점수 (높을수록 관련)
    # v0.5.4 — reranker 메타 prepend 에 사용. 기존 호출부 호환을 위해 기본값 0.
    chunk_index: int = 0


def search_chunks(question: str, top_k: int = DEFAULT_TOP_K) -> List[ChunkHit]:
    """하이브리드 검색 top-K."""
    if not question.strip():
        return []

    # v0.5.4 — 후보 풀은 READY document 만.
    ready_qs = DocumentChunk.objects.filter(
        document__status=Document.Status.READY,
    )

    # --- 1) 벡터 검색 ---
    q_vec = embed_text(question)
    vector_ids = list(
        ready_qs
        .annotate(distance=CosineDistance('embedding', q_vec))
        .order_by('distance', 'id')
        .values_list('id', flat=True)[:VECTOR_POOL_SIZE]
    )

    # --- 2) 키워드 검색 ---
    keywords = _extract_keywords(question)
    keyword_ids: List[int] = []
    hit_total_by_id: Dict[int, int] = {}
    if keywords:
        q_filter = Q()
        for kw in keywords:
            q_filter |= Q(content__icontains=kw)

        qs = ready_qs.filter(q_filter)
        # 각 키워드별 Case 를 annotate 로 더해 hit_total 계산.
        from django.db.models import F
        total_expr = None
        for i, kw in enumerate(keywords):
            field = f'_hit_{i}'
            qs = qs.annotate(
                **{
                    field: Case(
                        When(content__icontains=kw, then=Value(1)),
                        default=Value(0),
                        output_field=IntegerField(),
                    )
                }
            )
            col = F(field)
            total_expr = col if total_expr is None else total_expr + col
        qs = qs.annotate(hit_total=total_expr).order_by('-hit_total', 'id')

        for row in qs.values('id', 'hit_total')[:KEYWORD_POOL_SIZE]:
            cid = row['id']
            keyword_ids.append(cid)
            hit_total_by_id[cid] = int(row['hit_total'] or 0)

    # --- 3) RRF 병합 ---
    rrf_scores: Dict[int, float] = {}
    for rank, cid in enumerate(vector_ids, start=1):
        rrf_scores[cid] = rrf_scores.get(cid, 0.0) + 1.0 / (RRF_K + rank)
    for rank, cid in enumerate(keyword_ids, start=1):
        rrf_scores[cid] = rrf_scores.get(cid, 0.0) + 1.0 / (RRF_K + rank)

    if not rrf_scores:
        return []

    # --- 3.5) v0.5.4 boost — multi-keyword + exact phrase.
    candidate_ids = list(rrf_scores.keys())
    phrase = (question or '').strip()
    phrase_match_by_id: Dict[int, bool] = {}
    if phrase:
        matched = ready_qs.filter(
            id__in=candidate_ids, content__icontains=phrase,
        ).values_list('id', flat=True)
        phrase_match_by_id = {cid: True for cid in matched}

    for cid in candidate_ids:
        if hit_total_by_id.get(cid):
            rrf_scores[cid] += MULTI_KEYWORD_BOOST * hit_total_by_id[cid]
        if phrase_match_by_id.get(cid):
            rrf_scores[cid] += EXACT_PHRASE_BOOST

    # --- 4) 결정적 tie-break: score desc, id asc.
    top_ids = sorted(
        rrf_scores.keys(), key=lambda cid: (-rrf_scores[cid], cid),
    )[:top_k]

    # --- 5) 객체 조회 + 순서 보존 ---
    chunks_by_id = {
        c.id: c
        for c in DocumentChunk.objects.filter(id__in=top_ids).select_related('document')
    }
    hits: List[ChunkHit] = []
    for cid in top_ids:
        c = chunks_by_id.get(cid)
        if not c:
            continue
        hits.append(ChunkHit(
            chunk_id=c.id,
            document_id=c.document_id,
            document_name=c.document.original_name,
            document_url=c.document.file.url if c.document.file else '',
            content=c.content,
            score=rrf_scores[cid],
            chunk_index=c.chunk_index,
        ))
    return hits


def _extract_keywords(question: str) -> List[str]:
    """질문에서 의미 있는 단어들 추출.

    한국어 간단 토큰화: 공백·특수문자 제거, 2글자 이상, 불용어 제거.
    """
    # 특수문자 제거 후 공백 기준 분리
    tokens = re.findall(r'[가-힣A-Za-z0-9]+', question)
    # 조사/어미 정규화 → 2글자 이상 + 불용어 제외
    normalized: List[str] = []
    for t in tokens:
        n = _normalize_token(t)
        if len(n) >= 2 and n not in _STOPWORDS:
            normalized.append(n)
    # 중복 제거 (순서 유지)
    seen = set()
    uniq = []
    for kw in normalized:
        if kw not in seen:
            uniq.append(kw)
            seen.add(kw)
    return uniq
