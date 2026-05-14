"""qa_retriever.save_chat_log — dedup 정책 박제 (v0.5.3 QA 보강 S3).

기존 정책은 유사 existing 이 있으면 answer 가 달라도 그대로 재사용했다.
재임베딩으로 답변이 갱신됐는데 stale ChatLog 에 피드백이 붙는 회귀가 있어,
answer/sources 가 다르면 새 ChatLog 를 생성하도록 바뀜.
"""

from unittest.mock import patch

from django.test import TestCase

from chat.models import ChatLog
from chat.services.qa_retriever import save_chat_log


# 임베딩 호출을 패치할 때 쓸 더미 벡터 (1536-dim, 모두 동일 → cosine distance ≈ 0)
def _fake_embed(text):
    return [0.01] * 1536


class SaveChatLogDedupTests(TestCase):
    def test_reuses_existing_when_answer_and_sources_match(self):
        with patch('chat.services.qa_retriever.embed_text', side_effect=_fake_embed):
            first = save_chat_log('조부모 상 알려줘', '조부모 상은 2000만 원입니다', sources=[1])
            second = save_chat_log('조부모 상이 얼마야', '조부모 상은 2000만 원입니다', sources=[1])
        self.assertEqual(first.pk, second.pk)
        self.assertEqual(ChatLog.objects.count(), 1)

    def test_creates_new_when_answer_differs(self):
        """재임베딩 후 같은 질문이라도 답변이 바뀌면 새 ChatLog — stale log 에 피드백 막힘 방지."""
        with patch('chat.services.qa_retriever.embed_text', side_effect=_fake_embed):
            first = save_chat_log('조부모 상 알려줘', '조부모 상은 200만 원입니다', sources=[1])
            second = save_chat_log('조부모 상 알려줘', '조부모 상은 2000만 원입니다', sources=[1])
        self.assertNotEqual(first.pk, second.pk)
        self.assertEqual(ChatLog.objects.count(), 2)

    def test_creates_new_when_sources_differ(self):
        with patch('chat.services.qa_retriever.embed_text', side_effect=_fake_embed):
            first = save_chat_log('조부모 상', '답변', sources=[1])
            second = save_chat_log('조부모 상', '답변', sources=[1, 2])
        self.assertNotEqual(first.pk, second.pk)
        self.assertEqual(ChatLog.objects.count(), 2)
