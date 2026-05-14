"""InputNormalizationRule 모델 검증 + canonicalize 강제 적용 회귀 테스트."""

from django.core.exceptions import ValidationError
from django.test import TestCase

from chat.models import InputNormalizationRule


class InputNormalizationRuleModelTests(TestCase):
    def test_create_canonicalizes_pattern(self):
        # 전각 + 공백 + 대소문자 — canonicalize() 가 NFKC + strip + casefold 적용.
        rule = InputNormalizationRule.objects.create(
            pattern='RUDWHTK　',  # trailing full-width space
            replacement='경조사',
            match_type=InputNormalizationRule.MatchType.EXACT,
        )
        self.assertEqual(rule.pattern, 'rudwhtk')

    def test_instance_save_canonicalizes_pattern(self):
        rule = InputNormalizationRule(
            pattern=' ＡＢＣ ',
            replacement='alpha',
            match_type=InputNormalizationRule.MatchType.EXACT,
        )
        rule.save()
        self.assertEqual(rule.pattern, 'abc')

    def test_unique_constraint_uses_canonical_pattern(self):
        """기존 rudwhtk 와 RUDWHTK　 는 canonical 비교에서 충돌 — full_clean ValidationError."""
        InputNormalizationRule.objects.create(
            pattern='rudwhtk',
            replacement='경조사',
            match_type=InputNormalizationRule.MatchType.EXACT,
        )
        with self.assertRaises(ValidationError):
            InputNormalizationRule.objects.create(
                pattern='RUDWHTK　',
                replacement='경조사',
                match_type=InputNormalizationRule.MatchType.EXACT,
            )

    def test_same_pattern_different_match_type_allowed(self):
        InputNormalizationRule.objects.create(
            pattern='지급일',
            replacement='급여 지급일',
            match_type=InputNormalizationRule.MatchType.EXACT,
        )
        # contains 는 별개로 허용
        InputNormalizationRule.objects.create(
            pattern='지급일',
            replacement='급여 지급일',
            match_type=InputNormalizationRule.MatchType.CONTAINS,
        )

    def test_empty_replacement_rejected(self):
        with self.assertRaises(ValidationError):
            InputNormalizationRule.objects.create(
                pattern='abc',
                replacement='   ',
                match_type=InputNormalizationRule.MatchType.EXACT,
            )

    def test_pattern_equals_replacement_rejected(self):
        with self.assertRaises(ValidationError):
            InputNormalizationRule.objects.create(
                pattern='abc',
                replacement='abc',
                match_type=InputNormalizationRule.MatchType.EXACT,
            )

    def test_contains_min_length_rejected(self):
        with self.assertRaises(ValidationError):
            InputNormalizationRule.objects.create(
                pattern='a',
                replacement='alpha',
                match_type=InputNormalizationRule.MatchType.CONTAINS,
            )

    def test_priority_ordering(self):
        InputNormalizationRule.objects.create(
            pattern='aaa', replacement='alpha', priority=10,
        )
        InputNormalizationRule.objects.create(
            pattern='bbb', replacement='beta', priority=200,
        )
        InputNormalizationRule.objects.create(
            pattern='ccc', replacement='gamma', priority=100,
        )
        ordered = list(InputNormalizationRule.objects.all().values_list('pattern', flat=True))
        self.assertEqual(ordered, ['bbb', 'ccc', 'aaa'])
