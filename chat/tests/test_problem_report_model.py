"""ProblemReport 모델 단위 테스트 (v0.5.6 Issue #94)."""

from django.core.exceptions import ValidationError
from django.test import TestCase

from chat.models import ProblemReport


class ProblemReportModelTests(TestCase):
    def test_create_with_defaults(self):
        r = ProblemReport.objects.create(title='t', content='c')
        self.assertEqual(r.status, 'open')
        self.assertEqual(r.conversation, [])
        self.assertEqual(r.admin_note, '')
        self.assertEqual(r.turn_count, 0)
        self.assertEqual(r.session_key, '')
        self.assertEqual(r.last_question, '')

    def test_invalid_status_full_clean_raises(self):
        r = ProblemReport(title='t', content='c', status='nope')
        with self.assertRaises(ValidationError):
            r.full_clean()

    def test_str(self):
        r = ProblemReport.objects.create(title='hello', content='c')
        self.assertIn('hello', str(r))
        self.assertIn('open', str(r))
