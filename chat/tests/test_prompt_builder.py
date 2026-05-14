"""prompt_builder.build_messages — search_query 분기 가드 (v0.5.0 Phase 9-2 / S1 fix).

후속 질문 'A → 비싼거' 류는 `query_rewriter` 가 'A 중 가장 비싼 항목' 으로 풀어주지만,
이전엔 그 결과가 retrieval 에만 쓰이고 답변 LLM 입력에는 raw '비싼거' 만 들어가서
no-info 응답이 났다. 본 테스트는 builder 가 둘을 함께 노출하는지(다르면) /
기존 출력을 유지하는지(같거나 빈 경우) 박제한다.
"""

from django.test import SimpleTestCase

from files.services.retriever import ChunkHit

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


class BuildMessagesHistorySanitizationTests(SimpleTestCase):
    """v0.5.3 QA 보강 S2.

    같은 세션에서 BO 재임베딩으로 회사 자료가 200만 → 2000만 으로 갱신되었는데,
    이전 assistant 답변에 '200만' 이 남아 있으면 최종 답변 LLM 이 옛 답변에
    끌려 새 자료를 무시하는 회귀가 있었다. build_messages 가 답변 생성용 history
    에서 assistant 메시지를 떨어뜨려 numeric 오염을 차단하는지 박제한다.
    """

    def _chunk(self, content: str, *, cid: int = 630, did: int = 1) -> ChunkHit:
        return ChunkHit(
            chunk_id=cid,
            document_id=did,
            document_name='경조사_규정.txt',
            document_url='/media/origin/x.txt',
            content=content,
            score=1.0,
        )

    def test_assistant_history_is_dropped_from_final_messages(self):
        history = [
            {'role': 'user', 'content': '조부모 상 알려줘'},
            {'role': 'assistant', 'content': '조부모 상은 200만 원입니다'},
        ]
        chunk = self._chunk('조부모 상\n2000만\n2일')
        messages = build_messages(
            '조부모 상',
            chunk_hits=[chunk],
            qa_hits=[],
            history=history,
        )
        # assistant content (옛 200만) 가 어떤 메시지에도 포함되면 안 된다.
        for m in messages:
            self.assertNotIn('200만', m['content'])
        # assistant role 자체가 메시지 리스트에서 빠져 있어야 한다.
        self.assertFalse(any(m.get('role') == 'assistant' for m in messages))

    def test_user_history_is_retained(self):
        history = [
            {'role': 'user', 'content': '조부모 상 알려줘'},
            {'role': 'assistant', 'content': '조부모 상은 200만 원입니다'},
            {'role': 'user', 'content': '다시 조부모 상 알려줘'},
        ]
        messages = build_messages(
            '조부모 상',
            chunk_hits=[self._chunk('조부모 상\n2000만\n2일')],
            qa_hits=[],
            history=history,
        )
        user_contents = [m['content'] for m in messages if m.get('role') == 'user']
        self.assertIn('조부모 상 알려줘', user_contents)
        self.assertIn('다시 조부모 상 알려줘', user_contents)

    def test_key_excerpt_section_precedes_full_chunks(self):
        """v0.5.3 QA 보강 S3 — 질문/검색어 매치 주변 발췌가 회사 자료 앞에 박힌다."""
        chunk = self._chunk(
            '경조사 표\n... 본인 결혼 500만\n조부모 상\n2000만\n2일\n외조부모 상 100만'
        )
        messages = build_messages(
            '조부모 상',
            chunk_hits=[chunk],
            qa_hits=[],
            history=[],
        )
        last = messages[-1]['content']
        self.assertIn('[자료 1 핵심 발췌]', last)
        # 라벨과 회사 자료 사이에 '2000만' 이 인용되어야 한다.
        key_idx = last.index('[자료 1 핵심 발췌]')
        src_idx = last.index('=== 회사 자료 ===')
        self.assertLess(key_idx, src_idx)
        excerpt_block = last[key_idx:src_idx]
        self.assertIn('2000만', excerpt_block)
        self.assertIn('조부모 상', excerpt_block)

    def test_key_excerpt_prefers_search_query_over_raw(self):
        """search_query 가 있으면 그것을 기준으로 발췌한다."""
        chunk = self._chunk('경조사 표\n... 조부모 상\n2000만\n2일\n결혼 500만')
        messages = build_messages(
            '비싼거',
            chunk_hits=[chunk],
            qa_hits=[],
            history=[],
            search_query='조부모 상',
        )
        last = messages[-1]['content']
        self.assertIn('[자료 1 핵심 발췌]', last)
        self.assertIn('2000만', last.split('=== 회사 자료 ===')[0])

    def test_key_excerpt_section_absent_when_no_match(self):
        chunk = self._chunk('휴가 규정\n연차는 15일 입니다.')
        messages = build_messages(
            '조부모 상',
            chunk_hits=[chunk],
            qa_hits=[],
            history=[],
        )
        last = messages[-1]['content']
        self.assertNotIn('[자료 1 핵심 발췌]', last)

    def test_current_chunk_content_appears_in_last_user_message(self):
        chunk = self._chunk('조부모 상\n2000만\n2일')
        messages = build_messages(
            '조부모 상',
            chunk_hits=[chunk],
            qa_hits=[],
            history=[
                {'role': 'assistant', 'content': '조부모 상은 200만 원입니다'},
            ],
        )
        self.assertEqual(messages[-1]['role'], 'user')
        last = messages[-1]['content']
        self.assertIn('2000만', last)
        self.assertIn('조부모 상', last)
        self.assertNotIn('200만 원', last)
