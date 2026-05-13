"""Phase 9-1 — `chat.services.llm_router` 단위 / 통합 테스트.

§6.1~§6.5: `_llm_classify` 단위 — `chat.services.llm_router.run_chat_completion`
및 `chat.services.llm_router.record_token_usage` (call-site binding) 을 patch.
§6.6~§6.7: `route_question` 통합 — `chat.services.question_router._llm_classify`
(call-site binding) 을 patch.
"""

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from django.test import SimpleTestCase, TestCase

from chat.graph.routes import ROUTE_AGENT, ROUTE_SINGLE_SHOT, ROUTE_WORKFLOW
from chat.models import RouterRule
from chat.services import llm_router
from chat.services.llm_router import (
    LlmRouteResult,
    _llm_classify,
    _parse_and_validate,
)
from chat.services.question_router import RouteDecision, route_question
from chat.services.token_purpose import PURPOSE_LLM_ROUTER


def _fake_usage(prompt=10, completion=5, total=15):
    """`record_token_usage` 가 읽는 속성만 가진 가벼운 usage stub."""
    return SimpleNamespace(
        prompt_tokens=prompt,
        completion_tokens=completion,
        total_tokens=total,
    )


# ---------------------------------------------------------------------------
# §6.1 정상 경로
# ---------------------------------------------------------------------------

class LlmClassifyHappyPathTests(SimpleTestCase):
    """LLM 출력이 정상 JSON 일 때 LlmRouteResult 반환."""

    def _call(self, reply_text):
        with patch(
            'chat.services.llm_router.run_chat_completion',
            return_value=(reply_text, _fake_usage(), 'gpt-aux'),
        ), patch(
            'chat.services.llm_router.record_token_usage',
        ):
            return _llm_classify('aQ', [])

    def test_llm_classify_returns_single_shot_for_definition(self):
        result = self._call('{"route":"single_shot","reason":"llm:definition"}')
        self.assertIsInstance(result, LlmRouteResult)
        self.assertEqual(result.route, ROUTE_SINGLE_SHOT)
        self.assertEqual(result.reason, 'llm:definition')

    def test_llm_classify_returns_workflow_for_calculation(self):
        result = self._call('{"route":"workflow","reason":"llm:calc"}')
        self.assertEqual(result.route, ROUTE_WORKFLOW)
        self.assertEqual(result.reason, 'llm:calc')

    def test_llm_classify_returns_agent_for_comparison(self):
        result = self._call('{"route":"agent","reason":"llm:compare"}')
        self.assertEqual(result.route, ROUTE_AGENT)
        self.assertEqual(result.reason, 'llm:compare')


# ---------------------------------------------------------------------------
# §6.2 LLM 출력 검증 계약
# ---------------------------------------------------------------------------

class LlmOutputValidationTests(SimpleTestCase):
    """`_parse_and_validate` 가 비정상 출력에서 None 을 돌려준다."""

    def test_llm_classify_handles_invalid_json(self):
        self.assertIsNone(_parse_and_validate('not json'))

    def test_llm_classify_rejects_non_object_json(self):
        self.assertIsNone(_parse_and_validate('[1,2,3]'))
        self.assertIsNone(_parse_and_validate('null'))
        self.assertIsNone(_parse_and_validate('"x"'))

    def test_llm_classify_rejects_unknown_route(self):
        self.assertIsNone(_parse_and_validate('{"route":"chitchat"}'))

    def test_llm_classify_rejects_missing_route(self):
        self.assertIsNone(_parse_and_validate('{}'))
        self.assertIsNone(_parse_and_validate('{"reason":"x"}'))

    def test_llm_classify_trims_reason(self):
        result = _parse_and_validate(
            '{"route":"agent","reason":"   spaced   "}'
        )
        self.assertIsNotNone(result)
        self.assertEqual(result.reason, 'spaced')

    def test_llm_classify_truncates_long_reason(self):
        long_reason = 'x' * 500
        result = _parse_and_validate(
            '{"route":"single_shot","reason":"%s"}' % long_reason
        )
        self.assertIsNotNone(result)
        self.assertEqual(len(result.reason), 120)

    def test_llm_classify_drops_workflow_key_from_llm(self):
        # LLM 이 workflow_key 를 내도 LlmRouteResult 에는 필드가 없다 — 타입 수준 드롭.
        result = _parse_and_validate(
            '{"route":"workflow","reason":"llm","workflow_key":"date_calculation"}'
        )
        self.assertIsNotNone(result)
        self.assertFalse(hasattr(result, 'workflow_key'))
        # 그리고 route_question 변환 시 workflow_key='' 강제.
        # SimpleTestCase 라 DB 접근 차단 — `_match_db_rules` 까지 mock 해 Tier 1 우회.
        with patch(
            'chat.services.question_router._match_db_rules',
            return_value=None,
        ), patch(
            'chat.services.question_router._llm_classify',
            return_value=result,
        ):
            decision = route_question('foo', [])
        self.assertEqual(decision.workflow_key, '')

    def test_llm_classify_accepts_non_string_reason(self):
        # reason 이 null/number 라도 빈 reason 으로 LlmRouteResult 반환.
        result_null = _parse_and_validate('{"route":"agent","reason":null}')
        self.assertIsNotNone(result_null)
        self.assertEqual(result_null.reason, '')

        result_num = _parse_and_validate('{"route":"agent","reason":123}')
        self.assertIsNotNone(result_num)
        self.assertEqual(result_num.reason, '')


# ---------------------------------------------------------------------------
# §6.3 순환 import 회피 smoke
# ---------------------------------------------------------------------------

class CyclicImportSmokeTests(SimpleTestCase):

    def test_module_imports_without_route_decision(self):
        # 모듈이 로드되어 있고, RouteDecision 심볼은 노출되지 않음.
        self.assertFalse(hasattr(llm_router, 'RouteDecision'))


# ---------------------------------------------------------------------------
# §6.4 Token usage 기록 계약
# ---------------------------------------------------------------------------

class TokenUsageRecordTests(SimpleTestCase):

    def test_llm_classify_records_token_usage_with_llm_router_purpose(self):
        fake_usage = _fake_usage(prompt=80, completion=40, total=120)
        with patch(
            'chat.services.llm_router.run_chat_completion',
            return_value=(
                '{"route":"single_shot","reason":"llm:def"}',
                fake_usage,
                'gpt-aux',
            ),
        ), patch(
            'chat.services.llm_router.record_token_usage',
        ) as record_mock:
            _llm_classify('aQ', [])

        record_mock.assert_called_once()
        args, kwargs = record_mock.call_args
        self.assertEqual(args[0], 'gpt-aux')
        self.assertIs(args[1], fake_usage)
        self.assertEqual(kwargs.get('purpose'), PURPOSE_LLM_ROUTER)


# ---------------------------------------------------------------------------
# §6.5 History payload — `_llm_classify` 단위 (call-site mock)
# ---------------------------------------------------------------------------

class HistoryPayloadTests(SimpleTestCase):

    def _capture_messages(self, history):
        captured = {}

        def fake_run(messages, model=None):
            captured['messages'] = messages
            return (
                '{"route":"single_shot","reason":"llm"}',
                _fake_usage(),
                'gpt-aux',
            )

        with patch(
            'chat.services.llm_router.run_chat_completion',
            side_effect=fake_run,
        ), patch(
            'chat.services.llm_router.record_token_usage',
        ):
            _llm_classify('CURRENT_Q', history)
        return captured['messages']

    def test_llm_classify_uses_recent_three_history_messages(self):
        # 6턴 history — 최근 3개만 payload 에 들어가야 함.
        history = [
            {'role': 'user', 'content': 'OLD1'},
            {'role': 'assistant', 'content': 'OLD2'},
            {'role': 'user', 'content': 'OLD3'},
            {'role': 'assistant', 'content': 'RECENT1'},
            {'role': 'user', 'content': 'RECENT2'},
            {'role': 'assistant', 'content': 'RECENT3'},
        ]
        messages = self._capture_messages(history)
        payload = messages[1]['content']
        for recent in ('RECENT1', 'RECENT2', 'RECENT3'):
            self.assertIn(recent, payload)
        for old in ('OLD1', 'OLD2', 'OLD3'):
            self.assertNotIn(old, payload)

    def test_llm_classify_filters_non_user_assistant_history(self):
        history = [
            {'role': 'system', 'content': 'SYS_OUT'},
            {'role': 'tool', 'content': 'TOOL_OUT'},
            {'role': 'user', 'content': ''},                # 빈 content — 필터됨
            {'role': 'user', 'content': 'KEEP1'},
            {'role': 'assistant', 'content': 'KEEP2'},
            {'role': 'user', 'content': 'KEEP3'},
        ]
        messages = self._capture_messages(history)
        payload = messages[1]['content']
        for kept in ('KEEP1', 'KEEP2', 'KEEP3'):
            self.assertIn(kept, payload)
        for dropped in ('SYS_OUT', 'TOOL_OUT'):
            self.assertNotIn(dropped, payload)


# ---------------------------------------------------------------------------
# §6.6 라우터 통합 — LlmRouteResult → RouteDecision 변환
# ---------------------------------------------------------------------------

class RouteQuestionLlmIntegrationTests(TestCase):
    """`question_router._llm_classify` (call-site) 를 mock 해 Tier 3 진입 검증."""

    def test_route_question_falls_back_to_keyword_on_llm_failure(self):
        # `_llm_classify` 가 예외를 던져도 `route_question` 이 흡수해 키워드 fallback.
        with patch(
            'chat.services.question_router._llm_classify',
            side_effect=RuntimeError('boom'),
        ):
            decision = route_question('비교해줘', [])
        self.assertEqual(decision.route, ROUTE_AGENT)
        self.assertEqual(decision.reason, 'agent_keyword')

    def test_route_question_falls_back_when_llm_returns_none(self):
        with patch(
            'chat.services.question_router._llm_classify', return_value=None,
        ):
            decision = route_question('100 + 50 합계는?', [])
        self.assertEqual(decision.route, ROUTE_WORKFLOW)
        self.assertEqual(decision.reason, 'workflow_keyword')

    def test_route_question_db_rule_overrides_llm(self):
        RouterRule.objects.create(
            name='비교 질문', route='agent', match_type='contains',
            pattern='비교', priority=100, enabled=True,
        )
        llm_mock = MagicMock(return_value=None)
        with patch(
            'chat.services.question_router._llm_classify', llm_mock,
        ):
            decision = route_question('본인 자녀 비교', [])
        self.assertEqual(decision.route, ROUTE_AGENT)
        self.assertEqual(llm_mock.call_count, 0)

    def test_route_question_passes_history_through(self):
        original_history = [
            {'role': 'user', 'content': 'prev'},
            {'role': 'assistant', 'content': 'reply'},
        ]
        captured = {}

        def fake_classify(question, history):
            captured['history'] = history
            return None

        with patch(
            'chat.services.question_router._llm_classify',
            side_effect=fake_classify,
        ):
            route_question('foo', original_history)

        self.assertIs(captured['history'], original_history)

    def test_route_question_converts_llm_result_to_route_decision(self):
        llm_result = LlmRouteResult(route='agent', reason='llm:hypothesis')
        with patch(
            'chat.services.question_router._llm_classify',
            return_value=llm_result,
        ):
            decision = route_question('만약 시나리오?', [])
        self.assertEqual(decision.route, ROUTE_AGENT)
        self.assertEqual(decision.reason, 'llm:hypothesis')
        self.assertEqual(decision.workflow_key, '')
        self.assertIsInstance(decision, RouteDecision)


# ---------------------------------------------------------------------------
# §6.7 DATE_CONDITION 우선순위 보호 — LLM 호출 0 보장
# ---------------------------------------------------------------------------

class DateConditionPriorityTests(TestCase):

    def test_date_condition_keyword_skips_llm_call(self):
        llm_mock = MagicMock(return_value=None)
        with patch(
            'chat.services.question_router._llm_classify', llm_mock,
        ):
            decision = route_question('급여 지급일은?', [])
        self.assertEqual(decision.route, ROUTE_AGENT)
        self.assertEqual(decision.reason, 'date_condition_keyword')
        self.assertEqual(llm_mock.call_count, 0)

    def test_date_condition_skips_llm_even_when_llm_would_return_workflow(self):
        llm_mock = MagicMock(
            return_value=LlmRouteResult(route='workflow', reason='llm:calc'),
        )
        with patch(
            'chat.services.question_router._llm_classify', llm_mock,
        ):
            decision = route_question('급여 지급일은?', [])
        # Tier 2 가 Tier 3 보다 먼저 — LLM 이 workflow 라고 해도 agent 유지.
        self.assertEqual(decision.route, ROUTE_AGENT)
        self.assertEqual(decision.reason, 'date_condition_keyword')
        self.assertEqual(llm_mock.call_count, 0)

    def test_date_condition_keywords_each_skip_llm(self):
        for kw in ('지급일', '만료일', '정산일', '마감일'):
            with self.subTest(kw=kw):
                llm_mock = MagicMock(return_value=None)
                with patch(
                    'chat.services.question_router._llm_classify', llm_mock,
                ):
                    decision = route_question(f'관련 {kw} 알려줘', [])
                self.assertEqual(decision.route, ROUTE_AGENT)
                self.assertEqual(decision.reason, 'date_condition_keyword')
                self.assertEqual(llm_mock.call_count, 0)

    def test_db_rule_still_overrides_date_condition(self):
        # DB rule 이 있으면 Tier 1 이 Tier 2 보다 먼저 — 회귀 보호가 DB override 를 막지 않음.
        RouterRule.objects.create(
            name='지급일 workflow', route='workflow', match_type='contains',
            pattern='지급일', priority=100, enabled=True,
            workflow_key='date_calculation',
        )
        llm_mock = MagicMock(return_value=None)
        with patch(
            'chat.services.question_router._llm_classify', llm_mock,
        ):
            decision = route_question('급여 지급일은?', [])
        self.assertEqual(decision.route, ROUTE_WORKFLOW)
        self.assertEqual(decision.workflow_key, 'date_calculation')
        self.assertEqual(llm_mock.call_count, 0)
