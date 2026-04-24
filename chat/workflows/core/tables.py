"""마크다운 GFM 표 파서 (Phase 6-3).

`table_lookup` workflow 가 retrieval 로 받아온 청크 안에서 **표 만** 골라내기
위해 쓰인다. 순수 함수 — 다른 core 모듈 / 도메인 모듈을 import 하지 않는다.

입출력:
    parse_markdown_tables(text) -> list[dict]
        각 dict 는 {'headers': [str, ...], 'rows': [{header: cell, ...}, ...]}.
    비정상 입력(빈 문자열, 파이프 없는 문단 등) 은 빈 리스트.

규모 제한 (안전판):
    - 한 입력에서 최대 10 개 표.
    - 한 표 당 최대 200 행.
    - 구분자 라인(`|---|---|`) 이 있어야 표로 인정. 파이프만 들어간 일반 문장은 무시.
"""

from __future__ import annotations

import re
from typing import Any


MAX_TABLES_PER_INPUT = 10
MAX_ROWS_PER_TABLE = 200

# 구분자 라인 — `| --- | :---: | ---: |` 등. 파이프 사이에 대시와 선택적 콜론만 허용.
_SEPARATOR_RE = re.compile(r'^\s*\|?\s*:?-+:?\s*(\|\s*:?-+:?\s*)+\|?\s*$')


def parse_markdown_tables(text: str) -> list[dict[str, Any]]:
    """`text` 에서 모든 GFM 표를 파싱해 list[dict] 로 반환."""
    if not text:
        return []

    tables: list[dict[str, Any]] = []
    lines = text.splitlines()
    i = 0
    while i < len(lines) and len(tables) < MAX_TABLES_PER_INPUT:
        header_line = lines[i]
        # 헤더 후보는 파이프가 최소 하나 이상 있는 라인.
        if '|' not in header_line or i + 1 >= len(lines):
            i += 1
            continue
        sep_line = lines[i + 1]
        if not _SEPARATOR_RE.match(sep_line):
            i += 1
            continue

        headers = _split_row(header_line)
        if not headers:
            i += 1
            continue

        rows: list[dict[str, str]] = []
        j = i + 2
        while j < len(lines) and len(rows) < MAX_ROWS_PER_TABLE:
            line = lines[j]
            if '|' not in line or not line.strip():
                break
            cells = _split_row(line)
            if not cells:
                break
            row: dict[str, str] = {}
            for idx, header in enumerate(headers):
                row[header] = cells[idx] if idx < len(cells) else ''
            rows.append(row)
            j += 1

        if rows:
            tables.append({'headers': headers, 'rows': rows})
        i = j if rows else i + 1

    return tables


def serialize_table(table: dict[str, Any]) -> str:
    """파싱된 표를 다시 마크다운 문자열로 직렬화. LLM 프롬프트에 넣을 때 사용."""
    headers = table.get('headers') or []
    rows = table.get('rows') or []
    if not headers:
        return ''

    lines = ['| ' + ' | '.join(headers) + ' |']
    lines.append('| ' + ' | '.join('---' for _ in headers) + ' |')
    for row in rows:
        cells = [str(row.get(h, '')) for h in headers]
        lines.append('| ' + ' | '.join(cells) + ' |')
    return '\n'.join(lines)


def _split_row(line: str) -> list[str]:
    """`| a | b | c |` → `['a', 'b', 'c']`. 비정상 라인은 빈 리스트."""
    stripped = line.strip()
    if not stripped:
        return []
    # 앞뒤 파이프 제거 후 분리. 내부에 빈 셀(`| |`) 은 허용.
    if stripped.startswith('|'):
        stripped = stripped[1:]
    if stripped.endswith('|'):
        stripped = stripped[:-1]
    parts = [c.strip() for c in stripped.split('|')]
    return parts
