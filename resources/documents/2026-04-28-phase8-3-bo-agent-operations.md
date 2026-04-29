# 2026-04-28 개발 로그 — 0.4.0 Phase 8-3: BO Agent 운영 제어

## 배경

Phase 8-2 머지 직후 시점:

- agent runtime 의 동작 한도 (`DEFAULT_MAX_ITERATIONS=6`, `MAX_LOW_RELEVANCE_RETRIEVES=3` 등) 가 모두 코드 상수. 운영자가 BO 에서 조정 불가 — 변경하려면 코드 수정 + 재배포.
- agent route 는 항상 켜져 있음. 비상시 끌 방법이 RouterRule 일괄 disable 외엔 없음.
- agent 가 어떤 도구를 갖고 있는지 BO 에서 확인 불가.
- Phase 8-2 가 token_purpose 별 분리 집계 데이터를 만들었지만 BO 에서 본격 활용 없음.

운영 incident (예: agent 무한 루프 비용 폭증) 시 즉시 대응이 어렵다. Phase 8-3 의 목표는 **운영자가 BO 에서 agent 의 동작 범위를 안전하게 조정 / 가시화** 할 수 있는 첫 control plane 을 만드는 것.

---

## 1. 패키지 구조 변화

```
chat/
  models.py                       ← AgentSettings hard singleton (save() override pk=1 강제 + Meta.constraints CheckConstraint 두 개)
  migrations/
    0012_agentsettings.py         ← CreateModel + RunPython 으로 초기 1행 보장
  services/agent/
    runtime_settings.py           ← 신규 — DEFAULT_* single source of truth + load_runtime_settings() + _DEFAULTS 폴백
    react.py                      ← DEFAULT_MAX_ITERATIONS / MAX_LOW_RELEVANCE_RETRIEVES alias 로 변경, run_agent 에 settings 주입
  graph/nodes/
    agent.py                      ← 진입 직후 settings.enabled=False 시 single_shot_node 폴백
  tests/
    test_agent_settings_model.py            ← 신규 (7 cases)
    test_agent_runtime_settings.py          ← 신규 (5 cases)
    test_agent_react_settings_inject.py     ← 신규 (6 cases)
    test_agent_node_disabled.py             ← 신규 (2 cases)
    test_agent_node.py                      ← settings mock 추가 (회귀 가드 보강)

bo/
  views/agent.py                  ← 신규 — agent_view + AgentSettingsForm + tool catalog + 7일 통계
  views/__init__.py               ← agent_view export
  urls.py                         ← path('agent/', name='agent')
  templates/bo/agent.html         ← 신규
  templates/bo/base.html          ← 사이드바에 'Agent 운영' 메뉴 추가
  tests.py                        ← 신규 (5 cases — Phase 4-2 이후 비어있던 파일에 첫 테스트)
```

---

## 2. 핵심 결정

### Decision 1 — 설정 저장 위치: DB singleton

운영자 BO 즉시 변경 가치가 본 phase 의 **본 목표**. 변경 즉시 반영 (재배포 / 재시작 불필요) 위해 DB. 환경변수 / settings.py 모듈 상수는 incident 대응 가치 무력화.

### Decision 2 — Hard singleton 강제

`save()` override 가 `self.pk = 1` 강제:
- `objects.create(pk=N, ...)` 는 `force_insert=True` 로 진입 → save override 의 pk=1 강제 → 기존 row 있으면 IntegrityError, 없으면 pk=1 INSERT.
- `obj = AgentSettings(pk=99); obj.save()` 는 default `force_insert=False` 라 pk=1 으로 UPDATE/INSERT 자동 분기.

PK uniqueness 만으로는 부족 (admin / shell / `objects.create(pk=2, ...)` 우회) — save override 가 진짜 차단.

### Decision 3 — DB CheckConstraint + Form validators + runtime sanity 삼중 가드

- **DB 차원**: `Meta.constraints` 의 두 `CheckConstraint` (`max_iterations` 1~12 / `max_low_relevance_retrieves` 1~10). PostgreSQL 이 INSERT/UPDATE 시점에 강제, 위반 시 `IntegrityError` — raw SQL / `.save()` 직접 호출도 차단.
- **Form 차원**: `MinValueValidator` / `MaxValueValidator` — POST 검증 시 한국어 에러 메시지로 사용자에게 표시.
- **Runtime 차원**: `load_runtime_settings()` 가 DB 값 sanity check (범위 밖이면 `_DEFAULTS` 폴백). 마이그레이션 누락 / 외부 데이터 dump 같은 극단 상황의 마지막 안전망.

### Decision 4 — runtime_settings.py 가 default 의 single source of truth

순환 import 회피 — `react.py → runtime_settings.py` 단방향:
- `runtime_settings.DEFAULT_MAX_ITERATIONS` / `DEFAULT_MAX_LOW_RELEVANCE_RETRIEVES` 정의.
- `react.py` 가 alias 로 재노출:
  ```python
  DEFAULT_MAX_ITERATIONS = _rs.DEFAULT_MAX_ITERATIONS  # 동일 이름
  MAX_LOW_RELEVANCE_RETRIEVES = _rs.DEFAULT_MAX_LOW_RELEVANCE_RETRIEVES  # 이름 다름 (7-4 호환)
  ```
- 외부 import (`from chat.services.agent.react import DEFAULT_MAX_ITERATIONS / MAX_LOW_RELEVANCE_RETRIEVES`) 호환 유지.

### Decision 5 — agent disabled 시 single_shot 폴백

운영자가 agent 끄는 시점 = incident 대응 시점. 사용자에게 답변이 안 가는 것 (UNSUPPORTED 카피) 보다 quality 낮은 답변이 가는 게 (single_shot) 사용자 경험 우수. Phase 7-2 의 폴백 패턴 재사용 — 코드 / 멘탈 모델 일관.

### Decision 6 — 즉시 반영, 캐시 없음

`load_runtime_settings()` 매 `run_agent` 호출마다 DB SELECT. agent 호출 빈도 (분당 1~2 회) 대비 SELECT 비용 무시 가능. TTL 캐시 도입은 BO 변경과 실제 적용 사이 5~30초 윈도우가 incident 시 부담이라 회피.

---

## 3. 사용자-가시 변화

| 시나리오 | Before | After |
|---|---|---|
| 정상 (default settings) | agent 답변 정상 | 변화 없음 |
| 운영자가 `enabled=False` 저장 | (BO 페이지 자체가 없음) | 다음 요청부터 agent 경로가 single_shot 으로 폴백 — 사용자에겐 답변은 가지만 quality 낮을 수 있음 |
| 운영자가 `max_iterations=2` 저장 | agent 가 6 step 까지 시도 | 2 step 만에 NOT_FOUND 종료 — 비용 절감, 다만 비교형 답변 정확도 ↓ |
| 운영자가 잘못된 값 (예: 99) 저장 시도 | (BO 페이지 자체가 없음) | Form validator 가 거부 + 한국어 에러 메시지. DB 갱신 안 됨 → 다음 요청은 이전 값으로 동작 |

---

## 4. 운영자-가시 변화

- **BO 사이드바에 `Agent 운영` 메뉴** 추가.
- **`/bo/agent/` 페이지** — 한 화면에 세 영역:
  1. 설정 폼 (enabled / max_iterations / max_low_relevance_retrieves)
  2. 최근 7일 호출 통계 카드 — `agent_step` / `agent_final` / `query_rewriter` (Phase 8-2 산물 활용)
  3. Tool 카탈로그 (읽기 전용 — 이름 / 설명 / 입력 모드 / failure_check 여부)
- **incident 대응 시간 절감**: 코드 수정 + 배포 절차 (~수십 분) → BO 폼 한 번 저장 (~10초).

---

## 5. 검증

### 단위 테스트

| 모듈 | 신규 케이스 |
|---|---|
| `test_agent_settings_model.py` | 7 (singleton 멱등 / save override pk=1 강제 + IntegrityError / CheckConstraint 위반 / Form validators 2) |
| `test_agent_runtime_settings.py` | 5 (정상 2 + DB 폴백 1 + sanity demote 2) |
| `test_agent_react_settings_inject.py` | 6 (max_iter inject 2 + max_low_rel inject 1 + 폴백 1 + alias 동일성 2) |
| `test_agent_node_disabled.py` | 2 (enabled=True 정상 / enabled=False 폴백) |
| `bo/tests.py` | 5 (GET 200 + form/catalog/stats / POST 정상 / POST validator / disabling / sidebar URL name) |
| **총합** | **25** |

총 449/449 그린 (Phase 8-2 종료 실측 424 → +25).

### 운영 환경 smoke

5 시나리오 시퀀스 (기존 + 본 PR 추가):

1. default 채팅 — 8-1 / 8-2 와 동일 동작 (회귀 0).
2. `/bo/agent/` 진입 — 폼 + 3 도구 catalog + 통계 노출.
3. `enabled=False` 저장 → 비교형 질문 → `INFO chat.graph.nodes.agent: agent 비활성 (AgentSettings.enabled=False) — single_shot 폴백`. 사용자 답변은 옴.
4. `max_iterations=2` 저장 → 비교형 질문 → 2 step 만에 NOT_FOUND.
5. POST `max_iterations=99` → 폼 에러 표시, DB 갱신 안 됨.

---

## 6. 후속 (Phase 8-4 polish)

- 8-1 plan 의 backlog (retrieve false positive — workflow 답변 시 무관 sources) 일괄 처리.
- 8-2 의 BO 대시보드에 purpose 분해 컬럼 추가.
- 8-3 의 `MAX_CONSECUTIVE_FAILURES` / `MAX_REPEATED_CALL` BO 노출.
- AgentSettings 변경 audit 로그.
- TokenUsage `cost_usd` 환산 (Phase 4-4 OpenAI Admin API 와의 통합).
- agent 관련 RouterRule 필터 / 보강.
- 사용자별 agent 정책 / tool 별 권한.

Phase 8 milestone 은 본 PR 머지로 closing — 8-4 polish 는 같은 milestone 안 추가 issue 들 또는 새 milestone 으로 결정.
