"""Phase 8-3 — `AgentSettings` 모델의 hard singleton + DB / form validators 회귀."""

from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.test import TestCase

from chat.models import AgentSettings


class GetSoloIdempotentTests(TestCase):
    """`AgentSettingsManager.get_solo()` 가 항상 같은 row 를 반환."""

    def test_first_call_creates_row_subsequent_calls_return_same(self):
        # 마이그레이션의 RunPython 으로 이미 pk=1 row 가 있음 (TestCase 가 fixture
        # 처럼 사용). get_solo() 는 그 row 를 반환.
        first = AgentSettings.objects.get_solo()
        second = AgentSettings.objects.get_solo()
        self.assertEqual(first.pk, 1)
        self.assertEqual(first.pk, second.pk)
        self.assertEqual(AgentSettings.objects.count(), 1)


class SaveOverrideEnforcesPkOneTests(TestCase):
    """`save()` override 가 어떤 pk 로 시도해도 결국 pk=1 으로 정렬 또는 IntegrityError."""

    def test_save_with_explicit_pk_falls_back_to_one(self):
        # obj = AgentSettings(pk=99); obj.save() 는 default force_insert=False —
        # save override 의 self.pk = 1 적용 후 pk=1 으로 UPDATE/INSERT 자동 분기.
        # 이미 pk=1 row 가 있으므로 UPDATE 동작.
        obj = AgentSettings(pk=99, max_iterations=8)
        obj.save()
        self.assertEqual(obj.pk, 1)
        # 결과: pk=1 row 의 max_iterations 만 업데이트, extra row 없음.
        row = AgentSettings.objects.get(pk=1)
        self.assertEqual(row.max_iterations, 8)
        self.assertEqual(AgentSettings.objects.count(), 1)

    def test_objects_create_pk_two_raises_integrity_error_when_row_exists(self):
        # objects.create(pk=2, ...) 는 force_insert=True → save override 가
        # pk=1 강제 → INSERT INTO ... pk=1 시도 → 기존 pk=1 row 존재로 IntegrityError.
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                AgentSettings.objects.create(pk=2, max_iterations=10)
        # 기존 row 는 그대로.
        self.assertEqual(AgentSettings.objects.count(), 1)


class CheckConstraintTests(TestCase):
    """`Meta.constraints` 의 두 `CheckConstraint` 가 DB-level 범위 강제."""

    def test_max_iterations_out_of_range_raises_integrity_error(self):
        row = AgentSettings.objects.get_solo()
        # validators 우회 — 직접 update + queryset 으로 강제 INSERT 시도.
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                AgentSettings.objects.filter(pk=row.pk).update(max_iterations=99)

    def test_max_low_relevance_out_of_range_raises_integrity_error(self):
        row = AgentSettings.objects.get_solo()
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                AgentSettings.objects.filter(pk=row.pk).update(
                    max_low_relevance_retrieves=99,
                )


class FormValidatorsTests(TestCase):
    """`MinValueValidator` / `MaxValueValidator` — `full_clean()` 에서 ValidationError."""

    def test_full_clean_rejects_max_iterations_below_one(self):
        row = AgentSettings.objects.get_solo()
        row.max_iterations = 0
        with self.assertRaises(ValidationError):
            row.full_clean()

    def test_full_clean_rejects_max_low_relevance_above_ten(self):
        row = AgentSettings.objects.get_solo()
        row.max_low_relevance_retrieves = 11
        with self.assertRaises(ValidationError):
            row.full_clean()
