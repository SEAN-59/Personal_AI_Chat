"""qa_cache.resolve_cache_hit 회귀 테스트 (v0.5.4).

직접 호출. mock 없음. sourced CanonicalQA 는 immediate-cache 에서 skip,
sources 비어있는 row 는 종전대로 cache hit.
"""

from django.test import TestCase

from chat.models import CanonicalQA
from chat.services.qa_retriever import QAHit
from chat.services.single_shot import qa_cache
from files.models import Document


def _qa(answer='ANS', sources=None, embedding=None):
    return CanonicalQA.objects.create(
        question='q',
        question_embedding=embedding or [0.0] * 1536,
        answer=answer,
        sources=sources or [],
    )


class ResolveCacheHitSourcedSkipTests(TestCase):
    def test_below_threshold_returns_none(self):
        qa = _qa()
        hits = [QAHit(qa_id=qa.pk, question='q', answer='ANS', similarity=0.5)]
        self.assertIsNone(qa_cache.resolve_cache_hit(hits))

    def test_sourced_canonical_qa_skipped(self):
        doc = Document.objects.create(
            file='origin/x.txt', original_name='x.txt', size_bytes=1,
            mime_type='text/plain', status=Document.Status.READY, edited_text='x',
        )
        qa = _qa(answer='OLD ANSWER', sources=[doc.id])
        hits = [QAHit(qa_id=qa.pk, question='q', answer='OLD ANSWER', similarity=0.95)]
        # sources 비어있지 않으므로 cache hit 반환 금지.
        self.assertIsNone(qa_cache.resolve_cache_hit(hits))

    def test_empty_sources_returns_cache_hit(self):
        qa = _qa(answer='GENERIC ANSWER', sources=[])
        hits = [QAHit(qa_id=qa.pk, question='q', answer='GENERIC ANSWER', similarity=0.95)]
        result = qa_cache.resolve_cache_hit(hits)
        self.assertIsNotNone(result)
        self.assertEqual(result.reply, 'GENERIC ANSWER')
        self.assertEqual(result.total_tokens, 0)
        self.assertIsNone(result.chat_log_id)
        self.assertEqual(result.sources, [])

    def test_empty_hits_returns_none(self):
        self.assertIsNone(qa_cache.resolve_cache_hit([]))
