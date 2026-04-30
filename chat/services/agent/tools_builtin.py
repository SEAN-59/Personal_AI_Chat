"""Agent 도구 등록.

  - `retrieve_documents` — Phase 6-3 와 같은 reranker 포함 retrieval. schema 모드.
  - `find_canonical_qa` — 과거 승격된 Q&A 임베딩 검색. schema 모드.
  - `run_workflow` — 등록된 generic workflow 를 그대로 실행. raw 모드 (입력 형태가
    `workflow_key` 마다 달라서 schema 로 강제할 수 없음).
  - `weekday_of` / `is_business_day` / `next_business_day` (v0.4.2, 이슈 #73) —
    한국 달력 기준 요일·영업일 판단. 자료 안의 "토/공휴일이면 익일" 류 조건절을
    실제 날짜에 적용할 때 agent 가 호출.

각 도구는 callable 결과를 LLM 이 다시 보기 좋은 짧은 한국어 한두 줄로 요약한다.
원본 응답 전체를 다음 iteration 에 올리지 않는다 — 컨텍스트 폭주 방지.
"""

from __future__ import annotations

import re
import string
from datetime import date, datetime, timedelta
from typing import Any, List, Mapping

import holidays

from chat.services.agent.tools import Tool, register
from chat.services.single_shot.qa_cache import find_canonical_qa as _qa_cache_find
from chat.services.single_shot.retrieval import retrieve_documents as _retrieve
from chat.workflows.core import WorkflowResult
from chat.workflows.domains import dispatch as _workflow_dispatch
from chat.workflows.domains.field_spec import FieldSpec


# ---------------------------------------------------------------------------
# Phase 7-3: query-focused snippet windowing helpers
# ---------------------------------------------------------------------------

# 토큰 양 끝에 흔히 붙는 문장부호 — strip 대상.
# ASCII punctuation + 한국어 콤마/물음표/문장 부호.
_TOKEN_STRIP_CHARS = string.punctuation + '·、，。？！'

# 한국어 1자 조사/어미/단일 stopword 제거. 영문은 'a', 'I' 등 단일 문자도 같은 이유로 컷.
_KEYWORD_MIN_LEN = 2

# Phase 7-4: relevance 마커 판정에서 제외할 일반 토큰. windowing 매치는 이 토큰도
# 후보로 쓰지만 (자리 잡기에는 유용), 관련성 신호로는 부족 — 짧은 의문/비교/요청
# 표현이 우연히 매치돼 false relevant 가 되는 회귀 차단용.
#
# Phase 8-4: 시간/단위 단어 추가 (`년` `월` `일` `시` ...). 시나리오 A''' 의
# `2025년 1월 1일부터 100일 후 날짜는?` 같은 query 가 시간 토큰만 의미 토큰으로
# 남아 임의 PDF 와 매치하던 false positive 차단. `날짜` / `기간` 도 추가 — 도메인
# 명사가 아니라 일반 시간 표현.
_LOW_SIGNAL_TOKENS = frozenset({
    # 비교/연산 의도
    '비교', '차이', '차이점', '대비',
    # 의문/요청
    '얼마', '얼마나', '뭐야', '뭔가', '뭔가요', '어떤', '어떻게', '있나', '있나요',
    '알려', '알려줘', '말해', '말해줘',
    # 일반 지시
    '관련', '대해', '대한',
    # 시간/단위 일반어 (Phase 8-4)
    '년', '월', '일', '시', '분', '초', '주', '개월', '분기', '반기', '시간', '기간', '날짜',
    # 영문 일반어
    'compare', 'difference', 'about', 'what', 'how',
})


# Phase 8-4: 한국어 자주 쓰이는 조사/접미. 모든 시간·수량 regex 패턴에 부착해
# `1일부터` / `100일까지` / `날짜는` 같이 조사 붙은 토큰도 잡는다. `_tokenize_query`
# 가 조사 분리를 안 하므로 여기서 패턴 차원에서 흡수.
_PARTICLE_SUFFIX = r'(은|는|이|가|을|를|에|의|도|만|로|으로|부터|까지)?'

# Phase 8-4: 숫자+단위 + 조사 suffix 일반화. enumeration 으로는 `2025년` / `1년` /
# `100년` 모두 등록 못 하므로 regex 로. anchor `^...$` 로 부분 매치 방지 (`30년근속`
# 같은 도메인 명사는 의미 토큰 그대로 인정).
_LOW_SIGNAL_PATTERNS: tuple[re.Pattern, ...] = tuple(
    re.compile(p) for p in (
        rf'^\d+년{_PARTICLE_SUFFIX}$',
        rf'^\d+월{_PARTICLE_SUFFIX}$',
        rf'^\d+일{_PARTICLE_SUFFIX}$',
        rf'^\d+시{_PARTICLE_SUFFIX}$',
        rf'^\d+분{_PARTICLE_SUFFIX}$',
        rf'^\d+초{_PARTICLE_SUFFIX}$',
        rf'^\d+(개월|주|분기|반기|시간){_PARTICLE_SUFFIX}$',
        rf'^\d+(원|만원|억|조){_PARTICLE_SUFFIX}$',
        # `날짜` / `기간` 의 조사 일반화 — `_LOW_SIGNAL_TOKENS` 의 base 단어가
        # 이미 들어있어도 `날짜는` 같은 변형은 멤버십으로 못 잡음.
        rf'^날짜{_PARTICLE_SUFFIX}$',
        rf'^기간{_PARTICLE_SUFFIX}$',
    )
)


def _is_low_signal(token: str) -> bool:
    """Phase 8-4: 토큰이 low-signal 인지 판정.

    `_LOW_SIGNAL_TOKENS` 멤버십 OR `_LOW_SIGNAL_PATTERNS` 매치 둘 중 하나면 True.
    `_has_meaningful_match` 가 직접 멤버십 검사 대신 본 helper 호출.
    """
    if token.lower() in _LOW_SIGNAL_TOKENS:
        return True
    for pattern in _LOW_SIGNAL_PATTERNS:
        if pattern.match(token):
            return True
    return False


def _tokenize_query(query: str) -> List[str]:
    """Query 를 윈도우 매칭용 토큰으로 분리 (Phase 7-3).

    - 공백 split.
    - 토큰 양 끝 punctuation strip (`결혼?` → `결혼`, `"경조금"` → `경조금`).
    - 길이 ≥ 2 만 유지.
    - **길이 내림차순 정렬** — 긴 토큰일수록 도메인 키워드일 확률이 높음.
      매치 시 긴 토큰 위치 우선 → 일반 토큰 ("비교", "있는", "하는") 이 청크
      앞부분에 우연히 걸려 관련 없는 윈도우를 고르는 회귀 차단.

    한국어 형태소 분석기 (KoNLPy / Mecab) 미도입 — 의존성 비용 vs 효용. 운영
    데이터에서 부족이 입증되면 후속 Phase 에서 검토.
    """
    if not query:
        return []
    tokens: List[str] = []
    for raw in query.split():
        cleaned = raw.strip(_TOKEN_STRIP_CHARS)
        if len(cleaned) >= _KEYWORD_MIN_LEN:
            tokens.append(cleaned)
    # Python sort 는 stable — 같은 길이 토큰은 입력 순서 유지.
    tokens.sort(key=len, reverse=True)
    return tokens


def _earliest_match(content: str, query: str) -> int:
    """**Windowing 용** 매치 위치. 모든 토큰 (low-signal 포함) 후보. 미매치 -1.

    7-3 의 _focus_window 매치 정책 그대로 — 자리 잡기에 쓰이는 매치라 일반
    토큰 ("비교") 도 위치 후보가 됨. 관련성 신호로는 약하지만 windowing 정확도는
    유지. 관련성 마커 판정은 별도의 `_has_meaningful_match` 가 담당.
    """
    if not content or not query:
        return -1
    tokens = _tokenize_query(query)
    if not tokens:
        return -1
    lower = content.lower()
    for token in tokens:
        idx = lower.find(token.lower())
        if idx >= 0:
            return idx
    return -1


def _has_meaningful_match(content: str, query: str) -> bool:
    """**Relevance 마커 용** strict 판정 — 가장 긴 의미 토큰 (또는 동률 tier) 매치 요구 (Phase 7-4).

    1) low-signal 토큰 (`비교`, `얼마` 등) 제외.
    2) 남은 의미 토큰 중 **가장 긴 길이의 토큰들** (max_len 같으면 tier 전체) 만
       매치 후보로 사용. 그 중 하나라도 청크에 있으면 True.

    이게 더 느슨한 정책 ('의미 토큰 하나라도 매치') 보다 엄격한 이유는, 짧은
    의미 토큰 (예: `비용`) 이 다른 도메인 청크에 우연히 들어있어도 정작 핵심
    도메인 명사 (`우주여행`) 가 미매치면 False relevant 가 되어 무한 retrieve
    회로가 남기 때문 (Phase 7-3 smoke 의 Defect 1 query 변형).

    동률 max_len 토큰이 여러 개일 때는 그 중 하나라도 매치되면 True (`결혼 휴가`
    처럼 둘 다 2자인 query 에서 한쪽만 청크에 있어도 인정).

    알려진 한계: 동률 tier 중 하나가 일반 도메인 단어일 때 false relevant 발생
    가능 (`우주여행 프로그램 비교` 의 `프로그램` 이 다른 도메인에 우연히 매치).
    이 회귀는 Part 3 의 `MAX_LOW_RELEVANCE_RETRIEVES=3` 누적 가드가 보완.

    query 가 모두 low-signal 이면 (예: '비교', '알려줘만') False — 정보량 부족.
    """
    if not content or not query:
        return False
    tokens = _tokenize_query(query)
    meaningful = [t for t in tokens if not _is_low_signal(t)]
    if not meaningful:
        return False
    max_len = len(meaningful[0])  # tokens already sorted len desc
    longest_tier = [t for t in meaningful if len(t) == max_len]
    lower = content.lower()
    for token in longest_tier:
        if lower.find(token.lower()) >= 0:
            return True
    return False


def _focus_window(content: str, query: str, *, length: int) -> str:
    """Query 키워드 매치 위치 주변 forward-bias 윈도우. 미매치면 첫 N자 fallback.

    윈도우 정책: 매치 위치 기준 앞 1/4 + 뒤 3/4. `start = max(0, earliest -
    length//4)` 의 자연 클램프 덕분에 매치가 청크 매우 앞 (`< length//4`) 이면
    자동으로 `start=0` → 첫 N자 출력 = 7-2 fallback 과 byte-identical.

    Phase 7-4: 매치 위치 계산은 `_earliest_match` 로 추출 — 외부 시그니처 / 동작
    변경 0 (7-3 단위 테스트 17건 그대로 통과).
    """
    if not content:
        return ''
    if len(content) <= length:
        return content
    earliest = _earliest_match(content, query)
    if earliest < 0:
        return content[:length] + '…'

    # forward-bias: 앞 1/4 + 뒤 3/4. 표 행은 매치 위치 다음에 값/단위가 옴.
    pre = length // 4
    start = max(0, earliest - pre)
    end = min(len(content), start + length)
    # content 끝에 닿으면 start 를 뒤로 당겨 윈도우 길이 보존.
    start = max(0, end - length)

    snippet = content[start:end]
    prefix = '…' if start > 0 else ''
    suffix = '…' if end < len(content) else ''
    return prefix + snippet + suffix


# ---------------------------------------------------------------------------
# retrieve_documents
# ---------------------------------------------------------------------------

def _retrieve_callable(arguments: Mapping[str, Any]) -> dict:
    """retrieve_documents tool callable.

    Phase 7-3 부터 반환을 `{'query': ..., 'hits': [...]}` dict 로 감싼다 — query
    를 `_summarize_retrieve` 까지 흘려 keyword-aware windowing 을 가능하게 하기
    위한 우회. `Tool.summarize: Callable[[Any], str]` 시그니처는 그대로 둬서 다른
    도구 / 외부 코드 영향 없음.

    Phase 8-1: 결과 dict 에 `'evidence': [SourceRef]` 키 추가 — `tools.call` 이
    이 키를 보고 `Observation.evidence` 로 부착. **`hits[0]` 한 건만** evidence
    후보 (top-N=5 다 노출하면 sources 폭주, P2-2 단일 정책).
    """
    from chat.services.agent.result import SourceRef

    query = arguments['query']
    hits = _retrieve(query)
    evidence = []
    if hits:
        first = hits[0]
        evidence.append(SourceRef(
            name=getattr(first, 'document_name', None) or '(출처 미상)',
            url=getattr(first, 'document_url', None) or '',
        ))
    return {
        'query': query,
        'hits': hits,
        'evidence': evidence,
    }


_RETRIEVE_TOP_N = 3
# Phase 7-2 smoke: 180자는 표 헤더 정도밖에 못 담아 LLM 이 본문을 못 봄. 400자면
# 표 4~6 행 / 두세 단락이 들어가 비교형 질문에 답을 만들 수 있다. Phase 7-3 부터는
# 이 400자가 청크 첫 N자가 아니라 query 키워드 매치 위치 주변의 윈도우 길이 — 즉
# 위치는 가변, 길이만 고정.
_RETRIEVE_SNIPPET_LEN = 400


def _summarize_retrieve(result: Any) -> str:
    """top N 청크의 출처 + query 키워드 주변 윈도우 + 관련성 마커 (Phase 7-3 / 7-4).

    Phase 7-4 부터:
    - hit 별로 `_has_meaningful_match` 가 False (longest meaningful token 미매치)
      이면 출처 앞에 `[관련성 낮음] ` prefix.
    - 모든 hit 가 미매치면 summary 머리에 `[query 핵심 토큰 매치 없음 — 관련 자료
      부족 가능성]` 라인 추가.
    LLM 이 무관 결과 / 핵심 토큰 부재를 가시적으로 보고 final_answer 로 종료할
    수 있게.

    `result` 는 `_retrieve_callable` 이 만든 `{'query': ..., 'hits': [...]}` dict.
    """
    query = (result or {}).get('query') or ''
    hits = (result or {}).get('hits') or []
    if not hits:
        return '검색 결과 없음 (0건)'

    parts = [f'{len(hits)}건 검색됨:']
    meaningful_count = 0
    for idx, hit in enumerate(hits[:_RETRIEVE_TOP_N], start=1):
        name = getattr(hit, 'document_name', None) or '(출처 미상)'
        content = (getattr(hit, 'content', '') or '').replace('\n', ' ').strip()
        snippet = _focus_window(content, query, length=_RETRIEVE_SNIPPET_LEN)
        relevant = _has_meaningful_match(content, query)
        if relevant:
            meaningful_count += 1
        prefix = '' if relevant else '[관련성 낮음] '
        parts.append(f'[{idx}] {prefix}{name}: "{snippet}"')

    if meaningful_count == 0:
        # 모든 hit 가 의미 토큰 미매치 — 머리에 강한 신호.
        parts.insert(1, '[query 핵심 토큰 매치 없음 — 관련 자료 부족 가능성]')

    if len(hits) > _RETRIEVE_TOP_N:
        parts.append(f'(이하 {len(hits) - _RETRIEVE_TOP_N}건 생략)')
    return ' '.join(parts)


# ---------------------------------------------------------------------------
# find_canonical_qa
# ---------------------------------------------------------------------------

def _qa_callable(arguments: Mapping[str, Any]) -> list:
    return _qa_cache_find(arguments['query'])


def _summarize_qa(hits: Any) -> str:
    if not hits:
        return '과거 Q&A 일치 없음 (0건)'
    top = hits[0]
    return (
        f'{len(hits)}건, top similarity={top.similarity:.3f} — '
        f'질문: "{top.question[:60]}..."'
    )


# ---------------------------------------------------------------------------
# run_workflow
# ---------------------------------------------------------------------------

def _workflow_callable(arguments: Mapping[str, Any]) -> WorkflowResult:
    workflow_key = arguments.get('workflow_key') or ''
    workflow_input = arguments.get('input') or {}
    return _workflow_dispatch.run(workflow_key, workflow_input)


def _summarize_workflow(result: Any) -> str:
    """`WorkflowResult` 의 status 와 핵심 값만 한 줄로 요약."""
    if not isinstance(result, WorkflowResult):
        return f'예상치 못한 응답 형식: {type(result).__name__}'
    status = result.status.value
    if result.value is not None:
        return f'status={status}, value={_short_value(result.value)}'
    reason = ''
    if result.details and 'reason' in result.details:
        reason = str(result.details['reason'])[:120]
    if result.missing_fields:
        return f'status={status}, missing={list(result.missing_fields)}'
    return f'status={status}, {reason}' if reason else f'status={status}'


def _short_value(value: Any) -> str:
    if isinstance(value, (int, float, bool)):
        return str(value)
    text = str(value)
    return text if len(text) <= 80 else text[:79] + '…'


def _retrieve_failure_check(result: Any) -> bool:
    """retrieve_documents 가 진전 없음 신호 — 'low_relevance' failure_kind 카운터용 (Phase 7-4).

    True 조건:
    - 0건: "no useful evidence" — all-low-relevance 와 동일 의미로 통합.
    - 모든 hit 가 `_has_meaningful_match=False`: longest meaningful token 미매치.

    False (= success) 조건:
    - 적어도 한 hit 가 의미 토큰 매치.
    """
    query = (result or {}).get('query') or ''
    hits = (result or {}).get('hits') or []
    if not hits:
        return True
    return not any(_has_meaningful_match(getattr(h, 'content', '') or '', query) for h in hits)


# ---------------------------------------------------------------------------
# Calendar tools (v0.4.2, 이슈 #73)
# ---------------------------------------------------------------------------
#
# 한국 달력 기준 요일·영업일 판단. 자료 안의 "토/공휴일이면 익일" 류 조건절을
# 실제 날짜에 적용할 때 agent 가 호출한다.
#
# 도구 입력은 단일 string `date` 필드로 통일 — agent 가 `arguments={"date":
# "2026-06-21"}` 형태로 호출. 형식 파싱 실패는 callable 에서 ValueError 를
# 던져 `tools.call()` 의 `failure_kind='callable_error'` 분기에 흡수 — ReAct
# loop 가 다른 형식 (`2026.06.21` → `2026-06-21`) 으로 자유롭게 retry.

_KR_HOLIDAYS = holidays.KR(language='ko')  # 한국어 공휴일명. 전역 1회 생성, thread-safe.

_WEEKDAY_KO: tuple[str, ...] = ('월', '화', '수', '목', '금', '토', '일')

# 받아들이는 형식: 2026-06-21 / 2026/06/21 / 2026.06.21 / 20260621.
# 다른 형식은 ValueError 로 거부 — agent 가 다시 정규화하도록.
_DATE_FORMATS: tuple[str, ...] = ('%Y-%m-%d', '%Y/%m/%d', '%Y.%m.%d', '%Y%m%d')


def _parse_date(raw: Any) -> date:
    """문자열 또는 date 를 표준 `date` 로 변환. 실패 시 ValueError."""
    if isinstance(raw, date) and not isinstance(raw, datetime):
        return raw
    if isinstance(raw, datetime):
        return raw.date()
    if not isinstance(raw, str):
        raise ValueError(f'date 입력은 문자열이어야 합니다: type={type(raw).__name__}')
    text = raw.strip()
    if not text:
        raise ValueError('date 입력이 비어 있습니다.')
    for fmt in _DATE_FORMATS:
        try:
            return datetime.strptime(text, fmt).date()
        except ValueError:
            continue
    raise ValueError(
        f'date 형식을 인식하지 못했습니다: {text!r} '
        f'(허용: YYYY-MM-DD / YYYY/MM/DD / YYYY.MM.DD / YYYYMMDD)'
    )


def _is_business_day_check(d: date) -> bool:
    """주말이거나 한국 공휴일이면 False, 그 외 True."""
    if d.weekday() >= 5:  # 5=토, 6=일
        return False
    if d in _KR_HOLIDAYS:
        return False
    return True


# weekday_of -----------------------------------------------------------------

def _weekday_of_callable(arguments: Mapping[str, Any]) -> dict:
    d = _parse_date(arguments.get('date'))
    return {'date': d.isoformat(), 'weekday': _WEEKDAY_KO[d.weekday()]}


def _summarize_weekday_of(result: Any) -> str:
    if not isinstance(result, dict):
        return f'예상치 못한 응답 형식: {type(result).__name__}'
    return f"{result.get('date')} = {result.get('weekday')}요일"


# is_business_day ------------------------------------------------------------

def _is_business_day_callable(arguments: Mapping[str, Any]) -> dict:
    d = _parse_date(arguments.get('date'))
    is_bd = _is_business_day_check(d)
    holiday_name = _KR_HOLIDAYS.get(d) if d in _KR_HOLIDAYS else None
    return {
        'date': d.isoformat(),
        'weekday': _WEEKDAY_KO[d.weekday()],
        'is_business_day': is_bd,
        'holiday_name': holiday_name,
    }


def _summarize_is_business_day(result: Any) -> str:
    if not isinstance(result, dict):
        return f'예상치 못한 응답 형식: {type(result).__name__}'
    iso = result.get('date')
    weekday = result.get('weekday')
    if result.get('is_business_day'):
        return f'{iso} ({weekday}요일) = 영업일'
    holiday = result.get('holiday_name')
    if holiday:
        return f'{iso} ({weekday}요일) = 휴일 — {holiday}'
    return f'{iso} ({weekday}요일) = 휴일 (주말)'


# next_business_day ----------------------------------------------------------

# 무한 루프 방어 — 한국 공휴일이 연속으로 일주일 이상 이어지는 경우는 없음.
# 30 으로 잡으면 어떤 케이스도 안전.
_NEXT_BUSINESS_DAY_MAX_STEPS = 30


def _next_business_day_callable(arguments: Mapping[str, Any]) -> dict:
    """입력 날짜가 영업일이면 그대로, 아니면 다음 영업일을 반환."""
    d = _parse_date(arguments.get('date'))
    cursor = d
    for _ in range(_NEXT_BUSINESS_DAY_MAX_STEPS):
        if _is_business_day_check(cursor):
            return {
                'input_date': d.isoformat(),
                'next_business_day': cursor.isoformat(),
                'weekday': _WEEKDAY_KO[cursor.weekday()],
                'shifted': cursor != d,
            }
        cursor += timedelta(days=1)
    # 30일 안에도 못 찾으면 데이터 이상 — 보호적 raise.
    raise ValueError(
        f'next_business_day: {d.isoformat()} 부터 {_NEXT_BUSINESS_DAY_MAX_STEPS}일 안에 영업일을 찾지 못함.'
    )


def _summarize_next_business_day(result: Any) -> str:
    if not isinstance(result, dict):
        return f'예상치 못한 응답 형식: {type(result).__name__}'
    in_iso = result.get('input_date')
    out_iso = result.get('next_business_day')
    weekday = result.get('weekday')
    if result.get('shifted'):
        return f'{in_iso} → {out_iso} ({weekday}요일, 다음 영업일)'
    return f'{in_iso} = 영업일 그대로 ({weekday}요일)'


# ---------------------------------------------------------------------------
# 등록 — import 부작용
# ---------------------------------------------------------------------------

register(Tool(
    name='retrieve_documents',
    failure_check=_retrieve_failure_check,            # Phase 7-4: low-relevance 자동 failure.
    description=(
        '회사 문서 청크를 하이브리드 + reranker 로 검색합니다. '
        'query 는 자유형 한국어/영어 검색어.'
    ),
    input_schema={
        'query': FieldSpec(type='text', required=True, aliases=('query', '검색어')),
    },
    callable=_retrieve_callable,
    summarize=_summarize_retrieve,
))


register(Tool(
    name='find_canonical_qa',
    description=(
        '과거 공식 Q&A 중 유사 질문을 임베딩 거리로 찾습니다. '
        '같은 질문이 이미 답변된 적 있는지 확인할 때.'
    ),
    input_schema={
        'query': FieldSpec(type='text', required=True, aliases=('query', '질문')),
    },
    callable=_qa_callable,
    summarize=_summarize_qa,
))


register(Tool(
    name='run_workflow',
    description=(
        '등록된 generic workflow 를 직접 호출합니다. '
        'arguments 형태: {"workflow_key": "date_calculation|amount_calculation|table_lookup", '
        '"input": {workflow 가 요구하는 입력 dict}}. '
        '잘못된 key/input 은 workflow 가 자체 status 로 알려줍니다.'
    ),
    input_schema=None,   # raw 모드 — workflow_key 마다 input 형태가 달라 schema 강제 X
    callable=_workflow_callable,
    summarize=_summarize_workflow,
))


# v0.4.2 (이슈 #73) — agent 가 자료의 conditional date clause 를 실제 달력에 적용.

register(Tool(
    name='weekday_of',
    description=(
        '주어진 날짜의 요일을 한국어 한 글자로 반환합니다 (월/화/수/목/금/토/일). '
        'arguments: {"date": "YYYY-MM-DD"} (또는 YYYY/MM/DD, YYYY.MM.DD, YYYYMMDD).'
    ),
    input_schema={
        'date': FieldSpec(type='text', required=True, aliases=('date', '날짜')),
    },
    callable=_weekday_of_callable,
    summarize=_summarize_weekday_of,
))


register(Tool(
    name='is_business_day',
    description=(
        '주어진 날짜가 영업일(주말·한국 공휴일이 아닌 평일)인지 판단합니다. '
        'arguments: {"date": "YYYY-MM-DD"}. 반환에 holiday_name 이 있으면 공휴일.'
    ),
    input_schema={
        'date': FieldSpec(type='text', required=True, aliases=('date', '날짜')),
    },
    callable=_is_business_day_callable,
    summarize=_summarize_is_business_day,
))


register(Tool(
    name='next_business_day',
    description=(
        '주어진 날짜가 영업일이면 그대로, 주말·공휴일이면 다음 영업일을 반환합니다. '
        '"토/공휴일이면 익일" 류 규정의 실제 적용일 계산용. '
        'arguments: {"date": "YYYY-MM-DD"}.'
    ),
    input_schema={
        'date': FieldSpec(type='text', required=True, aliases=('date', '날짜')),
    },
    callable=_next_business_day_callable,
    summarize=_summarize_next_business_day,
))
