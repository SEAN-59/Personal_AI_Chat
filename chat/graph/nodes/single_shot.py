"""Single-shot node — single_shot 패키지의 파이프라인을 graph 에서 실행.

Phase 3 에서 `chat.services.single_shot.pipeline.run_single_shot` 으로 직접
연결. 예외는 node 안에서만 잡아 `state.error` 로 싣고, 다른 예외 타입은 그대로
올라가 Django 500 경로로 간다.
"""

from chat.graph.state import GraphState, processing_question, raw_question
from chat.services.single_shot.pipeline import run_single_shot
from chat.services.single_shot.types import QueryPipelineError


def single_shot_node(state: GraphState) -> dict:
    """normalized + raw 를 분리해 run_single_shot 에 전달.

    v0.5.2 — rewriter/retrieval/prompt_builder 입력은 normalized, ChatLog.question
    저장은 raw. raw 가 보존되도록 분리 전달.
    """
    try:
        result = run_single_shot(
            processing_question(state),
            history=state.get('history', []),
            raw_question=raw_question(state),
            normalization_applied=state.get('normalization_applied') or [],
        )
    except QueryPipelineError as exc:
        return {'error': str(exc)}
    return {'result': result}
