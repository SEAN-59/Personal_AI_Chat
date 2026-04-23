"""Single-shot 파이프라인의 공용 타입.

helper 들과 graph 레이어가 공통으로 참조하는 dataclass / 예외를 둔다.
순환 import 를 피하기 위해 이 모듈은 다른 single_shot helper 를 import 하지 않는다.
"""

from dataclasses import dataclass
from typing import Dict, List, Optional


@dataclass
class QueryResult:
    """파이프라인 최종 출력 — view 의 JSON 응답에 1:1 로 매핑된다."""

    reply: str
    sources: List[Dict]                 # [{'name': ..., 'url': ...}, ...]
    total_tokens: int
    chat_log_id: Optional[int] = None   # 저장된 ChatLog id (피드백 버튼용)


class QueryPipelineError(Exception):
    """파이프라인 내부에서 발생한, view 에 502 로 보내야 하는 오류."""
