"""Phase 5 base.run_workflow 단위 테스트."""

from typing import Any, Mapping

from django.test import SimpleTestCase

from chat.workflows.core import (
    BaseWorkflow,
    ValidationResult,
    WorkflowResult,
    WorkflowStatus,
    run_workflow,
)
from chat.workflows.core.numbers import sum_amounts


class _SumWorkflow:
    """a + b 를 계산하는 가상의 workflow — 4단계 계약 준수."""

    def prepare(self, raw: Mapping[str, Any]) -> Mapping[str, Any]:
        return {
            'a': raw.get('a'),
            'b': raw.get('b'),
        }

    def validate(self, normalized: Mapping[str, Any]) -> ValidationResult:
        missing = [k for k in ('a', 'b') if normalized.get(k) is None]
        if missing:
            return ValidationResult.fail(missing=missing)
        return ValidationResult.success()

    def execute(self, normalized: Mapping[str, Any]) -> WorkflowResult:
        total = sum_amounts([normalized['a'], normalized['b']])
        return WorkflowResult.ok(total, details={'operands': (normalized['a'], normalized['b'])})


class _InvalidWorkflow:
    def prepare(self, raw):
        return dict(raw)

    def validate(self, normalized):
        return ValidationResult.fail(errors=['always invalid'])

    def execute(self, normalized):
        raise AssertionError('execute 는 호출되면 안 된다.')


class BaseWorkflowProtocolTests(SimpleTestCase):
    def test_sum_workflow_satisfies_protocol(self):
        self.assertIsInstance(_SumWorkflow(), BaseWorkflow)

    def test_object_without_methods_is_not_base_workflow(self):
        class Empty:
            pass
        self.assertNotIsInstance(Empty(), BaseWorkflow)


class RunWorkflowTests(SimpleTestCase):
    def test_happy_path(self):
        r = run_workflow(_SumWorkflow(), {'a': '1,000', 'b': 2000})
        self.assertEqual(r.status, WorkflowStatus.OK)
        self.assertEqual(r.value, 3000)
        self.assertEqual(r.details['operands'], ('1,000', 2000))

    def test_missing_input_translated_to_missing_status(self):
        r = run_workflow(_SumWorkflow(), {'a': 1})
        self.assertEqual(r.status, WorkflowStatus.MISSING_INPUT)
        self.assertEqual(r.missing_fields, ('b',))

    def test_invalid_input_translated_to_invalid_status(self):
        r = run_workflow(_InvalidWorkflow(), {'a': 1, 'b': 2})
        self.assertEqual(r.status, WorkflowStatus.INVALID_INPUT)
        self.assertEqual(r.details['errors'], ('always invalid',))

    def test_rejects_non_workflow_argument(self):
        class NotAWorkflow:
            pass
        with self.assertRaises(TypeError):
            run_workflow(NotAWorkflow(), {})

    def test_prepare_must_return_mapping(self):
        class BadPrepare:
            def prepare(self, raw):
                return [1, 2, 3]  # not a mapping

            def validate(self, normalized):
                return ValidationResult.success()

            def execute(self, normalized):
                return WorkflowResult.ok(0)

        with self.assertRaises(TypeError):
            run_workflow(BadPrepare(), {})

    def test_validate_must_return_validation_result(self):
        class BadValidate:
            def prepare(self, raw):
                return {}

            def validate(self, normalized):
                return True  # wrong type

            def execute(self, normalized):
                return WorkflowResult.ok(0)

        with self.assertRaises(TypeError):
            run_workflow(BadValidate(), {})

    def test_execute_must_return_workflow_result(self):
        class BadExecute:
            def prepare(self, raw):
                return {}

            def validate(self, normalized):
                return ValidationResult.success()

            def execute(self, normalized):
                return 42  # wrong type

        with self.assertRaises(TypeError):
            run_workflow(BadExecute(), {})
