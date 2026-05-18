"""POST /report/ 엔드포인트 + /message/ /reset/ 통합 테스트 (v0.5.6)."""

import json
from unittest.mock import patch

from django.test import Client, TestCase
from django.urls import reverse

from chat.models import ProblemReport
from chat.services.history_service import (
    SESSION_HISTORY_KEY,
    SESSION_REPORT_SNAPSHOT_KEY,
)
from chat.services.single_shot.types import QueryResult


def _mock_result(reply='answer', sources=None, chat_log_id=99):
    return QueryResult(
        reply=reply,
        sources=sources if sources is not None else [{'name': 'doc.pdf', 'url': '/u'}],
        total_tokens=5,
        chat_log_id=chat_log_id,
    )


class MessageIntegrationTests(TestCase):
    @patch('chat.views.message.run_chat_graph')
    def test_message_appends_to_report_snapshot_and_chat_history(self, mock_run):
        mock_run.return_value = _mock_result(reply='Hi', sources=[{'name': 'a', 'url': 'b'}], chat_log_id=10)
        res = self.client.post(
            reverse('chat:message'),
            data=json.dumps({'message': 'Hello?'}),
            content_type='application/json',
        )
        self.assertEqual(res.status_code, 200)
        session = self.client.session
        snap = session.get(SESSION_REPORT_SNAPSHOT_KEY)
        self.assertIsNotNone(snap)
        self.assertEqual(len(snap), 2)
        self.assertEqual(snap[0]['role'], 'user')
        self.assertEqual(snap[0]['content'], 'Hello?')
        self.assertEqual(snap[1]['role'], 'assistant')
        self.assertEqual(snap[1]['content'], 'Hi')
        self.assertEqual(snap[1]['sources'], [{'name': 'a', 'url': 'b'}])
        self.assertEqual(snap[1]['chat_log_id'], 10)
        # chat_history 도 정상 갱신 (회귀)
        ch = session.get(SESSION_HISTORY_KEY)
        self.assertEqual(ch[-2], {'role': 'user', 'content': 'Hello?'})
        self.assertEqual(ch[-1], {'role': 'assistant', 'content': 'Hi'})

    @patch('chat.views.message.run_chat_graph')
    def test_reset_clears_both_history_and_snapshot(self, mock_run):
        mock_run.return_value = _mock_result()
        self.client.post(
            reverse('chat:message'),
            data=json.dumps({'message': 'q'}),
            content_type='application/json',
        )
        session = self.client.session
        self.assertTrue(session.get(SESSION_HISTORY_KEY))
        self.assertTrue(session.get(SESSION_REPORT_SNAPSHOT_KEY))

        self.client.post(reverse('chat:reset'))
        session = self.client.session
        self.assertEqual(session.get(SESSION_HISTORY_KEY), [])
        self.assertIsNone(session.get(SESSION_REPORT_SNAPSHOT_KEY))


class ReportEndpointTests(TestCase):
    @patch('chat.views.message.run_chat_graph')
    def test_successful_report_uses_server_snapshot(self, mock_run):
        mock_run.return_value = _mock_result(reply='Ans', chat_log_id=5)
        self.client.post(
            reverse('chat:message'),
            data=json.dumps({'message': 'why?'}),
            content_type='application/json',
        )

        # 클라이언트가 conversation 을 보내도 무시되어야 함.
        res = self.client.post(
            reverse('chat:problem_report'),
            data=json.dumps({
                'title': '문제있음',
                'content': '답변이 이상합니다',
                'conversation': [{'role': 'user', 'content': '클라이언트 위조'}],
            }),
            content_type='application/json',
        )
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertTrue(data['ok'])
        r = ProblemReport.objects.get(pk=data['id'])
        self.assertEqual(r.title, '문제있음')
        self.assertEqual(r.turn_count, 2)
        self.assertEqual(len(r.conversation), 2)
        self.assertEqual(r.conversation[0]['content'], 'why?')
        # 클라이언트 위조 내용은 저장 안 됨
        self.assertNotIn('위조', json.dumps(r.conversation, ensure_ascii=False))
        self.assertEqual(r.last_question, 'why?')

    def test_empty_snapshot_session_still_ok(self):
        res = self.client.post(
            reverse('chat:problem_report'),
            data=json.dumps({'title': 't', 'content': 'c'}),
            content_type='application/json',
        )
        self.assertEqual(res.status_code, 200)
        r = ProblemReport.objects.get(pk=res.json()['id'])
        self.assertEqual(r.conversation, [])
        self.assertEqual(r.last_question, '')
        self.assertEqual(r.turn_count, 0)

    def test_empty_title_returns_400(self):
        res = self.client.post(
            reverse('chat:problem_report'),
            data=json.dumps({'title': '   ', 'content': 'c'}),
            content_type='application/json',
        )
        self.assertEqual(res.status_code, 400)
        self.assertEqual(res.json()['error'], 'title_required')

    def test_content_too_long_returns_400(self):
        res = self.client.post(
            reverse('chat:problem_report'),
            data=json.dumps({'title': 't', 'content': 'x' * 4001}),
            content_type='application/json',
        )
        self.assertEqual(res.status_code, 400)
        self.assertEqual(res.json()['error'], 'content_required')

    def test_invalid_json_returns_400(self):
        res = self.client.post(
            reverse('chat:problem_report'),
            data='not json',
            content_type='application/json',
        )
        self.assertEqual(res.status_code, 400)
        self.assertEqual(res.json()['error'], 'invalid_json')

    def test_get_returns_405(self):
        res = self.client.get(reverse('chat:problem_report'))
        self.assertEqual(res.status_code, 405)

    def test_csrf_required_with_enforce(self):
        # Django 기본 Client 는 CSRF 검사를 우회하므로 enforce_csrf_checks=True 로
        # 명시. CSRF 차단 시 4xx 응답이 떨어지는지만 본다(실패 템플릿 렌더 환경
        # 의존성 회피 위해 raise_request_exception=False).
        c = Client(enforce_csrf_checks=True, raise_request_exception=False)
        res = c.post(
            reverse('chat:problem_report'),
            data=json.dumps({'title': 't', 'content': 'c'}),
            content_type='application/json',
        )
        # CSRF 미포함 → 403 이 정상. 환경에 따라 500(템플릿) 으로 잡힐 수 있어
        # 4xx/5xx 양쪽을 허용하되 정상 200 만 아니면 된다.
        self.assertNotEqual(res.status_code, 200)

    @patch('chat.views.message.run_chat_graph')
    def test_report_does_not_mutate_history_or_snapshot(self, mock_run):
        mock_run.return_value = _mock_result()
        self.client.post(
            reverse('chat:message'),
            data=json.dumps({'message': 'q1'}),
            content_type='application/json',
        )
        before_history = self.client.session.get(SESSION_HISTORY_KEY)
        before_snap = self.client.session.get(SESSION_REPORT_SNAPSHOT_KEY)

        self.client.post(
            reverse('chat:problem_report'),
            data=json.dumps({'title': 't', 'content': 'c'}),
            content_type='application/json',
        )
        after_history = self.client.session.get(SESSION_HISTORY_KEY)
        after_snap = self.client.session.get(SESSION_REPORT_SNAPSHOT_KEY)
        self.assertEqual(before_history, after_history)
        self.assertEqual(before_snap, after_snap)
