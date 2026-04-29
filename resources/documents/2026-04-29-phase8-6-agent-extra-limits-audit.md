# 2026-04-29 개발 로그 — 2.0.0 Phase 8-6: Agent Settings Expansion: Extra Limits & Audit Log

## 배경

Phase 8-5 머지 직후 (2026-04-29) 시점:

- Phase 8-3 의 `AgentSettings` singleton 이 `enabled` / `max_iterations` / `max_low_relevance_retrieves` 만 BO 노출. `react.py:55-56` 의 `MAX_CONSECUTIVE_FAILURES = 3` / `MAX_REPEATED_CALL = 3` 은 코드 상수 — incident 시 즉시 조정 불가.
- `AgentSettings` 변경 이력이 추적되지 않음. `updated_at` 만 있어 마지막 변경 시각만 알 뿐, "누가 / 무엇을 / 언제 / 어떤 값으로" 변경했는지 불명.

Phase 8-6 의 목표는 (1) **`MAX_CONSECUTIVE_FAILURES` / `MAX_REPEATED_CALL` 의 BO 노출** + (2) **`AgentSettings` 변경 audit log** 도입.

---

## 1. 패키지 구조 변화

```
chat/
  models.py                              ← AgentSettings 두 필드 + AgentSettingsAudit 신규
  migrations/
    0014_agentsettings_extra_limits.py   ← AddField × 2 + AddConstraint × 2
    0015_agentsettingsaudit.py           ← CreateModel
  services/agent/
    runtime_settings.py                  ← DEFAULT_* 두 상수 + AgentRuntimeSettings 확장 + sanity range 두 개
    react.py                             ← MAX_* alias + _decide_termination 시그니처 확장 + run_agent inject
  tests/
    test_agent_settings_model.py         ← ExtraLimitsTests +4
    test_agent_runtime_settings.py       ← 새 필드 freeze + sanity demote +2
    test_agent_react_settings_inject.py  ← Compat alias +2 + SettingsExtraLimitsInjectTests +2
    test_agent_settings_audit.py         ← 신규 (3 cases)

bo/
  views/agent.py                         ← AUDIT_FIELDS / RECENT_AUDIT_LIMIT / form 두 필드 / POST audit / GET recent_audits
  templates/bo/agent.html                ← 두 라벨 + Settings 변경 이력 섹션
  tests.py                               ← _full_form_data + 8 신규 cases
```

---

## 2. 핵심 결정

### Decision 1 — 두 한도 추가: 8-3 패턴 그대로

CheckConstraint + Form validator + runtime sanity check 삼중 가드. `max_consecutive_failures` 1~10 / `max_repeated_call` **2~10**.

### Decision 2 — `max_repeated_call` min=2 강제

`state.repeated_call_count(last.name, last.arguments)` 가 첫 정상 호출도 1로 세므로 max=1 이면 첫 tool call 직후 NO_MORE_USEFUL_TOOLS 발동. 정책 의도 충돌. min=2 로 운영자가 1 입력 못 함. help_text 에 "호환/기록용 — 8-3 차단 정책으로 실제 동작 변화 거의 없음" 명시 — 운영자 오조작 위험 차단.

### Decision 3 — Audit 저장 위치: view layer

Django signal 대신 `agent_view` POST 분기에서 명시. `request.user` 자연 접근 + 변경 컨텍스트 명확 (BO UI 액션만 audit, shell / migration save 는 의도적 미추적).

### Decision 4 — old 값 캡처 시점: form 바인딩 전 DB 값

`ModelForm.is_valid()` 가 cleaned_data 를 form.instance 에 반영하므로 form 으로부터 old 를 읽으면 = new 가 되어 변경 감지 실패. **form 바인딩 전에** DB 의 현재 값을 별도 dict (`old_values = {f: getattr(settings_obj, f) for f in AUDIT_FIELDS}`) 로 캡처.

### Decision 5 — Audit 모델: changes + snapshot 둘 다

- `changes` = 변경된 필드만 (`{field: {old, new}}`) — UI 표시용.
- `snapshot` = 변경 후 5 필드 전체 상태 — incident 분석용.
- 두 dict 의 저장 비용 미미.

### Decision 6 — 변경 0이면 audit row 미생성

empty form save (운영자가 폼만 열고 즉시 저장) 가 audit 잡음으로 안 남게.

### Decision 7 — `changed_by on_delete=SET_NULL`

운영자 계정 삭제 시 audit 보존, FK 만 NULL. CASCADE 안 씀 (audit 영구 보존 원칙).

### Decision 8 — BO 노출: 같은 페이지 하단 최근 10건

별 페이지 안 만듦. 운영자가 설정 변경 후 즉시 변경 이력 확인 가능. full history / 검색 / 필터는 별 plan.

---

## 3. 사용자-가시 변화

**없음** — 8-6 은 운영자 표면.

---

## 4. 운영자-가시 변화

| 영역 | Before | After |
|---|---|---|
| BO `/bo/agent/` 폼 | 3 필드 (enabled / max_iterations / max_low_relevance_retrieves) | **5 필드** (+ 연속 실패 한도 / 동일 호출 반복 한도) |
| `max_repeated_call` 필드 hint | 없음 | "호환/기록용 — 변경해도 실제 동작 변화 거의 없음. 정책 통합은 후속 Phase" 자동 노출 |
| `max_repeated_call=1` 입력 | 없음 | Form / DB validator 거부 + shake (Phase 8-4 hook) |
| Settings 변경 이력 | 없음 | **신규** — 페이지 하단에 최근 10건 표 (시각 / 변경자 / 변경 필드 + old → new) |
| 변경 없는 저장 | 같음 | audit row 미생성 (잡음 차단) |
| 운영자 계정 삭제 후 audit | 없음 | audit row 보존, "(익명)" 표시 |

---

## 5. 검증

### 단위 테스트

| 모듈 | 신규 케이스 |
|---|---|
| `test_agent_settings_model.py` (ExtraLimitsTests) | 4 (default 값 / max_repeated_call=1 ValidationError / IntegrityError / max_consecutive_failures>10 IntegrityError) |
| `test_agent_runtime_settings.py` | 2 (새 필드 freeze + sanity demote on max_repeated_call=1) |
| `test_agent_react_settings_inject.py` | 4 (Compat alias x2 + max_consecutive_failures=1 e2e + _decide_termination 단위) |
| `test_agent_settings_audit.py` | 3 (changed_by NULL / Meta.ordering / SET_NULL on user delete) |
| `bo/tests.py` (AgentSettingsViewTests) | 8 (새 필드 GET / max_repeated_call=1 거부 / hint 노출 / audit 생성·미생성 / changes 변경 필드만 / snapshot 5필드 / form 바인딩 전 old / recent_audits GET) |
| **총합** | **21** (계획 ≈18 보다 +3 — review 사이클에서 case 늘어남) |

총 504/504 그린 (Phase 8-5 종료 실측 484 → +20).

### 운영 환경 smoke (5 시나리오)

1. **마이그레이션 적용** — `0014_agentsettings_extra_limits` + `0015_agentsettingsaudit` OK.
2. **`/bo/agent/` GET** — 5 필드 + 빈 audit 섹션 ("최근 변경 내역 없음").
3. **변경 저장** — `max_iterations=4` + `max_consecutive_failures=5` → audit row 1건 (changes 두 필드, snapshot 5 필드).
4. **변경 없는 저장** — 폼만 열고 저장 → audit row 안 만들어짐.
5. **`max_consecutive_failures=1` 즉시 반영** — agent route 비교형 질문 → 첫 실패 직후 NO_MORE_USEFUL_TOOLS 종료.

---

## 6. 후속

- audit 의 별 BO 페이지 (full history + 검색 / 필터 / 페이지네이션 / export).
- audit retention 정책 (자동 정리 / archive).
- audit color diff 시각화.
- 다른 BO 모델 (RouterRule / Prompt 편집) 의 audit.
- `MAX_REPEATED_CALL` 의 정책 통합 (8-3 차단과 카운터 의미 통일).
- Phase 8-7 후보 — embedder / reranker `record_token_usage` 통합.

Phase 8 milestone 본 PR 머지로 **6/6 closed** — Phase 8 완료 후보. 후속 polish 는 새 milestone 또는 별 plan.
