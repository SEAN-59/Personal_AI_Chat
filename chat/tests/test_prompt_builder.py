"""prompt_builder.build_messages — search_query 분기 가드 (v0.5.0 Phase 9-2 / S1 fix).

후속 질문 'A → 비싼거' 류는 `query_rewriter` 가 'A 중 가장 비싼 항목' 으로 풀어주지만,
이전엔 그 결과가 retrieval 에만 쓰이고 답변 LLM 입력에는 raw '비싼거' 만 들어가서
no-info 응답이 났다. 본 테스트는 builder 가 둘을 함께 노출하는지(다르면) /
기존 출력을 유지하는지(같거나 빈 경우) 박제한다.
"""

from django.test import SimpleTestCase

from chat.services.prompt_builder import build_messages


class BuildMessagesSearchQueryTests(SimpleTestCase):
    """`search_query` 가 raw question 과 다를 때만 추가 라인이 붙는다."""

    def _last_user_content(self, messages):
        # 마지막이 이번 turn 의 user 메시지.
        self.assertEqual(messages[-1]['role'], 'user')
        return messages[-1]['content']

    def test_search_query_different_from_raw_appends_rewrite_line(self):
        messages = build_messages(
            '비싼거',
            chunk_hits=[],
            qa_hits=[],
            history=[],
            search_query='경조사 중 가장 비싼 항목',
        )
        body = self._last_user_content(messages)
        self.assertIn('=== 사용자 질문 ===', body)
        self.assertIn('원문: 비싼거', body)
        self.assertIn('대화 맥락 반영 질문: 경조사 중 가장 비싼 항목', body)

    def test_search_query_equal_to_raw_keeps_legacy_output(self):
        messages = build_messages(
            '퇴직금 계산식 알려줘',
            chunk_hits=[],
            qa_hits=[],
            history=[],
            search_query='퇴직금 계산식 알려줘',
        )
        body = self._last_user_content(messages)
        self.assertIn('=== 사용자 질문 ===', body)
        self.assertNotIn('대화 맥락 반영 질문', body)
        self.assertNotIn('원문:', body)

    def test_search_query_none_keeps_legacy_output(self):
        messages = build_messages(
            '경조사 규정 알려줘',
            chunk_hits=[],
            qa_hits=[],
            history=[],
        )
        body = self._last_user_content(messages)
        self.assertNotIn('대화 맥락 반영 질문', body)
        self.assertNotIn('원문:', body)
        # 질문은 한 줄로 그대로 들어간다.
        self.assertIn('경조사 규정 알려줘', body)

    def test_search_query_whitespace_only_treated_as_none(self):
        messages = build_messages(
            '경조사 규정 알려줘',
            chunk_hits=[],
            qa_hits=[],
            history=[],
            search_query='   ',
        )
        body = self._last_user_content(messages)
        self.assertNotIn('대화 맥락 반영 질문', body)

    def test_search_query_strips_before_compare(self):
        # raw 와 search_query 가 양옆 공백만 다를 때도 '같음' 으로 본다.
        messages = build_messages(
            '퇴직금 계산식',
            chunk_hits=[],
            qa_hits=[],
            history=[],
            search_query='  퇴직금 계산식  ',
        )
        body = self._last_user_content(messages)
        self.assertNotIn('대화 맥락 반영 질문', body)
