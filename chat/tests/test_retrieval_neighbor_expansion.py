"""v0.5.5 — retrieve_documents neighbor expansion 단위 테스트.

§4.1 적용 조건 / 윈도우 병합 / budget cap / 정렬·중복 제거 / status=READY 가드 확인.
OpenAI / embedder / reranker / search_chunks 는 모두 mock — 실제 외부 호출 0.
"""

from unittest.mock import patch

from django.test import TestCase

from chat.services.single_shot import retrieval as r
from files.models import Document, DocumentChunk
from files.services.retriever import ChunkHit


_TABLE_CONTENT = (
    '경조사 지원금 표\n\n'
    '| 항목 | 금액 |\n'
    '|---|---|\n'
    '| 본인 결혼 | 100만원 |\n'
    '| 본인 상 | 500만원 |\n'
)

_LIST_CONTENT = (
    '경조사 종류\n'
    '- 본인 결혼\n'
    '- 본인 상\n'
    '- 배우자 상\n'
)

_PLAIN_CONTENT = '연차는 입사 1년 차 11일을 부여한다. 자세한 사항은 휴가 규정 참조.'


def _doc(name='doc.txt', status=Document.Status.READY):
    return Document.objects.create(
        file=f'origin/{name}',
        original_name=name,
        size_bytes=10,
        mime_type='text/plain',
        status=status,
        edited_text='x',
    )


def _orm_chunk(doc, idx, content):
    return DocumentChunk.objects.create(
        document=doc,
        chunk_index=idx,
        content=content,
        embedding=[0.0] * 1536,
    )


def _hit(chunk):
    """ORM DocumentChunk → ChunkHit (search_chunks 결과 흉내)."""
    doc = chunk.document
    return ChunkHit(
        chunk_id=chunk.id,
        document_id=doc.id,
        document_name=doc.original_name,
        document_url='',
        content=chunk.content,
        score=1.0,
        chunk_index=chunk.chunk_index,
    )


class _PatchMixin:
    """search_chunks / rerank 를 identity-like stub 로 대체."""

    def _patch_pipeline(self, hits):
        # rerank 는 입력 hits 를 그대로 통과 (top_k slicing 만).
        def _rerank(question, candidates, top_k):
            return list(candidates[:top_k])

        return [
            patch.object(r, 'search_chunks', return_value=list(hits)),
            patch.object(r, 'rerank', side_effect=_rerank),
        ]


class NeighborExpansionConditionTests(TestCase, _PatchMixin):
    """§4.1 발동 조건 단위 테스트."""

    def _run(self, question, hits):
        ctxs = self._patch_pipeline(hits)
        for c in ctxs:
            c.start()
        try:
            return r.retrieve_documents(question)
        finally:
            for c in ctxs:
                c.stop()

    def test_enumeration_single_hit_expands_neighbors(self):
        doc = _doc('경조사.txt')
        chunks = [_orm_chunk(doc, i, f'행 {i}') for i in range(6)]
        # hit 은 chunk_index=3 한 개.
        hits = [_hit(chunks[3])]
        out = self._run('모든 종류 알려줘', hits)
        indices = [h.chunk_index for h in out]
        # radius=2 → 1,2,3,4,5 모두 포함.
        self.assertEqual(indices, [1, 2, 3, 4, 5])

    def test_non_enumeration_single_hit_does_not_expand(self):
        doc = _doc('연차.txt')
        chunks = [_orm_chunk(doc, i, f'본문 {i}') for i in range(5)]
        hits = [_hit(chunks[2])]
        out = self._run('연차 며칠?', hits)
        self.assertEqual([h.chunk_index for h in out], [2])

    def test_multi_hit_with_table_marker_merges_windows(self):
        doc = _doc('경조사표.txt')
        # chunk 4 와 6 에 표 marker.
        chunks = []
        for i in range(10):
            content = _TABLE_CONTENT if i in (4, 6) else f'본문 {i}'
            chunks.append(_orm_chunk(doc, i, content))
        hits = [_hit(chunks[4]), _hit(chunks[6])]
        # query 는 enumeration 신호 없음 — 조건 2 만으로 발동.
        out = self._run('경조사 정리해줘', hits)
        # window 4±2 ∪ 6±2 = 2..8.
        self.assertEqual([h.chunk_index for h in out], [2, 3, 4, 5, 6, 7, 8])

    def test_multi_hit_without_marker_does_not_expand(self):
        doc = _doc('일반.txt')
        chunks = [_orm_chunk(doc, i, f'평문 {i}') for i in range(6)]
        hits = [_hit(chunks[1]), _hit(chunks[3])]
        out = self._run('휴가 며칠 쓸 수 있어?', hits)
        self.assertEqual([h.chunk_index for h in out], [1, 3])

    def test_monetary_with_metric_and_table_marker_expands(self):
        doc = _doc('표.txt')
        chunks = []
        for i in range(7):
            content = _TABLE_CONTENT if i == 3 else f'본문 {i}'
            chunks.append(_orm_chunk(doc, i, content))
        hits = [_hit(chunks[3])]
        out = self._run('경조사 지급금액 중 가장 큰 항목', hits)
        self.assertEqual([h.chunk_index for h in out], [1, 2, 3, 4, 5])

    def test_monetary_without_table_marker_does_not_expand(self):
        doc = _doc('평문.txt')
        chunks = [_orm_chunk(doc, i, f'본문 {i}') for i in range(5)]
        hits = [_hit(chunks[2])]
        out = self._run('경조사 지급금액 중 가장 큰 항목', hits)
        self.assertEqual([h.chunk_index for h in out], [2])

    def test_short_ordinal_only_followup_does_not_expand(self):
        # `비싼거?` 단독 follow-up — metric 어휘도 table marker 도 없음.
        doc = _doc('평문.txt')
        chunks = [_orm_chunk(doc, i, f'본문 {i}') for i in range(5)]
        hits = [_hit(chunks[2])]
        out = self._run('비싼거?', hits)
        self.assertEqual([h.chunk_index for h in out], [2])

    def test_항목_alone_does_not_trigger_enumeration(self):
        doc = _doc('평문.txt')
        chunks = [_orm_chunk(doc, i, f'본문 {i}') for i in range(5)]
        hits = [_hit(chunks[2])]
        out = self._run('경조사 지급금액 중 가장 큰 항목', hits)
        # 위 case 와 동일 — `항목` 단어만으로는 발동 X.
        self.assertEqual([h.chunk_index for h in out], [2])


class NeighborExpansionOrderingTests(TestCase, _PatchMixin):

    def test_hit_in_middle_gets_full_window_in_index_order(self):
        doc = _doc('표연속.txt')
        chunks = []
        for i in range(10):
            content = _LIST_CONTENT if i == 6 else f'본문 {i}'
            chunks.append(_orm_chunk(doc, i, content))
        hits = [_hit(chunks[6])]
        ctxs = self._patch_pipeline(hits)
        for c in ctxs:
            c.start()
        try:
            out = r.retrieve_documents('모든 종류 알려줘')
        finally:
            for c in ctxs:
                c.stop()
        # 원본 hit chunk_index=6 + neighbor 4,5,7,8 → 4,5,6,7,8 순서.
        self.assertEqual([h.chunk_index for h in out], [4, 5, 6, 7, 8])


class NeighborExpansionBudgetTests(TestCase, _PatchMixin):

    def test_max_neighbor_chunks_per_doc_cap(self):
        doc = _doc('큰표.txt')
        # 25개 chunk + radius 2 → 윈도우 안에 다 들어가더라도 doc cap=8.
        chunks = []
        for i in range(25):
            content = _LIST_CONTENT if i in (4, 8, 12) else f'본문 {i}'
            chunks.append(_orm_chunk(doc, i, content))
        hits = [_hit(chunks[4]), _hit(chunks[8]), _hit(chunks[12])]
        ctxs = self._patch_pipeline(hits)
        for c in ctxs:
            c.start()
        try:
            out = r.retrieve_documents('모든 종류 알려줘')
        finally:
            for c in ctxs:
                c.stop()
        doc_count = sum(1 for h in out if h.document_id == doc.id)
        self.assertLessEqual(doc_count, r.MAX_NEIGHBOR_CHUNKS_PER_DOC)

    def test_max_total_chunks_after_expansion_cap(self):
        # 여러 document — 각각 enumeration window.
        out_hits = []
        for d_idx in range(4):
            doc = _doc(f'd{d_idx}.txt')
            chunks = [_orm_chunk(doc, i, f'본문 d{d_idx} {i}') for i in range(8)]
            out_hits.append(_hit(chunks[3]))
        ctxs = self._patch_pipeline(out_hits)
        for c in ctxs:
            c.start()
        try:
            out = r.retrieve_documents('모든 종류 알려줘')
        finally:
            for c in ctxs:
                c.stop()
        self.assertLessEqual(len(out), r.MAX_TOTAL_CHUNKS_AFTER_EXPANSION)

    def test_max_expansion_chars_cap(self):
        doc = _doc('롱.txt')
        # 매우 큰 청크 — 원본 hit 만으로도 cap 초과 → expansion skip.
        big_content = 'x' * (r.MAX_EXPANSION_CHARS + 100)
        chunks = []
        for i in range(5):
            content = big_content if i == 2 else 'y' * 4000
            chunks.append(_orm_chunk(doc, i, content))
        hits = [_hit(chunks[2])]
        ctxs = self._patch_pipeline(hits)
        for c in ctxs:
            c.start()
        try:
            out = r.retrieve_documents('모든 종류 알려줘')
        finally:
            for c in ctxs:
                c.stop()
        # 원본 hit 이 이미 cap 초과 → neighbor 부착 0.
        self.assertEqual([h.chunk_index for h in out], [2])


class NeighborExpansionScopeTests(TestCase, _PatchMixin):

    def test_other_documents_never_pulled_in(self):
        doc_a = _doc('a.txt')
        doc_b = _doc('b.txt')
        a_chunks = [_orm_chunk(doc_a, i, f'a {i}') for i in range(6)]
        b_chunks = [_orm_chunk(doc_b, i, f'b {i}') for i in range(6)]
        hits = [_hit(a_chunks[2])]
        ctxs = self._patch_pipeline(hits)
        for c in ctxs:
            c.start()
        try:
            out = r.retrieve_documents('모든 종류 알려줘')
        finally:
            for c in ctxs:
                c.stop()
        # B doc chunk 가 단 하나도 결과에 끼면 안 됨.
        doc_ids = {h.document_id for h in out}
        self.assertEqual(doc_ids, {doc_a.id})
        # b_chunks 는 fixture 검증용으로만 사용.
        del b_chunks

    def test_duplicate_chunk_ids_removed(self):
        doc = _doc('dup.txt')
        chunks = [_orm_chunk(doc, i, f'본문 {i}') for i in range(5)]
        # 같은 hit 두 번.
        hits = [_hit(chunks[2]), _hit(chunks[2])]
        ctxs = self._patch_pipeline(hits)
        for c in ctxs:
            c.start()
        try:
            out = r.retrieve_documents('모든 종류 알려줘')
        finally:
            for c in ctxs:
                c.stop()
        chunk_ids = [h.chunk_id for h in out]
        self.assertEqual(len(chunk_ids), len(set(chunk_ids)))

    def test_non_ready_neighbor_chunks_excluded(self):
        doc = _doc('mixed.txt', status=Document.Status.READY)
        # 같은 document 안의 청크들 — status 는 document 단위. 따라서 보강은
        # 신규 document(non-ready)에서 옴 케이스를 만든다.
        ready_chunks = [_orm_chunk(doc, i, f'r {i}') for i in range(6)]

        not_ready_doc = _doc('np.txt', status=Document.Status.PROCESSING)
        # not-ready document 에는 neighbor 가 추가되면 안 됨. 직접 hit 도 없으므로
        # expansion 도 거기에는 안 닿는 게 정상.
        _orm_chunk(not_ready_doc, 0, 'np0')

        hits = [_hit(ready_chunks[2])]
        ctxs = self._patch_pipeline(hits)
        for c in ctxs:
            c.start()
        try:
            out = r.retrieve_documents('모든 종류 알려줘')
        finally:
            for c in ctxs:
                c.stop()
        for h in out:
            self.assertEqual(h.document_id, doc.id)


class ExpandNeighborsFlagTests(TestCase, _PatchMixin):

    def test_expand_neighbors_false_disables_expansion(self):
        doc = _doc('표.txt')
        chunks = [_orm_chunk(doc, i, f'본문 {i}') for i in range(6)]
        hits = [_hit(chunks[2])]
        ctxs = self._patch_pipeline(hits)
        for c in ctxs:
            c.start()
        try:
            out = r.retrieve_documents('모든 종류 알려줘', expand_neighbors=False)
        finally:
            for c in ctxs:
                c.stop()
        self.assertEqual([h.chunk_index for h in out], [2])
