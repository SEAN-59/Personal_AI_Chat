"""Phase 6-1 date_calculation workflow 단위 테스트."""

from django.test import SimpleTestCase

from chat.workflows.core import WorkflowStatus, run_workflow
from chat.workflows.domains.general.date_calculation import (
    DateCalculationWorkflow,
    WORKFLOW_KEY,
)


class DateCalculationTests(SimpleTestCase):
    def _run(self, raw):
        return run_workflow(DateCalculationWorkflow(), raw)

    def test_days_between_default_unit(self):
        r = self._run({'start': '2025-01-01', 'end': '2025-01-31'})
        self.assertEqual(r.status, WorkflowStatus.OK)
        self.assertEqual(r.value, 30)
        self.assertEqual(r.details['unit'], 'days')
        self.assertEqual(r.details['unit_label'], '일')
        self.assertEqual(r.details['start'], '2025-01-01')
        self.assertEqual(r.details['end'], '2025-01-31')

    def test_months_unit(self):
        r = self._run({'start': '2024-01-15', 'end': '2024-03-15', 'unit': 'months'})
        self.assertEqual(r.value, 2)
        self.assertEqual(r.details['unit_label'], '개월')

    def test_years_unit(self):
        r = self._run({'start': '2020-05-10', 'end': '2025-05-10', 'unit': 'years'})
        self.assertEqual(r.value, 5)
        self.assertEqual(r.details['unit_label'], '년')

    def test_korean_natural_date(self):
        r = self._run({'start': '2024년 1월 1일', 'end': '2024년 2월 1일'})
        self.assertEqual(r.status, WorkflowStatus.OK)
        self.assertEqual(r.value, 31)

    def test_missing_end_returns_missing_input(self):
        r = self._run({'start': '2024-01-01'})
        self.assertEqual(r.status, WorkflowStatus.MISSING_INPUT)
        self.assertIn('end', r.missing_fields)

    def test_blank_string_counts_as_missing(self):
        r = self._run({'start': '  ', 'end': '2024-01-01'})
        self.assertEqual(r.status, WorkflowStatus.MISSING_INPUT)
        self.assertIn('start', r.missing_fields)

    def test_invalid_date_format_returns_invalid_input(self):
        r = self._run({'start': '31 January 2024', 'end': '2024-02-01'})
        self.assertEqual(r.status, WorkflowStatus.INVALID_INPUT)
        errors_text = '\n'.join(r.details['errors'])
        self.assertIn('시작일', errors_text)

    def test_reversed_order_returns_invalid_input(self):
        r = self._run({'start': '2024-12-31', 'end': '2024-01-01'})
        self.assertEqual(r.status, WorkflowStatus.INVALID_INPUT)
        self.assertTrue(
            any('시작일이 종료일보다 뒤' in e for e in r.details['errors'])
        )

    def test_unknown_unit_returns_invalid_input(self):
        r = self._run({'start': '2024-01-01', 'end': '2024-02-01', 'unit': 'weeks'})
        self.assertEqual(r.status, WorkflowStatus.INVALID_INPUT)
        self.assertTrue(
            any('unit' in e for e in r.details['errors'])
        )

    def test_registered_in_registry(self):
        """import 만으로 registry 에 자동 등록되는지 확인."""
        from chat.workflows.domains import registry
        self.assertTrue(registry.has(WORKFLOW_KEY))
        entry = registry.get(WORKFLOW_KEY)
        self.assertEqual(entry.status, registry.STATUS_STABLE)
