"""문제 제보 스냅샷 헬퍼 단위 테스트 (v0.5.6 Issue #94)."""

from django.test import RequestFactory, TestCase
from django.contrib.sessions.middleware import SessionMiddleware

from chat.services.history_service import (
    SESSION_REPORT_SNAPSHOT_KEY,
    append_report_snapshot_turn,
    clear_report_snapshot,
    get_report_snapshot,
    sanitize_report_snapshot,
)
from chat.services.single_shot.types import QueryResult


def _make_request():
    rf = RequestFactory()
    req = rf.post('/message/')
    mw = SessionMiddleware(lambda r: None)
    mw.process_request(req)
    req.session.save()
    return req


def _result(reply='hello', sources=None, chat_log_id=7):
    return QueryResult(
        reply=reply,
        sources=sources if sources is not None else [{'name': 'a.pdf', 'url': '/a'}],
        total_tokens=10,
        chat_log_id=chat_log_id,
    )


class SnapshotHelpersTests(TestCase):
    def test_append_uses_dataclass_attributes(self):
        req = _make_request()
        result = _result(reply='answer', sources=[{'name': 'x', 'url': 'y'}], chat_log_id=42)
        append_report_snapshot_turn(req, 'question?', result)
        snap = get_report_snapshot(req)
        self.assertEqual(len(snap), 2)
        self.assertEqual(snap[0]['role'], 'user')
        self.assertEqual(snap[0]['content'], 'question?')
        self.assertEqual(snap[1]['role'], 'assistant')
        self.assertEqual(snap[1]['content'], 'answer')
        self.assertEqual(snap[1]['sources'], [{'name': 'x', 'url': 'y'}])
        self.assertEqual(snap[1]['chat_log_id'], 42)

    def test_sanitize_drops_system_and_empty(self):
        cleaned = sanitize_report_snapshot([
            {'role': 'system', 'content': 'secret'},
            {'role': 'user', 'content': ''},
            {'role': 'user', 'content': '   '},
            {'role': 'user', 'content': 'real'},
        ])
        self.assertEqual(len(cleaned), 1)
        self.assertEqual(cleaned[0]['content'], 'real')

    def test_sanitize_caps_content_at_8000_chars(self):
        big = 'x' * 9000
        cleaned = sanitize_report_snapshot([
            {'role': 'user', 'content': big},
        ])
        self.assertEqual(len(cleaned[0]['content']), 8000)
        self.assertTrue(cleaned[0]['content'].endswith('…'))

    def test_sanitize_caps_source_strings(self):
        big = 'u' * 600
        cleaned = sanitize_report_snapshot([
            {'role': 'assistant', 'content': 'a', 'sources': [{'name': big, 'url': big}]},
        ])
        src = cleaned[0]['sources'][0]
        self.assertEqual(len(src['name']), 500)
        self.assertEqual(len(src['url']), 500)
        self.assertTrue(src['name'].endswith('…'))

    def test_sanitize_caps_at_100_messages_from_front(self):
        msgs = [{'role': 'user', 'content': f'm{i}'} for i in range(150)]
        cleaned = sanitize_report_snapshot(msgs)
        self.assertEqual(len(cleaned), 100)
        # 앞쪽 폐기 → 가장 오래된 50개 사라짐, m50~m149 남음
        self.assertEqual(cleaned[0]['content'], 'm50')
        self.assertEqual(cleaned[-1]['content'], 'm149')

    def test_sanitize_empty(self):
        self.assertEqual(sanitize_report_snapshot([]), [])

    def test_clear_report_snapshot(self):
        req = _make_request()
        append_report_snapshot_turn(req, 'q', _result())
        self.assertTrue(req.session.get(SESSION_REPORT_SNAPSHOT_KEY))
        clear_report_snapshot(req)
        self.assertNotIn(SESSION_REPORT_SNAPSHOT_KEY, req.session)

    def test_sanitize_sources_whitelists_name_and_url_only(self):
        cleaned = sanitize_report_snapshot([
            {
                'role': 'assistant',
                'content': 'a',
                'sources': [
                    {
                        'name': 'doc.pdf',
                        'url': '/d',
                        'score': 0.92,
                        'snippet': 'should be removed',
                        'secret': 'nope',
                    },
                ],
            },
        ])
        src = cleaned[0]['sources'][0]
        self.assertEqual(set(src.keys()), {'name', 'url'})
        self.assertEqual(src['name'], 'doc.pdf')
        self.assertEqual(src['url'], '/d')

    def test_sanitize_sources_skips_when_name_and_url_both_empty(self):
        cleaned = sanitize_report_snapshot([
            {
                'role': 'assistant',
                'content': 'a',
                'sources': [
                    {'score': 0.5, 'snippet': 'x'},
                    {'name': '', 'url': ''},
                    {'name': 'only-name'},
                    {'url': '/only-url'},
                ],
            },
        ])
        srcs = cleaned[0]['sources']
        self.assertEqual(srcs, [
            {'name': 'only-name', 'url': ''},
            {'name': '', 'url': '/only-url'},
        ])

    def test_assistant_handles_empty_sources_and_null_chat_log_id(self):
        req = _make_request()
        result = QueryResult(reply='r', sources=[], total_tokens=0, chat_log_id=None)
        append_report_snapshot_turn(req, 'q', result)
        snap = get_report_snapshot(req)
        self.assertEqual(snap[1]['sources'], [])
        self.assertIsNone(snap[1]['chat_log_id'])
