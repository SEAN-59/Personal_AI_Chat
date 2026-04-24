"""Phase 5 validation 헬퍼 단위 테스트."""

from django.test import SimpleTestCase

from chat.workflows.core.result import ValidationResult
from chat.workflows.core.validation import (
    combine_validations,
    require_fields,
    require_non_empty,
)


class RequireFieldsTests(SimpleTestCase):
    def test_all_present_non_empty(self):
        r = require_fields({'a': 1, 'b': 'x'}, ['a', 'b'])
        self.assertTrue(r.ok)

    def test_missing_key(self):
        r = require_fields({'a': 1}, ['a', 'b'])
        self.assertFalse(r.ok)
        self.assertEqual(r.missing_fields, ('b',))

    def test_none_value_counted_missing(self):
        r = require_fields({'a': None}, ['a'])
        self.assertEqual(r.missing_fields, ('a',))

    def test_blank_string_counted_missing(self):
        r = require_fields({'a': '   '}, ['a'])
        self.assertEqual(r.missing_fields, ('a',))

    def test_zero_is_not_missing(self):
        # 0 은 유효한 값 (금액 계산 등) — 비어있다고 보지 않는다.
        r = require_fields({'a': 0}, ['a'])
        self.assertTrue(r.ok)

    def test_data_must_be_mapping(self):
        with self.assertRaises(TypeError):
            require_fields(['a'], ['a'])


class RequireNonEmptyTests(SimpleTestCase):
    def test_non_empty_value_passes(self):
        self.assertTrue(require_non_empty('2026-01-01', 'start').ok)

    def test_none_fails_with_field_name(self):
        r = require_non_empty(None, 'start')
        self.assertEqual(r.missing_fields, ('start',))

    def test_blank_string_fails(self):
        r = require_non_empty('\t  ', 'start')
        self.assertEqual(r.missing_fields, ('start',))

    def test_field_name_required(self):
        with self.assertRaises(ValueError):
            require_non_empty('x', '')


class CombineValidationsTests(SimpleTestCase):
    def test_empty_input_returns_success(self):
        self.assertTrue(combine_validations().ok)

    def test_all_ok_returns_success(self):
        r = combine_validations(
            ValidationResult.success(),
            ValidationResult.success(),
        )
        self.assertTrue(r.ok)

    def test_merges_missing_fields_preserving_order(self):
        r = combine_validations(
            ValidationResult.fail(missing=['a', 'b']),
            ValidationResult.fail(missing=['b', 'c']),
        )
        self.assertFalse(r.ok)
        self.assertEqual(r.missing_fields, ('a', 'b', 'c'))

    def test_merges_errors_preserving_order(self):
        r = combine_validations(
            ValidationResult.fail(errors=['x']),
            ValidationResult.fail(errors=['y', 'x']),
        )
        self.assertEqual(r.errors, ('x', 'y'))

    def test_mixed_ok_and_fail_returns_fail(self):
        r = combine_validations(
            ValidationResult.success(),
            ValidationResult.fail(missing=['a']),
        )
        self.assertFalse(r.ok)
        self.assertEqual(r.missing_fields, ('a',))
