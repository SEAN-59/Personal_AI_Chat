# 2026-04-24 개발 로그 — 0.4.0 Phase 4-4: OpenAI 사용량 위젯

## 배경

BO 대시보드는 우리 서비스가 직접 `TokenUsage` 에 기록한 **내부 집계**만 보여주고 있었다. OpenAI 가 실제로 청구 기준으로 삼는 **조직 전체 사용량**(+ 비용)을 앱 안에서 확인할 방법이 없었다 — 운영자는 OpenAI Dashboard 웹으로 따로 들어가야 했다.

Phase 4-4 는 대시보드 타이틀 우측에 버튼 하나를 추가해, 클릭하면 화면 중앙에 **모달 팝업**이 열리고 그 안에서 OpenAI Admin API 로 집계한 **전체 누적 / 최근 7일 / 모델별 분해 + 비용** 을 보여준다. 기존 카드·일별 표는 그대로 둔다 — 둘의 역할이 다르기 때문이다:

| | 내부 `TokenUsage` | OpenAI Usage API |
|---|---|---|
| 정확도 | 호출 단위 정밀 | 일 버킷 집계 |
| 범위 | 우리 서비스 호출만 | 조직 전체 |
| 지연 | 실시간 | 수 분 지연 |
| 용도 | 기능별 관측 | 청구 기준 실사용량 |

---

## 1. 패키지 구조

```
chat/
  services/
    openai_usage.py              # 신규 — Admin API 클라이언트 + 집계
  tests/
    test_openai_usage.py         # 신규 — 4 케이스 (키 부재 / 집계 / 빈 / 모델별)
bo/
  views/
    openai_usage.py              # 신규 — JSON 엔드포인트
    __init__.py                  # export 추가
  urls.py                        # /api/openai-usage/ path 추가
  static/bo/
    bo.css                       # MODAL 섹션 포트 + 토큰 보강
  templates/bo/
    dashboard.html               # 버튼 + 모달 + 인라인 JS
```

---

## 2. 서비스 레이어 (`chat/services/openai_usage.py`)

진입점은 `fetch_usage_summary()` 하나. 내부에서 세 엔드포인트를 호출한다:

- `GET /v1/organization/usage/completions` — chat completion 토큰
- `GET /v1/organization/usage/embeddings` — 임베딩 토큰
- `GET /v1/organization/costs` — 달러 비용

**두 개의 시간축**
- **전체 누적**: `start_time = 2026-01-01 00:00 UTC` (운영 시작 시점 + Usage API 보유 범위)
- **최근 7일**: `start_time = now - 6d` 의 자정

**HTTP 는 stdlib `urllib.request`** 로 처리 — `requests` 를 명시적 의존성으로 추가하지 않는다. 페이지네이션은 `has_more` + `next_page` 를 순회하며 `MAX_PAGES=20` 안전판.

**오류 체계**
- `AdminKeyMissing` — `OPENAI_ADMIN_KEY` 미설정 (503 으로 매핑)
- `UsageAPIError(code, message, status)` — 502 로 매핑
  - `code='unauthorized'` → Admin 키 거부(401)
  - `code='upstream_failed'` → 네트워크 실패 / 5xx
  - `code='bad_payload'` → 응답 JSON 파싱 실패

**빈 버킷 처리 주의점**
`results=[]` 인 빈 버킷에 `setdefault` 가 먼저 걸려 `1970-01-01` 같은 가짜 행이 생기던 버그가 초기에 있었다. 현재는 **`for result in results:` 루프 안에서만** 날짜 키를 생성해 활동 없는 날은 집계에서 제외.

---

## 3. BO 엔드포인트 (`bo/views/openai_usage.py`)

`GET /bo/api/openai-usage/` — `require_GET`. 서비스 예외를 상태코드에 매핑한다:

```python
try:
    summary = fetch_usage_summary()
except AdminKeyMissing as exc:
    return JsonResponse({'error': 'admin_key_missing', 'message': str(exc)}, status=503)
except UsageAPIError as exc:
    return JsonResponse({'error': exc.code, 'message': str(exc)}, status=502)
except Exception:
    logger.exception(...)
    return JsonResponse({'error': 'unexpected', ...}, status=500)
```

모달은 `res.ok == false` 인 경로에서 `data.error` 를 읽어 친절한 한국어 타이틀로 치환.

---

## 4. 모달 컴포넌트

`assets/guides/ui/DesignGuideline.html:387-398` 의 모달 섹션 전체를 `bo/static/bo/bo.css` 로 포트. 추가로:

- `.modal.modal-wide { width: 720px; }` — 카드·표가 여럿인 본 위젯용
- `.modal-body { max-height: 80vh; overflow: auto; }` — 본문만 스크롤

동시에 bo.css 에 비어 있던 토큰들(**`--shadow-lg`, `--shadow-xl`, `--transition-slow`, `--z-dropdown/--z-sticky/--z-overlay/--z-modal/--z-toast`**)을 가이드라인 값 그대로 채워 향후 다른 위젯(drawer / sheet / tooltip)을 붙일 때도 기본 토큰이 준비돼 있게 했다.

---

## 5. 모달 UI 구성

```
┌───────────────────────────────────────────────┐
│  API 사용량                                ×  │
├───────────────────────────────────────────────┤
│  [ 전체 누적 ]                                 │
│  입력 · 출력 · 총 · 비용 (4 카드)               │
│                                               │
│  [ 최근 7일 ]                                  │
│  입력 · 출력 · 총 · 비용 (4 카드)               │
│  일별 테이블 (날짜 / 입력 / 출력 / 합계 / 비용) │
│                                               │
│  [ 최근 7일 · 모델별 ]                         │
│  모델 | 토큰 수 (내림차순)                     │
├───────────────────────────────────────────────┤
│                                     [ 닫기 ]  │
└───────────────────────────────────────────────┘
```

닫기 경로 세 가지: × 버튼 / 백드롭 클릭 / ESC. 렌더는 서버 JSON 을 그대로 받아 템플릿 리터럴로 DOM 구성, XSS 방지용 `esc()` 로 모든 동적 문자열 이스케이프.

에러 상태는 공통 `renderError(code, message)` 하나로 통일 + `다시 시도` 버튼 제공.

---

## 6. 테스트

`chat/tests/test_openai_usage.py` — OpenAI 실제 호출 없이 `_get_json` 을 mock:

- `test_missing_admin_key_raises_controlled_error` — `OPENAI_ADMIN_KEY=''` → `AdminKeyMissing`
- `test_aggregates_totals_across_endpoints` — completions + embeddings + costs 를 합산해 `total` 정확히 계산
- `test_handles_empty_result_list` — `results: []` 인 날은 빈 표·빈 모델 목록으로 정제
- `test_by_model_ordering_and_aggregation` — 모델별 집계는 토큰 내림차순, 같은 버킷 내 여러 모델 처리

```
Ran 4 tests in 0.006s
OK
```

---

## 7. 검증

### 자동
- `docker compose exec -T web python manage.py check` 통과
- `docker compose exec -T web python manage.py test chat.tests.test_openai_usage` 전건 OK

### 수동 (브라우저)
- [ ] `/bo/` 접속 → 타이틀 우측에 `API 사용량` 버튼
- [ ] 버튼 클릭 → 모달 중앙 오버레이 + 로딩 → 데이터 렌더
- [ ] 전체 누적 카드 4 개 / 최근 7일 카드 4 개 / 일별 7 행 / 모델별 분해 모두 채워짐
- [ ] × / 백드롭 / ESC 세 경로 모두 정상 닫힘
- [ ] `.env` 에서 `OPENAI_ADMIN_KEY` 주석 처리 후 재시작 → 모달에 "Admin 키가 설정되지 않았습니다" + `다시 시도` 버튼

### 회귀
- 기존 대시보드 카드·일별 표는 변경 없음 (추가 전용)
- `TokenUsage` 와 모달의 "최근 7일" 사이 **차이가 있을 수 있음** 이 정상 (범위·지연 차이)

---

## 8. Out of Scope (Phase 5 이후)

- 캐시(TTL / 수동 refresh)
- 기간 선택 드롭다운 / custom range
- 프로젝트·사용자·API 키 단위 분해
- 비용 경보·예산 한도
- 막대·추이 차트
- 모델별 비용 분해 (`/costs` 에 `group_by=model` 미지원 → rates 기반 추정은 별도)
