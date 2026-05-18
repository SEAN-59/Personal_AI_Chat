"""BO — 채팅 문제 제보 리스트/상세/업데이트 (v0.5.6 Issue #94)."""

from django.contrib import messages
from django.core.paginator import Paginator
from django.db.models import Q
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from chat.models import ProblemReport


PAGE_SIZE = 10
ADMIN_NOTE_MAX = 4000


def report_list(request):
    status = (request.GET.get('status') or '').strip()
    q = (request.GET.get('q') or '').strip()

    base_qs = ProblemReport.objects.all()
    status_counts = {
        code: base_qs.filter(status=code).count()
        for code, _label in ProblemReport.STATUS_CHOICES
    }

    qs = base_qs
    if status:
        valid_statuses = {c[0] for c in ProblemReport.STATUS_CHOICES}
        if status in valid_statuses:
            qs = qs.filter(status=status)
    if q:
        qs = qs.filter(
            Q(title__icontains=q)
            | Q(content__icontains=q)
            | Q(last_question__icontains=q)
        )

    paginator = Paginator(qs, PAGE_SIZE)
    page_obj = paginator.get_page(request.GET.get('page'))
    page_params = request.GET.copy()
    page_params.pop('page', None)
    page_query = page_params.urlencode()

    context = {
        'items': list(page_obj.object_list),
        'page_obj': page_obj,
        'total_count': paginator.count,
        'all_count': base_qs.count(),
        'status_counts': status_counts,
        'status': status,
        'q': q,
        'page_query': f'{page_query}&' if page_query else '',
        'status_choices': ProblemReport.STATUS_CHOICES,
    }
    return render(request, 'bo/reports_list.html', context)


def report_detail(request, pk):
    report = get_object_or_404(ProblemReport, pk=pk)
    context = {
        'report': report,
        'status_choices': ProblemReport.STATUS_CHOICES,
    }
    return render(request, 'bo/reports_detail.html', context)


@require_POST
def report_update(request, pk):
    report = get_object_or_404(ProblemReport, pk=pk)
    valid_statuses = {c[0] for c in ProblemReport.STATUS_CHOICES}

    new_status = request.POST.get('status')
    new_note = request.POST.get('admin_note', '')

    if new_status is not None:
        if new_status not in valid_statuses:
            messages.error(request, '잘못된 상태값입니다.')
            return render(
                request, 'bo/reports_detail.html',
                {'report': report, 'status_choices': ProblemReport.STATUS_CHOICES},
                status=400,
            )
        report.status = new_status

    if new_note is not None:
        if len(new_note) > ADMIN_NOTE_MAX:
            messages.error(request, '관리자 메모는 4,000자 이내로 작성해 주세요.')
            return render(
                request, 'bo/reports_detail.html',
                {'report': report, 'status_choices': ProblemReport.STATUS_CHOICES},
                status=400,
            )
        report.admin_note = new_note

    report.save(update_fields=['status', 'admin_note', 'updated_at'])
    messages.success(request, '저장되었습니다.')

    next_url = request.POST.get('next')
    if next_url and next_url.startswith('/bo/'):
        return redirect(next_url)
    return redirect('bo:report_detail', pk=report.pk)


@require_POST
def report_delete(request, pk):
    report = get_object_or_404(ProblemReport, pk=pk)
    report.delete()
    messages.success(request, '문제 제보가 삭제되었습니다.')
    return redirect('bo:report_list')
