"""Phase 5 숫자 헬퍼 단위 테스트."""

from django.test import SimpleTestCase

from chat.workflows.core.numbers import (
    average_amount,
    parse_int_like,
    parse_money,
    sum_amounts,
)


class ParseIntLikeTests(SimpleTestCase):
    def test_plain_int_passthrough(self):
        self.assertEqual(parse_int_like(42), 42)

    def test_digit_string(self):
        self.assertEqual(parse_int_like('42'), 42)

    def test_commas_removed(self):
        self.assertEqual(parse_int_like('1,234,567'), 1234567)

    def test_won_suffix_removed(self):
        self.assertEqual(parse_int_like('1,234원'), 1234)

    def test_month_suffix_removed(self):
        self.assertEqual(parse_int_like('3개월'), 3)

    def test_year_suffix_removed(self):
        self.assertEqual(parse_int_like('5년'), 5)

    def test_day_suffix_removed(self):
        self.assertEqual(parse_int_like('30일'), 30)

    def test_leading_whitespace_tolerated(self):
        self.assertEqual(parse_int_like(' 42 '), 42)

    def test_plus_sign_allowed(self):
        self.assertEqual(parse_int_like('+42'), 42)

    def test_minus_sign_allowed(self):
        self.assertEqual(parse_int_like('-42'), -42)

    def test_float_string_rejected(self):
        with self.assertRaises(ValueError):
            parse_int_like('3.14')

    def test_bool_rejected_as_type_error(self):
        with self.assertRaises(TypeError):
            parse_int_like(True)

    def test_non_numeric_string_rejected(self):
        with self.assertRaises(ValueError):
            parse_int_like('abc')

    def test_empty_string_rejected(self):
        with self.assertRaises(ValueError):
            parse_int_like('   ')

    def test_unsupported_type_rejected(self):
        with self.assertRaises(TypeError):
            parse_int_like(3.14)


class ParseMoneyTests(SimpleTestCase):
    def test_alias_behavior(self):
        self.assertEqual(parse_money('1,234,567원'), 1234567)


class SumAmountsTests(SimpleTestCase):
    def test_mixed_inputs(self):
        self.assertEqual(sum_amounts(['1,000원', 2000, '3,000']), 6000)

    def test_empty_is_zero(self):
        self.assertEqual(sum_amounts([]), 0)

    def test_propagates_parse_error(self):
        with self.assertRaises(ValueError):
            sum_amounts(['1,000', 'bad'])


class AverageAmountTests(SimpleTestCase):
    def test_basic_average(self):
        self.assertEqual(average_amount([100, 200, 300]), 200.0)

    def test_returns_float(self):
        result = average_amount([1, 2])
        self.assertIsInstance(result, float)
        self.assertEqual(result, 1.5)

    def test_parses_strings(self):
        self.assertEqual(average_amount(['1,000', '3,000']), 2000.0)

    def test_empty_raises(self):
        with self.assertRaises(ValueError):
            average_amount([])
