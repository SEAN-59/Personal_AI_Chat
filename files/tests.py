"""files app 회귀 테스트.

v0.5.4 — `search_chunks` 의 READY 필터 / phrase boost / multi-keyword boost /
deterministic tie-break 동작 검증. OpenAI 호출 없음 — `embed_text` 만 mock.
"""

from unittest.mock import patch

from django.test import TestCase

from files.models import Document, DocumentChunk
from files.services import retriever


def _fake_embed(_text):
    # 모든 임베딩을 같은 벡터로 두면 vector 검색이 chunk id 오름차순으로 결정적.
    return [0.0] * 1536


def _doc(name='doc.txt', status=Document.Status.READY):
    return Document.objects.create(
        file=f'origin/{name}',
        original_name=name,
        size_bytes=10,
        mime_type='text/plain',
        status=status,
        edited_text='x',
    )


def _chunk(doc, idx, content, embedding=None):
    return DocumentChunk.objects.create(
        document=doc,
        chunk_index=idx,
        content=content,
        embedding=embedding or [0.0] * 1536,
    )


class SearchChunksReadyFilterTests(TestCase):
    def test_non_ready_document_chunks_excluded(self):
        ready = _doc('ready.txt', status=Document.Status.READY)
        processing = _doc('processing.txt', status=Document.Status.PROCESSING)
        failed = _doc('failed.txt', status=Document.Status.FAILED)
        reviewing = _doc('reviewing.txt', status=Document.Status.REVIEWING)
        _chunk(ready, 0, 'alpha keyword here')
        _chunk(processing, 0, 'alpha keyword here')
        _chunk(failed, 0, 'alpha keyword here')
        _chunk(reviewing, 0, 'alpha keyword here')

        with patch('files.services.retriever.embed_text', side_effect=_fake_embed):
            hits = retriever.search_chunks('alpha keyword', top_k=10)

        doc_ids = {h.document_id for h in hits}
        self.assertEqual(doc_ids, {ready.id})


class SearchChunksBoostTests(TestCase):
    def test_multi_keyword_hit_boosts_score_above_single_hit(self):
        # 같은 RRF 베이스라인에서 multi-keyword 매치가 single 매치보다 위에 와야 한다.
        doc = _doc()
        single_hit = _chunk(doc, 0, '연차 안내')
        multi_hit = _chunk(doc, 1, '연차 휴가 안내')

        with patch('files.services.retriever.embed_text', side_effect=_fake_embed):
            hits = retriever.search_chunks('연차 휴가', top_k=2)

        self.assertEqual(len(hits), 2)
        self.assertEqual(hits[0].chunk_id, multi_hit.id)
        self.assertEqual(hits[1].chunk_id, single_hit.id)

    def test_exact_phrase_boost_promotes_phrase_match(self):
        # phrase 가 통째로 들어있는 chunk 가 단순 키워드 매치보다 우선.
        doc = _doc()
        partial = _chunk(doc, 0, '경조 한도 표 참고')
        phrase = _chunk(doc, 1, '경조사 전체 표는 다음과 같다')

        with patch('files.services.retriever.embed_text', side_effect=_fake_embed):
            hits = retriever.search_chunks('경조사', top_k=2)

        self.assertEqual(hits[0].chunk_id, phrase.id)
        self.assertIn(partial.id, [h.chunk_id for h in hits])


class ExtractKeywordsNormalizationTests(TestCase):
    """v0.5.5 — 조사/어미 정규화 + 범용 enumeration 단서 제외."""

    def test_strips_particles_and_endings(self):
        kws = retriever._extract_keywords('경조사에서 지급하는 모든 종류 알려줘')
        self.assertIn('경조사', kws)
        self.assertIn('지급', kws)
        for excluded in ('모든', '종류', '알려줘', '경조사에서', '지급하는'):
            self.assertNotIn(excluded, kws)

    def test_generic_enumeration_words_excluded(self):
        kws = retriever._extract_keywords('휴가 종류 전체 목록 보여줘')
        self.assertIn('휴가', kws)
        for excluded in ('종류', '전체', '목록', '보여줘'):
            self.assertNotIn(excluded, kws)

    def test_does_not_strip_short_or_domain_terms(self):
        # 회사 도메인 단어가 정규화로 사라지면 안 된다.
        kws = retriever._extract_keywords('연차 휴가 안내')
        self.assertEqual(set(kws), {'연차', '휴가', '안내'})


class SearchChunksKeywordNormalizationRegressionTests(TestCase):
    """v0.5.5 — 정규화된 keyword 로 핵심 chunk 가 후보에 잡혀야 한다."""

    def test_normalized_keywords_surface_relevant_chunk(self):
        doc = _doc('benefits.txt')
        # 핵심 chunk: '경조사' + '지급' 동시 포함
        relevant = _chunk(
            doc, 0,
            '복리후생 규정 - 경조사 지원금 지급 기준은 다음과 같다',
        )
        # noise chunk: 범용어만 매치
        _chunk(doc, 1, '모든 직원에게 안내합니다. 종류별 상세는 별도.')
        _chunk(doc, 2, '괴롭힘 방지 정책 안내')

        with patch('files.services.retriever.embed_text', side_effect=_fake_embed):
            hits = retriever.search_chunks(
                '경조사에서 지급하는 모든 종류 알려줘', top_k=3,
            )

        ids = [h.chunk_id for h in hits]
        self.assertIn(relevant.id, ids)
        # 핵심 chunk 가 최상위.
        self.assertEqual(hits[0].chunk_id, relevant.id)


class SearchChunksDeterministicTieBreakTests(TestCase):
    def test_ties_break_by_chunk_id_ascending(self):
        # 두 chunk 가 동일 keyword/phrase 매치로 동률이면 id ASC.
        doc = _doc()
        first = _chunk(doc, 0, '경조사 안내 A')
        second = _chunk(doc, 1, '경조사 안내 B')

        with patch('files.services.retriever.embed_text', side_effect=_fake_embed):
            hits = retriever.search_chunks('경조사', top_k=2)

        self.assertEqual([h.chunk_id for h in hits], [first.id, second.id])
