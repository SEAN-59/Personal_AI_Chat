"""input_normalizer 서비스 회귀 테스트 — single best rule 정책."""

from django.test import TestCase

from chat.models import InputNormalizationRule
from chat.services.input_normalizer import normalize


class InputNormalizerServiceTests(TestCase):
    def _mk(self, pattern, replacement, *, match_type='exact', priority=100, enabled=True):
        return InputNormalizationRule.objects.create(
            pattern=pattern,
            replacement=replacement,
            match_type=match_type,
            priority=priority,
            enabled=enabled,
        )

    def test_empty_input_noop(self):
        result = normalize('')
        self.assertFalse(result.changed)
        self.assertEqual(result.normalized, '')
        self.assertEqual(result.applied, [])

    def test_whitespace_only_noop(self):
        self.assertFalse(normalize('   ').changed)

    def test_no_rules_noop(self):
        result = normalize('rudwhtk')
        self.assertFalse(result.changed)
        self.assertEqual(result.normalized, 'rudwhtk')

    def test_disabled_rule_ignored(self):
        self._mk('rudwhtk', '경조사', enabled=False)
        result = normalize('rudwhtk')
        self.assertFalse(result.changed)

    def test_exact_match(self):
        rule = self._mk('rudwhtk', '경조사')
        result = normalize('rudwhtk')
        self.assertTrue(result.changed)
        self.assertEqual(result.normalized, '경조사')
        self.assertEqual(len(result.applied), 1)
        self.assertEqual(result.applied[0].id, rule.pk)
        self.assertEqual(result.raw, 'rudwhtk')

    def test_exact_match_canonicalize_input(self):
        # 입력 대소문자/전각/공백 차이 흡수
        self._mk('rudwhtk', '경조사')
        for raw in ['RUDWHTK', '  rudwhtk  ', 'ＲＵＤＷＨＴＫ']:
            result = normalize(raw)
            self.assertTrue(result.changed, f'expected changed for {raw!r}')
            self.assertEqual(result.normalized, '경조사')

    def test_contains_match_single_replace(self):
        self._mk('경조', '경조사', match_type='contains')
        result = normalize('경조 한도')
        self.assertTrue(result.changed)
        self.assertEqual(result.normalized, '경조사 한도')

    def test_exact_preempts_contains(self):
        # 둘 다 매칭되지만 exact 우선 + 종료. contains 추가 적용 없음 — applied 길이 1.
        self._mk('정산일', '급여 정산일', match_type='exact', priority=200)
        self._mk('정산', '정산일', match_type='contains', priority=100)
        result = normalize('정산일')
        self.assertTrue(result.changed)
        self.assertEqual(result.normalized, '급여 정산일')
        self.assertEqual(len(result.applied), 1)

    def test_contains_when_no_exact(self):
        self._mk('정산일', '급여 정산일', match_type='exact', priority=200)
        self._mk('정산', '정산일', match_type='contains', priority=100)
        result = normalize('정산만')
        self.assertTrue(result.changed)
        self.assertEqual(result.normalized, '정산일만')
        self.assertEqual(len(result.applied), 1)

    def test_priority_orders_within_same_type(self):
        # 같은 contains 두 개 매치 가능 — priority 큰 게 먼저, 첫 1건만.
        self._mk('가나', 'low', match_type='contains', priority=10)
        self._mk('가나다', 'high', match_type='contains', priority=200)
        result = normalize('가나다 입력')
        self.assertTrue(result.changed)
        self.assertEqual(result.normalized, 'high 입력')

    def test_raw_preserved(self):
        self._mk('rudwhtk', '경조사')
        result = normalize('  RUDWHTK  ')
        self.assertEqual(result.raw, '  RUDWHTK  ')
        self.assertEqual(result.normalized, '경조사')
