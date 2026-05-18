from django.utils import timezone
from chat.services.prompt_loader import load_prompt

# 세션에 저장할 대화 히스토리 키
SESSION_HISTORY_KEY = 'chat_history'

# v0.5.6 — 문제 제보용 별도 스냅샷 세션 키. chat_history 와 분리.
SESSION_REPORT_SNAPSHOT_KEY = 'problem_report_snapshot'

# 보고용 스냅샷 캡 정책
REPORT_MAX_MESSAGES = 100         # user/assistant 각 1개씩 카운트
REPORT_CONTENT_MAX_CHARS = 8000   # 각 메시지 content 캡
REPORT_SOURCE_FIELD_MAX = 500     # sources[i] 의 각 문자열 값 캡

# 대화 히스토리 최대 턴 수 (유저+어시스턴트 합산)
# 너무 길어지면 토큰 비용이 늘고 오래된 맥락이 희석되므로 적당히 자름
MAX_HISTORY_MESSAGES = 20

def initial_history():
    return [{'role': 'system', 'content': load_prompt('chat/system.md')}]


def get_history(request):
    return request.session.get(SESSION_HISTORY_KEY, [])


def save_history(request, history):
    # 최근 N개만 유지 (시스템 프롬프트는 매 요청마다 앞에 붙이므로 히스토리에는 미포함)
    request.session[SESSION_HISTORY_KEY] = history[-MAX_HISTORY_MESSAGES:]
    request.session.modified = True

def clear_history(request):
    request.session[SESSION_HISTORY_KEY] = []
    request.session.modified = True


# ---------------------------------------------------------------------------
# v0.5.6 — 문제 제보용 스냅샷 헬퍼
# ---------------------------------------------------------------------------

def _cap_text(s, limit):
    if s is None:
        return ''
    s = str(s)
    if len(s) > limit:
        return s[: max(0, limit - 1)] + '…'
    return s


def _sanitize_sources(sources):
    if not isinstance(sources, list):
        return []
    cleaned = []
    for src in sources:
        if not isinstance(src, dict):
            continue
        name = _cap_text(src.get('name'), REPORT_SOURCE_FIELD_MAX)
        url = _cap_text(src.get('url'), REPORT_SOURCE_FIELD_MAX)
        if not name and not url:
            continue
        cleaned.append({'name': name, 'url': url})
    return cleaned


def get_report_snapshot(request):
    return request.session.get(SESSION_REPORT_SNAPSHOT_KEY, [])


def clear_report_snapshot(request):
    if SESSION_REPORT_SNAPSHOT_KEY in request.session:
        del request.session[SESSION_REPORT_SNAPSHOT_KEY]
        request.session.modified = True


def append_report_snapshot_turn(request, user_text, result):
    """`/message/` 의 run_chat_graph 정상 반환 직후 1회 호출.

    `result` 는 `QueryResult` dataclass 인스턴스. 속성 접근으로 reply/sources/chat_log_id 사용.
    """
    snapshot = list(get_report_snapshot(request))
    ts = timezone.localtime(timezone.now()).isoformat()
    snapshot.append({
        'role': 'user',
        'content': user_text or '',
        'ts': ts,
    })
    assistant_msg = {
        'role': 'assistant',
        'content': result.reply or '',
        'sources': result.sources or [],
        'chat_log_id': result.chat_log_id,
        'ts': ts,
    }
    snapshot.append(assistant_msg)
    # 캡 적용은 sanitize 에 위임
    request.session[SESSION_REPORT_SNAPSHOT_KEY] = sanitize_report_snapshot(snapshot)
    request.session.modified = True


def sanitize_report_snapshot(snapshot):
    """이미 캡처된 보고 메시지 리스트를 정규화한다.

    - system / 빈 message 제외
    - content 길이 캡 (말미 `…`)
    - sources 의 문자열 값 길이 캡
    - 메시지 100개 초과 시 앞쪽 트림
    - 알 수 없는 키는 그대로 두지 않고 화이트리스트만 보존
    """
    if not isinstance(snapshot, list):
        return []
    cleaned = []
    for msg in snapshot:
        if not isinstance(msg, dict):
            continue
        role = msg.get('role')
        if role not in ('user', 'assistant'):
            continue
        content = msg.get('content') or ''
        content = str(content).strip()
        if not content:
            continue
        item = {
            'role': role,
            'content': _cap_text(content, REPORT_CONTENT_MAX_CHARS),
            'ts': msg.get('ts') or '',
        }
        if role == 'assistant':
            item['sources'] = _sanitize_sources(msg.get('sources') or [])
            if 'chat_log_id' in msg:
                item['chat_log_id'] = msg.get('chat_log_id')
        cleaned.append(item)
    if len(cleaned) > REPORT_MAX_MESSAGES:
        cleaned = cleaned[-REPORT_MAX_MESSAGES:]
    return cleaned
