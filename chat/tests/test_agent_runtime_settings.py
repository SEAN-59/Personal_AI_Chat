"""Phase 8-3 — `load_runtime_settings()` 의 정상 / 폴백 / sanity 분기 회귀."""

from unittest.mock import patch

from django.test import SimpleTestCase, TestCase

from chat.services.agent import runtime_settings as rs


class LoadRuntimeSettingsHappyPathTests(TestCase):
    """DB 의 `AgentSettings` 1행이 정상 → frozen dataclass 로 freeze."""

    def test_returns_settings_from_db(self):
        settings = rs.load_runtime_settings()
        self.assertEqual(settings.enabled, True)
        self.assertEqual(settings.max_iterations, rs.DEFAULT_MAX_ITERATIONS)
        self.assertEqual(
            settings.max_low_relevance_retrieves,
            rs.DEFAULT_MAX_LOW_RELEVANCE_RETRIEVES,
        )

    def test_db_value_changes_reflected_immediately(self):
        from chat.models import AgentSettings
        row = AgentSettings.objects.get_solo()
        row.max_iterations = 4
        row.save()

        settings = rs.load_runtime_settings()
        self.assertEqual(settings.max_iterations, 4)


class LoadRuntimeSettingsFallbackTests(SimpleTestCase):
    """DB 조회 실패 / sanity 실패 → `_DEFAULTS` 폴백."""

    def test_db_query_exception_falls_back_to_defaults(self):
        # AgentSettings.objects.get_solo() 가 예외 → _DEFAULTS.
        with patch(
            'chat.models.AgentSettings.objects.get_solo',
            side_effect=RuntimeError('db down'),
        ):
            settings = rs.load_runtime_settings()
        self.assertEqual(settings, rs._DEFAULTS)

    def test_sanity_check_demotes_invalid_db_value(self):
        # CheckConstraint 가 정상 환경에선 raw 비정상 값 INSERT 를 차단하므로
        # manager 자체를 patch 해 비정상 dataclass 반환시켜 sanity 분기 격리 검증.
        from types import SimpleNamespace
        bad_row = SimpleNamespace(
            enabled=True,
            max_iterations=999,                     # 범위 밖.
            max_low_relevance_retrieves=3,
        )
        with patch(
            'chat.models.AgentSettings.objects.get_solo',
            return_value=bad_row,
        ):
            settings = rs.load_runtime_settings()
        # _DEFAULTS 로 절감되었는지.
        self.assertEqual(settings, rs._DEFAULTS)

    def test_sanity_check_demotes_invalid_low_relevance(self):
        from types import SimpleNamespace
        bad_row = SimpleNamespace(
            enabled=True, max_iterations=6, max_low_relevance_retrieves=99,
        )
        with patch(
            'chat.models.AgentSettings.objects.get_solo',
            return_value=bad_row,
        ):
            settings = rs.load_runtime_settings()
        self.assertEqual(settings, rs._DEFAULTS)
