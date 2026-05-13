"""단계 6: OpenAI chat completion 호출.

외부에서 부르는 함수는 `run_chat_completion(messages, model=None)` 하나. 내부는 기존
query_pipeline 과 동일하게 `OPENAI_API_KEY` / `OPENAI_MODEL` 을 읽고
`temperature=0` 으로 호출한다. 호출 실패는 `QueryPipelineError` 로 래핑.

Phase 9-1: `model` 키워드 인자 추가. None 이면 기존처럼 `OPENAI_MODEL` env 로 폴백 —
기존 `run_chat_completion(messages)` 호출처는 회귀 0. LLM Router 같은 보조 호출처가
`OPENAI_AUX_MODEL` 등을 명시적으로 넘기기 위해 사용.
"""

import os
from typing import Any, Dict, List, Optional, Tuple

from openai import OpenAI

from chat.services.single_shot.types import QueryPipelineError


DEFAULT_MODEL = 'gpt-4o-mini'


def run_chat_completion(
    messages: List[Dict[str, Any]],
    model: Optional[str] = None,
) -> Tuple[str, Any, str]:
    """메시지 배열을 받아 (응답 텍스트, usage 객체, 사용한 모델명) 을 반환.

    usage 는 OpenAI SDK 가 돌려주는 원본 구조 그대로다. 호출부에서 필요한
    필드(prompt_tokens, completion_tokens, total_tokens)만 꺼내 쓴다.

    `model=None` 이면 `OPENAI_MODEL` env (또는 `DEFAULT_MODEL`) 로 폴백.
    """
    api_key = os.environ.get('OPENAI_API_KEY')
    if not api_key:
        raise QueryPipelineError('OPENAI_API_KEY가 설정되지 않았습니다.')
    if model is None:
        model = os.environ.get('OPENAI_MODEL', DEFAULT_MODEL)

    try:
        client = OpenAI(api_key=api_key)
        completion = client.chat.completions.create(
            model=model,
            messages=messages,
            temperature=0,   # 동일 질문엔 동일 답변이 나오도록 (사실·수치 중심 챗봇)
        )
    except Exception as exc:
        raise QueryPipelineError(f'OpenAI 호출 실패: {exc}') from exc

    reply = completion.choices[0].message.content or ''
    return reply, completion.usage, model
