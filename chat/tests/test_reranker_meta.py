"""reranker 메타 prepend / fallback 회귀 테스트 (v0.5.4).

실제 OpenAI 호출 금지 — `chat.services.reranker.OpenAI` 를 통째로 mock.
"""

import json
from unittest.mock import MagicMock, patch

from django.test import SimpleTestCase

from chat.services import reranker
from files.services.retriever import ChunkHit


def _hit(chunk_id, doc_name, idx, content):
    return ChunkHit(
        chunk_id=chunk_id,
        document_id=chunk_id,
        document_name=doc_name,
        document_url='',
        content=content,
        score=0.1,
        chunk_index=idx,
    )


def _stub_openai_client(json_payload):
    """OpenAI() 가 반환할 client 를 흉내. chat.completions.create 한 번만 본다."""
    client = MagicMock()
    message = MagicMock()
    message.content = json.dumps(json_payload)
    choice = MagicMock()
    choice.message = message
    resp = MagicMock()
    resp.choices = [choice]
    client.chat.completions.create.return_value = resp
    return client


class RerankerMetaPromptTests(SimpleTestCase):
    def test_candidate_block_includes_document_name_and_chunk_index(self):
        hits = [
            _hit(1, '경조사.md', 0, '본인 상 500만원'),
            _hit(2, '연차.md', 3, '연차 일수 안내'),
            _hit(3, '경조사.md', 7, '배우자 상 100만원'),
        ]
        client = _stub_openai_client({'ranking': [1, 0]})
        with patch.dict('os.environ', {'OPENAI_API_KEY': 'sk-test'}), \
             patch('chat.services.reranker.OpenAI', return_value=client):
            reranker.rerank('경조사', hits, top_k=2)

        # 호출 시 만들어진 prompt 본문에 메타가 prepend 되었는지.
        kwargs = client.chat.completions.create.call_args.kwargs
        prompt = kwargs['messages'][0]['content']
        self.assertIn('경조사.md', prompt)
        self.assertIn('연차.md', prompt)
        # chunk_index 도 노출 (값은 0 / 3).
        self.assertIn('chunk #0', prompt)
        self.assertIn('chunk #3', prompt)


class RerankerFallbackTests(SimpleTestCase):
    def test_no_api_key_returns_input_truncated(self):
        hits = [_hit(i, 'd.md', i, f'c{i}') for i in range(6)]
        with patch.dict('os.environ', {}, clear=True):
            out = reranker.rerank('q', hits, top_k=3)
        self.assertEqual([h.chunk_id for h in out], [0, 1, 2])

    def test_invalid_json_falls_back_to_input_order(self):
        hits = [_hit(i, 'd.md', i, f'c{i}') for i in range(6)]
        client = MagicMock()
        message = MagicMock()
        message.content = 'not-json-at-all'
        choice = MagicMock()
        choice.message = message
        resp = MagicMock()
        resp.choices = [choice]
        client.chat.completions.create.return_value = resp
        with patch.dict('os.environ', {'OPENAI_API_KEY': 'sk-test'}), \
             patch('chat.services.reranker.OpenAI', return_value=client):
            out = reranker.rerank('q', hits, top_k=3)
        self.assertEqual([h.chunk_id for h in out], [0, 1, 2])

    def test_empty_ranking_falls_back_to_input_order(self):
        hits = [_hit(i, 'd.md', i, f'c{i}') for i in range(6)]
        client = _stub_openai_client({'ranking': []})
        with patch.dict('os.environ', {'OPENAI_API_KEY': 'sk-test'}), \
             patch('chat.services.reranker.OpenAI', return_value=client):
            out = reranker.rerank('q', hits, top_k=3)
        self.assertEqual([h.chunk_id for h in out], [0, 1, 2])
