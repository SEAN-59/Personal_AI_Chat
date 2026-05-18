"""run_single_shot 통합 회귀 테스트 — sourced CanonicalQA cache skip (v0.5.4).

mock target 은 pipeline 의 실제 import binding 기준:
  - chat.services.single_shot.pipeline.find_canonical_qa
  - chat.services.single_shot.pipeline.retrieve_documents
  - chat.services.single_shot.pipeline.run_chat_completion
  - chat.services.single_shot.postprocess.record_token_usage
실제 OpenAI 호출 0.
"""

from unittest.mock import patch

from django.test import TestCase

from chat.models import CanonicalQA
from chat.services.qa_retriever import QAHit
from chat.services.single_shot import pipeline as ss_pipeline
from files.models import Document, DocumentChunk
from files.services.retriever import ChunkHit


class _Usage:
    prompt_tokens = 1
    completion_tokens = 1
    total_tokens = 2


def _llm_response(text='NEW ANSWER from fresh chunk'):
    return text, _Usage(), 'gpt-4o-mini'


def _ready_doc(name='경조사.md'):
    return Document.objects.create(
        file=f'origin/{name}', original_name=name, size_bytes=1,
        mime_type='text/markdown', status=Document.Status.READY,
        edited_text='2000만원',
    )


def _ready_chunk(doc, idx=0, content='조부모 상 경조사비 2000만원'):
    return DocumentChunk.objects.create(
        document=doc, chunk_index=idx, content=content, embedding=[0.0] * 1536,
    )


class SourcedCanonicalQACacheSkipTests(TestCase):
    def test_sourced_qa_does_not_short_circuit_and_llm_is_called(self):
        doc = _ready_doc()
        _ready_chunk(doc)
        stale = CanonicalQA.objects.create(
            question='조부모상 경조사비',
            question_embedding=[0.0] * 1536,
            answer='200만원',  # 옛 정답 (stale)
            sources=[doc.id],
        )
        qa_hits = [QAHit(qa_id=stale.pk, question='조부모상 경조사비',
                         answer='200만원', similarity=0.95)]
        chunk_hit = ChunkHit(
            chunk_id=1, document_id=doc.id, document_name=doc.original_name,
            document_url='', content='조부모 상 경조사비 2000만원', score=0.5,
            chunk_index=0,
        )

        with patch(
            'chat.services.single_shot.pipeline.find_canonical_qa',
            return_value=qa_hits,
        ), patch(
            'chat.services.single_shot.pipeline.retrieve_documents',
            return_value=[chunk_hit],
        ), patch(
            'chat.services.single_shot.pipeline.run_chat_completion',
            return_value=_llm_response('조부모 상 경조사비는 2000만원입니다.'),
        ) as llm_mock, patch(
            'chat.services.single_shot.postprocess.record_token_usage',
        ):
            result = ss_pipeline.run_single_shot('조부모상 경조사비', history=[])

        # sourced CA 가 있어도 LLM 이 호출되고 새 답이 반환.
        llm_mock.assert_called_once()
        self.assertIn('2000만원', result.reply)

    def test_empty_sourced_qa_still_short_circuits(self):
        generic_qa = CanonicalQA.objects.create(
            question='안녕',
            question_embedding=[0.0] * 1536,
            answer='안녕하세요',
            sources=[],
        )
        qa_hits = [QAHit(qa_id=generic_qa.pk, question='안녕',
                         answer='안녕하세요', similarity=0.95)]

        with patch(
            'chat.services.single_shot.pipeline.find_canonical_qa',
            return_value=qa_hits,
        ), patch(
            'chat.services.single_shot.pipeline.retrieve_documents',
            return_value=[],
        ), patch(
            'chat.services.single_shot.pipeline.run_chat_completion',
        ) as llm_mock, patch(
            'chat.services.single_shot.postprocess.record_token_usage',
        ):
            result = ss_pipeline.run_single_shot('안녕', history=[])

        # sources 빈 일반답은 종전대로 cache hit → LLM 호출 없음.
        llm_mock.assert_not_called()
        self.assertEqual(result.reply, '안녕하세요')
        self.assertEqual(result.total_tokens, 0)
