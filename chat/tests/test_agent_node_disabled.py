"""Phase 8-3 — `agent_node` 의 enabled=False 시 single_shot 폴백 회귀."""

from unittest.mock import patch

from django.test import TestCase

from chat.graph.nodes.agent import agent_node
from chat.services.agent.result import AgentResult, AgentTermination
from chat.services.single_shot.types import QueryResult
from chat.workflows.core import WorkflowStatus


def _ok_agent_result(value='답변'):
    return AgentResult(
        status=WorkflowStatus.OK, value=value,
        details={'termination': 'final_answer'},
        termination=AgentTermination.FINAL_ANSWER,
    )


def _single_shot_result():
    return {
        'result': QueryResult(
            reply='single_shot 답변',
            sources=[],
            total_tokens=0,
            chat_log_id=None,
        ),
    }


class AgentEnabledTrueTests(TestCase):
    """default enabled=True — agent runtime 정상 진입."""

    def test_run_agent_called_when_enabled_true(self):
        # default state (RunPython 으로 enabled=True 시드). run_agent 호출 검증.
        with patch(
            'chat.graph.nodes.agent.run_agent',
            return_value=_ok_agent_result('정상 답변'),
        ) as run, patch(
            'chat.graph.nodes.agent.rewrite_query_with_history',
            return_value=('Q', None, None),
        ), patch(
            'chat.graph.nodes.agent.single_shot_node',
            return_value=_single_shot_result(),
        ) as fallback:
            out = agent_node({'question': 'Q', 'history': []})

        run.assert_called_once()
        fallback.assert_not_called()
        self.assertEqual(out['result'].reply, '정상 답변')


class AgentEnabledFalseTests(TestCase):
    """enabled=False — single_shot 폴백."""

    def test_single_shot_fallback_when_enabled_false(self):
        from chat.models import AgentSettings
        row = AgentSettings.objects.get_solo()
        row.enabled = False
        row.save()

        with patch(
            'chat.graph.nodes.agent.run_agent',
        ) as run, patch(
            'chat.graph.nodes.agent.single_shot_node',
            return_value=_single_shot_result(),
        ) as fallback:
            out = agent_node({'question': 'Q', 'history': []})

        # run_agent 호출 안 됨 — single_shot 으로 폴백.
        run.assert_not_called()
        fallback.assert_called_once_with({'question': 'Q', 'history': []})
        self.assertEqual(out['result'].reply, 'single_shot 답변')
