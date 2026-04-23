"""Deprecated shim — Phase 3 리팩토링 중 하위 호환용으로만 남아 있다.

신규 코드는 아래를 직접 import 할 것:
    - chat.services.single_shot.pipeline.run_single_shot
    - chat.services.single_shot.types.QueryResult / QueryPipelineError

이 모듈은 Phase 3 PR 마지막 커밋에서 삭제된다.
"""

from typing import Dict, List, Optional

from chat.services.single_shot.pipeline import run_single_shot
from chat.services.single_shot.types import QueryPipelineError, QueryResult


def answer_question(
    question: str,
    history: Optional[List[Dict]] = None,
) -> QueryResult:
    """기존 호출자를 위한 얇은 delegator. `run_single_shot` 을 그대로 호출."""
    return run_single_shot(question, history=history)


__all__ = ['answer_question', 'QueryPipelineError', 'QueryResult']
