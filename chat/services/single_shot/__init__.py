"""Single-shot 채팅 파이프라인 패키지.

이 패키지는 "질문 하나 → 답변 하나" 형태의 기존 single-shot RAG 흐름을
작은 helper 단위로 분해한 것이다. 외부에서는 보통 `pipeline.run_single_shot`
하나만 호출한다. helper 들(retrieval / qa_cache / prompting / llm / postprocess)은
LangGraph 노드나 향후 workflow/agent 가 필요한 부분만 골라 재사용할 수 있도록
서로 독립적이다.

공통 규칙 — 이후 Phase 5~7 에서도 같은 기준을 따른다.

1. History 는 view 에서만 load/save 한다.
   - `chat/views/message.py` 만 `chat.services.history_service` 를 쓴다.
   - graph 노드 / single_shot helper / workflow / agent 모두 history 를 저장하지 않는다.
   - service 계층은 history 를 read-only 파라미터로만 받는다.

2. Error 는 `QueryPipelineError` 만 raise.
   - 모든 service helper 는 의도된 실패를 `QueryPipelineError` 로 돌려보낸다.
   - graph 노드는 이 예외를 잡아 `state.error` 로 적재.
   - view 는 `state.error` 가 있으면 502 로 변환.
   - 그 외 예외는 상위로 올려 Django 의 500 경로로.

3. TokenUsage 기록은 `postprocess.record_token_usage` 에서만.
   - OpenAI 호출 직후 한 번만 기록. 다른 위치에서 중복 기록 금지.
   - 캐시 히트(OpenAI 호출 없음) 케이스에서는 기록하지 않는다.

4. ChatLog 저장은 `postprocess.persist_chat_log` 에서만.
   - 자료 기반 답변(청크 있음 + no-info 아님 + casual 아님) 때만 저장.
   - 캐시 히트 시 별도 ChatLog 를 만들지 않는다 (기존 규칙).

5. Sources 구성은 `postprocess.build_sources` 에서만.
   - chunk 의 document_id 기준으로 중복 제거.
   - no-info / casual 응답일 때는 빈 리스트.

6. no-info / casual 분류는 `postprocess.classify_reply` 가 단일 책임.
   - 분류 상수(마커, 길이)도 이 모듈에 모아둠.
   - 호출부에선 `(is_no_info, is_casual)` 튜플만 받아 분기.
"""
