"""Phase 6-3 마크다운 표 파서 단위 테스트."""

from django.test import SimpleTestCase

from chat.workflows.core.tables import (
    MAX_ROWS_PER_TABLE,
    MAX_TABLES_PER_INPUT,
    parse_markdown_tables,
    serialize_table,
)


class ParseMarkdownTablesTests(SimpleTestCase):
    def test_empty_input_returns_empty_list(self):
        self.assertEqual(parse_markdown_tables(''), [])
        self.assertEqual(parse_markdown_tables(None), [])

    def test_no_pipe_returns_empty_list(self):
        self.assertEqual(parse_markdown_tables('일반 문단입니다.'), [])

    def test_single_table_round_trip(self):
        text = (
            '| 항목 | 금액 |\n'
            '|---|---|\n'
            '| 본인 상 | 500만원 |\n'
            '| 배우자 상 | 100만원 |\n'
        )
        tables = parse_markdown_tables(text)
        self.assertEqual(len(tables), 1)
        self.assertEqual(tables[0]['headers'], ['항목', '금액'])
        self.assertEqual(
            tables[0]['rows'],
            [
                {'항목': '본인 상', '금액': '500만원'},
                {'항목': '배우자 상', '금액': '100만원'},
            ],
        )

    def test_multiple_tables_in_one_input(self):
        text = (
            '| A | B |\n|---|---|\n| 1 | 2 |\n\n'
            '설명 문단입니다.\n\n'
            '| X | Y |\n|---|---|\n| x | y |\n'
        )
        tables = parse_markdown_tables(text)
        self.assertEqual(len(tables), 2)
        self.assertEqual(tables[0]['headers'], ['A', 'B'])
        self.assertEqual(tables[1]['headers'], ['X', 'Y'])

    def test_pipe_without_separator_is_ignored(self):
        text = (
            '| 그냥 | 파이프만 | 있는 |\n'   # 구분자 라인 없음
            '| 표 아님 | 무시됨 |\n'
        )
        self.assertEqual(parse_markdown_tables(text), [])

    def test_table_with_alignment_colons(self):
        text = (
            '| 항목 | 금액 |\n'
            '| :--- | ---: |\n'
            '| A | 100 |\n'
        )
        tables = parse_markdown_tables(text)
        self.assertEqual(len(tables), 1)
        self.assertEqual(tables[0]['rows'][0]['금액'], '100')

    def test_row_cell_count_mismatch_pads_with_empty(self):
        text = (
            '| 항목 | 금액 | 비고 |\n'
            '|---|---|---|\n'
            '| A | 100 |\n'      # 비고 누락
        )
        tables = parse_markdown_tables(text)
        self.assertEqual(tables[0]['rows'][0]['비고'], '')

    def test_max_tables_limit(self):
        # 안전판 — 11 번째 표는 잘린다.
        blocks = []
        for i in range(MAX_TABLES_PER_INPUT + 3):
            blocks.append(f'| h{i} | h{i}b |\n|---|---|\n| v{i} | v{i}b |\n')
        tables = parse_markdown_tables('\n\n'.join(blocks))
        self.assertEqual(len(tables), MAX_TABLES_PER_INPUT)

    def test_unicode_headers_and_cells(self):
        text = (
            '| 구분 | 내용 |\n'
            '|---|---|\n'
            '| 경조사 | 🎉 축하합니다 |\n'
        )
        tables = parse_markdown_tables(text)
        self.assertEqual(tables[0]['rows'][0]['내용'], '🎉 축하합니다')


class SerializeTableTests(SimpleTestCase):
    def test_round_trip_preserves_structure(self):
        text = (
            '| A | B |\n|---|---|\n| 1 | 2 |\n| 3 | 4 |\n'
        )
        parsed = parse_markdown_tables(text)[0]
        serialized = serialize_table(parsed)
        # 재파싱해서 같은 구조가 나오는지만 확인 — 공백 포맷은 정규화되어 달라질 수 있다.
        reparsed = parse_markdown_tables(serialized)[0]
        self.assertEqual(reparsed['headers'], parsed['headers'])
        self.assertEqual(reparsed['rows'], parsed['rows'])

    def test_empty_headers_returns_empty_string(self):
        self.assertEqual(serialize_table({'headers': [], 'rows': []}), '')
