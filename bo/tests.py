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
