"""Input Normalization Rule 관리 뷰 (v0.5.2).

`InputNormalizationRule` CRUD 를 BO 에 노출. 코드/마이그레이션 어디에도 사내 용어
사전을 하드코딩하지 않고, 운영자가 이 화면에서 등록한 규칙만으로 사용자 입력을
정규화한다. raw 입력은 ChatLog.question/UI 표시에 보존되고, normalized 는 router/
rewriter/retrieval/agent/workflow 내부 처리에만 사용된다.

validation 책임은 `InputNormalizationRule.clean()` 에 일원화 — Form 은 model
full_clean() 을 그대로 사용하며 메시지만 UX 화한다. 그래서 BO 우회 경로(admin /
shell `objects.create(...)`)에서도 동일한 검증이 작동한다.
"""

from django import forms
from django.contrib import messages
from django.core.paginator import Paginator
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from chat.models import InputNormalizationRule


RULES_PER_PAGE = 20


class InputNormalizationRuleForm(forms.ModelForm):
    """`InputNormalizationRule` 생성/편집 폼.

    model.clean() 이 canonicalize + V1~V3 검증을 모두 책임진다. Form 단에서는
    위젯 class 만 주입하고 별도 validation 을 추가하지 않는다.
    """

    class Meta:
        model = InputNormalizationRule
        fields = (
            'pattern',
            'replacement',
            'match_type',
            'priority',
            'enabled',
            'description',
        )
        widgets = {
            'pattern':     forms.TextInput(attrs={'class': 'input'}),
            'replacement': forms.TextInput(attrs={'class': 'input'}),
            'match_type':  forms.Select(attrs={'class': 'input'}),
            'priority':    forms.NumberInput(attrs={'class': 'input'}),
            'description': forms.TextInput(attrs={'class': 'input'}),
        }


def input_norm_index(request):
    paginator = Paginator(InputNormalizationRule.objects.all(), RULES_PER_PAGE)
    page_obj = paginator.get_page(request.GET.get('page'))
    context = {
        'section': 'input_norm',
        'rules': page_obj,
        'page_obj': page_obj,
        'total_count': paginator.count,
    }
    return render(request, 'bo/input_normalization.html', context)


def input_norm_new(request):
    if request.method == 'POST':
        form = InputNormalizationRuleForm(request.POST)
        if form.is_valid():
            rule = form.save()
            messages.success(
                request,
                f'정규화 규칙 "{rule.pattern} → {rule.replacement}" 를 추가했습니다.',
            )
            return redirect('bo:input_norm')
    else:
        form = InputNormalizationRuleForm()

    context = {
        'section': 'input_norm',
        'form': form,
        'mode': 'new',
    }
    return render(request, 'bo/input_normalization_form.html', context)


def input_norm_edit(request, pk: int):
    rule = get_object_or_404(InputNormalizationRule, pk=pk)
    if request.method == 'POST':
        form = InputNormalizationRuleForm(request.POST, instance=rule)
        if form.is_valid():
            form.save()
            messages.success(request, f'정규화 규칙 #{rule.pk} 을(를) 저장했습니다.')
            return redirect('bo:input_norm')
    else:
        form = InputNormalizationRuleForm(instance=rule)

    context = {
        'section': 'input_norm',
        'form': form,
        'mode': 'edit',
        'rule': rule,
    }
    return render(request, 'bo/input_normalization_form.html', context)


@require_POST
def input_norm_toggle(request, pk: int):
    rule = get_object_or_404(InputNormalizationRule, pk=pk)
    rule.enabled = not rule.enabled
    # full_clean 을 우회하지 않기 위해 save() 그대로. update_fields 도 model.save()
    # 가 super().save 에 전달.
    rule.save(update_fields=['enabled', 'updated_at'])
    state = '활성화' if rule.enabled else '비활성화'
    messages.success(request, f'규칙 #{rule.pk} 을(를) {state}했습니다.')
    return redirect('bo:input_norm')


@require_POST
def input_norm_delete(request, pk: int):
    rule = get_object_or_404(InputNormalizationRule, pk=pk)
    pattern = rule.pattern
    rule.delete()
    messages.success(request, f'규칙 "{pattern}" 을(를) 삭제했습니다.')
    return redirect('bo:input_norm')
