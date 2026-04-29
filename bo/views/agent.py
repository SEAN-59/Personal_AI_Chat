"""Agent 운영 제어 뷰 (Phase 8-3).

`AgentSettings` singleton 폼 + tool catalog (읽기 전용) + 최근 7일 호출 통계.
GET / POST 한 view 로 통합 — singleton 이라 URL 에 pk 없음.
"""

from datetime import timedelta

from django import forms
from django.contrib import messages
from django.core.paginator import Paginator
from django.db import transaction
from django.db.models import Count
from django.shortcuts import redirect, render
from django.utils import timezone

from chat.models import AgentSettings, AgentSettingsAudit, TokenUsage
from chat.services.agent import tools as agent_tools
from chat.services.token_purpose import (
    PURPOSE_AGENT_FINAL,
    PURPOSE_AGENT_STEP,
    PURPOSE_QUERY_REWRITER,
)


# Phase 8-6: audit 가 추적하는 5 필드. 새 필드 추가 시 한 곳만 갱신.
AUDIT_FIELDS = (
    'enabled',
    'max_iterations',
    'max_low_relevance_retrieves',
    'max_consecutive_failures',
    'max_repeated_call',
)

# BO 보조 섹션 페이지 크기 — 메인 기능이 아닌 사이드 표는 5건 단위 통일.
SECONDARY_PAGE_SIZE = 5


class AgentSettingsForm(forms.ModelForm):
    """`AgentSettings` 편집 폼. validators 가 자동으로 min/max 범위 강제.

    Phase 8-4: 숫자 input 에 `data-shake-input` 추가 — 공용 bo.js 의 initFormShake
    가 hook 으로 사용. HTML5 `required` 미적용 input 이라 명시 opt-in 경로.

    Phase 8-6: max_consecutive_failures (1~10) / max_repeated_call (2~10) 두 필드 추가.
    """

    class Meta:
        model = AgentSettings
        fields = (
            'enabled',
            'max_iterations',
            'max_low_relevance_retrieves',
            'max_consecutive_failures',
            'max_repeated_call',
        )
        widgets = {
            'max_iterations': forms.NumberInput(attrs={
                'class': 'input', 'min': 1, 'max': 12, 'data-shake-input': '1',
            }),
            'max_low_relevance_retrieves': forms.NumberInput(attrs={
                'class': 'input', 'min': 1, 'max': 10, 'data-shake-input': '1',
            }),
            'max_consecutive_failures': forms.NumberInput(attrs={
                'class': 'input', 'min': 1, 'max': 10, 'data-shake-input': '1',
            }),
            'max_repeated_call': forms.NumberInput(attrs={
                'class': 'input', 'min': 2, 'max': 10, 'data-shake-input': '1',
            }),
            # enabled 는 체크박스 — .input 적용 시 스타일 깨짐.
        }


def _tool_catalog() -> list[dict]:
    """등록된 모든 Tool 의 메타 (이름 / 설명 / 모드 / failure_check 여부)."""
    catalog = []
    for tool in agent_tools.all_entries():
        catalog.append({
            'name': tool.name,
            'description': tool.description,
            'mode': 'schema' if tool.input_schema is not None else 'raw',
            'has_failure_check': tool.failure_check is not None,
        })
    return catalog


def _recent_usage_summary(days: int = 7) -> dict:
    """최근 N일 agent 관련 TokenUsage 카운트 (Phase 8-2 산물 활용).

    `agent_step` / `agent_final` / `query_rewriter` 분리 카운트. 단 `query_rewriter`
    는 single_shot / workflow / agent 세 경로 통합이라 "agent 전용" 분리 불가 —
    표시는 하되 라벨에 한계 명시.
    """
    since = timezone.now() - timedelta(days=days)
    rows = (
        TokenUsage.objects
        .filter(created_at__gte=since, purpose__in=(
            PURPOSE_AGENT_STEP, PURPOSE_AGENT_FINAL, PURPOSE_QUERY_REWRITER,
        ))
        .values('purpose')
        .annotate(calls=Count('id'))
    )
    by_purpose = {row['purpose']: row['calls'] for row in rows}
    return {
        'agent_step': by_purpose.get(PURPOSE_AGENT_STEP, 0),
        'agent_final': by_purpose.get(PURPOSE_AGENT_FINAL, 0),
        'query_rewriter': by_purpose.get(PURPOSE_QUERY_REWRITER, 0),
        'days': days,
    }


def agent_view(request):
    """`/bo/agent/` GET / POST.

    GET: 현재 settings + tool catalog + 최근 호출 통계 + 최근 audit 10건.
    POST: form 검증 후 저장. 잘못된 값은 form error 로 표시 (DB 갱신 안 됨).
          변경된 필드가 있을 때만 `AgentSettingsAudit` row 생성 (Phase 8-6).
    """
    settings_obj = AgentSettings.objects.get_solo()

    if request.method == 'POST':
        # Phase 8-6 P2-1: form 바인딩 / is_valid() 호출 전에 DB 의 현재 값을 별도 dict
        # 으로 캡처. ModelForm.is_valid() 가 cleaned_data 를 form.instance 에 반영하므로
        # form 으로부터 old 를 읽으면 = new 가 되어 변경 감지 실패.
        old_values = {f: getattr(settings_obj, f) for f in AUDIT_FIELDS}

        form = AgentSettingsForm(request.POST, instance=settings_obj)
        if form.is_valid():
            with transaction.atomic():
                saved = form.save()

                # 변경 감지 — old 와 saved 의 새 값 비교, 변경된 필드만 changes.
                changes = {}
                for field in AUDIT_FIELDS:
                    new_val = getattr(saved, field)
                    if old_values[field] != new_val:
                        changes[field] = {
                            'old': old_values[field], 'new': new_val,
                        }

                # 변경 0 이면 audit row 미생성 (empty save 노이즈 차단).
                if changes:
                    snapshot = {f: getattr(saved, f) for f in AUDIT_FIELDS}
                    AgentSettingsAudit.objects.create(
                        changed_by=(
                            request.user if request.user.is_authenticated else None
                        ),
                        changes=changes,
                        snapshot=snapshot,
                    )

            messages.success(request, 'Agent 설정을 저장했습니다.')
            return redirect('bo:agent')
    else:
        form = AgentSettingsForm(instance=settings_obj)

    # Phase 8-6: 보조 섹션 (audit / tool catalog) 5건 단위 페이지네이션.
    # 한 페이지에 두 표가 있어 query key 분리: audit_page / catalog_page.
    audit_paginator = Paginator(
        AgentSettingsAudit.objects.all(), SECONDARY_PAGE_SIZE,
    )
    audit_page = audit_paginator.get_page(request.GET.get('audit_page'))

    catalog_paginator = Paginator(_tool_catalog(), SECONDARY_PAGE_SIZE)
    catalog_page = catalog_paginator.get_page(request.GET.get('catalog_page'))

    context = {
        'section': 'agent',
        'form': form,
        'settings': settings_obj,
        'tool_catalog': catalog_page,
        'catalog_page': catalog_page,
        'recent_usage': _recent_usage_summary(),
        'recent_audits': audit_page,
        'audit_page': audit_page,
    }
    return render(request, 'bo/agent.html', context)
