"""v0.5.1 plan §3 / §5 — follow-up rewrite + prompt 통합 e2e.

`run_single_shot` direct 호출로 LLM tier 4건 follow-up 의 rewrite → prompt
주입 흐름을 박제한다. route 분기와 `_llm_classify` 호출 횟수는 본 파일이
다루지 않는다 (담당: `test_llm_router.py` / `test_routing_e2e.py`).

모든 외부 호출(`run_chat_completion`, `retrieve_documents`, `find_canonical_qa`,
`resolve_cache_hit`, `record_token_usage`, `_call_rewriter_llm`) 은 mock —
`OPENAI_API_KEY=` 빈 환경에서도 통과한다.
"""

from types import SimpleNamespace
from unittest.mock import patch

from django.test import TestCase

from chat.services.single_shot.pipeline import run_single_shot


def _fake_usage(total=10):
    return SimpleNamespace(prompt_tokens=6, completion_tokens=4, total_tokens=total)


class FollowupRewriteToPromptTests(TestCase):
    """4개 LLM tier follow-up 각각에서 rewriter 출력이 prompt 의 search_query 로 전달."""

    CASES = (
        (
            '비싼거',
            '경조사 중 가장 비싼 항목',
            [
                {'role': 'user', 'content': '경조사 규정 알려줘'},
                {'role': 'assistant', 'content': '본인 상 500만원, 배우자 상 100만원 ...'},
            ],
        ),
        (
            '2번째로 비싼거',
            '경조사 중 두 번째로 비싼 항목',
            [
                {'role': 'user', 'content': '경조사 규정 알려줘'},
                {'role': 'assistant', 'content': '본인 상 500만원, 배우자 상 100만원 ...'},
            ],
        ),
        (
            '이거 말고 더 있을건데',
            '경조사 규정에서 추가로 다루는 다른 항목',
            [
                {'role': 'user', 'content': '경조사 규정 알려줘'},
                {'role': 'assistant', 'content': '본인 상 500만원, 배우자 상 100만원 ...'},
            ],
        ),
        (
            '만약 5년 근무하면?',
            '5년 근무 시 퇴직금 계산',
            [
                {'role': 'user', 'content': '퇴직금 계산식 알려줘'},
                {'role': 'assistant', 'content': '퇴직금 = 평균임금 × 30일 × 근속연수/365 ...'},
            ],
        ),
    )

    def _run_case(self, question, rewritten, history):
        captured = {}

        def fake_build(raw_q, chunk_hits, qa_hits, hist, search_query=None):
            captured['raw_question'] = raw_q
            captured['search_query'] = search_query
            captured['history'] = hist
            return [{'role': 'user', 'content': 'stub'}]

        rewriter_usage = _fake_usage()

        with patch(
            'chat.services.single_shot.pipeline.rewrite_query_with_history',
            return_value=(rewritten, rewriter_usage, 'gpt-mini'),
        ) as rewrite_mock, patch(
            'chat.services.single_shot.pipeline.retrieve_documents',
            return_value=[],
        ), patch(
            'chat.services.single_shot.pipeline.find_canonical_qa',
            return_value=[],
        ), patch(
            'chat.services.single_shot.pipeline.resolve_cache_hit',
            return_value=None,
        ), patch(
            'chat.services.single_shot.pipeline.build_single_shot_messages',
            side_effect=fake_build,
        ) as build_mock, patch(
            'chat.services.single_shot.pipeline.run_chat_completion',
            return_value=('답변 stub', _fake_usage(total=20), 'gpt-aux'),
        ), patch(
            'chat.services.single_shot.pipeline.record_token_usage',
        ) as record_mock:
            result = run_single_shot(question, history=history)

        return result, captured, rewrite_mock, build_mock, record_mock

    def test_each_followup_passes_rewritten_query_to_prompt_builder(self):
        for question, rewritten, history in self.CASES:
            with self.subTest(question=question):
                _, captured, rewrite_mock, build_mock, _ = self._run_case(
                    question, rewritten, history,
                )
                # raw question 은 원문 그대로 prompt builder 로.
                self.assertEqual(captured['raw_question'], question)
                # rewriter 결과가 search_query 로 분리 전달.
                self.assertEqual(captured['search_query'], rewritten)
                # history 도 함께 전달.
                self.assertIs(captured['history'], history)
                rewrite_mock.assert_called_once()
                build_mock.assert_called_once()

    def test_rewriter_usage_recorded_with_query_rewriter_purpose(self):
        question, rewritten, history = self.CASES[0]
        _, _, _, _, record_mock = self._run_case(question, rewritten, history)
        # 두 번 호출: 한 번은 rewriter usage (purpose=PURPOSE_QUERY_REWRITER),
        # 한 번은 single_shot answer usage (purpose=PURPOSE_SINGLE_SHOT_ANSWER).
        from chat.services.token_purpose import (
            PURPOSE_QUERY_REWRITER,
            PURPOSE_SINGLE_SHOT_ANSWER,
        )
        purposes = [c.kwargs.get('purpose') for c in record_mock.call_args_list]
        self.assertIn(PURPOSE_QUERY_REWRITER, purposes)
        self.assertIn(PURPOSE_SINGLE_SHOT_ANSWER, purposes)
        self.assertEqual(record_mock.call_count, 2)

    def test_returns_query_result_with_reply(self):
        question, rewritten, history = self.CASES[0]
        result, _, _, _, _ = self._run_case(question, rewritten, history)
        self.assertEqual(result.reply, '답변 stub')
        self.assertEqual(result.total_tokens, 20)
