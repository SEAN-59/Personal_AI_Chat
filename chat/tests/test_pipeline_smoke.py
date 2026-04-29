"""Phase 9 — 대표 질문셋의 파이프라인 smoke (노드 자체 mock + cache_clear).

`run_chat_graph(<query>, history=[])` end-to-end 호출. 노드 자체를 mock 으로 patch
해 라우터 → 노드 진입 정합만 검증. LLM / embedding / reranker 호출 0회.

`_compiled_graph` 는 `lru_cache(maxsize=1)` 라 patch 적용 직후 cache_clear() 필수
— 안 그러면 이미 컴파일된 graph 가 원래 node binding 을 들고 있어 mock 무시.
기존 `test_graph_agent_wiring.py` 가 같은 패턴.
"""

from unittest.mock import patch

from django.test import TestCase

from chat.graph.app import _compiled_graph, run_chat_graph
from chat.models import RouterRule
from chat.services.single_shot.types import QueryResult


def _stub_node(reply_marker):
    """라우터가 도달한 노드의 reply 에 marker 박아 어느 노드가 호출됐는지 식별."""
    def _node(state):
        return {
            'result': QueryResult(
                reply=reply_marker,
                sources=[], total_tokens=0, chat_log_id=None,
            ),
        }
    return _node


class PipelineSmokeBase(TestCase):
    """공통 setUp — _compiled_graph cache 비우기 + 세 노드 stub patch."""

    def setUp(self):
        # 이전 테스트가 컴파일한 graph 의 원래 node binding 차단.
        _compiled_graph.cache_clear()
        self.addCleanup(_compiled_graph.cache_clear)

        # 세 노드 모두 stub 으로 patch — 어떤 노드가 호출되는지로 라우팅 검증.
        self._patches = [
            patch('chat.graph.app.single_shot_node',
                  side_effect=_stub_node('[single_shot stub]')),
            patch('chat.graph.app.workflow_node',
                  side_effect=_stub_node('[workflow stub]')),
            patch('chat.graph.app.agent_node',
                  side_effect=_stub_node('[agent stub]')),
        ]
        self.mocks = [p.start() for p in self._patches]
        self.single_shot_mock, self.workflow_mock, self.agent_mock = self.mocks
        for p in self._patches:
            self.addCleanup(p.stop)
        # patch 후 cache 비워 stub binding 으로 재컴파일.
        _compiled_graph.cache_clear()


class SingleShotPipelineSmokeTests(PipelineSmokeBase):
    """대표 질문 S1~S3 — single_shot 으로 라우팅."""

    def test_경조사_규정(self):
        result = run_chat_graph('경조사 규정 알려줘', history=[])
        self.assertEqual(result.reply, '[single_shot stub]')
        self.assertEqual(self.single_shot_mock.call_count, 1)

    def test_복리후생_정리(self):
        result = run_chat_graph('복리후생 항목별로 정리해줘', history=[])
        self.assertEqual(result.reply, '[single_shot stub]')

    def test_회사_휴가(self):
        result = run_chat_graph('회사 휴가 종류 알려줘', history=[])
        self.assertEqual(result.reply, '[single_shot stub]')


class WorkflowPipelineSmokeTests(PipelineSmokeBase):
    """대표 질문 W1~W3 — RouterRule fixture 로 workflow 라우팅."""

    def setUp(self):
        super().setUp()
        RouterRule.objects.create(
            name='며칠', route='workflow', match_type='contains',
            pattern='며칠', priority=100, enabled=True,
            workflow_key='date_calculation',
        )
        RouterRule.objects.create(
            name='합계', route='workflow', match_type='contains',
            pattern='합계', priority=100, enabled=True,
            workflow_key='amount_calculation',
        )
        RouterRule.objects.create(
            name='복리후생 표', route='workflow', match_type='contains',
            pattern='복리후생 규정에서', priority=100, enabled=True,
            workflow_key='table_lookup',
        )

    def test_date_calculation(self):
        result = run_chat_graph('2025-01-01부터 2025-04-11까지 며칠?', history=[])
        self.assertEqual(result.reply, '[workflow stub]')
        self.assertEqual(self.workflow_mock.call_count, 1)

    def test_amount_calculation(self):
        result = run_chat_graph('100 + 50 합계는?', history=[])
        self.assertEqual(result.reply, '[workflow stub]')

    def test_table_lookup(self):
        result = run_chat_graph('복리후생 규정에서 본인 결혼 경조금은?', history=[])
        self.assertEqual(result.reply, '[workflow stub]')


class AgentPipelineSmokeTests(PipelineSmokeBase):
    """대표 질문 A1~A3 — RouterRule fixture 로 agent 라우팅."""

    def setUp(self):
        super().setUp()
        RouterRule.objects.create(
            name='비교', route='agent', match_type='contains',
            pattern='비교', priority=100, enabled=True,
        )

    def test_본인_자녀_비교(self):
        result = run_chat_graph(
            '본인 결혼 경조금이랑 자녀 결혼 경조금 비교해줘', history=[],
        )
        self.assertEqual(result.reply, '[agent stub]')
        self.assertEqual(self.agent_mock.call_count, 1)

    def test_복리후생_취업규칙_비교(self):
        result = run_chat_graph(
            '복리후생 규정과 취업규칙의 휴가 항목 비교', history=[],
        )
        self.assertEqual(result.reply, '[agent stub]')

    def test_우주여행_비교(self):
        result = run_chat_graph('우주여행 비용 비교', history=[])
        self.assertEqual(result.reply, '[agent stub]')
