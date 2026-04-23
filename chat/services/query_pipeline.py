"""질문을 받아 답변까지 내는 전체 쿼리 파이프라인.

흐름:
  1) DocumentChunk 검색 (회사 자료, 하이브리드 + 재정렬)
  2) CanonicalQA 검색 (공식 Q&A 참고)
  3) 프롬프트 조립
  4) OpenAI chat completion 호출
  5) TokenUsage 로그 저장
  6) ChatLog 저장 (자료 기반 답변일 때만 — 피드백·검수 대상)
"""

from typing import Dict, List, Optional

from chat.services.single_shot.llm import run_chat_completion
from chat.services.single_shot.postprocess import (
    build_sources,
    classify_reply,
    persist_chat_log,
    record_token_usage,
)
from chat.services.single_shot.prompting import build_single_shot_messages
from chat.services.single_shot.qa_cache import find_canonical_qa, resolve_cache_hit
from chat.services.single_shot.retrieval import retrieve_documents
from chat.services.single_shot.types import QueryPipelineError, QueryResult


# 검색·분류 상수는 각 helper 모듈로 이전됨:
#   - 청크: single_shot.retrieval
#   - QA:   single_shot.qa_cache
#   - 분류 마커: single_shot.postprocess


def answer_question(
    question: str,
    history: Optional[List[Dict]] = None,
) -> QueryResult:
    history = history or []

    # 1~2) 자료 후보 검색 + 재정렬
    chunk_hits = retrieve_documents(question)

    # 3) 공식 Q&A 검색
    qa_hits = find_canonical_qa(question)

    # 4) 캐시 히트면 즉시 반환 (OpenAI 호출 생략)
    cached = resolve_cache_hit(qa_hits)
    if cached is not None:
        return cached

    # 5) 프롬프트 조립
    messages = build_single_shot_messages(question, chunk_hits, qa_hits, history)

    # 6) OpenAI 호출
    reply, usage, model = run_chat_completion(messages)

    # 7) 후처리: 토큰 기록 → 응답 분류 → sources/ChatLog 구성
    record_token_usage(model, usage)

    is_no_info, is_casual = classify_reply(reply)

    saved_chat_log_id: Optional[int] = None
    sources: List[Dict] = []
    if chunk_hits and not is_no_info and not is_casual:
        saved_chat_log_id = persist_chat_log(question, reply, chunk_hits)
        sources = build_sources(chunk_hits)

    return QueryResult(
        reply=reply,
        sources=sources,
        total_tokens=usage.total_tokens,
        chat_log_id=saved_chat_log_id,
    )
