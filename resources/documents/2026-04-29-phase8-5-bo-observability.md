# 2026-04-29 개발 로그 — 0.4.0 Phase 8-5: BO Observability — Purpose Breakdown & Cost

## 배경

Phase 8-4 머지 직후 (2026-04-29) 시점:

- Phase 8-2 가 `TokenUsage.purpose` 필드를 도입해 7 호출 사이트별 분류가 DB 에 쌓이지만, **BO 대시보드 가 이 데이터를 활용하지 않음** — 일별 / 전체 합계만 노출.
- `TokenUsage` 에 cost 필드 없음. 운영자가 비용을 추정하려면 외부 가격표를 봐야 함.
- Phase 4-4 OpenAI Admin API widget 이 cost 를 보여주지만 **외부 청구 기준** — 자체 추정과 데이터 소스가 다름. 두 표면이 분리돼 있어 비교 불가.

Phase 8-5 의 목표는 **TokenUsage 에 cost_usd 추가 + BO 대시보드의 purpose 분해 / cost 노출** 으로 운영자가 BO 한 화면에서 자체 추정 비용 / purpose 분해 / 일별 추이를 모두 볼 수 있게.

---

## 1. 패키지 구조 변화

```
chat/
  models.py                              ← TokenUsage.cost_usd DecimalField 추가
  migrations/
    0013_tokenusage_cost_usd.py          ← AddField + default 0
  services/
    openai_pricing.py                    ← 신규 — MODEL_PRICING + compute_cost_usd
    single_shot/postprocess.py           ← record_token_usage 가 cost 자동 계산 + 저장
  tests/
    test_openai_pricing.py               ← 신규 (9 cases)
    test_postprocess_record_token_usage.py  ← +2 cases (cost 자동 저장)

bo/
  views/dashboard.py                     ← daily_rows / totals 에 cost / 신규 purpose_rows / 한국어 라벨
  templates/bo/dashboard.html            ← 5 카드 + 비용 caption + 비용 컬럼 + Purpose 별 사용량 섹션
  tests.py                               ← DashboardViewTests 4 cases 신규
```

---

## 2. 핵심 결정

### Decision 1 — 단가 저장 위치: Python module 상수

DB 모델 / env var 대신 `chat/services/openai_pricing.py` 의 `MODEL_PRICING` dict. OpenAI 가격 변경 빈도가 분기에 한 번 정도라 코드 수정 + 배포로 충분. DB 도입은 audit 추적 / migration 부담 + BO 편집 UI 까지 가야 의미 — over-engineering.

### Decision 2 — cost 계산 시점: record 시점 DB 저장

`record_token_usage` 가 호출 직전에 `compute_cost_usd` 로 cost 계산해 row 에 저장. 시점 cost 보존 — 단가가 후에 바뀌어도 과거 row 의 cost 는 그 시점 단가 기준. 회계 / 청구 비교 시 정확.

### Decision 3 — Decimal 타입

`DecimalField(max_digits=12, decimal_places=6, default=0)`. 토큰당 cost 가 매우 작아 (`gpt-4o-mini input: $0.00000015 / token`) float 누적 오차가 N개월 운영 시 무시 못함. Python `Decimal` 로 정확도 우선.

### Decision 4 — 미등록 모델 fail-silent

`compute_cost_usd` 가 미등록 모델은 `Decimal('0')` + `logger.warning` 반환. 비용 추적이 답변 자체를 막지 않게. warning 로그가 미등록 모델 시그널 — 운영자가 발견 시 `MODEL_PRICING` 추가.

### Decision 5 — Phase 4-4 widget 과 의도적 분리

본 plan 의 cost 는 **`TokenUsage` 에 기록된 채팅 LLM 호출 비용의 추정치**:
- Phase 8-2 의 7 호출 사이트만 (single_shot_answer / query_rewriter ×3 / workflow_extractor / workflow_table_lookup / agent_step / agent_final).
- 모델 단가 매핑 × 토큰 수 (단순 곱).
- 할인 / 리베이트 / 캐시 hit 환급 미반영.
- **embedding (`files/services/embedder.py`) / reranker (`chat/services/reranker.py`) 호출 비용은 미포함** — 두 사이트가 record_token_usage 안 부름. Phase 8-7 후보.

Phase 4-4 widget 의 cost 는 **외부 청구 기준** (OpenAI Admin API):
- 모든 API 호출 + 할인 반영.
- "OpenAI 가 청구하는 정확 값".

두 데이터 소스 분리 의도. 운영자가 두 값을 비교해 자체 추정과 외부 청구 차이 (할인 효과 / 누락된 호출) 인지 가능. 본 plan 은 통합 안 함 — 같은 BO 페이지에서 분리 표시.

### Decision 6 — purpose 한국어 라벨: view 안의 dict

`single_shot_answer` → `single-shot 답변` 같은 mapping 은 view 안 dict (`_PURPOSE_LABELS`). 도메인 로직 (`token_purpose.py`) 과 분리. 미등록 purpose 는 영문 코드 그대로 fallback. 향후 다국어 / i18n 시 Django translation 으로 자연스럽게 이동.

### Decision 7 — purpose 별 표: observed-only (zero-fill 미도입)

`values('purpose')` 집계는 실제 row 가 있는 purpose 만 반환. 기간 동안 발생 안 한 purpose 는 표에 없음. zero-fill (모든 known purpose 를 0행 포함) 은 over-engineering — 운영자가 "이번 주 어떤 purpose 가 발생했나" 는 직관적으로 보면 됨. 빈 상태 안내 별도 (empty-state).

---

## 3. 사용자-가시 변화

**없음** — 8-5 는 운영자 표면. 사용자 답변 / UI 변화 없음.

---

## 4. 운영자-가시 변화

| 영역 | Before | After |
|---|---|---|
| BO `/bo/` 상단 카드 | 4개 (호출 / 총 토큰 / 입력 / 출력) | **5개** (+ 비용 USD, 자체 추정) |
| BO `/bo/` 일별 표 | 5 컬럼 (날짜 / 호출 / 입력 / 출력 / 총 토큰) | **6 컬럼** (+ 비용) |
| BO `/bo/` purpose 섹션 | 없음 | **신규** — 한국어 라벨 + 영문 코드 + 5 컬럼 (호출 / 입력 / 출력 / 총 토큰 / 비용). observed-only — 발생한 purpose 만. |
| 비용 caption | 없음 | "TokenUsage 에 기록된 채팅 LLM 호출 기준 자체 추정. embedding · reranker 미포함" 명시 |
| TokenUsage row 의 cost_usd | 없음 | **자동 저장** (record 시점 단가 lookup) |
| Phase 4-4 widget | 변화 없음 | 변화 없음 (의도적 분리) |

---

## 5. 검증

### 단위 테스트

| 모듈 | 신규 케이스 |
|---|---|
| `test_openai_pricing.py` | 9 (happy path 3 + 미등록 모델 2 + 0 토큰 1 + Decimal 정밀도 1 + MODEL_PRICING 멤버십 2) |
| `test_postprocess_record_token_usage.py` | +2 (cost 자동 저장 / 미등록 모델 0) |
| `bo/tests.py` (`DashboardViewTests`) | 4 (5 카드 + caption / purpose 섹션 / 빈 상태 / observed-only) |
| **총합** | **15** |

총 484/484 그린 (Phase 8-4 종료 실측 469 → +15).

### 운영 환경 smoke (5 시나리오)

1. **마이그레이션 적용 + 기존 row cost=0 확인**:
   ```bash
   docker compose exec -T web python manage.py migrate
   docker compose exec -T web python manage.py shell -c "
   from chat.models import TokenUsage
   pre = TokenUsage.objects.filter(cost_usd=0).count()
   total = TokenUsage.objects.count()
   print(f'cost=0: {pre}/{total}')"
   ```

2. **새 채팅 → cost 자동 저장**:
   - 브라우저에서 임의 질문 → 답변.
   - 최신 row 의 `cost_usd` 가 0 보다 큰 값.

3. **BO `/bo/` GET**:
   - 상단 5 카드 (호출 / 총 토큰 / 입력 / 출력 / 비용) 노출.
   - 비용 caption — "embedding · reranker 미포함" 명시.
   - 일별 표 비용 컬럼.
   - Purpose 별 사용량 섹션 — observed-only (발생한 purpose 만).

4. **미등록 모델 fail-silent** — shell 로 `compute_cost_usd('unknown', 1000, 500)` → `Decimal('0')` + warning 로그.

5. **Phase 4-4 widget 무회귀** — `API 사용량` 모달 정상 (외부 Admin API).

---

## 6. 후속 (Phase 8-6 / 8-7 후속)

- **Phase 8-6** — `MAX_CONSECUTIVE_FAILURES` / `MAX_REPEATED_CALL` BO 노출 (#4) + `AgentSettings` audit log (#5).
- **Phase 8-7 후보** — embedder.py / reranker.py 의 `record_token_usage` 통합. `embedding_*` / `reranker_*` purpose 추가 + `MODEL_PRICING` 에 embedding 모델 추가. 본 plan 의 BO cost 가 OpenAI 외부 청구 cost 에 더 근접하게.
- 단가의 BO 편집 / audit / Phase 4-4 widget 통합 / cost 알림 / cross-tab — 별 plan.
