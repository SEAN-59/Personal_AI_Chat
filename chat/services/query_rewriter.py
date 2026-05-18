"""검색어 재작성 (Phase 4-3).

사용자의 후속 질문("비싼거", "첫번째") 이 직전 대화 맥락을 참조할 때,
retrieval 은 해당 문자열만 받으면 엉뚱한 문서를 뽑아온다. 이 모듈은
"대화 맥락 + 현재 질문" 을 cheap LLM 으로 한 번 정제해 self-contained
검색어로 바꿔준다. 최종 답변 LLM 호출은 건드리지 않는다 — 원본 질문은
그대로 UI·ChatLog 에 흐르고, 여기서 만든 문자열은 retrieve_documents /
find_canonical_qa 에만 전달된다.

fallback:
    - history 가 비어 있으면 원본 질문 반환 (LLM 호출 없음).
    - LLM 이 sentinel 'NOOP' 을 내면 원본 질문 반환.
    - OpenAI 호출 실패·빈 응답·포맷 이상은 warning 로그 + 원본 질문 반환.

이 세 fallback 중 하나라도 걸리면 기존(Phase 4-2) 동작 그대로 유지돼
회귀 0 을 보장한다.
"""

from __future__ import annotations

import logging
import re
from typing import Any, Dict, List, Optional, Tuple

from chat.services.prompt_loader import load_prompt
from chat.services.single_shot.llm import run_chat_completion
from chat.services.single_shot.types import QueryPipelineError


logger = logging.getLogger(__name__)


# 재작성에 사용할 history 턴 수 (user/assistant 합산 메시지 개수 기준).
# 너무 많이 넣으면 오래된 맥락이 오히려 노이즈가 되고 토큰도 늘어난다.
REWRITE_HISTORY_TURNS = 6  # 사용자 3턴 + 어시스턴트 3턴 수준

# LLM 이 '이미 자립적이라 손대지 않아도 됨' 을 알리는 약속된 응답.
NOOP_SENTINEL = 'NOOP'

# 프롬프트 파일 (prompt_registry 의 'chat-query-rewriter' 와 동일 경로)
_PROMPT_PATH = 'chat/query_rewriter.md'

# 비정상적으로 긴 응답은 프롬프트 탈선으로 간주하고 버린다.
_MAX_REWRITE_LEN = 200


# ---------------------------------------------------------------------------
# v0.5.4 — monetary metric guard
#
# 도메인 어휘/행 이름/숫자 하드코딩 없이, "금액 축으로 비교를 요청한 follow-up
# 인지" 만 generic 단서로 판정한다. 단서가 모이면 cleaned rewrite 에 generic
# metric phrase (`지급금액 기준`) 를 덧붙여 retriever 가 기간/일수 등 비-금액
# chunk 로 흐르는 회귀를 차단한다.
# ---------------------------------------------------------------------------

# 가격 축 비교 신호. 부분 문자열 매칭으로 `비싼거`/`더 비싸`/`2번째로 비싼` 같은
# 변형을 모두 포착.
_MONETARY_COMPARATIVE_HINTS = ('비싼', '비싸', '싼거', '싼것', '저렴')

# 직전 답변/표가 금전 축임을 시사하는 generic metric 단어. 도메인 어휘는 포함
# 하지 않는다.
_MONETARY_HISTORY_METRIC_WORDS = (
    '금액', '지원금액', '지급금액', '지원금',
    '비용', '한도', '단가', '가격', '요금',
)

# 금액 표기 정규식. 숫자 뒤에 단위(`만원`/`만 원`/`만`/`억원`/`억`/`원`) 가 붙은
# 형태만 본다. 단일 문자 `원` 의 substring 매칭은 의도적으로 회피해 일반 단어
# 안에 `원` 이 들어가는 경우의 false positive 를 막는다.
_AMOUNT_PATTERN = re.compile(
    r'\d[\d,\.]*\s*(?:만\s*원|만원|만|억\s*원|억원|억|원)'
)

# 이미 rewrite 가 금전 축을 명시한 경우엔 손대지 않는다.
_MONETARY_METRIC_TOKENS_IN_REWRITE = (
    '금액', '지급금액', '지원금액', '지원금', '비용', '한도',
    '단가', '가격', '요금',
)

# 사용자가 명시적으로 기간/일수 축을 물은 경우엔 guard 발동 금지.
_DURATION_AXIS_HINTS = (
    '휴가', '일수', '며칠', '몇일', '기간', '일째', '날짜',
)

# 부착할 generic metric phrase. 회사 고유어 없음.
_MONETARY_METRIC_SUFFIX = '지급금액 기준'


def rewrite_query_with_history(
    question: str,
    history: List[Dict[str, Any]],
) -> Tuple[str, Optional[Any], Optional[str]]:
    """검색용으로 정제된 쿼리와 (있다면) 호출 usage 를 반환.

    반환값은 `(search_query, usage, model)`. LLM 호출이 없었거나 실패해서
    원본을 그대로 쓴 경우 `usage` / `model` 은 `None`. 호출부(pipeline)
    에서 usage 가 있으면 TokenUsage 레코드로 기록한다.
    """
    if not history:
        return question, None, None

    history_slice = _tail_history(history, REWRITE_HISTORY_TURNS)
    if not history_slice:
        return question, None, None

    try:
        rewritten, usage, model = _call_rewriter_llm(question, history_slice)
    except QueryPipelineError as exc:
        logger.warning('쿼리 재작성 실패, 원본 사용: %s', exc)
        return question, None, None
    except Exception as exc:  # noqa: BLE001 — OpenAI SDK 비정형 예외 방어
        logger.warning('쿼리 재작성 중 예기치 못한 오류, 원본 사용: %s', exc)
        return question, None, None

    cleaned = _clean_llm_output(rewritten)
    if not cleaned or _is_noop(cleaned):
        return question, usage, model

    if len(cleaned) > _MAX_REWRITE_LEN:
        logger.warning(
            '쿼리 재작성 결과가 비정상적으로 길어 원본 사용 (len=%d)',
            len(cleaned),
        )
        return question, usage, model

    cleaned = _apply_monetary_metric_guard(question, history_slice, cleaned)

    logger.info('쿼리 재작성: %r → %r', question, cleaned)
    return cleaned, usage, model


def _apply_monetary_metric_guard(
    question: str,
    history_slice: List[Dict[str, Any]],
    cleaned: str,
) -> str:
    """가격 축 follow-up 에 금액 metric 토큰이 빠져있으면 generic suffix 부착.

    프롬프트가 metric 보존 규칙을 지시해도 LLM 이 흘릴 수 있어, deterministic
    guard 로 retrieval 입력을 안정화한다. 도메인 어휘 하드코딩 없음.
    """
    q = (question or '').strip()
    if not q:
        return cleaned

    # (a) 현재 질문이 가격 축 비교 follow-up 인가?
    if not any(hint in q for hint in _MONETARY_COMPARATIVE_HINTS):
        return cleaned

    # (b) 사용자가 명시적으로 기간/휴가 축을 물었다면 guard 발동 금지.
    if any(hint in q for hint in _DURATION_AXIS_HINTS):
        return cleaned

    # (c) 직전 history 에 금전 단위 단서가 있는가? (generic 단어 OR 금액 패턴)
    history_blob = ' '.join(
        (m.get('content') or '') for m in history_slice
    )
    has_metric_word = any(
        word in history_blob for word in _MONETARY_HISTORY_METRIC_WORDS
    )
    has_amount = bool(_AMOUNT_PATTERN.search(history_blob))
    if not (has_metric_word or has_amount):
        return cleaned

    # (d) 이미 rewrite 가 금전 metric 을 포함한다면 손대지 않는다.
    if any(tok in cleaned for tok in _MONETARY_METRIC_TOKENS_IN_REWRITE):
        return cleaned

    return f'{cleaned} {_MONETARY_METRIC_SUFFIX}'


# ---------------------------------------------------------------------------
# 내부
# ---------------------------------------------------------------------------

def _tail_history(
    history: List[Dict[str, Any]],
    max_messages: int,
) -> List[Dict[str, Any]]:
    """최근 N 개 메시지만 잘라서 반환 (role=user/assistant 만)."""
    trimmed = [
        msg for msg in history
        if msg.get('role') in ('user', 'assistant') and msg.get('content')
    ]
    return trimmed[-max_messages:]


def _call_rewriter_llm(
    question: str,
    history_slice: List[Dict[str, Any]],
) -> Tuple[str, Any, str]:
    """rewriter 프롬프트 + 현재 맥락을 LLM 으로 보내 원문자열을 돌려받음."""
    system_prompt = load_prompt(_PROMPT_PATH)
    user_payload = _format_user_payload(question, history_slice)
    messages = [
        {'role': 'system', 'content': system_prompt},
        {'role': 'user', 'content': user_payload},
    ]
    return run_chat_completion(messages)


def _format_user_payload(
    question: str,
    history_slice: List[Dict[str, Any]],
) -> str:
    """LLM 에 전달할 user 메시지 — 최근 대화 + 현재 질문 구조."""
    lines = ['Conversation:']
    for msg in history_slice:
        role = msg['role']
        content = msg['content'].strip()
        lines.append(f'{role}: {content}')
    lines.append('')
    lines.append(f'Current question: {question.strip()}')
    lines.append('Rewrite:')
    return '\n'.join(lines)


def _clean_llm_output(raw: str) -> str:
    """따옴표·접두어·마침표 등 흔한 프롬프트 탈선을 최소한만 정리."""
    text = (raw or '').strip()
    if not text:
        return ''
    # 첫 줄만 사용 (프롬프트 규칙상 한 줄 출력)
    text = text.splitlines()[0].strip()
    # 흔한 접두어 제거
    for prefix in ('검색어:', 'Rewrite:', 'rewrite:', 'Query:', 'query:'):
        if text.startswith(prefix):
            text = text[len(prefix):].strip()
    # 외곽 따옴표 제거
    if len(text) >= 2 and text[0] == text[-1] and text[0] in ('"', "'", '`'):
        text = text[1:-1].strip()
    return text


def _is_noop(text: str) -> bool:
    return text.strip().upper() == NOOP_SENTINEL
