"""BO 문제 제보 표시용 템플릿 필터."""

from __future__ import annotations

import html
import re
from datetime import datetime
from typing import Iterable

from django import template
from django.utils import timezone
from django.utils.dateparse import parse_datetime
from django.utils.safestring import mark_safe


register = template.Library()


@register.filter
def server_time(value, fmt: str = '%Y-%m-%d %H:%M') -> str:
    """서버 기본 timezone 기준으로 날짜/시간을 표시한다."""
    if not value:
        return ''
    dt = _coerce_datetime(value)
    if dt is None:
        return str(value)

    default_tz = timezone.get_default_timezone()
    if timezone.is_naive(dt):
        dt = timezone.make_aware(dt, default_tz)
    else:
        dt = timezone.localtime(dt, default_tz)
    return dt.strftime(fmt)


@register.filter
def report_markdown(value) -> str:
    """문제 제보 Markdown 텍스트를 안전한 HTML 로 렌더링한다.

    외부 markdown 패키지 없이 BO 표시용으로 필요한 subset 만 지원한다:
    paragraph, line break, bold, inline code, unordered/ordered list, table.
    모든 원문은 먼저 HTML escape 하므로 저장된 raw HTML 은 실행되지 않는다.
    """
    text = str(value or '').replace('\r\n', '\n').replace('\r', '\n').strip()
    if not text:
        return ''

    lines = text.split('\n')
    html_parts: list[str] = []
    paragraph: list[str] = []
    i = 0

    def flush_paragraph() -> None:
        if paragraph:
            body = '<br>'.join(_inline_md(line) for line in paragraph)
            html_parts.append(f'<p>{body}</p>')
            paragraph.clear()

    while i < len(lines):
        line = lines[i]
        stripped = line.strip()
        if not stripped:
            flush_paragraph()
            i += 1
            continue

        table_end = _table_block_end(lines, i)
        if table_end:
            flush_paragraph()
            html_parts.append(_render_table(lines[i:table_end]))
            i = table_end
            continue

        if _is_unordered_item(stripped):
            flush_paragraph()
            items, i = _consume_list(lines, i, ordered=False)
            html_parts.append(_render_list(items, ordered=False))
            continue

        if _is_ordered_item(stripped):
            flush_paragraph()
            items, i = _consume_list(lines, i, ordered=True)
            html_parts.append(_render_list(items, ordered=True))
            continue

        paragraph.append(stripped)
        i += 1

    flush_paragraph()
    return mark_safe('\n'.join(html_parts))


def _coerce_datetime(value) -> datetime | None:
    if isinstance(value, datetime):
        return value
    if isinstance(value, str):
        return parse_datetime(value)
    return None


def _inline_md(text: str) -> str:
    escaped = html.escape(text, quote=False)
    escaped = re.sub(r'`([^`]+)`', r'<code>\1</code>', escaped)
    escaped = re.sub(r'\*\*([^*]+)\*\*', r'<strong>\1</strong>', escaped)
    return escaped


def _split_table_row(line: str) -> list[str]:
    return [cell.strip() for cell in line.strip().strip('|').split('|')]


def _is_separator_row(line: str) -> bool:
    cells = _split_table_row(line)
    if not cells:
        return False
    return all(re.fullmatch(r':?-{3,}:?', cell.replace(' ', '')) for cell in cells)


def _looks_like_table_row(line: str) -> bool:
    return line.count('|') >= 2


def _table_block_end(lines: list[str], start: int) -> int | None:
    if start + 1 >= len(lines):
        return None
    if not _looks_like_table_row(lines[start]):
        return None
    if not _is_separator_row(lines[start + 1]):
        return None
    end = start + 2
    while end < len(lines) and _looks_like_table_row(lines[end]):
        end += 1
    return end


def _render_table(lines: list[str]) -> str:
    header = _split_table_row(lines[0])
    rows = [_split_table_row(line) for line in lines[2:]]
    head_html = ''.join(f'<th>{_inline_md(cell)}</th>' for cell in header)
    body_rows = []
    for row in rows:
        if len(row) < len(header):
            row = row + [''] * (len(header) - len(row))
        cells = ''.join(f'<td>{_inline_md(cell)}</td>' for cell in row[:len(header)])
        body_rows.append(f'<tr>{cells}</tr>')
    return (
        '<div class="report-md-table-wrap">'
        '<table class="report-md-table">'
        f'<thead><tr>{head_html}</tr></thead>'
        f'<tbody>{"".join(body_rows)}</tbody>'
        '</table>'
        '</div>'
    )


def _is_unordered_item(line: str) -> bool:
    return bool(re.match(r'^(?:[-*•])\s+', line))


def _is_ordered_item(line: str) -> bool:
    return bool(re.match(r'^\d+[.)]\s+', line))


def _consume_list(lines: list[str], start: int, *, ordered: bool) -> tuple[list[str], int]:
    items: list[str] = []
    i = start
    pattern = r'^\d+[.)]\s+' if ordered else r'^(?:[-*•])\s+'
    while i < len(lines):
        stripped = lines[i].strip()
        if not re.match(pattern, stripped):
            break
        items.append(re.sub(pattern, '', stripped, count=1).strip())
        i += 1
    return items, i


def _render_list(items: Iterable[str], *, ordered: bool) -> str:
    tag = 'ol' if ordered else 'ul'
    body = ''.join(f'<li>{_inline_md(item)}</li>' for item in items)
    return f'<{tag}>{body}</{tag}>'
