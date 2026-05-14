"""OpenAI에 보낼 메시지 리스트를 조립하는 모듈.

입력:
- 현재 질문
- DocumentChunk 검색 결과 (회사 자료)
- QAPair 검색 결과 (과거 참고 답변)
- 세션 대화 히스토리

출력:
- OpenAI chat.completions.create()에 바로 넘길 수 있는 messages 리스트

프롬프트 문구는 assets/prompts/chat/*.md 파일에서 로드한다.
prompt_loader 가 프로세스 캐시를 담당하므로 함수마다 매번 디스크를 읽지 않는다.
"""

from typing import List, Dict, Any, Optional

from chat.services.prompt_loader import load_prompt
from chat.services.qa_retriever import QAHit
from files.services.retriever import ChunkHit


def build_messages(
    question: str,
    chunk_hits: List[ChunkHit],
    qa_hits: List[QAHit],
    history: List[Dict[str, Any]],
    *,
    search_query: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """OpenAI 호환 messages 리스트를 만든다.

    Args:
        question: 사용자 질문 (raw, 가공 안 된 원문)
        chunk_hits: DocumentChunk 검색 결과
        qa_hits: QAPair 검색 결과
        history: 세션 히스토리 [{'role': ..., 'content': ...}, ...]
        search_query: query_rewriter 가 만든 self-contained 검색어. raw question
            과 다를 때만 사용자 질문 섹션에 '대화 맥락 반영 질문' 으로 함께
            렌더링한다. None / 빈 문자열 / question 과 동일하면 기존 출력
            그대로 유지 (회귀 0).

    Returns:
        OpenAI API에 바로 넘길 수 있는 메시지 리스트
    """
    messages: List[Dict[str, Any]] = []

    # ① 시스템 프롬프트 (역할·말투 규칙)
    messages.append({'role': 'system', 'content': load_prompt('chat/system.md')})

    # ② 과거 대화 히스토리: 최종 답변 생성 단계에서는 이전 assistant 답변의
    #    숫자·금액·일수 같은 factual content 가 현재 회사 자료보다 우선되어
    #    답변을 오염시키는 사례가 있어(v0.5.3 QA 보강 S2), assistant role
    #    메시지는 제외하고 user role 만 남긴다. query_rewriter / llm_router /
    #    workflow extractor 가 쓰는 history 는 별도 경로이므로 영향 없음.
    messages.extend(_sanitize_history_for_answer(history))

    # ③ 이번 turn의 user 메시지: 자료 + 과거참고 + 질문
    user_content = _render_user_content(
        question, chunk_hits, qa_hits, search_query=search_query,
    )
    messages.append({'role': 'user', 'content': user_content})

    return messages


def _sanitize_history_for_answer(
    history: List[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    """답변 생성용 history sanitization.

    이전 assistant 답변은 숫자/금액/일수가 박혀 있어, 같은 세션에서 회사 자료가
    재임베딩으로 갱신된 경우(예: 200만 → 2000만) 모델이 옛 assistant 답변을
    근거로 삼아 새 자료를 무시하는 회귀가 관찰되었다. 따라서 assistant 메시지는
    제외하고, user 메시지만 유지해 대화 흐름은 보존한다.
    """
    sanitized: List[Dict[str, Any]] = []
    for msg in history:
        if not isinstance(msg, dict):
            continue
        if msg.get('role') == 'user':
            sanitized.append(msg)
    return sanitized


def _extract_key_excerpts(
    query: str,
    chunk_hits: List[ChunkHit],
    *,
    max_chars: int = 320,
    window: int = 150,
) -> List[tuple]:
    """질문/검색어가 chunk content 안에서 매치되는 주변 텍스트를 잘라낸다.

    v0.5.3 QA 보강 S3 — 전체 chunk content 를 그대로 나열만 하면 LLM 이 핵심
    수치를 흘리는 회귀가 있어, 매치 주변 window 를 '핵심 발췌' 로 먼저 보여 준다.

    매칭 우선순위: ① 전체 phrase (공백 포함) → ② 2글자 이상 token 중 가장 긴 것.
    chunk 별로 최대 한 개 발췌만 추출, 발췌는 `max_chars` 로 잘라낸다.
    반환: [(자료번호(1-base), 발췌 텍스트), ...]
    """
    q = (query or '').strip()
    if not q or not chunk_hits:
        return []

    tokens = sorted(
        {t for t in q.split() if len(t) >= 2},
        key=len,
        reverse=True,
    )
    candidates = [q] + [t for t in tokens if t != q]

    excerpts: List[tuple] = []
    for i, hit in enumerate(chunk_hits, 1):
        content = hit.content or ''
        if not content:
            continue
        for cand in candidates:
            idx = content.find(cand)
            if idx < 0:
                continue
            start = max(0, idx - window)
            end = min(len(content), idx + len(cand) + window)
            snippet = content[start:end].strip()
            if len(snippet) > max_chars:
                snippet = snippet[:max_chars].rstrip() + '…'
            excerpts.append((i, snippet))
            break
    return excerpts


def _render_user_content(
    question: str,
    chunk_hits: List[ChunkHit],
    qa_hits: List[QAHit],
    *,
    search_query: Optional[str] = None,
) -> str:
    """현재 turn의 user 메시지 본문을 조립."""
    sections: List[str] = []

    # 회사 자료 섹션 (청크가 있을 때만)
    if chunk_hits:
        # 핵심 발췌: 질문/검색어가 청크 안에서 매치되는 주변 window 를 먼저 노출.
        # 전체 chunk content 가 길어 LLM 이 핵심 수치를 흘리는 회귀 방지용 (v0.5.3 QA 보강 S3).
        query_source = (search_query or '').strip() or question
        excerpts = _extract_key_excerpts(query_source, chunk_hits)
        if excerpts:
            for idx, snippet in excerpts:
                sections.append(f'[자료 {idx} 핵심 발췌]')
                sections.append(snippet)
                sections.append('')
        sections.append('=== 회사 자료 ===')
        sections.append(load_prompt('chat/source_instruction.md'))
        sections.append('')
        for i, hit in enumerate(chunk_hits, 1):
            sections.append(hit.content)
            sections.append('')
    else:
        # 검색 결과 없음 — 일반 지식 답변 차단 가드
        sections.append('=== 중요 ===')
        sections.append(load_prompt('chat/no_sources_guard.md'))
        sections.append('')

    # 과거 참고 답변 섹션 (QAPair가 있을 때만)
    if qa_hits:
        sections.append('=== 과거 참고 답변 ===')
        sections.append(load_prompt('chat/qa_instruction.md'))
        sections.append('')
        for hit in qa_hits:
            sections.append(f'Q: {hit.question}')
            sections.append(f'A: {hit.answer}')
            sections.append('')

    # 이번 질문
    sections.append('=== 사용자 질문 ===')
    rewritten = (search_query or '').strip()
    if rewritten and rewritten != question.strip():
        # query_rewriter 가 후속 질문을 self-contained 검색어로 풀었다면,
        # raw 원문은 UI/ChatLog 에 그대로 두되 LLM 에는 둘 다 보여 의도가
        # 사라지지 않게 한다 (예: '비싼거' → '경조사 중 가장 비싼 항목').
        sections.append(f'원문: {question}')
        sections.append(f'대화 맥락 반영 질문: {rewritten}')
    else:
        sections.append(question)

    return '\n'.join(sections)
