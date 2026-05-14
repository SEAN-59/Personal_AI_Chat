"""Single-shot 조합자.

rewrite → retrieve → qa_cache → prompting → llm → postprocess 순서로
helper 들을 엮어 하나의 질문에 대한 `QueryResult` 를 만든다. 외부 진입점은
`run_single_shot` 하나. view / graph 노드 / 향후 workflow 에서 모두 이 함수를
호출한다.

Phase 4-3: retrieval 앞단에 쿼리 재작성(rewrite) 단계가 붙는다. "비싼거"
같이 맥락에 의존하는 후속 질문을 직전 대화 내용과 함께 cheap LLM 에 보내
self-contained 검색어로 바꾼 뒤, 그 결과를 retrieve_documents /
find_canonical_qa 에 넘긴다.

v0.5.2: 첫 positional 은 **normalized_question** 으로 변경. rewrite / retrieval /
prompt_builder 모두 normalized 입력을 사용한다. **raw_question** 은 keyword 인자
로 함께 받아 ChatLog.question 저장(=UI/표시 진실 소스) 에만 쓰인다. raw_question
이 생략되면 normalized 와 동일하다고 간주 — 정규화가 없는 코드 경로의 동작 변화 없음.
"""

from typing import Dict, List, Optional

from chat.services.query_rewriter import rewrite_query_with_history
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
from chat.services.single_shot.types import QueryResult
from chat.services.token_purpose import (
    PURPOSE_QUERY_REWRITER,
    PURPOSE_SINGLE_SHOT_ANSWER,
)


def run_single_shot(
    normalized_question: str,
    history: Optional[List[Dict]] = None,
    *,
    raw_question: Optional[str] = None,
    normalization_applied: Optional[List[Dict]] = None,
) -> QueryResult:
    """질문 하나를 single-shot 경로로 처리해 QueryResult 를 반환.

    v0.5.2 — 첫 positional 은 **normalized**. 내부 rewriter/retrieval/prompt_builder
    의 입력으로 사용. `raw_question` 은 ChatLog.question 저장용 (UI/표시 진실 소스).
    `raw_question` 생략 시 normalized 와 동일하다고 간주 — 정규화가 없는 코드 경로
    에서도 동작 변화 없음.

    실패 시 `QueryPipelineError` 를 raise.
    """
    history = history or []
    raw = raw_question if raw_question is not None else normalized_question

    # 0) 검색어 재작성 — normalized 입력 기준. history 가 비어있거나 LLM 실패 시 원본 반환.
    search_query, rewriter_usage, rewriter_model = rewrite_query_with_history(
        normalized_question, history,
    )
    if rewriter_usage is not None and rewriter_model is not None:
        record_token_usage(
            rewriter_model, rewriter_usage,
            purpose=PURPOSE_QUERY_REWRITER,
        )

    # 1~2) 자료 후보 검색 + 재정렬
    chunk_hits = retrieve_documents(search_query)

    # 3) 공식 Q&A 검색
    qa_hits = find_canonical_qa(search_query)

    # 4) 캐시 히트면 즉시 반환 (OpenAI 호출 생략)
    cached = resolve_cache_hit(qa_hits)
    if cached is not None:
        return cached

    # 5) 프롬프트 조립 — LLM 입력 질문은 normalized. retrieval/rewriter 모두 normalized 기반.
    messages = build_single_shot_messages(
        normalized_question, chunk_hits, qa_hits, history, search_query=search_query,
    )

    # 6) OpenAI 호출
    reply, usage, model = run_chat_completion(messages)

    # 7) 후처리: 토큰 기록 → 응답 분류 → sources/ChatLog 구성
    record_token_usage(model, usage, purpose=PURPOSE_SINGLE_SHOT_ANSWER)

    is_no_info, is_casual = classify_reply(reply)

    saved_chat_log_id: Optional[int] = None
    sources: List[Dict] = []
    if chunk_hits and not is_no_info and not is_casual:
        saved_chat_log_id = persist_chat_log(
            raw, reply, chunk_hits,
            normalized_question=normalized_question if normalized_question != raw else '',
        )
        sources = build_sources(chunk_hits)

    return QueryResult(
        reply=reply,
        sources=sources,
        total_tokens=usage.total_tokens,
        chat_log_id=saved_chat_log_id,
    )
