"""Phase 8-6 — `AgentSettingsAudit` 모델 단위 테스트."""

from django.contrib.auth import get_user_model
from django.test import TestCase

from chat.models import AgentSettingsAudit


User = get_user_model()


class AgentSettingsAuditTests(TestCase):
    def test_default_changed_by_null_allowed(self):
        # 익명 변경도 허용 (audit 은 변경 시도 자체를 보존).
        audit = AgentSettingsAudit.objects.create(
            changed_by=None,
            changes={'max_iterations': {'old': 6, 'new': 4}},
            snapshot={'max_iterations': 4, 'enabled': True},
        )
        self.assertIsNone(audit.changed_by)
        self.assertEqual(audit.changes['max_iterations']['new'], 4)
        self.assertEqual(audit.snapshot['max_iterations'], 4)

    def test_meta_ordering_newest_first(self):
        first = AgentSettingsAudit.objects.create(changes={'a': {'old': 1, 'new': 2}})
        second = AgentSettingsAudit.objects.create(changes={'b': {'old': 3, 'new': 4}})
        rows = list(AgentSettingsAudit.objects.all())
        # ordering ['-changed_at'] — 최신이 먼저.
        self.assertEqual(rows[0].pk, second.pk)
        self.assertEqual(rows[1].pk, first.pk)

    def test_changed_by_set_null_on_user_delete(self):
        user = User.objects.create_user(username='admin1', password='x')
        audit = AgentSettingsAudit.objects.create(
            changed_by=user,
            changes={'enabled': {'old': True, 'new': False}},
            snapshot={'enabled': False},
        )
        user.delete()
        audit.refresh_from_db()
        # SET_NULL — audit 보존, user FK 만 NULL.
        self.assertIsNone(audit.changed_by)
        self.assertEqual(audit.changes['enabled']['new'], False)
