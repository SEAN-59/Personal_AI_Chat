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

    # ② 과거 대화 히스토리 그대로 이어붙임
    messages.extend(history)

    # ③ 이번 turn의 user 메시지: 자료 + 과거참고 + 질문
    user_content = _render_user_content(
        question, chunk_hits, qa_hits, search_query=search_query,
    )
    messages.append({'role': 'user', 'content': user_content})

    return messages


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
