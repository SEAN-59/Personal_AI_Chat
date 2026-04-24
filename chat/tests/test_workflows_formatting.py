"""Phase 5 formatting 헬퍼 단위 테스트."""

from datetime import date, datetime

from django.test import SimpleTestCase

from chat.workflows.core.formatting import (
    format_currency,
    format_date,
    format_duration,
)


class FormatCurrencyTests(SimpleTestCase):
    def test_basic(self):
        self.assertEqual(format_currency(1234567), '1,234,567원')

    def test_zero(self):
        self.assertEqual(format_currency(0), '0원')

    def test_negative(self):
        self.assertEqual(format_currency(-500), '-500원')

    def test_bool_rejected(self):
        with self.assertRaises(TypeError):
            format_currency(True)

    def test_float_rejected(self):
        with self.assertRaises(TypeError):
            format_currency(1.5)


class FormatDateTests(SimpleTestCase):
    def test_date_instance(self):
        self.assertEqual(format_date(date(2025, 1, 31)), '2025-01-31')

    def test_datetime_instance(self):
        self.assertEqual(
            format_date(datetime(2025, 1, 31, 15, 0)),
            '2025-01-31',
        )

    def test_iso_string(self):
        self.assertEqual(format_date('2025-01-31'), '2025-01-31')

    def test_non_iso_string_rejected(self):
        with self.assertRaises(ValueError):
            format_date('2025.01.31')

    def test_unsupported_type_rejected(self):
        with self.assertRaises(TypeError):
            format_date(12345)


class FormatDurationTests(SimpleTestCase):
    def test_all_parts(self):
        self.assertEqual(
            format_duration(years=1, months=2, days=3),
            '1년 2개월 3일',
        )

    def test_only_days(self):
        self.assertEqual(format_duration(days=30), '30일')

    def test_only_months(self):
        self.assertEqual(format_duration(months=3), '3개월')

    def test_only_years(self):
        self.assertEqual(format_duration(years=5), '5년')

    def test_skips_zero(self):
        self.assertEqual(format_duration(years=1, months=0, days=3), '1년 3일')

    def test_all_none_returns_empty(self):
        self.assertEqual(format_duration(), '')

    def test_negative_passed_through(self):
        self.assertEqual(format_duration(days=-5), '-5일')
