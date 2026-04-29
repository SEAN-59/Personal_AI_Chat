"""Phase 8-5 — `chat.services.openai_pricing` 단위 테스트."""

from decimal import Decimal

from django.test import SimpleTestCase

from chat.services.openai_pricing import MODEL_PRICING, compute_cost_usd


class ComputeCostHappyPathTests(SimpleTestCase):
    """등록된 모델의 cost 계산 정합."""

    def test_gpt_4o_mini_input_only(self):
        # 1000 input × $0.00015 / 1K = $0.00015.
        cost = compute_cost_usd('gpt-4o-mini', 1000, 0)
        self.assertEqual(cost, Decimal('0.00015'))

    def test_gpt_4o_mini_input_and_output(self):
        # 1000 input × $0.00015 + 500 output × $0.00060 / 1K
        # = 0.00015 + 0.00030 = $0.00045.
        cost = compute_cost_usd('gpt-4o-mini', 1000, 500)
        self.assertEqual(cost, Decimal('0.00045'))

    def test_gpt_4o_pricing(self):
        # 1000 input × $0.0025 + 1000 output × $0.0100 / 1K
        # = 0.0025 + 0.0100 = $0.0125.
        cost = compute_cost_usd('gpt-4o', 1000, 1000)
        self.assertEqual(cost, Decimal('0.0125'))


class ComputeCostUnregisteredModelTests(SimpleTestCase):
    """미등록 모델 — fail-silent 0 + warning."""

    def test_unregistered_model_returns_zero(self):
        cost = compute_cost_usd('unregistered-model-x', 1000, 500)
        self.assertEqual(cost, Decimal('0'))

    def test_empty_model_returns_zero(self):
        cost = compute_cost_usd('', 1000, 500)
        self.assertEqual(cost, Decimal('0'))


class ComputeCostEdgeCaseTests(SimpleTestCase):
    """0 토큰 / Decimal 정밀도."""

    def test_zero_tokens_returns_zero(self):
        self.assertEqual(compute_cost_usd('gpt-4o-mini', 0, 0), Decimal('0'))

    def test_decimal_precision_no_float_drift(self):
        # 7 호출 누적 (각 100 input, 50 output) — float 였다면 drift 발생 가능.
        # 1회 cost = 100 × 0.00015 + 50 × 0.00060 = 0.000015 + 0.000030 = 0.000045
        # 7회 합 = 0.000315 (정확).
        total = Decimal('0')
        for _ in range(7):
            total += compute_cost_usd('gpt-4o-mini', 100, 50)
        self.assertEqual(total, Decimal('0.000315'))


class ModelPricingMembershipTests(SimpleTestCase):
    """`MODEL_PRICING` 가 record_token_usage 의 default 모델을 포함."""

    def test_default_chat_model_registered(self):
        # chat/services/single_shot/llm.py 의 OPENAI_MODEL default.
        self.assertIn('gpt-4o-mini', MODEL_PRICING)

    def test_embedding_model_intentionally_omitted(self):
        # Phase 8-5 의 의도적 제외 — embedder.py 가 record_token_usage 안 부름.
        # Phase 8-7 후보로 통합 예정.
        self.assertNotIn('text-embedding-3-small', MODEL_PRICING)
