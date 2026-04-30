"""Router Rule 관리 뷰 (Phase 4-2).

`RouterRule` CRUD 를 BO 에 노출. Phase 4-2 범위는 contains 매칭뿐이고 preview /
conflict detection / 변경 이력은 다루지 않는다 (설계 §5-6 out-of-scope).

저장 흐름:
    1. ModelForm 으로 입력 수신
    2. 유효하면 save + success 메시지 → 목록으로 redirect
    3. 잘못된 pk 는 404 (or 에러 메시지 + 목록 redirect)
"""

from django import forms
from django.contrib import messages
from django.core.paginator import Paginator
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from chat.models import RouterRule
from chat.services.question_router import (
    AGENT_KEYWORDS,
    DATE_CONDITION_KEYWORDS,
    WORKFLOW_KEYWORDS,
)


# 페이지당 RouterRule 수 — 운영자가 한 화면에서 훑기 좋은 양 + 코드 키워드
# 박스가 너무 멀어지지 않을 정도. files / qa_logs 의 패턴과 동일하게 모듈 상수.
RULES_PER_PAGE = 10


def _workflow_key_choices():
    """registry 에 등록된 workflow 를 드롭다운 옵션으로 변환.

    빈 값("") 을 첫 옵션으로 허용 — `route='workflow'` 라도 key 미지정 시
    workflow_node 가 single_shot 으로 폴백하므로 의도된 기본값.
    """
    from chat.workflows.domains import registry
    options = [('', '— 선택 안 함 (single_shot 으로 폴백) —')]
    for entry in registry.all_entries():
        label = f'{entry.title} ({entry.key})'
        options.append((entry.key, label))
    return options


class RouterRuleForm(forms.ModelForm):
    """새 rule 생성 / 기존 rule 편집 공용 폼.

    모든 위젯에 bo.css 의 `.input` 클래스를 주입해 디자인 가이드 Form 규격을
    그대로 적용한다 (guide §Form / bo.css FORM 섹션).
    """

    workflow_key = forms.ChoiceField(
        required=False,
        label='Workflow',
        help_text=RouterRule._meta.get_field('workflow_key').help_text,
        widget=forms.Select(attrs={'class': 'input'}),
    )

    class Meta:
        model = RouterRule
        fields = (
            'name',
            'route',
            'match_type',
            'pattern',
            'workflow_key',
            'priority',
            'enabled',
            'description',
        )
        widgets = {
            'name':        forms.TextInput(attrs={'class': 'input'}),
            'route':       forms.Select(attrs={'class': 'input'}),
            'match_type':  forms.Select(attrs={'class': 'input'}),
            'pattern':     forms.TextInput(attrs={'class': 'input'}),
            'priority':    forms.NumberInput(attrs={'class': 'input'}),
            'description': forms.Textarea(attrs={'class': 'input', 'rows': 3}),
            # enabled 는 체크박스 — `.input` 을 적용하면 스타일이 깨진다.
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # registry 는 앱 로드 시 import 부작용으로 채워지므로, __init__ 시점에
        # 조회해 choices 를 채운다. 빈 값 포함.
        self.fields['workflow_key'].choices = _workflow_key_choices()

    def clean(self):
        """같은 (pattern, match_type) 조합의 다른 RouterRule 이 이미 있으면 거부.

        v0.4.2 (이슈 #73 검증 중 발견) — 운영자가 BO 에서 같은 키워드를 실수로
        두 번 등록할 수 있었음 (`며칠` rule 이 두 개 등록되어 있던 사례). 띄어쓰기
        포함 정확히 일치하는 패턴 + match_type 조합은 단일 rule 로 충분.

        편집 모드에선 자기 자신은 제외해야 self-conflict 안남 (`pk` 비교).
        """
        cleaned = super().clean()
        pattern = cleaned.get('pattern', '')
        match_type = cleaned.get('match_type')
        if not pattern or not match_type:
            return cleaned

        existing = RouterRule.objects.filter(
            pattern=pattern, match_type=match_type,
        )
        if self.instance.pk is not None:
            existing = existing.exclude(pk=self.instance.pk)
        if existing.exists():
            other = existing.first()
            raise forms.ValidationError(
                f'같은 키워드 "{pattern}" + 매칭 방식 "{match_type}" 의 규칙이 '
                f'이미 있습니다 (이름: "{other.name}"). 기존 규칙을 수정하거나 '
                f'다른 키워드를 사용하세요.'
            )
        return cleaned


def router_rules_index(request):
    """RouterRule 목록 + 코드 내장 기본 키워드(읽기 전용).

    기본 키워드는 question_router 의 fallback 레이어 — DB rule 이 매치되지
    않을 때 실제 분류를 담당. 운영자가 'BO 가 비어도 기본 동작은 무엇인가' 를
    확인할 수 있도록 접이식 섹션으로 함께 노출한다. 수정은 코드에서만 가능.

    Phase 8-3: rule 누적 시 한 화면이 너무 길어지므로 10개 단위 페이지네이션
    (`files` / `qa_logs` 패턴 동일).
    """
    paginator = Paginator(RouterRule.objects.all(), RULES_PER_PAGE)
    page_obj = paginator.get_page(request.GET.get('page'))
    context = {
        'section': 'router_rules',
        'rules': page_obj,                 # 템플릿에서 for 순회 시 현재 페이지 항목
        'page_obj': page_obj,              # 페이지네이션 컨트롤용
        'total_count': paginator.count,
        'date_condition_keywords': DATE_CONDITION_KEYWORDS,
        'workflow_keywords': WORKFLOW_KEYWORDS,
        'agent_keywords': AGENT_KEYWORDS,
    }
    return render(request, 'bo/router_rules.html', context)


def router_rules_new(request):
    """신규 rule 생성."""
    if request.method == 'POST':
        form = RouterRuleForm(request.POST)
        if form.is_valid():
            rule = form.save()
            messages.success(request, f'규칙 "{rule.name}" 를 추가했습니다.')
            return redirect('bo:router_rules')
    else:
        form = RouterRuleForm()

    context = {
        'section': 'router_rules',
        'form': form,
        'mode': 'new',
    }
    return render(request, 'bo/router_rule_form.html', context)


def router_rules_edit(request, pk: int):
    """기존 rule 편집."""
    rule = get_object_or_404(RouterRule, pk=pk)
    if request.method == 'POST':
        form = RouterRuleForm(request.POST, instance=rule)
        if form.is_valid():
            form.save()
            messages.success(request, f'규칙 "{rule.name}" 를 저장했습니다.')
            return redirect('bo:router_rules')
    else:
        form = RouterRuleForm(instance=rule)

    context = {
        'section': 'router_rules',
        'form': form,
        'mode': 'edit',
        'rule': rule,
    }
    return render(request, 'bo/router_rule_form.html', context)


@require_POST
def router_rules_toggle(request, pk: int):
    """enabled 토글 — rule 을 삭제 없이 즉시 무력화/재활성화."""
    rule = get_object_or_404(RouterRule, pk=pk)
    rule.enabled = not rule.enabled
    rule.save(update_fields=['enabled', 'updated_at'])
    state = '활성화' if rule.enabled else '비활성화'
    messages.success(request, f'규칙 "{rule.name}" 를 {state}했습니다.')
    return redirect('bo:router_rules')


@require_POST
def router_rules_delete(request, pk: int):
    """rule 완전 삭제. 기본 동작은 코드 상수가 담당하므로 복구 불필요."""
    rule = get_object_or_404(RouterRule, pk=pk)
    name = rule.name
    rule.delete()
    messages.success(request, f'규칙 "{name}" 를 삭제했습니다.')
    return redirect('bo:router_rules')


# ---------------------------------------------------------------------------
# 일괄 액션 (Phase 8-3 운영자 피드백)
# ---------------------------------------------------------------------------

def _bulk_ids(request) -> list[int]:
    """`ids` POST list 를 정수로 안전 변환. 잘못된 토큰은 무시."""
    raw = request.POST.getlist('ids')
    out: list[int] = []
    for v in raw:
        try:
            out.append(int(v))
        except (TypeError, ValueError):
            continue
    return out


@require_POST
def router_rules_bulk_enable(request):
    ids = _bulk_ids(request)
    if not ids:
        messages.warning(request, '선택된 규칙이 없습니다.')
        return redirect('bo:router_rules')
    count = RouterRule.objects.filter(pk__in=ids, enabled=False).update(enabled=True)
    messages.success(request, f'{count}건을 활성화했습니다.')
    return redirect('bo:router_rules')


@require_POST
def router_rules_bulk_disable(request):
    ids = _bulk_ids(request)
    if not ids:
        messages.warning(request, '선택된 규칙이 없습니다.')
        return redirect('bo:router_rules')
    count = RouterRule.objects.filter(pk__in=ids, enabled=True).update(enabled=False)
    messages.success(request, f'{count}건을 비활성화했습니다.')
    return redirect('bo:router_rules')


@require_POST
def router_rules_bulk_delete(request):
    ids = _bulk_ids(request)
    if not ids:
        messages.warning(request, '선택된 규칙이 없습니다.')
        return redirect('bo:router_rules')
    count, _ = RouterRule.objects.filter(pk__in=ids).delete()
    messages.success(request, f'{count}건을 삭제했습니다.')
    return redirect('bo:router_rules')
