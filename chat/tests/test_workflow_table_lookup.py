"""Phase 6-3 table_lookup workflow 단위 테스트."""

from types import SimpleNamespace
from unittest.mock import patch

from django.test import SimpleTestCase

from chat.workflows.core import WorkflowStatus, run_workflow
from chat.workflows.domains.general.table_lookup import (
    INPUT_SCHEMA,
    TableLookupWorkflow,
    WORKFLOW_KEY,
)


_TABLE_CHUNK = (
    '경조사 규정 표입니다.\n\n'
    '| 항목 | 금액 |\n'
    '|---|---|\n'
    '| 본인 상 | 500만원 |\n'
    '| 배우자 상 | 100만원 |\n'
)

_NO_TABLE_CHUNK = '표가 없는 일반 문단 청크입니다.'


def _chunk(content: str, filename: str = '경조사_규정.pdf'):
    """ChunkHit 유사 객체. 최소 속성만 갖춤."""
    return SimpleNamespace(content=content, document_name=filename)


class _UsageStub:
    prompt_tokens = 80
    completion_tokens = 20
    total_tokens = 100


class TableLookupInputTests(SimpleTestCase):
    """scaffold 때 확인한 입력 검증이 retrieval 연결 후에도 그대로인지."""

    def _run(self, raw):
        return run_workflow(TableLookupWorkflow(), raw)

    def test_query_required(self):
        r = self._run({})
        self.assertEqual(r.status, WorkflowStatus.MISSING_INPUT)
        self.assertIn('query', r.missing_fields)

    def test_registered_with_text_query_schema(self):
        from chat.workflows.domains import registry
        self.assertTrue(registry.has(WORKFLOW_KEY))
        entry = registry.get(WORKFLOW_KEY)
        self.assertEqual(entry.input_schema, INPUT_SCHEMA)
        self.assertEqual(entry.input_schema['query'].type, 'text')
        self.assertEqual(entry.status, registry.STATUS_STABLE)


class TableLookupRetrievalTests(SimpleTestCase):
    """retrieval + LLM mock 기반 동작 검증."""

    def _run(self, raw):
        return run_workflow(TableLookupWorkflow(), raw)

    def _patch_retrieve(self, hits):
        return patch(
            'chat.workflows.domains.general.table_lookup.retrieve_documents',
            return_value=hits,
        )

    def _patch_llm(self, reply, usage=None, model='gpt-4o-mini'):
        return patch(
            'chat.workflows.domains.general.table_lookup.run_chat_completion',
            return_value=(reply, usage or _UsageStub(), model),
        )

    def _patch_load_prompt(self):
        return patch(
            'chat.workflows.domains.general.table_lookup.load_prompt',
            return_value='PROMPT',
        )

    def _patch_record_usage(self):
        return patch(
            'chat.workflows.domains.general.table_lookup.record_token_usage',
        )

    def test_no_candidate_table_returns_not_found(self):
        # 모든 hit 이 표를 포함하지 않으면 LLM 은 호출조차 되지 않고 NOT_FOUND.
        with self._patch_retrieve([_chunk(_NO_TABLE_CHUNK)]), \
             self._patch_llm('{}') as llm, \
             self._patch_load_prompt():
            r = self._run({'query': '본인 상 경조금 얼마야?'})
        self.assertEqual(r.status, WorkflowStatus.NOT_FOUND)
        self.assertIn('관련 문서', r.details['reason'])
        llm.assert_not_called()

    def test_empty_hits_returns_not_found(self):
        with self._patch_retrieve([]):
            r = self._run({'query': '본인 상 경조금 얼마야?'})
        self.assertEqual(r.status, WorkflowStatus.NOT_FOUND)

    def test_happy_path_returns_ok_with_details(self):
        llm_reply = (
            '{"answer": "500만원", "source_document": "경조사_규정.pdf",'
            ' "matched_row": "본인 상", "matched_column": "금액"}'
        )
        with self._patch_retrieve([_chunk(_TABLE_CHUNK)]), \
             self._patch_llm(llm_reply), \
             self._patch_load_prompt(), \
             self._patch_record_usage() as record:
            r = self._run({'query': '본인 상 경조금 얼마야?'})

        self.assertEqual(r.status, WorkflowStatus.OK)
        self.assertEqual(r.value, '500만원')
        self.assertEqual(r.details['source_document'], '경조사_규정.pdf')
        self.assertEqual(r.details['matched_row'], '본인 상')
        self.assertEqual(r.details['matched_column'], '금액')
        record.assert_called_once()

    def test_llm_empty_object_returns_not_found(self):
        with self._patch_retrieve([_chunk(_TABLE_CHUNK)]), \
             self._patch_llm('{}'), \
             self._patch_load_prompt(), \
             self._patch_record_usage() as record:
            r = self._run({'query': '질문'})
        self.assertEqual(r.status, WorkflowStatus.NOT_FOUND)
        self.assertIn('항목 이름', r.details['reason'])
        # 호출은 됐으므로 토큰은 기록.
        record.assert_called_once()

    def test_llm_missing_answer_key_returns_not_found(self):
        with self._patch_retrieve([_chunk(_TABLE_CHUNK)]), \
             self._patch_llm('{"source_document": "x.pdf"}'), \
             self._patch_load_prompt(), \
             self._patch_record_usage():
            r = self._run({'query': '질문'})
        self.assertEqual(r.status, WorkflowStatus.NOT_FOUND)

    def test_llm_exception_returns_upstream_error(self):
        from chat.services.single_shot.types import QueryPipelineError
        with self._patch_retrieve([_chunk(_TABLE_CHUNK)]), \
             self._patch_load_prompt(), \
             patch(
                 'chat.workflows.domains.general.table_lookup.run_chat_completion',
                 side_effect=QueryPipelineError('boom'),
             ):
            r = self._run({'query': '질문'})
        self.assertEqual(r.status, WorkflowStatus.UPSTREAM_ERROR)
        self.assertIn('일시적', r.details['reason'])

    def test_llm_json_garbage_returns_upstream_error(self):
        with self._patch_retrieve([_chunk(_TABLE_CHUNK)]), \
             self._patch_llm('not json at all'), \
             self._patch_load_prompt(), \
             self._patch_record_usage():
            r = self._run({'query': '질문'})
        self.assertEqual(r.status, WorkflowStatus.UPSTREAM_ERROR)
