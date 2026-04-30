"""v0.4.2 (이슈 #73) — agent calendar 도구 단위 테스트.

- 3 도구 (`weekday_of` / `is_business_day` / `next_business_day`) 의 입력/출력
- date 형식 변형 (`YYYY-MM-DD` / `YYYY/MM/DD` / `YYYY.MM.DD` / `YYYYMMDD`)
- 잘못된 입력 → `tools.call()` Observation 의 `failure_kind='callable_error'`
- 한국 공휴일 정확성 (현충일 / 어린이날 / 광복절 / 삼일절)
"""

from django.test import SimpleTestCase

from chat.services.agent import tools
# tools_builtin import 부작용으로 도구가 등록됨.
from chat.services.agent import tools_builtin  # noqa: F401


class WeekdayOfTests(SimpleTestCase):
    """`weekday_of` — 한국어 한 글자 요일 반환."""

    def test_sunday(self):
        obs = tools.call('weekday_of', {'date': '2026-06-21'})
        self.assertFalse(obs.is_failure)
        self.assertIn('일요일', obs.summary)

    def test_monday(self):
        obs = tools.call('weekday_of', {'date': '2026-06-22'})
        self.assertFalse(obs.is_failure)
        self.assertIn('월요일', obs.summary)

    def test_alt_format_dot(self):
        # `YYYY.MM.DD` 도 같은 결과.
        obs = tools.call('weekday_of', {'date': '2026.06.21'})
        self.assertFalse(obs.is_failure)
        self.assertIn('일요일', obs.summary)

    def test_alt_format_compact(self):
        obs = tools.call('weekday_of', {'date': '20260621'})
        self.assertFalse(obs.is_failure)
        self.assertIn('일요일', obs.summary)

    def test_invalid_date_format(self):
        obs = tools.call('weekday_of', {'date': 'invalid'})
        self.assertTrue(obs.is_failure)
        self.assertEqual(obs.failure_kind, 'callable_error')
        # ValueError 메시지가 summary 에 포함되는지.
        self.assertIn('형식', obs.summary)

    def test_empty_date(self):
        # 빈 문자열은 schema 의 require_fields 단계에서 missing 으로 처리됨 →
        # callable 호출 전 schema_invalid. callable_error 와 분리.
        obs = tools.call('weekday_of', {'date': ''})
        self.assertTrue(obs.is_failure)
        self.assertEqual(obs.failure_kind, 'schema_invalid')

    def test_missing_required_field(self):
        # schema 검증으로 `failure_kind='schema_invalid'` (callable 도달 X).
        obs = tools.call('weekday_of', {})
        self.assertTrue(obs.is_failure)
        self.assertEqual(obs.failure_kind, 'schema_invalid')


class IsBusinessDayTests(SimpleTestCase):
    """`is_business_day` — 주말·한국 공휴일 회피."""

    def test_business_day_monday(self):
        obs = tools.call('is_business_day', {'date': '2026-06-22'})
        self.assertFalse(obs.is_failure)
        self.assertIn('영업일', obs.summary)
        self.assertNotIn('휴일', obs.summary)

    def test_weekend_sunday(self):
        obs = tools.call('is_business_day', {'date': '2026-06-21'})
        self.assertFalse(obs.is_failure)
        self.assertIn('주말', obs.summary)

    def test_korean_holiday_memorial_day(self):
        # 현충일 (6월 6일) — `holidays.KR(language='ko')` 로 한국어명.
        obs = tools.call('is_business_day', {'date': '2026-06-06'})
        self.assertFalse(obs.is_failure)
        self.assertIn('현충일', obs.summary)

    def test_korean_holiday_independence_day(self):
        # 삼일절.
        obs = tools.call('is_business_day', {'date': '2026-03-01'})
        self.assertFalse(obs.is_failure)
        self.assertIn('삼일절', obs.summary)

    def test_korean_holiday_liberation_day(self):
        # 광복절.
        obs = tools.call('is_business_day', {'date': '2026-08-15'})
        self.assertFalse(obs.is_failure)
        self.assertIn('광복절', obs.summary)

    def test_korean_holiday_childrens_day(self):
        # 어린이날.
        obs = tools.call('is_business_day', {'date': '2026-05-05'})
        self.assertFalse(obs.is_failure)
        self.assertIn('어린이날', obs.summary)


class NextBusinessDayTests(SimpleTestCase):
    """`next_business_day` — 영업일 그대로 / 주말·공휴일이면 다음 영업일."""

    def test_already_business_day(self):
        obs = tools.call('next_business_day', {'date': '2026-06-22'})
        self.assertFalse(obs.is_failure)
        # 같은 날.
        self.assertIn('영업일 그대로', obs.summary)

    def test_sunday_skips_to_monday(self):
        # 2026-06-21 (일) → 2026-06-22 (월).
        obs = tools.call('next_business_day', {'date': '2026-06-21'})
        self.assertFalse(obs.is_failure)
        self.assertIn('2026-06-22', obs.summary)
        self.assertIn('월요일', obs.summary)

    def test_saturday_skips_to_monday(self):
        # 2026-06-20 (토) → 2026-06-22 (월) — 일요일 건너뜀.
        obs = tools.call('next_business_day', {'date': '2026-06-20'})
        self.assertFalse(obs.is_failure)
        self.assertIn('2026-06-22', obs.summary)

    def test_holiday_memorial_day_saturday_skips_to_monday(self):
        # 2026-06-06 (토 + 현충일) → 2026-06-08 (월) — 주말+공휴일 후 월요일.
        obs = tools.call('next_business_day', {'date': '2026-06-06'})
        self.assertFalse(obs.is_failure)
        self.assertIn('2026-06-08', obs.summary)

    def test_invalid_date(self):
        obs = tools.call('next_business_day', {'date': 'not-a-date'})
        self.assertTrue(obs.is_failure)
        self.assertEqual(obs.failure_kind, 'callable_error')


class CalendarToolsRegisteredTests(SimpleTestCase):
    """tools 레지스트리에 3 도구가 등록되어 있는지."""

    def test_registered(self):
        names = {t.name for t in tools.all_entries()}
        self.assertIn('weekday_of', names)
        self.assertIn('is_business_day', names)
        self.assertIn('next_business_day', names)
