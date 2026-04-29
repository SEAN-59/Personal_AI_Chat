/**
 * BO 공용 JS (Phase 8-4).
 *
 * 세 가지 패턴을 페이지별 인라인 스크립트 대신 단일 파일로:
 *
 *   - initFormShake()         : 폼 invalid 입력 시 빨간 테두리 + 흔들림 + scroll/focus.
 *                               두 hook 모두 지원:
 *                                 1. data-shake-input opt-in (HTML5 required 미적용 input 용)
 *                                 2. input.input[required] / select.input[required] / textarea.input[required] 자동
 *                               server-side 에러 (.form-error[data-server-error]) 가 있는 필드도 자동 시각 효과.
 *
 *   - initAlertAutoDismiss()  : .alert[data-auto-dismiss] 3초 후 fade-out.
 *                               alert-danger 는 자동 제거 대상에서 제외 (사용자가 읽고 조치).
 *
 *   - initBulkActions()       : data-bulk-* attribute 기반 일괄 액션.
 *                               edit-toggle 은 page 컨테이너 밖 (header) 에 위치 가능 —
 *                               data-bulk-edit-toggle data-bulk-target="<id>" 와
 *                               data-bulk-page="<id>" 가 짝 매칭.
 *
 * fail-silent 정책: selector 없으면 즉시 return — 콘솔 에러 0.
 */
(function () {
  'use strict';

  // -------------------------------------------------------------------------
  // initFormShake — 폼 invalid 시각 효과
  // -------------------------------------------------------------------------
  function initFormShake() {
    document.querySelectorAll('form').forEach((form) => {
      const explicit = Array.from(form.querySelectorAll('[data-shake-input]'));
      const required = Array.from(form.querySelectorAll(
        'input.input[required], select.input[required], textarea.input[required]'
      ));
      // 두 hook 합집합 (중복 제거).
      const inputs = Array.from(new Set([...explicit, ...required]));
      if (inputs.length === 0) return;

      function getClientErrorEl(input) {
        const group = input.closest('.form-group');
        return group ? group.querySelector('.form-error[data-client-error]') : null;
      }

      function getLabelText(input) {
        const label = form.querySelector(`label[for="${input.id}"]`);
        if (!label) return '';
        return label.childNodes[0]
          ? label.childNodes[0].textContent.trim()
          : label.textContent.trim();
      }

      function showFieldError(input, message) {
        input.classList.add('is-error');
        input.classList.remove('shake');
        requestAnimationFrame(() => input.classList.add('shake'));
        input.addEventListener('animationend', () => input.classList.remove('shake'), { once: true });

        const msgEl = getClientErrorEl(input);
        if (msgEl && message) {
          msgEl.textContent = message;
          msgEl.style.display = 'block';
        }
      }

      function clearFieldError(input) {
        input.classList.remove('is-error');
        const msgEl = getClientErrorEl(input);
        if (msgEl) {
          msgEl.textContent = '';
          msgEl.style.display = 'none';
        }
        // server-side 에러도 함께 제거 (사용자가 값을 바꾸기 시작했으므로).
        const group = input.closest('.form-group');
        const serverErr = group ? group.querySelector('.form-error[data-server-error]') : null;
        if (serverErr) serverErr.remove();
      }

      inputs.forEach((input) => {
        input.addEventListener('input', () => clearFieldError(input));
        input.addEventListener('change', () => clearFieldError(input));
      });

      // 페이지 로드 시 server-side 에러 표시된 필드는 자동으로 .is-error + shake.
      form.querySelectorAll('.form-error[data-server-error]').forEach((errEl) => {
        const group = errEl.closest('.form-group');
        const input = group ? group.querySelector('input.input, select.input, textarea.input') : null;
        if (input) showFieldError(input, '');
      });

      form.addEventListener('submit', (e) => {
        let firstInvalid = null;
        inputs.forEach((input) => {
          const v = (input.value || '').trim();
          const min = Number(input.getAttribute('min'));
          const max = Number(input.getAttribute('max'));
          const num = Number(v);
          let msg = '';

          if (input.hasAttribute('required') && !v) {
            const label = getLabelText(input);
            msg = label ? `${label}을(를) 입력해주세요.` : '필수 항목입니다.';
          } else if (input.type === 'number' && v) {
            if (Number.isFinite(min) && num < min) msg = `${min} 이상이어야 합니다.`;
            else if (Number.isFinite(max) && num > max) msg = `${max} 이하여야 합니다.`;
          }

          if (msg) {
            showFieldError(input, msg);
            if (!firstInvalid) firstInvalid = input;
          }
        });
        if (firstInvalid) {
          e.preventDefault();
          firstInvalid.scrollIntoView({ behavior: 'smooth', block: 'center' });
          firstInvalid.focus({ preventScroll: true });
        }
      });
    });
  }

  // -------------------------------------------------------------------------
  // initAlertAutoDismiss — 토스트 자동 사라짐 (alert-danger 제외)
  // -------------------------------------------------------------------------
  function initAlertAutoDismiss() {
    document.querySelectorAll('.alert[data-auto-dismiss]').forEach((el) => {
      // 사용자가 에러 메시지 읽고 조치해야 하므로 자동 제거 제외.
      if (el.classList.contains('alert-danger')) return;
      setTimeout(() => {
        el.style.transition = 'opacity 0.4s ease';
        el.style.opacity = '0';
        setTimeout(() => el.remove(), 400);
      }, 3000);
    });
  }

  // -------------------------------------------------------------------------
  // initBulkActions — data-bulk-* 일괄 액션
  // -------------------------------------------------------------------------
  function initBulkActions() {
    document.querySelectorAll('[data-bulk-page]').forEach((page) => {
      const pageId = page.getAttribute('data-bulk-page');
      const toolbar = page.querySelector('[data-bulk-toolbar]');
      // edit-toggle 은 page 컨테이너 밖 (header) 에 있을 수 있음 — data-bulk-target 으로 매칭.
      const toggleBtn = document.querySelector(
        `[data-bulk-edit-toggle][data-bulk-target="${pageId}"]`
      );
      if (!toolbar || !toggleBtn) return;

      const selectAllBtn = toolbar.querySelector('[data-bulk-select-all]');
      const actionBtns = toolbar.querySelectorAll('[data-bulk-action]');
      const countEl = toolbar.querySelector('[data-bulk-count]');

      function checkboxes() {
        return Array.from(page.querySelectorAll('[data-bulk-check]'));
      }

      function refreshState() {
        const boxes = checkboxes();
        const selected = boxes.filter((b) => b.checked);
        if (countEl) countEl.textContent = String(selected.length);
        actionBtns.forEach((b) => { b.disabled = selected.length === 0; });
        if (selectAllBtn) {
          selectAllBtn.textContent = (boxes.length > 0 && selected.length === boxes.length)
            ? '전체 해제'
            : '전체 선택';
        }
      }

      function setSelected(row, on) {
        const box = row.querySelector('[data-bulk-check]');
        if (!box) return;
        box.checked = on;
        row.classList.toggle('selected', on);
      }

      function clearAll() {
        page.querySelectorAll('[data-bulk-row]').forEach((r) => setSelected(r, false));
        refreshState();
      }

      // 수정 / 완료 토글
      toggleBtn.addEventListener('click', () => {
        const on = !page.classList.contains('bulk-mode');
        page.classList.toggle('bulk-mode', on);
        toggleBtn.classList.toggle('active', on);
        toggleBtn.textContent = on ? '완료' : '수정';
        if (!on) clearAll(); else refreshState();
      });

      // 행 클릭 → 선택 토글 (.bulk-mode 에서만, 인터랙티브 요소 제외)
      page.addEventListener('click', (e) => {
        if (!page.classList.contains('bulk-mode')) return;
        const row = e.target.closest('[data-bulk-row]');
        if (!row) return;
        if (e.target.closest('a, button, form, input, textarea, select, label')) return;
        const box = row.querySelector('[data-bulk-check]');
        if (!box) return;
        setSelected(row, !box.checked);
        refreshState();
      });

      if (selectAllBtn) {
        selectAllBtn.addEventListener('click', () => {
          const boxes = checkboxes();
          const allSelected = boxes.length > 0 && boxes.every((b) => b.checked);
          boxes.forEach((b) => {
            const row = b.closest('[data-bulk-row]');
            if (row) setSelected(row, !allSelected);
          });
          refreshState();
        });
      }

      // 위험 액션 confirm
      actionBtns.forEach((btn) => {
        const msg = btn.getAttribute('data-bulk-confirm');
        if (!msg) return;
        btn.addEventListener('click', (e) => {
          if (!confirm(msg)) e.preventDefault();
        });
      });

      refreshState();
    });
  }

  // -------------------------------------------------------------------------
  // 자동 실행
  // -------------------------------------------------------------------------
  document.addEventListener('DOMContentLoaded', () => {
    initFormShake();
    initAlertAutoDismiss();
    initBulkActions();
  });
})();
