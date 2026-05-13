# v0.5.1 — LLM Router Follow-up Stabilization (#83)

- Issue: #83 fix: Stabilize LLM router follow-up handling
- Milestone: v0.5.1: LLM Router Stabilization
- Plan: `resources/plans/v_0_x/v_0_5_1/detail/0.5.1_llm_router_followup_stabilization_개발_플랜.md`

## 무엇을 바꿨나
v0.5.0 LLM Router 도입 후 fragile 했던 9개 follow-up 케이스의 라우팅·재작성 동작을 prompt 보강 + 회귀 테스트로 박제했다. 구조 변경 없이 prompt 와 test 위주의 변경.

### prompt 보강
- `assets/prompts/chat/llm_router.md`
  - follow-up fragment(비교·순위·지시어·가정형) 는 `single_shot` 으로 분류한다는 규칙 + 예시 추가.
  - `agent` 정의를 "서로 다른 규정/문서 간 비교·추천" + "외부 도구·탐색" 으로 좁힘. 같은 문서 안의 단순 비교 fragment 가 agent 로 새지 않게.
- `assets/prompts/chat/query_rewriter.md`
  - exclusion/negation follow-up(`이거 말고`, `그거 말고`, `다른 거`, `더 있을건데`) 보존 규칙 추가.
  - `이거 말고 더 있을건데` example 추가.

### 회귀 테스트
- `chat/tests/test_llm_router.py`
  - `LlmRouterPromptContentTests` — llm_router prompt content guard (route 3개 + follow-up 키워드 + agent 정의 키워드).
  - `LlmTierFollowupCallCountTests` — LLM tier 4건 (`비싼거`, `2번째로 비싼거`, `이거 말고 더 있을건데`, `만약 5년 근무하면?`) 이 `_llm_classify` 를 1회 호출하고 single_shot 으로 분류됨을 박제. history 전달 경로도 확인.
  - `DateConditionPriorityTests.test_date_condition_5_fragile_cases_skip_llm_call` — DATE_CONDITION 5건 (`급여 지급일은?`, `지급 일`, `정산일`, `만료일`, `마감일`) 이 `_llm_classify` 를 0회 호출.
- `chat/tests/test_routing_e2e.py`
  - `V051DateConditionFragileCaseTests` — §3 정확한 fragile 문자열로 route=agent / reason=date_condition_keyword 박제.
- `chat/tests/test_query_rewriter.py`
  - prompt content guard (exclusion 규칙 + example).
  - `이거 말고 더 있을건데` cleanup 보존, `_MAX_REWRITE_LEN` 초과 fallback, `_call_rewriter_llm` 비정형 예외 fallback fixture 추가.
- `chat/tests/test_router_followup_e2e.py` (신규)
  - `run_single_shot` direct 호출로 LLM tier 4건의 rewriter 결과가 `build_single_shot_messages` 의 `search_query` 로 전달되는지, rewriter usage 가 `PURPOSE_QUERY_REWRITER` 로 기록되는지 박제. 그래프/`_llm_classify` 는 다루지 않음 (담당 분리).

## 테스트 결과
- `docker compose exec -T web env OPENAI_API_KEY= python manage.py check` — 통과 (0 issues).
- `docker compose exec -T web env OPENAI_API_KEY= python manage.py test chat.tests.test_llm_router chat.tests.test_routing_e2e chat.tests.test_query_rewriter chat.tests.test_prompt_builder chat.tests.test_pipeline_smoke chat.tests.test_token_usage_purpose_call_sites chat.tests.test_router_followup_e2e -v 2 --keepdb` — 94 tests OK (0.573s).

## DoD 매핑 (plan §10)
- [x] §3 의 9개 case 가 route / rewrite / `_llm_classify` 호출 횟수까지 mock 테스트로 통과
- [x] DATE_CONDITION 5건은 `_llm_classify` 가 호출되지 않음을 단언
- [x] `python manage.py check` 통과
- [x] §7 의 focused test 전부 통과 (`OPENAI_API_KEY=` 빈 환경)
- [ ] 수동 QA A/B/C — 별도 실행 필요 (BO RouterRule 충돌 확인 후 진행)
- [x] README + 본 dev log 업데이트
- [x] router/rewriter 구조 변경 없음 (diff 가 prompt/test 위주)

## 미해결 / 후속
- 수동 QA(시나리오 A 경조사 / B 퇴직금 / C 동의어 날짜) 는 사용자가 직접 실행. BO RouterRule 충돌 확인 + LLM 라우터 카운트 baseline 기록 필요.
- `agent` 가 "서로 다른 규정 간 비교/도구 탐색" 으로 좁혀졌으므로 일반 비교 질문이 single_shot 으로 빠질 가능성 — prompt 가 example 로 충분히 분리하는지는 운영 데이터에서 관찰.
