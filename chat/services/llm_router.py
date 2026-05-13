"""LLM 기반 의도 분류기 (Phase 9-1).

사용자 질문을 ALL_ROUTES 중 하나로 분류만 한다. workflow_key 매핑은 본 모듈의
책임이 아니다 — DB RouterRule 전담. 본 모듈의 자체 dataclass `LlmRouteResult`
(neutral) 만 반환하고, 호출자(`question_router`) 가 라우팅 결정 dataclass 로
변환한다.

`question_router` 의 라우팅 결정 타입은 본 모듈에서 import 하지 않는다 —
순환 차단. 이 파일 안에는 해당 심볼이 어떤 형태(import / 주석 / docstring /
문자열 리터럴 / 타입 힌트)로도 등장하지 않는다.
"""

from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

from chat.graph.routes import ALL_ROUTES
from chat.services.prompt_loader import load_prompt
from chat.services.single_shot.llm import run_chat_completion
from chat.services.single_shot.postprocess import record_token_usage
from chat.services.token_purpose import PURPOSE_LLM_ROUTER


logger = logging.getLogger(__name__)


# user/assistant 합산 메시지 개수 기준. 너무 많이 넣으면 노이즈 + 토큰 비용 증가.
_ROUTER_HISTORY_TURNS = 3

# reason 비정상 길이 컷오프 (운영자-facing 로그/UI 보호용).
_MAX_REASON_LEN = 120

# 프롬프트 파일 (prompt_registry 의 'chat-llm-router' entry 와 동일 경로).
_PROMPT_PATH = 'chat/llm_router.md'


@dataclass(frozen=True)
class LlmRouteResult:
    """LLM 라우터의 의도 분류 결과 (검증 완료).

    필드는 정확히 두 개. workflow_key 필드는 의도적으로 두지 않는다 —
    LLM 출력에 workflow_key 가 와도 타입 수준에서 자연 드롭된다.
    호출자가 라우팅 결정 dataclass 로 변환할 책임을 진다.
    """

    route: str    # ALL_ROUTES 멤버 (검증 완료)
    reason: str   # 'llm:<짧은 근거>' 또는 'llm'


def _tail_history(
    history: List[Dict[str, Any]],
    max_messages: int,
) -> List[Dict[str, Any]]:
    """최근 N 개 메시지만 잘라서 반환 (role=user/assistant + content 비어있지 않음)."""
    trimmed = [
        msg for msg in history
        if msg.get('role') in ('user', 'assistant') and msg.get('content')
    ]
    return trimmed[-max_messages:]


def _format_user_payload(
    question: str,
    history_slice: List[Dict[str, Any]],
) -> str:
    """LLM 에 전달할 user 메시지 — 최근 대화 + 현재 질문 구조.

    `query_rewriter._format_user_payload` 와 동일 라인 포맷, 마지막만 `Route:` 로
    바뀌어 LLM 이 라우터 출력으로 전환되도록 신호.
    """
    lines = ['Conversation:']
    for msg in history_slice:
        role = msg['role']
        content = msg['content'].strip()
        lines.append(f'{role}: {content}')
    lines.append('')
    lines.append(f'Current question: {question.strip()}')
    lines.append('Route:')
    return '\n'.join(lines)


def _parse_and_validate(text: str) -> Optional[LlmRouteResult]:
    """LLM 출력 문자열을 검증해 LlmRouteResult 또는 None 반환.

    검증 단계:
      1. JSON 파싱 성공
      2. dict 타입
      3. route 가 ALL_ROUTES 멤버
      4. reason 정제 (strip + 길이 컷오프)
      5. workflow_key 는 있어도 무시 (LlmRouteResult 가 필드를 안 가짐)
    어디서 실패하든 None → 호출자가 키워드 fallback 으로 진행.
    """
    try:
        parsed = json.loads(text)
    except (ValueError, TypeError):
        return None

    if not isinstance(parsed, dict):
        return None

    route = parsed.get('route')
    if route not in ALL_ROUTES:
        return None

    raw_reason = parsed.get('reason', '')
    if not isinstance(raw_reason, str):
        reason = ''
    else:
        reason = raw_reason.strip()
        if len(reason) > _MAX_REASON_LEN:
            reason = reason[:_MAX_REASON_LEN]

    return LlmRouteResult(route=route, reason=reason)


def _llm_classify(
    question: str,
    history: List[Dict[str, Any]],
) -> Optional[LlmRouteResult]:
    """LLM 으로 질문 의도를 분류. 실패 시 None → 호출자가 키워드 fallback.

    `history` 는 list 라고 가정 — 호출자(`route_question`) 가 `history or []` 로
    None 분기를 차단한다.

    `record_token_usage(..., purpose=PURPOSE_LLM_ROUTER)` 를 정확히 1 회 호출.
    """
    try:
        system_prompt = load_prompt(_PROMPT_PATH)
        user_payload = _format_user_payload(
            question, _tail_history(history, _ROUTER_HISTORY_TURNS),
        )
        messages = [
            {'role': 'system', 'content': system_prompt},
            {'role': 'user', 'content': user_payload},
        ]
        aux_model = os.environ.get('OPENAI_AUX_MODEL') or os.environ.get('OPENAI_MODEL')
        reply, usage, model = run_chat_completion(messages, model=aux_model)
        record_token_usage(model, usage, purpose=PURPOSE_LLM_ROUTER)
    except Exception as exc:  # noqa: BLE001 — OpenAI SDK 비정형 예외 방어
        logger.warning('LLM 라우터 실패, 키워드 fallback: %s', exc)
        return None

    return _parse_and_validate(reply)
