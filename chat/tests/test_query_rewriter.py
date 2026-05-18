"""query_rewriter 단위 테스트 (Phase 4-3).

회귀 0 을 보장하는 세 가지 fallback 경로와 일반 재작성 경로를 검증한다.
LLM 실제 호출은 하지 않고 `run_chat_completion` 만 mock 한다.
"""

from unittest.mock import patch

from django.test import TestCase

from chat.services import query_rewriter


def _stub_completion(text: str):
    """`run_chat_completion` 의 세 튜플 반환(reply, usage, model) 을 흉내."""
    class _Usage:
        prompt_tokens = 10
        completion_tokens = 4
        total_tokens = 14
    return text, _Usage(), 'gpt-4o-mini'


class QueryRewriterTests(TestCase):
    def test_empty_history_returns_original_without_llm_call(self):
        with patch('chat.services.query_rewriter.run_chat_completion') as mocked:
            result, usage, model = query_rewriter.rewrite_query_with_history(
                '비싼거',
                history=[],
            )
        self.assertEqual(result, '비싼거')
        self.assertIsNone(usage)
        self.assertIsNone(model)
        mocked.assert_not_called()

    def test_noop_sentinel_keeps_original_question(self):
        history = [
            {'role': 'user', 'content': '퇴직금 계산식 알려줘'},
            {'role': 'assistant', 'content': '퇴직금 = 평균임금 × 30일 × 근속연수/365 ...'},
        ]
        with patch(
            'chat.services.query_rewriter.run_chat_completion',
            return_value=_stub_completion(query_rewriter.NOOP_SENTINEL),
        ):
            result, usage, model = query_rewriter.rewrite_query_with_history(
                '퇴직금 계산식 알려줘',
                history=history,
            )
        # NOOP 이라도 LLM 이 돌긴 했으므로 usage 는 기록 대상이다.
        self.assertEqual(result, '퇴직금 계산식 알려줘')
        self.assertIsNotNone(usage)
        self.assertEqual(model, 'gpt-4o-mini')

    def test_llm_failure_falls_back_to_original(self):
        history = [{'role': 'user', 'content': '이전 질문'}]
        from chat.services.single_shot.types import QueryPipelineError
        with patch(
            'chat.services.query_rewriter.run_chat_completion',
            side_effect=QueryPipelineError('network down'),
        ):
            result, usage, model = query_rewriter.rewrite_query_with_history(
                '비싼거',
                history=history,
            )
        self.assertEqual(result, '비싼거')
        self.assertIsNone(usage)
        self.assertIsNone(model)

    def test_follow_up_uses_rewritten_query(self):
        # 비교 follow-up 이지만 history 에 금전 단서가 없도록 다른 도메인으로 구성.
        # (monetary metric guard 는 별도 테스트에서 검증.)
        history = [
            {'role': 'user', 'content': '연차 규정 알려줘'},
            {'role': 'assistant', 'content': '입사 1년 11일, 2년 15일, 3년 16일 ...'},
        ]
        with patch(
            'chat.services.query_rewriter.run_chat_completion',
            return_value=_stub_completion('연차 일수가 가장 많은 연차'),
        ):
            result, usage, model = query_rewriter.rewrite_query_with_history(
                '제일 많은거',
                history=history,
            )
        self.assertEqual(result, '연차 일수가 가장 많은 연차')
        self.assertEqual(model, 'gpt-4o-mini')
        self.assertIsNotNone(usage)

    def test_llm_output_cleanup_strips_quotes_and_prefix(self):
        history = [{'role': 'user', 'content': '이전 질문'}]
        # 모델이 가끔 뱉는 흔한 프롬프트 탈선 패턴 — 접두어 + 외곽 따옴표.
        with patch(
            'chat.services.query_rewriter.run_chat_completion',
            return_value=_stub_completion('검색어: "연차 일수"'),
        ):
            result, _, _ = query_rewriter.rewrite_query_with_history(
                '몇 일?',
                history=history,
            )
        self.assertEqual(result, '연차 일수')


class QueryRewriterPremiseTests(TestCase):
    """v0.5.0 Phase 9-2 / #76 — 가설·전제 보존 가드.

    (a) Prompt content guard: `assets/prompts/chat/query_rewriter.md` 가 premise
        보존 규칙 + example 을 갖고 있는지 확인. silent regression 차단.
    (b) Rewrite function guard: `_call_rewriter_llm` 을 mock 한 상태에서
        `rewrite_query_with_history` 가 cleanup pipeline 으로 LLM 출력을 깎아먹지
        않고 그대로 돌려주는지 확인. 실제 LLM 호출 금지.
    """

    def test_query_rewriter_prompt_contains_premise_rule(self):
        from chat.services.prompt_loader import load_prompt

        prompt_text = load_prompt('chat/query_rewriter.md')
        # 규칙 라인 — 영문 키워드 + 한국어 트리거.
        self.assertIn('Preserve premises', prompt_text)
        self.assertIn('만약', prompt_text)
        # Example 의 rewrite 라인.
        self.assertIn('Rewrite: 5년 근무 시 퇴직금 계산', prompt_text)

    def test_rewrite_query_with_history_returns_cleaned_llm_output(self):
        history = [
            {'role': 'user', 'content': '퇴직금 계산식 알려줘'},
            {'role': 'assistant', 'content': '퇴직금 = 평균임금 × 30일 × 근속연수/365 ...'},
        ]
        # plan §4 계약: `_call_rewriter_llm` 을 call-site 에서 mock — 실제 LLM 호출 금지.
        usage_stub = _stub_completion('5년 근무 시 퇴직금 계산')[1]
        with patch(
            'chat.services.query_rewriter._call_rewriter_llm',
            return_value=('5년 근무 시 퇴직금 계산', usage_stub, 'gpt-mini'),
        ) as mocked:
            result, usage, model = query_rewriter.rewrite_query_with_history(
                '만약 5년 근무하면?',
                history=history,
            )
        mocked.assert_called_once()
        # cleanup pipeline 이 premise 토큰을 깎아먹지 않는다.
        self.assertEqual(result, '5년 근무 시 퇴직금 계산')
        self.assertIs(usage, usage_stub)
        self.assertEqual(model, 'gpt-mini')

    # ------------------------------------------------------------------
    # Phase 9-2 S1b — ordinal / ranking 보존 (#76 폴리시 추가분)
    # ------------------------------------------------------------------

    def test_query_rewriter_prompt_contains_ordinal_rule(self):
        from chat.services.prompt_loader import load_prompt

        prompt_text = load_prompt('chat/query_rewriter.md')
        # 규칙 라인 — ordinal/ranking 키워드 + 부정 신호.
        self.assertIn('Preserve ordinal and ranking signals', prompt_text)
        self.assertIn('2번째', prompt_text)
        self.assertIn('가장', prompt_text)
        # rewriter 가 후보 행을 미리 확정하지 말라는 부정 지시.
        self.assertIn('부모 상', prompt_text)
        # Example (v0.5.4 monetary metric — "비싼" 은 금액 축으로 고정).
        self.assertIn('Current question: 2번째로 비싼거', prompt_text)
        self.assertIn('Rewrite: 경조사 지급금액 중 두 번째로 큰 항목', prompt_text)

    def test_query_rewriter_prompt_contains_monetary_metric_rule(self):
        """v0.5.4 — monetary comparative follow-up 은 금액 축을 보존해야 한다.

        '비싼/싼/큰/작은/높은/낮은' 같은 비교 후속 질의가 휴가 일수 등 비-금액
        chunk 로 라우팅되는 회귀(=취업규칙 출산 휴가 20일이 '비싼거' 로 잡힘)를
        막기 위해 prompt rule + example 둘 다 박혀 있어야 한다.
        """
        from chat.services.prompt_loader import load_prompt

        prompt_text = load_prompt('chat/query_rewriter.md')
        # 규칙 라인.
        self.assertIn('Preserve the comparison metric', prompt_text)
        self.assertIn('지급금액', prompt_text)
        self.assertIn('경조금', prompt_text)
        # 휴가 축으로 흘리지 말라는 부정 신호.
        self.assertIn('일수', prompt_text)
        self.assertIn('휴가', prompt_text)
        # `비싼거` 예제가 금액 metric 으로 재작성된다.
        self.assertIn('Current question: 비싼거', prompt_text)
        self.assertIn('Rewrite: 경조사 지급금액 중 가장 큰 항목', prompt_text)

    def test_query_rewriter_prompt_contains_exclusion_rule(self):
        """v0.5.1 plan §3 — exclusion/negation follow-up 보존 가드."""
        from chat.services.prompt_loader import load_prompt

        prompt_text = load_prompt('chat/query_rewriter.md')
        self.assertIn('exclusion', prompt_text.lower())
        self.assertIn('이거 말고', prompt_text)
        self.assertIn('더 있을건데', prompt_text)
        # Example.
        self.assertIn('Current question: 이거 말고 더 있을건데', prompt_text)

    def test_exclusion_followup_preserves_topic_in_cleanup(self):
        """v0.5.1 plan §3 — `이거 말고 더 있을건데` 가 직전 주제(경조사) 를 유지."""
        history = [
            {'role': 'user', 'content': '경조사 규정 알려줘'},
            {'role': 'assistant', 'content': '본인 상 500만원, 배우자 상 100만원, 부모 상 50만원 ...'},
        ]
        usage_stub = _stub_completion('경조사 규정에서 추가로 다루는 다른 항목')[1]
        with patch(
            'chat.services.query_rewriter._call_rewriter_llm',
            return_value=(
                '경조사 규정에서 추가로 다루는 다른 항목', usage_stub, 'gpt-mini',
            ),
        ) as mocked:
            result, usage, model = query_rewriter.rewrite_query_with_history(
                '이거 말고 더 있을건데',
                history=history,
            )
        mocked.assert_called_once()
        self.assertEqual(result, '경조사 규정에서 추가로 다루는 다른 항목')
        self.assertIs(usage, usage_stub)
        self.assertEqual(model, 'gpt-mini')

    def test_overlength_rewrite_falls_back_to_original(self):
        """v0.5.1 plan §5 — `_MAX_REWRITE_LEN` 초과 시 원본 유지, usage 는 보존."""
        history = [{'role': 'user', 'content': '이전 질문'}]
        overlong = '경조사' * 200  # > 200 chars
        usage_stub = _stub_completion(overlong)[1]
        with patch(
            'chat.services.query_rewriter._call_rewriter_llm',
            return_value=(overlong, usage_stub, 'gpt-mini'),
        ):
            result, usage, model = query_rewriter.rewrite_query_with_history(
                '비싼거',
                history=history,
            )
        # 비정상 길이 → 원본 fallback. usage/model 은 호출이 일어났으므로 유지.
        self.assertEqual(result, '비싼거')
        self.assertIs(usage, usage_stub)
        self.assertEqual(model, 'gpt-mini')

    def test_generic_exception_falls_back_to_original_without_usage(self):
        """v0.5.1 plan §5 — `_call_rewriter_llm` 의 비정형 예외도 흡수."""
        history = [{'role': 'user', 'content': '이전 질문'}]
        with patch(
            'chat.services.query_rewriter._call_rewriter_llm',
            side_effect=RuntimeError('boom'),
        ):
            result, usage, model = query_rewriter.rewrite_query_with_history(
                '비싼거',
                history=history,
            )
        self.assertEqual(result, '비싼거')
        self.assertIsNone(usage)
        self.assertIsNone(model)

    # ------------------------------------------------------------------
    # v0.5.4 — deterministic monetary metric guard
    # ------------------------------------------------------------------

    def _money_history(self):
        return [
            {'role': 'user', 'content': '경조사 규정 알려줘'},
            {'role': 'assistant',
             'content': '경조사 지원금액 표 — 본인 결혼 100만원, 본인 상 500만원, 배우자 상 100만원 ...'},
        ]

    def test_monetary_guard_adds_metric_suffix_when_missing(self):
        history = self._money_history()
        usage_stub = _stub_completion('경조사 중 가장 비싼 항목')[1]
        with patch(
            'chat.services.query_rewriter._call_rewriter_llm',
            return_value=('경조사 중 가장 비싼 항목', usage_stub, 'gpt-mini'),
        ):
            result, _, _ = query_rewriter.rewrite_query_with_history(
                '비싼거?', history=history,
            )
        # 금액 축 토큰 보강.
        self.assertTrue('금액' in result or '지급금액' in result)
        # 원본 LLM 출력의 의미·ordinal·comparative 토큰 보존.
        self.assertIn('경조사', result)
        self.assertIn('가장', result)
        self.assertIn('비싼', result)

    def test_monetary_guard_preserves_ordinal(self):
        history = self._money_history()
        usage_stub = _stub_completion('경조사 중 두 번째로 비싼 항목')[1]
        with patch(
            'chat.services.query_rewriter._call_rewriter_llm',
            return_value=('경조사 중 두 번째로 비싼 항목', usage_stub, 'gpt-mini'),
        ):
            result, _, _ = query_rewriter.rewrite_query_with_history(
                '2번째로 비싼거?', history=history,
            )
        self.assertTrue('금액' in result or '지급금액' in result)
        self.assertIn('두 번째', result)
        self.assertIn('비싼', result)

    def test_monetary_guard_skipped_when_duration_axis_explicit(self):
        history = self._money_history()
        usage_stub = _stub_completion('경조사 휴가 일수 가장 긴 항목')[1]
        with patch(
            'chat.services.query_rewriter._call_rewriter_llm',
            return_value=('경조사 휴가 일수 가장 긴 항목', usage_stub, 'gpt-mini'),
        ):
            result, _, _ = query_rewriter.rewrite_query_with_history(
                '휴가가 제일 긴거?', history=history,
            )
        # 명시적 휴가/일수 축 → 금액 metric 부착 금지.
        self.assertNotIn('지급금액 기준', result)
        self.assertNotIn('금액', result)

    def test_monetary_guard_noop_when_rewrite_already_has_metric(self):
        history = self._money_history()
        usage_stub = _stub_completion('경조사 지급금액 중 가장 큰 항목')[1]
        with patch(
            'chat.services.query_rewriter._call_rewriter_llm',
            return_value=('경조사 지급금액 중 가장 큰 항목', usage_stub, 'gpt-mini'),
        ):
            result, _, _ = query_rewriter.rewrite_query_with_history(
                '비싼거?', history=history,
            )
        # 이미 metric 이 들어있으므로 그대로.
        self.assertEqual(result, '경조사 지급금액 중 가장 큰 항목')

    def test_monetary_guard_triggers_on_amount_pattern_only_history(self):
        # history 에 `금액` 같은 generic 단어 없이 금액 표기 패턴만 있어도 발동.
        history = [
            {'role': 'user', 'content': '경조사 규정 알려줘'},
            {'role': 'assistant', 'content': '본인 결혼 100만 원, 본인 상 500만원, 부모 상 20,000원 ...'},
        ]
        usage_stub = _stub_completion('경조사 중 가장 비싼 항목')[1]
        with patch(
            'chat.services.query_rewriter._call_rewriter_llm',
            return_value=('경조사 중 가장 비싼 항목', usage_stub, 'gpt-mini'),
        ):
            result, _, _ = query_rewriter.rewrite_query_with_history(
                '비싼거?', history=history,
            )
        self.assertIn('지급금액 기준', result)

    def test_monetary_guard_skipped_on_false_positive_words(self):
        # history 에 `직원/원칙/원본` 등만 있고 금액 패턴/금전 metric 단어가
        # 없으면 발동 금지 (single-char `원` substring 매칭 회귀 방지).
        history = [
            {'role': 'user', 'content': '회사 정책 알려줘'},
            {'role': 'assistant', 'content': '직원 행동 원칙 — 원본 자료는 사내 포털에 보관 ...'},
        ]
        usage_stub = _stub_completion('회사 정책 중 가장 비싼 항목')[1]
        with patch(
            'chat.services.query_rewriter._call_rewriter_llm',
            return_value=('회사 정책 중 가장 비싼 항목', usage_stub, 'gpt-mini'),
        ):
            result, _, _ = query_rewriter.rewrite_query_with_history(
                '비싼거?', history=history,
            )
        self.assertNotIn('지급금액 기준', result)
        self.assertNotIn('금액', result)

    def test_monetary_guard_skipped_without_history_monetary_cue(self):
        # history 에 금전 단서가 없으면 가격 비교 follow-up 이라도 guard 미발동.
        history = [
            {'role': 'user', 'content': '연차 규정 알려줘'},
            {'role': 'assistant', 'content': '입사 1년 차 연차 일수 11일, 2년 차 15일 ...'},
        ]
        usage_stub = _stub_completion('연차 일수가 가장 비싼 항목')[1]
        with patch(
            'chat.services.query_rewriter._call_rewriter_llm',
            return_value=('연차 일수가 가장 비싼 항목', usage_stub, 'gpt-mini'),
        ):
            result, _, _ = query_rewriter.rewrite_query_with_history(
                '비싼거?', history=history,
            )
        self.assertNotIn('지급금액 기준', result)

    # ------------------------------------------------------------------
    # v0.5.5 — neighbor expansion 회귀 봉인
    # ------------------------------------------------------------------

    def test_v055_monetary_guard_still_attaches_metric_suffix(self):
        """`비싼거` follow-up 에서 `지급금액 기준` 부착이 v0.5.5 후에도 유지."""
        history = self._money_history()
        usage_stub = _stub_completion('경조사 중 가장 비싼 항목')[1]
        with patch(
            'chat.services.query_rewriter._call_rewriter_llm',
            return_value=('경조사 중 가장 비싼 항목', usage_stub, 'gpt-mini'),
        ):
            result, _, _ = query_rewriter.rewrite_query_with_history(
                '비싼거', history=history,
            )
        self.assertIn('지급금액 기준', result)

    def test_v055_enumeration_question_skips_monetary_guard(self):
        """`모든 종류 알려줘` 는 비교/금액 query 가 아니므로 metric suffix 부착 X."""
        history = self._money_history()
        usage_stub = _stub_completion('경조사 모든 종류')[1]
        with patch(
            'chat.services.query_rewriter._call_rewriter_llm',
            return_value=('경조사 모든 종류', usage_stub, 'gpt-mini'),
        ):
            result, _, _ = query_rewriter.rewrite_query_with_history(
                '모든 종류 알려줘', history=history,
            )
        self.assertNotIn('지급금액 기준', result)

    def test_rewrite_query_with_history_preserves_ordinal_in_cleanup(self):
        history = [
            {'role': 'user', 'content': '경조사 규정 알려줘'},
            {'role': 'assistant', 'content': '본인 결혼 100만, 본인 상 500만, 배우자 상 100만, 부모 상 50만 ...'},
        ]
        usage_stub = _stub_completion('경조사 중 두 번째로 비싼 항목')[1]
        with patch(
            'chat.services.query_rewriter._call_rewriter_llm',
            return_value=(
                '경조사 중 두 번째로 비싼 항목', usage_stub, 'gpt-mini',
            ),
        ) as mocked:
            result, usage, model = query_rewriter.rewrite_query_with_history(
                '2번째로 비싼거',
                history=history,
            )
        mocked.assert_called_once()
        # cleanup pipeline 이 ordinal/ranking 토큰을 깎아먹지 않는다.
        # v0.5.4 — history 에 금액 패턴(`500만`) 이 있으므로 monetary guard 가
        # `지급금액 기준` suffix 를 덧붙일 수 있다. 핵심은 ordinal/comparative
        # 토큰이 살아있는 것.
        self.assertIn('두 번째', result)
        self.assertIn('비싼', result)
        self.assertIn('경조사', result)
        self.assertIs(usage, usage_stub)
        self.assertEqual(model, 'gpt-mini')
