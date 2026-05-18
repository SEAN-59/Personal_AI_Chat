"""run_single_shot — query_rewriter ↔ retrieve_documents 결선 회귀 테스트.

Plan §7 case 8/9 — history follow-up 시 rewritten search_query 가 retrieval 까지
전달되어야 하고, history 가 빈 첫 turn 에서는 rewriter LLM 이 호출되지 않고
원문 그대로 retrieval 에 전달돼야 한다.

mock target 은 pipeline 의 실제 import binding 기준. OpenAI 실제 호출 0.
"""

from unittest.mock import patch

from django.test import TestCase

from chat.services.single_shot import pipeline as ss_pipeline


class _Usage:
    prompt_tokens = 1
    completion_tokens = 1
    total_tokens = 2


def _llm_response(text='답변'):
    return text, _Usage(), 'gpt-4o-mini'


def _rewriter_response(text):
    """`rewrite_query_with_history` 의 (search_query, usage, model) 반환."""
    return text, _Usage(), 'gpt-4o-mini'


class RewriterToRetrievalWiringTests(TestCase):
    def test_followup_uses_rewritten_query_in_retrieval(self):
        history = [
            {'role': 'user', 'content': '경조사 규정 알려줘'},
            {'role': 'assistant', 'content': '본인 상 500만, 배우자 상 100만 ...'},
        ]
        rewritten = '경조사 중 가장 비싼 항목'

        with patch(
            'chat.services.single_shot.pipeline.rewrite_query_with_history',
            return_value=_rewriter_response(rewritten),
        ) as rewriter_mock, patch(
            'chat.services.single_shot.pipeline.retrieve_documents',
            return_value=[],
        ) as retrieve_mock, patch(
            'chat.services.single_shot.pipeline.find_canonical_qa',
            return_value=[],
        ) as find_qa_mock, patch(
            'chat.services.single_shot.pipeline.run_chat_completion',
            return_value=_llm_response('답변'),
        ), patch(
            'chat.services.single_shot.postprocess.record_token_usage',
        ):
            ss_pipeline.run_single_shot('비싼거', history=history)

        rewriter_mock.assert_called_once_with('비싼거', history)
        # retrieve / find_qa 모두 rewritten search_query 로 호출.
        retrieve_mock.assert_called_once_with(rewritten)
        find_qa_mock.assert_called_once_with(rewritten)

    def test_monetary_followup_rewrite_reaches_retrieval(self):
        # v0.5.4 manual QA blocker — `비싼거` 가 휴가 일수 chunk 로 흐르는 회귀를
        # 막기 위해, rewriter 가 `지급금액` 토큰을 포함한 self-contained 검색어를
        # 만들면 그 문자열이 그대로 retrieve_documents 에 전달돼야 한다.
        history = [
            {'role': 'user', 'content': '경조사 규정 알려줘'},
            {'role': 'assistant', 'content': '경조사 지급금액 표 — 본인 결혼 100만, 본인 상 500만 ...'},
        ]
        rewritten = '경조사 지급금액 중 가장 큰 항목'

        with patch(
            'chat.services.single_shot.pipeline.rewrite_query_with_history',
            return_value=_rewriter_response(rewritten),
        ), patch(
            'chat.services.single_shot.pipeline.retrieve_documents',
            return_value=[],
        ) as retrieve_mock, patch(
            'chat.services.single_shot.pipeline.find_canonical_qa',
            return_value=[],
        ), patch(
            'chat.services.single_shot.pipeline.run_chat_completion',
            return_value=_llm_response('답변'),
        ), patch(
            'chat.services.single_shot.postprocess.record_token_usage',
        ):
            ss_pipeline.run_single_shot('비싼거', history=history)

        retrieve_mock.assert_called_once_with(rewritten)
        # 핵심: retrieval 까지 metric 토큰이 살아 있어야 한다.
        (called_arg,), _ = retrieve_mock.call_args
        self.assertIn('지급금액', called_arg)

    def test_empty_history_does_not_invoke_rewriter_llm(self):
        # history 비었을 때 rewrite_query_with_history 는 원본을 그대로 반환하는
        # 기존 fallback 을 가진다. 그 fallback 경로에서는 rewriter 가 내부적으로
        # LLM 을 부르지 않아야 한다 (회귀 0). retrieve_documents 에는 원문이 전달.
        with patch(
            'chat.services.query_rewriter.run_chat_completion',
        ) as rewriter_llm_mock, patch(
            'chat.services.single_shot.pipeline.retrieve_documents',
            return_value=[],
        ) as retrieve_mock, patch(
            'chat.services.single_shot.pipeline.find_canonical_qa',
            return_value=[],
        ) as find_qa_mock, patch(
            'chat.services.single_shot.pipeline.run_chat_completion',
            return_value=_llm_response('답변'),
        ), patch(
            'chat.services.single_shot.postprocess.record_token_usage',
        ):
            ss_pipeline.run_single_shot('비싼거', history=[])

        rewriter_llm_mock.assert_not_called()
        retrieve_mock.assert_called_once_with('비싼거')
        find_qa_mock.assert_called_once_with('비싼거')
