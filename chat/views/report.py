"""v0.5.6 — POST /report/ 엔드포인트.

채팅 화면 모달이 호출. 페이로드는 `{title, content}` 만 받고, 대화 스냅샷은
서버 세션의 `problem_report_snapshot` (별도 누적분) 만 사용한다.
이 뷰는 chat_history / problem_report_snapshot 어느 쪽도 변경하지 않는다.
"""

import json

from django.http import JsonResponse
from django.views.decorators.http import require_http_methods

from chat.models import ProblemReport
from chat.services.history_service import (
    get_report_snapshot,
    sanitize_report_snapshot,
)


TITLE_MAX = 120
CONTENT_MAX = 4000
LAST_QUESTION_MAX = 500


@require_http_methods(['POST'])
def problem_report(request):
    try:
        body = json.loads(request.body.decode('utf-8'))
    except (ValueError, UnicodeDecodeError):
        return JsonResponse({'error': 'invalid_json'}, status=400)

    if not isinstance(body, dict):
        return JsonResponse({'error': 'invalid_json'}, status=400)

    title = (body.get('title') or '').strip()
    content = (body.get('content') or '').strip()

    if not title or len(title) > TITLE_MAX:
        return JsonResponse({'error': 'title_required'}, status=400)
    if not content or len(content) > CONTENT_MAX:
        return JsonResponse({'error': 'content_required'}, status=400)

    snapshot = sanitize_report_snapshot(get_report_snapshot(request))

    last_question = ''
    for msg in reversed(snapshot):
        if msg.get('role') == 'user':
            last_question = (msg.get('content') or '')[:LAST_QUESTION_MAX]
            break

    session_key = request.session.session_key or ''
    if not session_key:
        request.session.save()
        session_key = request.session.session_key or ''

    report = ProblemReport.objects.create(
        title=title,
        content=content,
        session_key=session_key,
        last_question=last_question,
        conversation=snapshot,
        turn_count=len(snapshot),
    )
    return JsonResponse({'ok': True, 'id': report.id})
