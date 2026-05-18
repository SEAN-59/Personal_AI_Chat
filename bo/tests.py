"""BO 뷰 단위 테스트."""

from unittest.mock import patch

from django.test import TestCase, override_settings
from django.urls import reverse

from chat.models import AgentSettings
from files.models import Document, DocumentChunk


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

    def _full_form_data(self, **overrides):
        """Phase 8-6: 5 필드 폼 — 테스트별 override 가능."""
        data = {
            'enabled': 'on',
            'max_iterations': '4',
            'max_low_relevance_retrieves': '2',
            'max_consecutive_failures': '3',
            'max_repeated_call': '3',
        }
        data.update({k: str(v) for k, v in overrides.items()})
        return data

    def test_post_valid_data_saves_and_redirects(self):
        url = reverse('bo:agent')
        response = self.client.post(url, self._full_form_data())

        self.assertRedirects(response, url)
        row = AgentSettings.objects.get_solo()
        self.assertEqual(row.max_iterations, 4)
        self.assertEqual(row.max_low_relevance_retrieves, 2)
        self.assertTrue(row.enabled)

    def test_post_invalid_max_iterations_returns_form_error(self):
        url = reverse('bo:agent')
        response = self.client.post(url, self._full_form_data(max_iterations=99))

        # 폼 에러 — redirect 안 함, 같은 페이지 200 + 에러 메시지.
        self.assertEqual(response.status_code, 200)
        # DB 갱신 안 됨 (default 값 그대로).
        row = AgentSettings.objects.get_solo()
        self.assertEqual(row.max_iterations, 6)

    def test_post_disabling_persists_enabled_false(self):
        url = reverse('bo:agent')
        # checkbox 미전송 = unchecked → enabled=False.
        data = self._full_form_data()
        del data['enabled']
        response = self.client.post(url, data)

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

    # ---------------- Phase 8-6: 새 필드 + audit ----------------

    def test_get_shows_new_extra_limit_fields(self):
        url = reverse('bo:agent')
        response = self.client.get(url)
        self.assertContains(response, '연속 실패 한도')
        self.assertContains(response, '동일 호출 반복 한도')

    def test_max_repeated_call_one_rejected(self):
        # P2-3: max_repeated_call=1 form/DB validator 거부.
        url = reverse('bo:agent')
        response = self.client.post(url, self._full_form_data(max_repeated_call=1))
        self.assertEqual(response.status_code, 200)
        row = AgentSettings.objects.get_solo()
        self.assertEqual(row.max_repeated_call, 3)

    def test_max_repeated_call_help_text_compatibility_note(self):
        # P2 보강: 호환/기록용 hint 가 GET 응답 본문에 노출.
        url = reverse('bo:agent')
        response = self.client.get(url)
        self.assertContains(response, '호환/기록용')

    def test_audit_row_created_when_value_changed(self):
        from chat.models import AgentSettingsAudit
        before = AgentSettingsAudit.objects.count()
        url = reverse('bo:agent')
        # max_iterations 만 4로 변경 (default 6 → 4).
        self.client.post(url, self._full_form_data(max_iterations=4))
        self.assertEqual(AgentSettingsAudit.objects.count(), before + 1)

        audit = AgentSettingsAudit.objects.first()
        # changes — 변경된 필드 (max_iterations) 만.
        self.assertIn('max_iterations', audit.changes)
        self.assertEqual(audit.changes['max_iterations']['old'], 6)
        self.assertEqual(audit.changes['max_iterations']['new'], 4)
        # 변경 안 된 필드는 changes 에 없음.
        self.assertNotIn('enabled', audit.changes)
        self.assertNotIn('max_consecutive_failures', audit.changes)

    def test_audit_snapshot_contains_all_five_fields(self):
        # P2-2 보강: snapshot 이 변경 후 5 필드 전체 상태를 담음.
        from chat.models import AgentSettingsAudit
        url = reverse('bo:agent')
        self.client.post(url, self._full_form_data(max_iterations=8))

        audit = AgentSettingsAudit.objects.first()
        self.assertEqual(
            set(audit.snapshot.keys()),
            {'enabled', 'max_iterations', 'max_low_relevance_retrieves',
             'max_consecutive_failures', 'max_repeated_call'},
        )
        self.assertEqual(audit.snapshot['max_iterations'], 8)

    def test_audit_row_not_created_when_no_change(self):
        from chat.models import AgentSettingsAudit
        # 한 번 저장으로 baseline 잡고, 같은 값으로 다시 저장.
        url = reverse('bo:agent')
        self.client.post(url, self._full_form_data(max_iterations=5))
        before = AgentSettingsAudit.objects.count()
        # 동일 값으로 또 POST.
        self.client.post(url, self._full_form_data(max_iterations=5))
        self.assertEqual(AgentSettingsAudit.objects.count(), before)

    def test_old_value_captured_before_form_binding(self):
        # P2-1 회귀 가드 — ModelForm.is_valid() 가 cleaned_data 를 form.instance 에
        # 반영하기 전에 old 값을 캡처해야 변경 감지 정확. 변경 후 audit 의 old 가
        # 직전 DB 값과 일치하는지.
        from chat.models import AgentSettingsAudit
        url = reverse('bo:agent')
        # baseline: max_iterations=4 로 저장.
        self.client.post(url, self._full_form_data(max_iterations=4))
        # 다시 7 로 변경 → audit 의 old 가 4 여야 (form.instance 의 4 가 아니라).
        self.client.post(url, self._full_form_data(max_iterations=7))

        latest = AgentSettingsAudit.objects.first()
        self.assertEqual(latest.changes['max_iterations']['old'], 4)
        self.assertEqual(latest.changes['max_iterations']['new'], 7)

    def test_recent_audits_in_get_response(self):
        # GET 응답이 최근 audit 행을 본문에 노출.
        url = reverse('bo:agent')
        # 변경 한 번 발생시킴.
        self.client.post(url, self._full_form_data(max_iterations=9))
        response = self.client.get(url)
        self.assertContains(response, 'Settings 변경 이력')
        self.assertContains(response, 'max_iterations')


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


class RouterRuleFormDuplicatePreventionTests(TestCase):
    """v0.4.2 (이슈 #73 검증 부산물) — 같은 (pattern, match_type) RouterRule 중복 등록 거부."""

    def setUp(self):
        from chat.models import RouterRule
        self.existing = RouterRule.objects.create(
            name='기존 며칠', route='workflow', match_type='contains',
            pattern='며칠', priority=100, enabled=True,
            workflow_key='date_calculation',
        )

    def _form_data(self, **overrides):
        data = {
            'name': '신규 며칠',
            'route': 'workflow',
            'match_type': 'contains',
            'pattern': '며칠',
            'workflow_key': 'date_calculation',
            'priority': 100,
            'enabled': 'on',
            'description': '',
        }
        data.update(overrides)
        return data

    def test_duplicate_pattern_match_type_rejected(self):
        from bo.views.router_rules import RouterRuleForm
        form = RouterRuleForm(self._form_data())
        self.assertFalse(form.is_valid())
        self.assertIn('이미 있습니다', str(form.errors))

    def test_different_match_type_allowed(self):
        from bo.views.router_rules import RouterRuleForm
        # 같은 pattern 이라도 match_type 이 다르면 허용 (현재는 contains 만 사용중이지만
        # 미래 정확 일치 / 정규식 도입 시를 대비).
        form = RouterRuleForm(self._form_data(match_type='exact'))
        self.assertFalse(form.is_valid())  # exact 가 choices 에 없으면 form 자체 invalid
        # 하지만 pattern/match_type 충돌 에러는 없어야 함.
        self.assertNotIn('이미 있습니다', str(form.errors))

    def test_different_pattern_allowed(self):
        from bo.views.router_rules import RouterRuleForm
        form = RouterRuleForm(self._form_data(pattern='몇 일'))
        self.assertTrue(form.is_valid(), msg=form.errors)

    def test_whitespace_distinguished(self):
        from bo.views.router_rules import RouterRuleForm
        # `며칠` 과 `며 칠` 은 다른 패턴 — 띄어쓰기까지 정확히 일치할 때만 충돌.
        form = RouterRuleForm(self._form_data(pattern='며 칠'))
        self.assertTrue(form.is_valid(), msg=form.errors)

    def test_edit_self_does_not_self_conflict(self):
        from bo.views.router_rules import RouterRuleForm
        # 기존 rule 편집 시 자기 자신은 제외 — 패턴 그대로 두고 다른 필드만 수정 가능.
        form = RouterRuleForm(
            self._form_data(name='이름만 변경'),
            instance=self.existing,
        )
        self.assertTrue(form.is_valid(), msg=form.errors)


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
        TokenUsage.objects.create(
            model='gpt-4o-mini', prompt_tokens=80, completion_tokens=40,
            total_tokens=120, purpose='llm_router',
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
        self.assertIn('LLM 라우터', body)
        self.assertIn('llm_router', body)

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


class PromptRegistryConsistencyTests(TestCase):
    """Phase 9 — `prompt_registry.all_entries()` 의 모든 entry 의 `relative_path` 가
    실제 파일로 존재하는지 회귀 가드.

    Phase 1 의 prompt_loader 가 BO 편집 page 에서 entry 를 fetch 할 때 파일이
    없으면 PromptNotFound + warning 처리는 있지만, registry 와 실제 파일 정합이
    누적된 phase 동안 깨질 위험. 본 테스트로 release 직전 한 번 가드.
    """

    def test_all_registered_prompts_exist_on_disk(self):
        from pathlib import Path
        from django.conf import settings as django_settings
        from chat.services.prompt_registry import all_entries

        base = Path(django_settings.PROMPTS_DIR).resolve()
        missing = []
        for entry in all_entries():
            full = base / entry.relative_path
            if not full.is_file():
                missing.append(entry.relative_path)
        self.assertEqual(
            missing, [],
            f'Missing prompt files: {missing}',
        )


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


@override_settings(STORAGES=_NO_MANIFEST_STORAGES)
class InputNormalizationViewTests(TestCase):
    """v0.5.2 — `/bo/input-normalization/` CRUD 회귀.

    BO 인증 decorator 는 본 스코프 비포함 (plan §5.3). CSRF/POST 보호만 검증.
    """

    def test_index_empty(self):
        url = reverse('bo:input_norm')
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, '입력 정규화')
        self.assertContains(response, '아직 등록된 규칙이 없습니다')

    def test_create_canonicalizes_pattern(self):
        url = reverse('bo:input_norm_new')
        response = self.client.post(url, {
            'pattern': 'RUDWHTK　',
            'replacement': '경조사',
            'match_type': 'exact',
            'priority': '100',
            'enabled': 'on',
            'description': '',
        })
        self.assertEqual(response.status_code, 302)
        from chat.models import InputNormalizationRule
        rule = InputNormalizationRule.objects.get()
        self.assertEqual(rule.pattern, 'rudwhtk')

    def test_create_invalid_returns_form(self):
        url = reverse('bo:input_norm_new')
        response = self.client.post(url, {
            'pattern': 'a',
            'replacement': 'alpha',
            'match_type': 'contains',
            'priority': '100',
            'enabled': 'on',
            'description': '',
        })
        # 검증 실패 → form 재렌더 (200), DB 추가 없음.
        self.assertEqual(response.status_code, 200)
        from chat.models import InputNormalizationRule
        self.assertEqual(InputNormalizationRule.objects.count(), 0)

    def test_toggle_post_only(self):
        from chat.models import InputNormalizationRule
        rule = InputNormalizationRule.objects.create(
            pattern='abc', replacement='alpha', match_type='exact',
        )
        url = reverse('bo:input_norm_toggle', args=[rule.pk])
        # GET 거부 (require_POST).
        self.assertEqual(self.client.get(url).status_code, 405)
        # POST 토글.
        response = self.client.post(url)
        self.assertEqual(response.status_code, 302)
        rule.refresh_from_db()
        self.assertFalse(rule.enabled)

    def test_delete_post_only(self):
        from chat.models import InputNormalizationRule
        rule = InputNormalizationRule.objects.create(
            pattern='abc', replacement='alpha', match_type='exact',
        )
        url = reverse('bo:input_norm_delete', args=[rule.pk])
        self.assertEqual(self.client.get(url).status_code, 405)
        response = self.client.post(url)
        self.assertEqual(response.status_code, 302)
        self.assertEqual(InputNormalizationRule.objects.count(), 0)


# ---------------------------------------------------------------------------
# v0.5.3 — BO 파일관리 READY 수정 + 재임베딩 + 청크 확인
# ---------------------------------------------------------------------------

def _make_doc(status=Document.Status.READY, edited_text='OLD TEXT', **kwargs):
    """테스트용 Document 헬퍼 (실제 파일 생성 없이 문자열 경로 사용)."""
    return Document.objects.create(
        file='origin/test.txt',
        original_name='test.txt',
        size_bytes=11,
        mime_type='text/plain',
        status=status,
        edited_text=edited_text,
        **kwargs,
    )


def _make_chunks(doc, count=3):
    """테스트용 DocumentChunk 헬퍼."""
    return [
        DocumentChunk.objects.create(
            document=doc,
            chunk_index=i,
            content=f'chunk {i}',
            embedding=[0.0] * 1536,
        )
        for i in range(count)
    ]


@override_settings(STORAGES=_NO_MANIFEST_STORAGES)
class FileListButtonTests(TestCase):
    """§9.1.1 — 파일 목록 버튼 노출 및 순서."""

    def _get_row_html(self, doc):
        response = self.client.get(reverse('bo:files'))
        content = response.content.decode()
        row_start = content.find(f'bo/files/{doc.pk}/')
        row_end = content.find('</tr>', row_start)
        return content[row_start:row_end]

    def test_ready_doc_shows_three_buttons_in_order(self):
        doc = _make_doc(status=Document.Status.READY)
        row = self._get_row_html(doc)
        chunk_pos = row.find('청크 확인')
        edit_pos = row.find('수정')
        delete_pos = row.find('삭제')
        self.assertGreater(chunk_pos, -1, '청크 확인 버튼 없음')
        self.assertGreater(edit_pos, -1, '수정 버튼 없음')
        self.assertGreater(delete_pos, -1, '삭제 버튼 없음')
        self.assertLess(chunk_pos, edit_pos)
        self.assertLess(edit_pos, delete_pos)

    def test_reviewing_doc_has_no_chunk_button(self):
        doc = _make_doc(status=Document.Status.REVIEWING)
        row = self._get_row_html(doc)
        self.assertEqual(row.find('청크 확인'), -1)
        self.assertGreater(row.find('검토'), -1)

    def test_failed_doc_has_no_chunk_button(self):
        doc = _make_doc(status=Document.Status.FAILED)
        row = self._get_row_html(doc)
        self.assertEqual(row.find('청크 확인'), -1)
        self.assertGreater(row.find('검토'), -1)

    def test_pending_doc_has_no_chunk_or_edit_button(self):
        doc = _make_doc(status=Document.Status.PENDING)
        row = self._get_row_html(doc)
        self.assertEqual(row.find('청크 확인'), -1)
        self.assertEqual(row.find('수정'), -1)


@override_settings(STORAGES=_NO_MANIFEST_STORAGES)
class ReadyDocReviewPageTests(TestCase):
    """§9.1.2 — READY 문서 review 진입."""

    def test_ready_doc_review_returns_200(self):
        doc = _make_doc(status=Document.Status.READY)
        response = self.client.get(reverse('bo:review', args=[doc.pk]))
        self.assertEqual(response.status_code, 200)

    def test_ready_doc_review_shows_banner(self):
        doc = _make_doc(status=Document.Status.READY)
        response = self.client.get(reverse('bo:review', args=[doc.pk]))
        self.assertContains(response, '이미 검색 가능한 상태')

    def test_ready_doc_review_shows_reembed_button(self):
        doc = _make_doc(status=Document.Status.READY)
        response = self.client.get(reverse('bo:review', args=[doc.pk]))
        self.assertContains(response, '재임베딩 진행')

    def test_ready_doc_review_has_confirm_onsubmit(self):
        doc = _make_doc(status=Document.Status.READY)
        response = self.client.get(reverse('bo:review', args=[doc.pk]))
        self.assertContains(response, '이미 검색 가능한 문서입니다')


@override_settings(STORAGES=_NO_MANIFEST_STORAGES)
class ReembedSuccessTests(TestCase):
    """§9.1.3 — READY 재임베딩 성공 시 old chunks 교체."""

    def test_reembed_success_replaces_chunks(self):
        doc = _make_doc(status=Document.Status.READY, edited_text='OLD TEXT')
        _make_chunks(doc, count=3)

        new_vectors = [[0.1] * 1536, [0.2] * 1536]
        with patch('files.services.pipeline.embed_texts', return_value=new_vectors), \
             patch('files.services.pipeline.chunk_text', return_value=['chunk A', 'chunk B']):
            response = self.client.post(
                reverse('bo:confirm', args=[doc.pk]),
                {'edited_text': 'NEW TEXT'},
            )

        self.assertRedirects(response, reverse('bo:files'))
        doc.refresh_from_db()
        self.assertEqual(doc.edited_text, 'NEW TEXT')
        self.assertEqual(doc.status, Document.Status.READY)
        self.assertEqual(doc.error_message, '')
        chunks = list(DocumentChunk.objects.filter(document=doc).order_by('chunk_index'))
        self.assertEqual(len(chunks), 2)
        self.assertEqual(chunks[0].chunk_index, 0)


@override_settings(STORAGES=_NO_MANIFEST_STORAGES)
class ReembedFailureTests(TestCase):
    """§9.1.4 — READY 재임베딩 실패 시 기존 상태 보존."""

    def test_reembed_failure_preserves_status_and_chunks(self):
        from files.services.embedder import EmbeddingError
        doc = _make_doc(status=Document.Status.READY, edited_text='OLD TEXT')
        _make_chunks(doc, count=3)

        with patch('files.services.pipeline.embed_texts', side_effect=EmbeddingError('API 오류')), \
             patch('files.services.pipeline.chunk_text', return_value=['chunk A', 'chunk B']):
            response = self.client.post(
                reverse('bo:confirm', args=[doc.pk]),
                {'edited_text': 'NEW TEXT'},
            )

        self.assertRedirects(response, reverse('bo:review', args=[doc.pk]))
        doc.refresh_from_db()
        self.assertEqual(doc.status, Document.Status.READY)
        self.assertEqual(doc.edited_text, 'OLD TEXT')
        self.assertEqual(DocumentChunk.objects.filter(document=doc).count(), 3)
        self.assertNotEqual(doc.error_message, '')


@override_settings(STORAGES=_NO_MANIFEST_STORAGES)
class ChunksPageTests(TestCase):
    """§9.1.5 — 청크 확인 페이지 read-only / 순서."""

    def test_chunks_page_returns_200(self):
        doc = _make_doc(status=Document.Status.READY)
        response = self.client.get(reverse('bo:chunks', args=[doc.pk]))
        self.assertEqual(response.status_code, 200)

    def test_chunks_page_has_no_form_post_or_inputs(self):
        doc = _make_doc(status=Document.Status.READY)
        _make_chunks(doc, count=2)
        response = self.client.get(reverse('bo:chunks', args=[doc.pk]))
        content = response.content.decode()
        self.assertNotIn('<form method="post"', content.lower().replace('method="post"', 'method="post"'))
        self.assertNotIn('<textarea', content)
        self.assertNotIn('<input', content)

    def test_chunks_page_orders_by_chunk_index(self):
        doc = _make_doc(status=Document.Status.READY)
        DocumentChunk.objects.create(document=doc, chunk_index=2, content='C', embedding=[0.0]*1536)
        DocumentChunk.objects.create(document=doc, chunk_index=0, content='A', embedding=[0.0]*1536)
        DocumentChunk.objects.create(document=doc, chunk_index=1, content='B', embedding=[0.0]*1536)
        response = self.client.get(reverse('bo:chunks', args=[doc.pk]))
        content = response.content.decode()
        pos0 = content.find('#0')
        pos1 = content.find('#1')
        pos2 = content.find('#2')
        self.assertLess(pos0, pos1)
        self.assertLess(pos1, pos2)


@override_settings(STORAGES=_NO_MANIFEST_STORAGES)
class ReviewingConfirmRegressionTests(TestCase):
    """§9.1.6 — 기존 REVIEWING 검토 흐름 회귀."""

    def test_reviewing_confirm_uses_finalize_not_reembed(self):
        doc = _make_doc(status=Document.Status.REVIEWING, edited_text='')

        with patch('bo.views.files.reembed_document') as mock_reembed, \
             patch('bo.views.files.finalize_document', return_value=2) as mock_finalize:
            self.client.post(
                reverse('bo:confirm', args=[doc.pk]),
                {'edited_text': 'SOME TEXT'},
            )

        mock_finalize.assert_called_once()
        mock_reembed.assert_not_called()

    def test_failed_confirm_uses_finalize_not_reembed(self):
        doc = _make_doc(status=Document.Status.FAILED, edited_text='')

        with patch('bo.views.files.reembed_document') as mock_reembed, \
             patch('bo.views.files.finalize_document', return_value=1) as mock_finalize:
            self.client.post(
                reverse('bo:confirm', args=[doc.pk]),
                {'edited_text': 'SOME TEXT'},
            )

        mock_finalize.assert_called_once()
        mock_reembed.assert_not_called()


@override_settings(STORAGES=_NO_MANIFEST_STORAGES)
class ReadyReviewCancelButtonTests(TestCase):
    """§9.1.7 — READY review 페이지에서 취소 및 삭제 문구 부재."""

    def test_ready_review_has_no_cancel_delete_text(self):
        doc = _make_doc(status=Document.Status.READY)
        response = self.client.get(reverse('bo:review', args=[doc.pk]))
        self.assertNotContains(response, '취소 및 삭제')
        self.assertNotContains(response, '업로드를 취소')

    def test_ready_review_has_back_to_list_link(self):
        doc = _make_doc(status=Document.Status.READY)
        response = self.client.get(reverse('bo:review', args=[doc.pk]))
        self.assertContains(response, '목록으로')

    def test_reviewing_review_keeps_cancel_button(self):
        doc = _make_doc(status=Document.Status.REVIEWING)
        response = self.client.get(reverse('bo:review', args=[doc.pk]))
        self.assertContains(response, '취소 및 삭제')


@override_settings(STORAGES=_NO_MANIFEST_STORAGES)
class ChunksSidebarActiveTests(TestCase):
    """§9.1.8 — 청크 확인 페이지 사이드바 파일관리 active."""

    def test_chunks_page_sidebar_files_active(self):
        doc = _make_doc(status=Document.Status.READY)
        response = self.client.get(reverse('bo:chunks', args=[doc.pk]))
        content = response.content.decode()
        # 파일관리 사이드바 링크에 active 클래스가 있는지 확인
        import re
        match = re.search(r'href="/bo/files/"[^>]*class="([^"]*)"', content)
        self.assertIsNotNone(match, '파일관리 링크를 찾을 수 없음')
        self.assertIn('active', match.group(1))


@override_settings(STORAGES=_NO_MANIFEST_STORAGES)
class ChunksRelatedNameTests(TestCase):
    """§9.1.9 — doc.chunks related_name 회귀."""

    def test_doc_chunks_related_name_works(self):
        doc = _make_doc(status=Document.Status.READY)
        DocumentChunk.objects.create(document=doc, chunk_index=0, content='test', embedding=[0.0]*1536)
        self.assertEqual(doc.chunks.count(), 1)

    def test_doc_chunks_order_by(self):
        doc = _make_doc(status=Document.Status.READY)
        DocumentChunk.objects.create(document=doc, chunk_index=1, content='B', embedding=[0.0]*1536)
        DocumentChunk.objects.create(document=doc, chunk_index=0, content='A', embedding=[0.0]*1536)
        ordered = list(doc.chunks.order_by('chunk_index').values_list('chunk_index', flat=True))
        self.assertEqual(ordered, [0, 1])

    def test_documentchunk_set_does_not_exist(self):
        doc = _make_doc(status=Document.Status.READY)
        with self.assertRaises(AttributeError):
            _ = doc.documentchunk_set


# ---------------------------------------------------------------------------
# Issue #93 — chunk 단위 편집 & 재임베딩
# ---------------------------------------------------------------------------


def _fake_vec(_text):
    # 결정적 벡터. 입력 길이로 0번 슬롯만 살짝 바꿔서 변경 가능 여부 확인.
    v = [0.0] * 1536
    v[0] = float(len(_text) % 7) + 0.1
    return v


@override_settings(STORAGES=_NO_MANIFEST_STORAGES)
class ReembedChunkServiceTests(TestCase):
    """Issue #93 §8.1 — `reembed_chunk` 서비스 단위."""

    def test_reembed_chunk_success_updates_content_and_embedding(self):
        from files.services import pipeline
        doc = _make_doc(status=Document.Status.READY)
        chunks = _make_chunks(doc, count=3)
        target = chunks[1]
        other = chunks[2]

        with patch('files.services.pipeline.embed_text', side_effect=_fake_vec) as m:
            pipeline.reembed_chunk(target, '새 내용')

        m.assert_called_once_with('새 내용')
        target.refresh_from_db()
        other.refresh_from_db()
        self.assertEqual(target.content, '새 내용')
        self.assertNotEqual(target.embedding[0], 0.0)
        # 다른 chunk 미변경.
        self.assertEqual(other.content, 'chunk 2')

    def test_reembed_chunk_empty_content_raises_pipeline_error(self):
        from files.services import pipeline
        doc = _make_doc(status=Document.Status.READY)
        chunk = _make_chunks(doc, 1)[0]
        with patch('files.services.pipeline.embed_text', side_effect=_fake_vec) as m:
            with self.assertRaises(pipeline.PipelineError):
                pipeline.reembed_chunk(chunk, '   ')
        m.assert_not_called()
        chunk.refresh_from_db()
        self.assertEqual(chunk.content, 'chunk 0')

    def test_reembed_chunk_embedding_failure_preserves_original(self):
        from files.services import pipeline
        from files.services.embedder import EmbeddingError
        doc = _make_doc(status=Document.Status.READY)
        chunk = _make_chunks(doc, 1)[0]

        with patch('files.services.pipeline.embed_text', side_effect=EmbeddingError('boom')):
            with self.assertRaises(pipeline.PipelineError):
                pipeline.reembed_chunk(chunk, '새 내용')

        chunk.refresh_from_db()
        self.assertEqual(chunk.content, 'chunk 0')


@override_settings(STORAGES=_NO_MANIFEST_STORAGES)
class ChunkEditViewTests(TestCase):
    """Issue #93 §8.2 — chunk_edit view 통합."""

    def _url(self, doc, chunk):
        return reverse('bo:chunk_edit', args=[doc.pk, chunk.pk])

    def test_get_renders_form_for_ready_doc(self):
        doc = _make_doc(status=Document.Status.READY)
        chunk = _make_chunks(doc, 1)[0]
        response = self.client.get(self._url(doc, chunk))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, '단 하나의 chunk만 재임베딩')
        self.assertContains(response, '임베딩 API 1회 호출')
        self.assertContains(response, 'chunk 0')

    def test_get_404_for_chunk_belonging_to_other_doc(self):
        doc_a = _make_doc(status=Document.Status.READY)
        doc_b = _make_doc(status=Document.Status.READY)
        chunk_b = _make_chunks(doc_b, 1)[0]
        url = reverse('bo:chunk_edit', args=[doc_a.pk, chunk_b.pk])
        response = self.client.get(url)
        self.assertEqual(response.status_code, 404)

    def test_get_redirects_when_doc_not_ready(self):
        doc = _make_doc(status=Document.Status.REVIEWING)
        chunk = _make_chunks(doc, 1)[0]
        response = self.client.get(self._url(doc, chunk))
        self.assertRedirects(response, reverse('bo:chunks', args=[doc.pk]))

    def test_post_calls_service_and_redirects(self):
        doc = _make_doc(status=Document.Status.READY)
        chunk = _make_chunks(doc, 1)[0]
        with patch('bo.views.files.reembed_chunk') as m:
            response = self.client.post(self._url(doc, chunk), {'content': '새 본문'})
        self.assertRedirects(response, reverse('bo:chunks', args=[doc.pk]))
        self.assertEqual(m.call_count, 1)
        args, _kwargs = m.call_args
        self.assertEqual(args[0].pk, chunk.pk)
        self.assertEqual(args[1], '새 본문')

    def test_post_real_service_updates_db_with_embed_text_patched(self):
        doc = _make_doc(status=Document.Status.READY)
        chunk = _make_chunks(doc, 1)[0]
        with patch('files.services.pipeline.embed_text', side_effect=_fake_vec):
            response = self.client.post(self._url(doc, chunk), {'content': '실서비스 갱신'})
        self.assertEqual(response.status_code, 302)
        chunk.refresh_from_db()
        self.assertEqual(chunk.content, '실서비스 갱신')
        self.assertNotEqual(chunk.embedding[0], 0.0)

    def test_post_embedding_failure_shows_error_and_keeps_content(self):
        from files.services.embedder import EmbeddingError
        doc = _make_doc(status=Document.Status.READY)
        chunk = _make_chunks(doc, 1)[0]
        with patch('files.services.pipeline.embed_text', side_effect=EmbeddingError('nope')):
            response = self.client.post(self._url(doc, chunk), {'content': '실패해라'})
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, '재임베딩 실패')
        chunk.refresh_from_db()
        self.assertEqual(chunk.content, 'chunk 0')

    def test_post_over_token_limit_rejects_without_calling_service(self):
        doc = _make_doc(status=Document.Status.READY)
        chunk = _make_chunks(doc, 1)[0]
        # 8001 토큰 이상 — 단순한 영문 단어 반복으로 충분히 초과.
        huge = ('word ' * 9000).strip()
        with patch('bo.views.files.reembed_chunk') as m_svc, \
             patch('files.services.pipeline.embed_text') as m_emb:
            response = self.client.post(self._url(doc, chunk), {'content': huge})
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, '토큰 상한')
        m_svc.assert_not_called()
        m_emb.assert_not_called()
        chunk.refresh_from_db()
        self.assertEqual(chunk.content, 'chunk 0')

    def test_post_empty_content_rejects_without_calling_service(self):
        doc = _make_doc(status=Document.Status.READY)
        chunk = _make_chunks(doc, 1)[0]
        with patch('bo.views.files.reembed_chunk') as m_svc, \
             patch('files.services.pipeline.embed_text') as m_emb:
            response = self.client.post(self._url(doc, chunk), {'content': '   '})
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, '내용이 비어')
        m_svc.assert_not_called()
        m_emb.assert_not_called()

    def test_chunks_page_shows_edit_button_only_when_ready(self):
        ready_doc = _make_doc(status=Document.Status.READY)
        _make_chunks(ready_doc, 1)
        response = self.client.get(reverse('bo:chunks', args=[ready_doc.pk]))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, '/edit/')
        self.assertContains(response, '>수정</a>')

        # 비-READY 상태: edit 버튼 없음.
        reviewing = _make_doc(status=Document.Status.REVIEWING)
        _make_chunks(reviewing, 1)
        response2 = self.client.get(reverse('bo:chunks', args=[reviewing.pk]))
        self.assertEqual(response2.status_code, 200)
        self.assertNotContains(response2, '>수정</a>')

    def test_sidebar_active_on_chunk_edit_page(self):
        doc = _make_doc(status=Document.Status.READY)
        chunk = _make_chunks(doc, 1)[0]
        response = self.client.get(self._url(doc, chunk))
        content = response.content.decode()
        # 파일관리 사이드바 항목이 active 클래스로 렌더되는지.
        import re
        match = re.search(r'<a[^>]+href="[^"]*/bo/files/"[^>]+class="([^"]+)"', content)
        self.assertIsNotNone(match, '파일관리 사이드바 링크를 찾을 수 없음')
        self.assertIn('active', match.group(1))

    def test_review_page_shows_full_reembed_warning_when_ready(self):
        doc = _make_doc(status=Document.Status.READY)
        response = self.client.get(reverse('bo:review', args=[doc.pk]))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, '모든 chunk 를 새로 생성')

    def _unused(self):
        pass


# ---------------------------------------------------------------------------
# v0.5.6 — BO 문제 제보 (Issue #94)
# ---------------------------------------------------------------------------

@override_settings(STORAGES=_NO_MANIFEST_STORAGES)
class ProblemReportBoTests(TestCase):
    """BO 리스트/상세/업데이트 회귀."""

    def setUp(self):
        from chat.models import ProblemReport
        self.r = ProblemReport.objects.create(
            title='버그',
            content='답이 이상함',
            last_question='왜 안 돼?',
            turn_count=2,
            conversation=[
                {'role': 'user', 'content': '왜 안 돼?', 'ts': ''},
                {'role': 'assistant', 'content': '죄송합니다', 'sources': [{'name': 'a', 'url': 'b'}], 'chat_log_id': 7, 'ts': ''},
            ],
        )

    def test_list_renders(self):
        url = reverse('bo:report_list')
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, '문제 제보')
        self.assertContains(response, '<table class="report-table">')
        self.assertContains(response, '버그')
        self.assertContains(response, '마지막 질문')
        self.assertContains(response, '메시지')
        self.assertContains(response, '2개')
        self.assertContains(response, '전체')
        self.assertContains(response, '신규')

    def test_list_paginates_ten_reports_per_page(self):
        from chat.models import ProblemReport
        for idx in range(11):
            ProblemReport.objects.create(title=f'제보 {idx}', content='내용')

        url = reverse('bo:report_list')
        first = self.client.get(url)
        second = self.client.get(url, {'page': 2})

        self.assertEqual(len(first.context['items']), 10)
        self.assertEqual(len(second.context['items']), 2)
        self.assertContains(first, '1 / 2 페이지')
        self.assertContains(second, '2 / 2 페이지')

    def test_list_filter_by_status(self):
        from chat.models import ProblemReport
        ProblemReport.objects.create(title='완료된거', content='c', status='resolved')
        url = reverse('bo:report_list')
        response = self.client.get(url, {'status': 'resolved'})
        self.assertContains(response, '완료된거')
        self.assertNotContains(response, '버그')

    def test_list_filter_by_q(self):
        url = reverse('bo:report_list')
        response = self.client.get(url, {'q': '버그'})
        self.assertContains(response, '버그')

    def test_detail_renders(self):
        url = reverse('bo:report_detail', args=[self.r.pk])
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, '버그')
        self.assertContains(response, '답이 이상함')
        self.assertContains(response, '사용자')
        self.assertContains(response, 'TA9')
        self.assertContains(response, '죄송합니다')
        # chat_log_id 는 텍스트만, 링크 아님
        self.assertContains(response, 'chat_log_id: 7')
        self.assertNotContains(response, 'href="/bo/qa/logs/7')

    def test_detail_renders_markdown_and_server_time(self):
        from chat.models import ProblemReport
        report = ProblemReport.objects.create(
            title='마크다운',
            content='**굵게**\n\n| 구분 | 값 |\n| --- | --- |\n| A | `1` |',
            conversation=[
                {'role': 'user', 'content': '- 항목', 'ts': '2026-05-18T09:10:11+09:00'},
            ],
        )

        response = self.client.get(reverse('bo:report_detail', args=[report.pk]))

        self.assertContains(response, '<strong>굵게</strong>', html=True)
        self.assertContains(response, '<table class="report-md-table">')
        self.assertContains(response, '<code>1</code>', html=True)
        self.assertContains(response, '<li>항목</li>', html=True)
        self.assertContains(response, '2026-05-18 09:10:11')

    def test_update_status(self):
        url = reverse('bo:report_update', args=[self.r.pk])
        response = self.client.post(url, {'status': 'in_progress', 'admin_note': ''})
        self.assertEqual(response.status_code, 302)
        self.r.refresh_from_db()
        self.assertEqual(self.r.status, 'in_progress')

    def test_update_admin_note(self):
        url = reverse('bo:report_update', args=[self.r.pk])
        response = self.client.post(url, {'status': 'open', 'admin_note': '확인했음'})
        self.assertEqual(response.status_code, 302)
        self.r.refresh_from_db()
        self.assertEqual(self.r.admin_note, '확인했음')

    def test_update_invalid_status_rejected(self):
        url = reverse('bo:report_update', args=[self.r.pk])
        response = self.client.post(url, {'status': 'nope', 'admin_note': ''})
        self.assertEqual(response.status_code, 400)
        self.r.refresh_from_db()
        self.assertEqual(self.r.status, 'open')

    def test_update_admin_note_too_long_rejected(self):
        url = reverse('bo:report_update', args=[self.r.pk])
        response = self.client.post(url, {'status': 'open', 'admin_note': 'x' * 4001})
        self.assertEqual(response.status_code, 400)
        self.r.refresh_from_db()
        self.assertEqual(self.r.admin_note, '')

    def test_delete_hard_deletes_report(self):
        from chat.models import ProblemReport
        url = reverse('bo:report_delete', args=[self.r.pk])
        response = self.client.post(url)

        self.assertRedirects(response, reverse('bo:report_list'))
        self.assertFalse(ProblemReport.objects.filter(pk=self.r.pk).exists())

    def test_sidebar_active_on_report_pages(self):
        # base.html 사이드바에서 report_list 가 active 클래스로 렌더되는지.
        import re
        url = reverse('bo:report_detail', args=[self.r.pk])
        response = self.client.get(url)
        content = response.content.decode()
        match = re.search(r'href="/bo/reports/"[^>]*class="([^"]+)"', content)
        self.assertIsNotNone(match)
        self.assertIn('active', match.group(1))


# ---------------------------------------------------------------------------
# (이전 ChunkEdit 클래스의 잔여 메서드는 보존)
# ---------------------------------------------------------------------------

class _ChunkEditExtraTests(TestCase):
    """Issue #93 §8.2 추가 — chunk 단위 편집 후 전체 재임베딩 회귀."""

    def test_full_reembed_document_still_works_after_chunk_edit(self):
        from files.services import pipeline
        doc = _make_doc(status=Document.Status.READY, edited_text='원문')
        chunks = _make_chunks(doc, 3)
        # chunk 편집 1회.
        with patch('files.services.pipeline.embed_text', side_effect=_fake_vec):
            pipeline.reembed_chunk(chunks[1], 'chunk 단위 마커')
        chunks[1].refresh_from_db()
        self.assertEqual(chunks[1].content, 'chunk 단위 마커')

        # 전체 재임베딩 → 새 chunk 셋으로 교체.
        with patch('files.services.pipeline.embed_texts', return_value=[[0.0]*1536]):
            pipeline.reembed_document(doc, '새 전체 본문')

        # chunk 단위 수정분 사라짐.
        contents = list(doc.chunks.values_list('content', flat=True))
        self.assertNotIn('chunk 단위 마커', contents)
