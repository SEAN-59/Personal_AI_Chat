"""Phase 8-3 — `run_agent` 의 settings 주입 회귀.

`AgentSettings` 의 max_iterations / max_low_relevance_retrieves 가 ReAct loop
에 실제 적용되는지 / positional 인자가 settings 보다 우선하는지 / 폴백 동작.
"""

from unittest.mock import patch

from django.test import TestCase

from chat.services.agent import react, runtime_settings as rs, tools as agent_tools
from chat.services.agent.tools import Tool
from chat.workflows.core import WorkflowStatus
from chat.workflows.domains.field_spec import FieldSpec


class _UsageStub:
    prompt_tokens = 10
    completion_tokens = 5
    total_tokens = 15


def _completion(*replies):
    iterator = iter(replies)

    def _side_effect(messages):
        return (next(iterator), _UsageStub(), 'gpt-4o-mini')

    return _side_effect


def _make_dummy_tool(*, low_relevance=False):
    return Tool(
        name='dummy',
        description='',
        input_schema={'query': FieldSpec(type='text', required=True)},
        callable=lambda args: f'echo:{args["query"]}',
        summarize=lambda r: f'ok: {r}',
        failure_check=(lambda r: True) if low_relevance else None,
    )


class SettingsMaxIterationsInjectTests(TestCase):
    """settings.max_iterations 가 실제 loop 한도로 작용."""

    def setUp(self):
        self._snapshot = agent_tools._snapshot_for_tests()
        agent_tools._reset_for_tests()
        agent_tools.register(_make_dummy_tool())

    def tearDown(self):
        agent_tools._restore_for_tests(self._snapshot)

    def _set_settings(self, *, max_iterations=6, max_low_rel=3):
        from chat.models import AgentSettings
        row = AgentSettings.objects.get_solo()
        row.max_iterations = max_iterations
        row.max_low_relevance_retrieves = max_low_rel
        row.save()

    def test_settings_max_iter_two_terminates_at_two_iterations(self):
        # settings.max_iterations=2 → 2 step 만에 MAX_ITERATIONS_EXCEEDED.
        self._set_settings(max_iterations=2)
        replies = [
            f'{{"thought": "{i}", "action": "dummy", "arguments": {{"query": "q{i}"}}}}'
            for i in range(2)
        ]
        with patch('chat.services.agent.prompts.load_prompt', return_value='[STUB]'), \
                patch('chat.services.agent.react.record_token_usage'), \
                patch(
                    'chat.services.agent.react.run_chat_completion',
                    side_effect=_completion(*replies),
                ):
            r = react.run_agent('Q', history=[])
        self.assertEqual(r.status, WorkflowStatus.NOT_FOUND)
        self.assertEqual(len(r.tool_calls), 2)

    def test_positional_max_iter_overrides_settings(self):
        # max_iterations=3 명시 호출이 settings (2) 를 override.
        self._set_settings(max_iterations=2)
        replies = [
            f'{{"thought": "{i}", "action": "dummy", "arguments": {{"query": "q{i}"}}}}'
            for i in range(3)
        ]
        with patch('chat.services.agent.prompts.load_prompt', return_value='[STUB]'), \
                patch('chat.services.agent.react.record_token_usage'), \
                patch(
                    'chat.services.agent.react.run_chat_completion',
                    side_effect=_completion(*replies),
                ):
            r = react.run_agent('Q', history=[], max_iterations=3)
        self.assertEqual(len(r.tool_calls), 3)


class SettingsMaxLowRelevanceInjectTests(TestCase):
    """settings.max_low_relevance_retrieves 가 실제 누적 가드로 작용."""

    def setUp(self):
        self._snapshot = agent_tools._snapshot_for_tests()
        agent_tools._reset_for_tests()
        # retrieve mock — 항상 low_relevance 반환.
        agent_tools.register(Tool(
            name='retrieve_documents',
            description='',
            input_schema={'query': FieldSpec(type='text', required=True)},
            callable=lambda args: {'query': args['query'], 'hits': []},
            summarize=lambda r: f"검색결과: {r.get('query', '')}",
            failure_check=lambda r: True,
        ))

    def tearDown(self):
        agent_tools._restore_for_tests(self._snapshot)

    def _set_settings(self, *, max_low_rel):
        from chat.models import AgentSettings
        row = AgentSettings.objects.get_solo()
        row.max_low_relevance_retrieves = max_low_rel
        row.save()

    def test_max_low_relevance_one_terminates_after_first_low_rel(self):
        # settings.max_low_relevance_retrieves=1 → 첫 low-rel retrieve 직후
        # NO_MORE_USEFUL_TOOLS 종료.
        self._set_settings(max_low_rel=1)
        replies = [
            '{"thought": "1", "action": "retrieve_documents", "arguments": {"query": "q1"}}',
        ]
        with patch('chat.services.agent.prompts.load_prompt', return_value='[STUB]'), \
                patch('chat.services.agent.react.record_token_usage'), \
                patch(
                    'chat.services.agent.react.run_chat_completion',
                    side_effect=_completion(*replies),
                ):
            r = react.run_agent('Q', history=[])
        # 1 retrieve 후 즉시 종료.
        self.assertEqual(r.status, WorkflowStatus.NOT_FOUND)
        self.assertEqual(len(r.tool_calls), 1)


class SettingsFallbackTests(TestCase):
    """settings 조회 실패 / sanity 실패 시 `_DEFAULTS` 폴백."""

    def setUp(self):
        self._snapshot = agent_tools._snapshot_for_tests()
        agent_tools._reset_for_tests()
        agent_tools.register(_make_dummy_tool())

    def tearDown(self):
        agent_tools._restore_for_tests(self._snapshot)

    def test_load_settings_failure_uses_defaults(self):
        # load_runtime_settings 가 _DEFAULTS 반환 → max_iter=6 적용.
        with patch(
            'chat.services.agent.react._rs.load_runtime_settings',
            return_value=rs._DEFAULTS,
        ), patch('chat.services.agent.prompts.load_prompt', return_value='[STUB]'), \
                patch('chat.services.agent.react.record_token_usage'), \
                patch(
                    'chat.services.agent.react.run_chat_completion',
                    side_effect=_completion(
                        '{"thought": "끝", "action": "final_answer", "answer": "ok"}',
                    ),
                ):
            r = react.run_agent('Q', history=[])
        self.assertEqual(r.status, WorkflowStatus.OK)


class CompatibilityAliasTests(TestCase):
    """Phase 8-3 alias 계약 — react.py 가 runtime_settings 의 default 를 재노출."""

    def test_react_default_max_iterations_aliased(self):
        self.assertEqual(react.DEFAULT_MAX_ITERATIONS, rs.DEFAULT_MAX_ITERATIONS)

    def test_react_max_low_relevance_retrieves_aliased(self):
        # 이름 다름 — react.MAX_LOW_RELEVANCE_RETRIEVES = rs.DEFAULT_MAX_LOW_RELEVANCE_RETRIEVES.
        self.assertEqual(
            react.MAX_LOW_RELEVANCE_RETRIEVES,
            rs.DEFAULT_MAX_LOW_RELEVANCE_RETRIEVES,
        )
