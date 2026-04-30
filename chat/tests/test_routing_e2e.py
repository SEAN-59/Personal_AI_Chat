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


class DateConditionRoutingTests(TestCase):
    """v0.4.2 (이슈 #73) — DATE_CONDITION_KEYWORDS 코드 fallback tier.

    DB RouterRule fixture 없이 코드 키워드만으로 agent 로 라우팅되는지,
    그리고 WORKFLOW_KEYWORDS 와 충돌하는 합성 질문에서도 DATE_CONDITION 이
    이기는지 검증.
    """

    def test_simple_지급일(self):
        decision = route_question('지급일은?')
        self.assertEqual(decision.route, ROUTE_AGENT)
        self.assertEqual(decision.reason, 'date_condition_keyword')
        self.assertIn('지급일', decision.matched_rules)

    def test_simple_만료일(self):
        decision = route_question('만료일은?')
        self.assertEqual(decision.route, ROUTE_AGENT)
        self.assertEqual(decision.reason, 'date_condition_keyword')

    def test_simple_정산일(self):
        decision = route_question('정산일은?')
        self.assertEqual(decision.route, ROUTE_AGENT)
        self.assertEqual(decision.reason, 'date_condition_keyword')

    def test_simple_마감일(self):
        decision = route_question('마감일은?')
        self.assertEqual(decision.route, ROUTE_AGENT)
        self.assertEqual(decision.reason, 'date_condition_keyword')

    def test_collision_급여_지급일(self):
        # `급여` (WORKFLOW) + `지급일` (DATE_CONDITION) 동시 매치 — DATE_CONDITION 우선.
        decision = route_question('26년 6월 급여 지급일은?')
        self.assertEqual(decision.route, ROUTE_AGENT)
        self.assertEqual(decision.reason, 'date_condition_keyword')

    def test_collision_퇴직금_만료일(self):
        decision = route_question('퇴직금 신청 만료일은?')
        self.assertEqual(decision.route, ROUTE_AGENT)
        self.assertEqual(decision.reason, 'date_condition_keyword')

    def test_collision_수당_정산일(self):
        decision = route_question('수당 정산일 알려줘')
        self.assertEqual(decision.route, ROUTE_AGENT)
        self.assertEqual(decision.reason, 'date_condition_keyword')

    def test_collision_연차_마감일(self):
        decision = route_question('연차 신청 마감일은 며칠까지?')
        self.assertEqual(decision.route, ROUTE_AGENT)
        self.assertEqual(decision.reason, 'date_condition_keyword')

    def test_negative_급여_얼마(self):
        # DATE_CONDITION 미매치 — WORKFLOW 그대로 (기존 동작 유지).
        decision = route_question('급여는 얼마야?')
        self.assertEqual(decision.route, ROUTE_WORKFLOW)
        self.assertEqual(decision.reason, 'workflow_keyword')
