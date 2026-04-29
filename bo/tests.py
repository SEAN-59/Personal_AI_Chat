"""BO 뷰 단위 테스트."""

from django.test import TestCase, override_settings
from django.urls import reverse

from chat.models import AgentSettings


# WhiteNoise 의 Manifest staticfiles 가 테스트 환경에선 collectstatic 안 된
# 상태라 ValueError 를 던진다. 본 테스트는 BO 뷰 분기만 보면 되므로 manifest
# 없는 storage 로 override.
_NO_MANIFEST_STORAGES = {
    'default': {'BACKEND': 'django.core.files.storage.FileSystemStorage'},
    'staticfiles': {'BACKEND': 'django.contrib.staticfiles.storage.StaticFilesStorage'},
}


@override_settings(STORAGES=_NO_MANIFEST_STORAGES)
class AgentSettingsViewTests(TestCase):
    """Phase 8-3 — `/bo/agent/` 페이지 GET / POST 회귀."""

    def test_get_returns_200_with_form_and_catalog(self):
        url = reverse('bo:agent')
        response = self.client.get(url)

        self.assertEqual(response.status_code, 200)
        # form 필드 노출.
        self.assertContains(response, 'Agent 경로 활성화')
        self.assertContains(response, '최대 iteration 수')
        self.assertContains(response, 'low_relevance 누적 한도')
        # tool catalog — Phase 7-1 에 등록된 3 도구.
        self.assertContains(response, 'retrieve_documents')
        self.assertContains(response, 'find_canonical_qa')
        self.assertContains(response, 'run_workflow')
        # 최근 호출 통계 카드.
        self.assertContains(response, 'agent_step')
        self.assertContains(response, 'agent_final')

    def test_post_valid_data_saves_and_redirects(self):
        url = reverse('bo:agent')
        response = self.client.post(url, {
            'enabled': 'on',
            'max_iterations': '4',
            'max_low_relevance_retrieves': '2',
        })

        self.assertRedirects(response, url)
        row = AgentSettings.objects.get_solo()
        self.assertEqual(row.max_iterations, 4)
        self.assertEqual(row.max_low_relevance_retrieves, 2)
        self.assertTrue(row.enabled)

    def test_post_invalid_max_iterations_returns_form_error(self):
        url = reverse('bo:agent')
        response = self.client.post(url, {
            'enabled': 'on',
            'max_iterations': '99',           # > 12 — validator 위반.
            'max_low_relevance_retrieves': '3',
        })

        # 폼 에러 — redirect 안 함, 같은 페이지 200 + 에러 메시지.
        self.assertEqual(response.status_code, 200)
        # DB 갱신 안 됨 (default 값 그대로).
        row = AgentSettings.objects.get_solo()
        self.assertEqual(row.max_iterations, 6)

    def test_post_disabling_persists_enabled_false(self):
        url = reverse('bo:agent')
        # checkbox 미전송 = unchecked → enabled=False.
        response = self.client.post(url, {
            'max_iterations': '6',
            'max_low_relevance_retrieves': '3',
        })

        self.assertRedirects(response, url)
        row = AgentSettings.objects.get_solo()
        self.assertFalse(row.enabled)

    def test_section_marker_for_sidebar_active(self):
        # base.html 의 사이드바가 `current == 'agent'` 로 active 표시 — section
        # 키와 url_name 이 일치해야 함.
        url = reverse('bo:agent')
        response = self.client.get(url)
        # 'section' 컨텍스트는 직접 확인 어렵지만 url_name 이 `agent` 인지 확인.
        self.assertEqual(response.resolver_match.url_name, 'agent')


@override_settings(STORAGES=_NO_MANIFEST_STORAGES)
class RouterRulesBulkActionsTests(TestCase):
    """Phase 8-3 — RouterRule 일괄 액션 (활성화 / 비활성화 / 삭제) 회귀."""

    def setUp(self):
        from chat.models import RouterRule
        self.r1 = RouterRule.objects.create(
            name='r1', route='agent', match_type='contains',
            pattern='비교', priority=100, enabled=True,
        )
        self.r2 = RouterRule.objects.create(
            name='r2', route='workflow', match_type='contains',
            pattern='날짜', priority=100, enabled=True,
        )
        self.r3 = RouterRule.objects.create(
            name='r3', route='single_shot', match_type='contains',
            pattern='안녕', priority=100, enabled=False,
        )

    def test_bulk_enable_activates_selected(self):
        url = reverse('bo:router_rules_bulk_enable')
        response = self.client.post(url, {'ids': [str(self.r3.pk), str(self.r1.pk)]})

        self.assertRedirects(response, reverse('bo:router_rules'))
        self.r3.refresh_from_db()
        self.assertTrue(self.r3.enabled)
        # r1 은 이미 enabled=True 라 update 영향 없음 (count 1).

    def test_bulk_disable_deactivates_selected(self):
        url = reverse('bo:router_rules_bulk_disable')
        response = self.client.post(url, {'ids': [str(self.r1.pk), str(self.r2.pk)]})

        self.assertRedirects(response, reverse('bo:router_rules'))
        self.r1.refresh_from_db()
        self.r2.refresh_from_db()
        self.assertFalse(self.r1.enabled)
        self.assertFalse(self.r2.enabled)

    def test_bulk_delete_removes_selected(self):
        from chat.models import RouterRule
        url = reverse('bo:router_rules_bulk_delete')
        response = self.client.post(url, {'ids': [str(self.r1.pk), str(self.r3.pk)]})

        self.assertRedirects(response, reverse('bo:router_rules'))
        # r2 만 남아야 함.
        remaining = list(RouterRule.objects.values_list('pk', flat=True))
        self.assertEqual(remaining, [self.r2.pk])

    def test_bulk_action_with_empty_ids_warns_and_redirects(self):
        url = reverse('bo:router_rules_bulk_delete')
        response = self.client.post(url, {})

        self.assertRedirects(response, reverse('bo:router_rules'))
        # 모두 그대로.
        from chat.models import RouterRule
        self.assertEqual(RouterRule.objects.count(), 3)

    def test_bulk_action_ignores_non_integer_ids(self):
        from chat.models import RouterRule
        url = reverse('bo:router_rules_bulk_delete')
        response = self.client.post(url, {'ids': ['abc', '', str(self.r1.pk)]})

        self.assertRedirects(response, reverse('bo:router_rules'))
        # r1 만 삭제, 잘못된 토큰은 무시.
        self.assertEqual(RouterRule.objects.count(), 2)
        self.assertFalse(RouterRule.objects.filter(pk=self.r1.pk).exists())


@override_settings(STORAGES=_NO_MANIFEST_STORAGES)
class DashboardViewTests(TestCase):
    """Phase 8-5 — `/bo/` 대시보드 GET 회귀 (5 카드 / 비용 컬럼 / purpose 섹션)."""

    def test_get_returns_200_with_five_cards(self):
        from chat.models import TokenUsage
        # 시드: 다양한 purpose row.
        TokenUsage.objects.create(
            model='gpt-4o-mini', prompt_tokens=1000, completion_tokens=500,
            total_tokens=1500, purpose='single_shot_answer',
        )
        TokenUsage.objects.create(
            model='gpt-4o-mini', prompt_tokens=200, completion_tokens=100,
            total_tokens=300, purpose='agent_step',
        )

        url = reverse('bo:dashboard')
        response = self.client.get(url)

        self.assertEqual(response.status_code, 200)
        body = response.content.decode('utf-8')
        # 5 카드 (호출 / 총 토큰 / 입력 / 출력 / 비용).
        self.assertIn('호출 수', body)
        self.assertIn('총 토큰', body)
        self.assertIn('입력 토큰', body)
        self.assertIn('출력 토큰', body)
        self.assertIn('비용 (USD)', body)
        # 비용 caption — 자체 추정 / embedding 미포함 명시.
        self.assertIn('자체 추정', body)
        self.assertIn('embedding', body)

    def test_purpose_breakdown_section_renders(self):
        from chat.models import TokenUsage
        TokenUsage.objects.create(
            model='gpt-4o-mini', prompt_tokens=1000, completion_tokens=500,
            total_tokens=1500, purpose='single_shot_answer',
        )
        TokenUsage.objects.create(
            model='gpt-4o-mini', prompt_tokens=200, completion_tokens=100,
            total_tokens=300, purpose='agent_step',
        )

        url = reverse('bo:dashboard')
        response = self.client.get(url)
        body = response.content.decode('utf-8')

        # purpose 섹션 헤더 + 한국어 라벨 + 영문 코드.
        self.assertIn('Purpose 별 사용량', body)
        self.assertIn('single-shot 답변', body)
        self.assertIn('agent 추론', body)
        self.assertIn('single_shot_answer', body)
        self.assertIn('agent_step', body)

    def test_empty_dashboard_shows_empty_states(self):
        # TokenUsage 0건 — 두 섹션 모두 empty state.
        url = reverse('bo:dashboard')
        response = self.client.get(url)
        body = response.content.decode('utf-8')

        self.assertEqual(response.status_code, 200)
        self.assertIn('아직 사용 기록이 없습니다', body)
        self.assertIn('purpose 가 없습니다', body)

    def test_observed_only_does_not_emit_unused_purposes(self):
        # single_shot_answer 만 있는 환경 → purpose 표에 single_shot_answer 만 등장,
        # 다른 known purpose (agent_step / workflow_extractor 등) 는 표에 없음.
        from chat.models import TokenUsage
        TokenUsage.objects.create(
            model='gpt-4o-mini', prompt_tokens=1000, completion_tokens=500,
            total_tokens=1500, purpose='single_shot_answer',
        )

        url = reverse('bo:dashboard')
        response = self.client.get(url)
        body = response.content.decode('utf-8')

        self.assertIn('single_shot_answer', body)
        # purpose 섹션의 표 row 안에 다른 코드 출현 안 함 (caption 의 일반 단어와 별).
        # 구체적으로 한국어 라벨 'agent 추론' 가 표에 안 나타나야 함.
        self.assertNotIn('agent 추론', body)
        self.assertNotIn('workflow 입력 추출', body)


@override_settings(STORAGES=_NO_MANIFEST_STORAGES)
class BoSharedPartialsMarkupTests(TestCase):
    """Phase 8-4 — `bo.js` 가 동작하기 위한 마크업 attribute 회귀 가드."""

    def setUp(self):
        from chat.models import RouterRule
        RouterRule.objects.create(
            name='r1', route='agent', match_type='contains',
            pattern='비교', priority=100, enabled=True,
        )

    def test_router_rules_page_emits_bulk_attributes(self):
        url = reverse('bo:router_rules')
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        body = response.content.decode('utf-8')
        # bo.js 의 hook 들이 정확히 출력되는지 — 이게 깨지면 일괄 액션 동작 안 함.
        self.assertIn('data-bulk-page="router"', body)
        self.assertIn('data-bulk-edit-toggle', body)
        self.assertIn('data-bulk-target="router"', body)
        self.assertIn('data-bulk-toolbar', body)
        self.assertIn('data-bulk-action', body)
        self.assertIn('data-bulk-row', body)
        self.assertIn('data-bulk-check', body)

    def test_base_template_loads_bo_js(self):
        url = reverse('bo:router_rules')
        response = self.client.get(url)
        body = response.content.decode('utf-8')
        # base.html 이 모든 페이지에 bo.js 로드.
        self.assertIn("/static/bo/bo.js", body)
