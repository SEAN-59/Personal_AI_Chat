"""Agent 운영 제어 뷰 (Phase 8-3).

`AgentSettings` singleton 폼 + tool catalog (읽기 전용) + 최근 7일 호출 통계.
GET / POST 한 view 로 통합 — singleton 이라 URL 에 pk 없음.
"""

from datetime import timedelta

from django import forms
from django.contrib import messages
from django.db.models import Count
from django.shortcuts import redirect, render
from django.utils import timezone

from chat.models import AgentSettings, TokenUsage
from chat.services.agent import tools as agent_tools
from chat.services.token_purpose import (
    PURPOSE_AGENT_FINAL,
    PURPOSE_AGENT_STEP,
    PURPOSE_QUERY_REWRITER,
)


class AgentSettingsForm(forms.ModelForm):
    """`AgentSettings` 편집 폼. validators 가 자동으로 min/max 범위 강제."""

    class Meta:
        model = AgentSettings
        fields = ('enabled', 'max_iterations', 'max_low_relevance_retrieves')
        widgets = {
            'max_iterations': forms.NumberInput(attrs={'class': 'input', 'min': 1, 'max': 12}),
            'max_low_relevance_retrieves': forms.NumberInput(attrs={'class': 'input', 'min': 1, 'max': 10}),
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

    GET: 현재 settings + tool catalog + 최근 호출 통계.
    POST: form 검증 후 저장. 잘못된 값은 form error 로 표시 (DB 갱신 안 됨).
    """
    settings_obj = AgentSettings.objects.get_solo()

    if request.method == 'POST':
        form = AgentSettingsForm(request.POST, instance=settings_obj)
        if form.is_valid():
            form.save()
            messages.success(request, 'Agent 설정을 저장했습니다.')
            return redirect('bo:agent')
    else:
        form = AgentSettingsForm(instance=settings_obj)

    context = {
        'section': 'agent',
        'form': form,
        'settings': settings_obj,
        'tool_catalog': _tool_catalog(),
        'recent_usage': _recent_usage_summary(),
    }
    return render(request, 'bo/agent.html', context)
