"""Phase 8-2 — `record_token_usage` 의 keyword-only purpose 회귀 테스트.

Phase 8-5: cost_usd 자동 저장 회귀 가드 추가.
"""

from decimal import Decimal
from types import SimpleNamespace

from django.test import TestCase

from chat.models import TokenUsage
from chat.services import token_purpose as tp
from chat.services.single_shot.postprocess import record_token_usage


def _usage(prompt=10, completion=5, total=15):
    return SimpleNamespace(
        prompt_tokens=prompt, completion_tokens=completion, total_tokens=total,
    )


class RecordTokenUsagePurposeTests(TestCase):
    """purpose 미지정 default / 명시 전달 / 알 수 없는 값 절감."""

    def test_default_purpose_is_unknown(self):
        # positional 시그니처 호환 — 기존 두 인자 호출은 'unknown' 으로 떨어짐.
        record_token_usage('gpt-4o-mini', _usage())
        row = TokenUsage.objects.latest('id')
        self.assertEqual(row.purpose, tp.PURPOSE_UNKNOWN)

    def test_explicit_known_purpose_persists_as_is(self):
        record_token_usage(
            'gpt-4o-mini', _usage(),
            purpose=tp.PURPOSE_AGENT_FINAL,
        )
        row = TokenUsage.objects.latest('id')
        self.assertEqual(row.purpose, tp.PURPOSE_AGENT_FINAL)

    def test_unknown_string_demoted_to_unknown(self):
        # 호출부 오타 시뮬레이션 — validate_purpose 방어망이 절감.
        record_token_usage(
            'gpt-4o-mini', _usage(),
            purpose='agent_step_typo',
        )
        row = TokenUsage.objects.latest('id')
        self.assertEqual(row.purpose, tp.PURPOSE_UNKNOWN)


class RecordTokenUsageCostTests(TestCase):
    """Phase 8-5 — record_token_usage 가 cost_usd 를 자동 계산해 저장."""

    def test_cost_computed_for_registered_model(self):
        # gpt-4o-mini 1000 input + 500 output → 0.00015 + 0.00030 = $0.00045.
        record_token_usage(
            'gpt-4o-mini',
            _usage(prompt=1000, completion=500, total=1500),
            purpose=tp.PURPOSE_SINGLE_SHOT_ANSWER,
        )
        row = TokenUsage.objects.latest('id')
        self.assertEqual(row.cost_usd, Decimal('0.000450'))

    def test_cost_zero_for_unregistered_model(self):
        # 미등록 모델 → fail-silent 0 (warning 로그는 있음).
        record_token_usage(
            'unknown-future-model',
            _usage(prompt=1000, completion=500, total=1500),
        )
        row = TokenUsage.objects.latest('id')
        self.assertEqual(row.cost_usd, Decimal('0'))
