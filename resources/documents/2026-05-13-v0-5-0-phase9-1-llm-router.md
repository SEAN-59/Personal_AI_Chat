# 2026-05-13 개발 로그 — v0.5.0 Phase 9-1: LLM Router + 인프라

## 요약

- `llm_router` purpose / prompt / 단위 테스트 추가.
- `route_question(question, history)` 로 확장하고 `router_node` 가 history 를 전달.
- `run_chat_completion(model=None)` 지원으로 라우터 전용 모델 선택 기반 마련.
- `지급일` 계열 DATE_CONDITION 보호 우선순위와 공백 변이(`지급 일`) 라우팅 회귀를 보강.
- agent tool schema alias 정규화로 `retrieve_documents({"text": ...})` 호출도 `query` 로 처리.

## 검증

- `python manage.py check`
- `chat.tests.test_llm_router`
- `chat.tests.test_agent_tools`, `chat.tests.test_agent_tools_builtin`, `chat.tests.test_agent_react`
- `chat.tests.test_routing_e2e`, `chat.tests.test_pipeline_smoke`, `chat.tests.test_graph_agent_wiring`
