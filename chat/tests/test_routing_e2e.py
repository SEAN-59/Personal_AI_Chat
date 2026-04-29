"""Phase 9 — 대표 질문셋의 라우팅 정합 e2e.

`route_question(<query>)` 직접 호출로 세 layer (DB RouterRule / 코드 키워드
fallback / default) 모두 cover. workflow_key 매핑은 RouterRule fixture 명시.
"""

from django.test import TestCase

from chat.graph.routes import ROUTE_AGENT, ROUTE_SINGLE_SHOT, ROUTE_WORKFLOW
from chat.models import RouterRule
from chat.services.question_router import route_question


class SingleShotRoutingTests(TestCase):
    """대표 질문 S1~S3 — default layer (키워드 미매치)."""

    def test_경조사_규정_알려줘(self):
        decision = route_question('경조사 규정 알려줘')
        self.assertEqual(decision.route, ROUTE_SINGLE_SHOT)
        self.assertEqual(decision.reason, 'default')

    def test_복리후생_항목별로_정리해줘(self):
        decision = route_question('복리후생 항목별로 정리해줘')
        self.assertEqual(decision.route, ROUTE_SINGLE_SHOT)
        self.assertEqual(decision.reason, 'default')

    def test_회사_휴가_종류_알려줘(self):
        # WORKFLOW_KEYWORDS / AGENT_KEYWORDS 모두 미매치 → default.
        decision = route_question('회사 휴가 종류 알려줘')
        self.assertEqual(decision.route, ROUTE_SINGLE_SHOT)
        self.assertEqual(decision.reason, 'default')


class WorkflowRoutingTests(TestCase):
    """대표 질문 W1~W3 — DB RouterRule layer (workflow_key 매핑)."""

    def setUp(self):
        # Phase 9 e2e — workflow_key 매핑은 RouterRule fixture 명시.
        # clean DB 라 fixture 없으면 코드 키워드 fallback 으로 떨어져 workflow_key=''.
        RouterRule.objects.create(
            name='기간 며칠', route='workflow', match_type='contains',
            pattern='며칠', priority=100, enabled=True,
            workflow_key='date_calculation',
        )
        RouterRule.objects.create(
            name='합계 산정', route='workflow', match_type='contains',
            pattern='합계', priority=100, enabled=True,
            workflow_key='amount_calculation',
        )
        RouterRule.objects.create(
            name='복리후생 표', route='workflow', match_type='contains',
            pattern='복리후생 규정에서', priority=100, enabled=True,
            workflow_key='table_lookup',
        )

    def test_date_calculation(self):
        decision = route_question('2025-01-01부터 2025-04-11까지 며칠?')
        self.assertEqual(decision.route, ROUTE_WORKFLOW)
        self.assertEqual(decision.workflow_key, 'date_calculation')

    def test_amount_calculation(self):
        decision = route_question('100 + 50 합계는?')
        self.assertEqual(decision.route, ROUTE_WORKFLOW)
        self.assertEqual(decision.workflow_key, 'amount_calculation')

    def test_table_lookup(self):
        decision = route_question('복리후생 규정에서 본인 결혼 경조금은?')
        self.assertEqual(decision.route, ROUTE_WORKFLOW)
        self.assertEqual(decision.workflow_key, 'table_lookup')


class AgentRoutingTests(TestCase):
    """대표 질문 A1~A3 — DB RouterRule layer 또는 코드 키워드 fallback."""

    def setUp(self):
        # 운영 환경에 흔한 RouterRule '비교' 키워드 — agent 라우팅.
        RouterRule.objects.create(
            name='비교 질문', route='agent', match_type='contains',
            pattern='비교', priority=100, enabled=True,
        )

    def test_본인_자녀_비교(self):
        decision = route_question('본인 결혼 경조금이랑 자녀 결혼 경조금 비교해줘')
        self.assertEqual(decision.route, ROUTE_AGENT)

    def test_복리후생_취업규칙_비교(self):
        decision = route_question('복리후생 규정과 취업규칙의 휴가 항목 비교')
        self.assertEqual(decision.route, ROUTE_AGENT)

    def test_우주여행_비교(self):
        decision = route_question('우주여행 비용 비교')
        self.assertEqual(decision.route, ROUTE_AGENT)
