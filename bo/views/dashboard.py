from datetime import timedelta

from django.core.paginator import Paginator
from django.db.models import Count, Sum
from django.db.models.functions import TruncDate
from django.shortcuts import render
from django.utils import timezone

from chat.models import TokenUsage
from chat.services.token_purpose import (
    PURPOSE_AGENT_FINAL,
    PURPOSE_AGENT_STEP,
    PURPOSE_QUERY_REWRITER,
    PURPOSE_SINGLE_SHOT_ANSWER,
    PURPOSE_UNKNOWN,
    PURPOSE_WORKFLOW_EXTRACTOR,
    PURPOSE_WORKFLOW_TABLE_LOOKUP,
)


# 대시보드에서 보여줄 과거 일수
DASHBOARD_DAYS = 7

# Phase 8-6: 보조 섹션 페이지 크기 — 메인 기능이 아닌 사이드 표는 5건 단위 통일.
SECONDARY_PAGE_SIZE = 5


# Phase 8-5: purpose 코드 → 한국어 라벨. 운영자-facing 표시 용도라 view 안 dict.
# 미등록 purpose 는 dict.get(purpose, purpose) 로 fallback (영문 코드 그대로).
_PURPOSE_LABELS = {
    PURPOSE_SINGLE_SHOT_ANSWER: 'single-shot 답변',
    PURPOSE_QUERY_REWRITER: '쿼리 재작성',
    PURPOSE_WORKFLOW_EXTRACTOR: 'workflow 입력 추출',
    PURPOSE_WORKFLOW_TABLE_LOOKUP: 'workflow 표 조회',
    PURPOSE_AGENT_STEP: 'agent 추론',
    PURPOSE_AGENT_FINAL: 'agent 최종 답변',
    PURPOSE_UNKNOWN: '미상',
}


def dashboard(request):
    # 최근 N일 범위
    now = timezone.localtime()
    since = now - timedelta(days=DASHBOARD_DAYS - 1)
    since_start = since.replace(hour=0, minute=0, second=0, microsecond=0)

    # 일별 집계 쿼리 (Phase 8-5: cost 추가)
    daily_rows = (
        TokenUsage.objects
        .filter(created_at__gte=since_start)
        .annotate(date=TruncDate('created_at'))
        .values('date')
        .annotate(
            calls=Count('id'),
            prompt=Sum('prompt_tokens'),
            completion=Sum('completion_tokens'),
            total=Sum('total_tokens'),
            cost=Sum('cost_usd'),
        )
        .order_by('-date')
    )

    # Phase 8-5: purpose 별 집계 (observed-only — 기간 내 발생한 purpose 만).
    # values('purpose') 는 실제 row 가 있는 purpose 만 반환. zero-fill 미도입.
    purpose_rows_raw = (
        TokenUsage.objects
        .filter(created_at__gte=since_start)
        .values('purpose')
        .annotate(
            calls=Count('id'),
            prompt=Sum('prompt_tokens'),
            completion=Sum('completion_tokens'),
            total=Sum('total_tokens'),
            cost=Sum('cost_usd'),
        )
        .order_by('-cost')
    )
    # 한국어 라벨 부착.
    purpose_rows_labeled = [
        {**row, 'label': _PURPOSE_LABELS.get(row['purpose'], row['purpose'])}
        for row in purpose_rows_raw
    ]
    # Phase 8-6: 5건 단위 페이지네이션 (보조 섹션 통일 정책).
    purpose_paginator = Paginator(purpose_rows_labeled, SECONDARY_PAGE_SIZE)
    purpose_page = purpose_paginator.get_page(request.GET.get('purpose_page'))

    # 전체 기간 합계 (상단 요약 카드용, Phase 8-5: cost 추가)
    totals = TokenUsage.objects.filter(created_at__gte=since_start).aggregate(
        calls=Count('id'),
        prompt=Sum('prompt_tokens'),
        completion=Sum('completion_tokens'),
        total=Sum('total_tokens'),
        cost=Sum('cost_usd'),
    )

    context = {
        'rows': list(daily_rows),
        'purpose_rows': purpose_page,
        'purpose_page': purpose_page,
        'totals': totals,
        'days': DASHBOARD_DAYS,
    }
    return render(request, 'bo/dashboard.html', context)
