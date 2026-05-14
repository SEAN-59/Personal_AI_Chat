"""Q&A 검색·저장·승격 모듈.

분리된 두 개념:
- ChatLog  : 모든 채팅 기록 (저장·피드백 대상)
- CanonicalQA : 관리자가 큐레이션한 공식 Q&A (검색 대상)
"""

from dataclasses import dataclass
from typing import List, Optional

from pgvector.django import CosineDistance

from chat.models import CanonicalQA, ChatLog
from files.services.embedder import embed_text


# 검색 기본 설정 (CanonicalQA)
DEFAULT_TOP_K = 3
DEFAULT_SIMILARITY_THRESHOLD = 0.80


@dataclass
class QAHit:
    """CanonicalQA 검색 결과 한 건 (프롬프트 조립에 사용됨)."""
    qa_id: int
    question: str
    answer: str
    similarity: float


def search_canonical_qa(
    question: str,
    top_k: int = DEFAULT_TOP_K,
    similarity_threshold: float = DEFAULT_SIMILARITY_THRESHOLD,
) -> List[QAHit]:
    """공식 Q&A(CanonicalQA)에서 유사 질문 top-K를 찾는다."""
    if not question.strip():
        return []

    q_vec = embed_text(question)
    max_distance = 1.0 - similarity_threshold

    qs = (
        CanonicalQA.objects
        .annotate(distance=CosineDistance('question_embedding', q_vec))
        .filter(distance__lte=max_distance)
        .order_by('distance')[:top_k]
    )

    hits: List[QAHit] = []
    for qa in qs:
        hits.append(QAHit(
            qa_id=qa.pk,
            question=qa.question,
            answer=qa.answer,
            similarity=1.0 - float(qa.distance),
        ))
    return hits


# ChatLog 중복 판정 기준 (코사인 거리 0.10 이하 = 유사도 0.90 이상)
CHATLOG_DEDUP_MAX_DISTANCE = 0.10


def save_chat_log(
    question: str,
    answer: str,
    sources: Optional[list] = None,
    *,
    normalized_question: str = '',
) -> ChatLog:
    """대화 한 턴을 ChatLog에 저장. 유사 질문이 있으면 기존 것 재사용.

    v0.5.2 — `question` 은 raw (UI/표시 진실 소스). `normalized_question` 이 있으면
    embedding/dedup 키로 사용해 typo ChatLog cluster 오염을 막는다. 비어있으면
    raw 와 동일하다고 간주.

    - 유사도 0.90 이상이고 answer/sources 가 동일한 기존 ChatLog 가 있으면 재사용.
    - 유사 existing 이 있어도 answer 또는 sources 가 다르면 새 ChatLog 를 만든다
      (v0.5.3 QA 보강 S3 — BO 재임베딩으로 답변이 바뀌었는데 stale ChatLog 에
      피드백이 붙는 회귀 차단).
    - 피드백이 동일 ChatLog 에 누적되도록 dedup 자체는 유지.
    """
    embedding_key = normalized_question or question
    q_vec = embed_text(embedding_key)

    existing = (
        ChatLog.objects
        .annotate(distance=CosineDistance('question_embedding', q_vec))
        .filter(distance__lte=CHATLOG_DEDUP_MAX_DISTANCE)
        .order_by('distance')
        .first()
    )
    new_sources = list(sources or [])
    if existing and existing.answer == answer and list(existing.sources or []) == new_sources:
        return existing

    return ChatLog.objects.create(
        question=question,
        normalized_question=normalized_question or '',
        question_embedding=q_vec,
        answer=answer,
        sources=new_sources,
    )


def promote_to_canonical(chat_log: ChatLog) -> CanonicalQA:
    """ChatLog를 CanonicalQA로 승격 (관리자 액션).

    v0.5.2 — 공식 Q&A 의 question 은 `chat_log.normalized_question or chat_log.question`
    을 사용. raw typo 가 그대로 promote 되어 CanonicalQA 가 오염되는 것을 막는다.
    이미 이 ChatLog에서 승격된 CanonicalQA가 있으면 중복 생성하지 않고 기존 것을 반환.
    """
    existing = CanonicalQA.objects.filter(source_chatlog=chat_log).first()
    if existing:
        return existing
    canonical_question = chat_log.normalized_question or chat_log.question
    return CanonicalQA.objects.create(
        question=canonical_question,
        question_embedding=chat_log.question_embedding,
        answer=chat_log.answer,
        sources=chat_log.sources,
        source_chatlog=chat_log,
    )
