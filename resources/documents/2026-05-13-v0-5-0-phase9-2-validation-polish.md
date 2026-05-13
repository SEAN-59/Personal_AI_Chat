# 2026-05-13 개발 로그 — v0.5.0 Phase 9-2: Validation + Polish

> **상위 플랜**: [`0.5.0_Phase_9-2_validation_polish_개발_플랜.md`](../plans/v_0_x/v_0_5_0/detail/0.5.0_Phase_9-2_validation_polish_개발_플랜.md)
> **선행 Phase**: [v0.5.0 Phase 9-1](./2026-05-13-v0-5-0-phase9-1-llm-router.md) (LLM Router 인프라)
> **Issue**: #76 (가설/전제 질문)
> **Branch**: `feature/76-v0-5-0-polish` → `develop`

---

## 1. 요약

- Phase 9-1 의 LLM Router 가 운영 의도대로 도는지 S1~S7 / R1·R2 수동 QA 시나리오 정리.
- **#76 종결**: query rewriter 가 "만약 5년 근무하면?" 같은 후속 질문의 전제(`5년`/`근무`) 를 erase 하지 않도록 prompt 규칙 + example + deterministic 테스트 가드 추가.
- README §3 (chat 앱), §7 (쿼리 파이프라인), §11 (개발 로그 표) 업데이트 — 4-tier 라우터 / `llm_router` / premise 보존 반영.
- 라우팅·LLM Router·workflow 코드는 손대지 않음 (Phase scope 준수).

---

## 2. 변경 파일

| 경로 | 변경 |
|---|---|
| `assets/prompts/chat/query_rewriter.md` | Rules 에 premise/hypothetical 보존 1줄 + Examples 에 `만약 5년 근무하면?` → `5년 근무 시 퇴직금 계산` 케이스 추가 |
| `chat/tests/test_query_rewriter.py` | `QueryRewriterPremiseTests` 신규 클래스 + 2 케이스 (`test_query_rewriter_prompt_contains_premise_rule`, `test_rewrite_query_with_history_returns_cleaned_llm_output`). patch target 은 `chat.services.query_rewriter._call_rewriter_llm` (call-site). 실제 LLM 호출 없음 |
| `README.md` | §3-1 chat 서비스 레이어에 `llm_router` 항목 추가 + `query_rewriter` 의 premise 보존 한 줄 보강. `question_router` 설명을 4-tier 로 갱신. §7 쿼리 파이프라인 앞에 라우팅 0 단계 추가. §11 개발 로그 표에 9-2 항목 추가 |
| `resources/documents/2026-05-13-v0-5-0-phase9-2-validation-polish.md` | 본 dev log 신규 |
| `resources/plans/v_0_x/v_0_5_0/detail/0.5.0_Phase_9-2_validation_polish_개발_플랜.md` | 본 Phase 세부 플랜 (Codex review 6 라운드 반영) |

**의도적으로 변경하지 않음**:
- `chat/services/question_router.py`, `chat/services/llm_router.py`, `chat/graph/nodes/*.py` — 라우팅 코드 동작 변경 금지 (Phase scope).
- `assets/prompts/chat/llm_router.md` — LLM Router 시스템 프롬프트는 운영 데이터 관측 전 변경 금지 (over-tuning 회피, 플랜 §10 리스크 표 참조).

---

## 3. 자동 테스트 결과 (Docker canonical)

> 명령: `docker compose exec -T web env OPENAI_API_KEY= python manage.py ...` — `OPENAI_API_KEY` 미설정 상태에서 오프라인 그린 확인 (call-site mock 동작 검증).

| # | 명령 | 결과 |
|---|---|---|
| 1 | `python manage.py check` | ✅ System check 0 issues |
| 2 | `test chat.tests.test_routing_e2e chat.tests.test_pipeline_smoke` | ✅ Ran 32 tests, OK |
| 3 | `test chat.tests.test_llm_router chat.tests.test_token_purpose` | ✅ Ran 30 tests, OK |
| 4 | `test chat.tests.test_query_rewriter` | ✅ Ran 7 tests, OK (기존 5 + 신규 `QueryRewriterPremiseTests` 2) |
| 5 | `test bo` | ✅ Ran 30 tests, OK (staticfiles UserWarning 무관, 정적 디렉토리 미수집 안내) |
| 6 | `test chat.tests.test_query_rewriter.QueryRewriterPremiseTests` (단독) | ✅ Ran 2 tests, OK |

> 모든 명령은 `--noinput --keepdb` 옵션과 함께 실행. (CI 와 동일하게 깨끗한 DB 가 필요하면 `--keepdb` 제거 후 `--noinput` 만 사용 — 기존 test DB 가 있으면 prompt 가 뜨므로 `--noinput` 만으로는 EOFError 가 난다. 본 실행은 로컬 `--keepdb` 로 시간 절약.)

---

## 4. 수동 QA 시나리오 (사용자 진행 완료 — 이상 없음)

> 사용자 브라우저 수동 QA 완료. 전 시나리오 통과 확인. §4-1 / §4-2 fix 적용 후 S1 / S1b 도 재검증 통과.
>
> 진입점: 루트 `/` (`AI_Chat/urls.py` 가 `path('', include('chat.urls'))`; 로컬 dev 는 `http://localhost:8001/`). BO dashboard 는 `/bo/`.

| # | 시나리오 | 기대 / 합격선 | 결과 |
|---|---|---|---|
| S1 | "경조사" → "비싼거" | rewriter 가 `경조사 중 가장 비싼 항목` 으로 치환, single_shot 응답 정상 | ✅ §4-1 fix 후 재검증 통과 — `본인 상 500만원` 정상 응답 |
| S1b | "경조사" → "2번째로 비싼거" | rewriter 가 `경조사 중 두 번째로 비싼 항목` 처럼 ordinal 보존, 표의 두 번째 행 응답 | ✅ §4-2 prompt+test 가드 후 재검증 통과 — `배우자 상 100만원` 정상 응답 |
| S2 | "경조사" → "이거 말고 더 있을건데?" | 메타-요청 인식 | ✅ 사용자 수동 QA 통과 |
| S3 | "본인 결혼?" → "자녀는?" | rewriter `자녀 결혼 경조금` 으로 치환 | ✅ 사용자 수동 QA 통과 |
| S4 | "퇴직금 계산식?" 단발 | rewriter NOOP, 정상 응답 | ✅ 사용자 수동 QA 통과 |
| S5 | 첫 질문 (history=[]) — 예: `회사 규정에서 반려동물 동반 가능 여부는?` (fallback: `사내 도서 구매 지원 기준은?`) | rewriter skip → Tier 3 LLM Router 진입 → BO dashboard `LLM 라우터` 카운트 +1 | ✅ 사용자 수동 QA 통과 |
| S6 | "퇴직금 비교 vs 계산 vs 정의" | reason `llm:...` 가 매번 잡힘 | ✅ 사용자 수동 QA 통과 |
| **S7** | **2-turn**: turn1 `퇴직금 계산식 알려줘` → turn2 `만약 5년 근무하면?` | route `agent` + premise 토큰 보존 | ✅ 사용자 수동 QA 통과 |
| R1 | "급여 지급일은?" | route `agent`, reason `date_condition_keyword`. dashboard `LLM 라우터` 카운트 불변 | ✅ 사용자 수동 QA 통과 |
| R2 | shell 임시 RouterRule `(pattern='지급일', route='workflow')` 등록 → `route_question` 호출 → `.delete()` | `route='workflow'`, `reason.startswith('db_rule:')` + cleanup 완료 | ✅ 사용자 수동 QA 통과 |

---

## 4-1. S1 수동 QA 실패 및 fix (#76 폴리시 추가분)

**증상**: turn1 `경조사` 정상 → turn2 `비싼거` 답변이 `회사 자료에 해당 정보가 없습니다.` 로 실패.

**원인**: `chat/services/single_shot/pipeline.py:run_single_shot()` 이 `query_rewriter` 결과 `search_query` 를 `retrieve_documents` / `find_canonical_qa` 입력에만 쓰고, 최종 `build_single_shot_messages(question, ...)` 에는 raw `비싼거` 만 넘김 → 답변 LLM 이 후속 질문 의도(`경조사 중 가장 비싼 항목`) 를 못 보고 no-info 분기로 빠짐.

**fix** (원본 질문은 UI / ChatLog 에 그대로 보존):

| 파일 | 변경 |
|---|---|
| `chat/services/prompt_builder.py` | `build_messages(..., *, search_query=None)` + `_render_user_content(..., *, search_query=None)`. `search_query.strip()` 가 비어있지 않고 raw question 과 다를 때만 `=== 사용자 질문 ===` 아래에 `원문: ...` + `대화 맥락 반영 질문: ...` 두 줄 렌더. 같거나 None 이면 기존 출력 동일 (회귀 0) |
| `chat/services/single_shot/prompting.py` | `build_single_shot_messages(..., *, search_query=None)` 시그니처 확장 → `build_messages` 로 forward |
| `chat/services/single_shot/pipeline.py` | `build_single_shot_messages(question, chunk_hits, qa_hits, history, search_query=search_query)` 로 호출. rewriter 가 NOOP/실패면 `search_query == question` 이라 builder 가 기존 출력 유지 |
| `chat/tests/test_prompt_builder.py` (신규) | 5 케이스: rewrite 다를 때 라인 추가 / 동일 시 누락 / None 시 누락 / whitespace-only 시 누락 / strip 비교 |
| `chat/tests/test_token_usage_purpose_call_sites.py` | `test_rewriter_search_query_passed_to_prompt_builder` 1 케이스 추가 — pipeline 이 `search_query='rewritten'` 을 builder 에 keyword 로 전달함을 단언 |

**계약**: rewriter 가 빈 history / NOOP / 예외 fallback 으로 raw 와 같은 문자열을 돌려주면 builder 의 분기가 자연 드롭 → 기존 동작과 byte-identical. 비교는 `strip()` 후 정확 일치만 본다 (대소문자/조사 변형은 분기 발동).

---

## 4-2. S1b 수동 QA 실패 및 fix — ordinal/ranking 보존

**증상**: turn1 `경조사` (표 정상) → turn2 `2번째로 비싼거` 응답이 `부모 상 50만원` (오답). 표 기준 정답은 `배우자 상 100만원`.

**원인 (로그)**: `chat.services.query_rewriter` INFO 로그 `쿼리 재작성: '2번째로 비싼거' → '부모 상 경조사 지원금'`. 즉 rewriter 가 ordinal 신호(`2번째`, `비싼`) 를 erase 하고 후보 행(`부모 상`) 으로 임의 확정 → retrieval 이 `부모 상` 청크만 잡고 답변 LLM 도 그대로 응답. §4-1 의 search_query 전달 fix 와 별개의 rewriter prompt 버그.

**fix (prompt + test 가드, 코드 동작 변경 없음)**:

| 파일 | 변경 |
|---|---|
| `assets/prompts/chat/query_rewriter.md` | Rules 에 ordinal/ranking 보존 규칙 1줄 추가 — `2번째 / 두 번째 / n번째 / 가장 / 최대·최소 / 비싼·싼 / 높은·낮은` 보존 + 후보 행 임의 확정 금지(`"부모 상"` 예시로 명시). Examples 에 `2번째로 비싼거` → `경조사 중 두 번째로 비싼 항목` 케이스 추가 |
| `chat/tests/test_query_rewriter.py` | `QueryRewriterPremiseTests` 에 2 케이스 추가 — (a) `test_query_rewriter_prompt_contains_ordinal_rule` (prompt content guard: 규칙 문구 + 부정 신호 `부모 상` + example 라인), (b) `test_rewrite_query_with_history_preserves_ordinal_in_cleanup` (cleanup 회귀 guard: `_call_rewriter_llm` mock 결과를 깎아먹지 않음) |

**계약**: 코드 동작은 변경 없음. ordinal 보존은 LLM 의 prompt 준수에 의존하며, prompt 파일이 silent 하게 회귀하면 (a) 가, cleanup pipeline 이 ranking 토큰을 깎아먹으면 (b) 가 차단한다. 사용자 manual S1b 재검증 통과 — 표의 두 번째 행 `배우자 상 100만원` 정상 응답.

---

## 5. 미해결 리스크

수동 QA 대기 리스크는 해소 (사용자 전 시나리오 통과 확인). 잔존 리스크는 일반 운영 리스크 한정:

| 리스크 | 상태 |
|---|---|
| LLM Router / rewriter prompt 가 운영 중 새 패턴에 약하게 반응 | observed-only dashboard (`LLM 라우터` purpose) 로 운영 데이터 누적 관측. 새 prompt 튜닝은 v0.5.x 후속 작업, 본 Phase 종결 시점에는 변경 금지 |
| prompt content guard 의 한계 | (a) prompt 파일이 silent 하게 회귀하면 `QueryRewriterPremiseTests` 가 차단. (b) cleanup pipeline 회귀는 `_call_rewriter_llm` mock guard 로 별도 차단. 단 실제 LLM 의 prompt 추종은 자동으로 보지 못함 — manual 회귀가 발견되면 후속 Phase 에서 케이스 추가 |

---

## 6. 부록 — 실 검증 실행 출력

```
$ docker compose exec -T web env OPENAI_API_KEY= python manage.py check
System check identified no issues (0 silenced).

$ docker compose exec -T web env OPENAI_API_KEY= python manage.py test --noinput --keepdb chat.tests.test_routing_e2e chat.tests.test_pipeline_smoke
Using existing test database for alias 'default'...
... router INFO 로그 다수 ...
----------------------------------------------------------------------
Ran 32 tests in 0.251s
OK

$ docker compose exec -T web env OPENAI_API_KEY= python manage.py test --noinput --keepdb chat.tests.test_llm_router chat.tests.test_token_purpose
... validate_purpose WARNING 2건 (의도된 음성 케이스) ...
----------------------------------------------------------------------
Ran 30 tests in 0.042s
OK

$ docker compose exec -T web env OPENAI_API_KEY= python manage.py test --noinput --keepdb chat.tests.test_query_rewriter
INFO chat.services.query_rewriter: 쿼리 재작성: '몇 일?' → '연차 일수'
INFO chat.services.query_rewriter: 쿼리 재작성: '만약 5년 근무하면?' → '5년 근무 시 퇴직금 계산'
----------------------------------------------------------------------
Ran 7 tests in 0.019s
OK

$ docker compose exec -T web env OPENAI_API_KEY= python manage.py test --noinput --keepdb bo
... staticfiles UserWarning (정적 미수집 안내, 무관) ...
----------------------------------------------------------------------
Ran 30 tests in 0.344s
OK

$ docker compose exec -T web env OPENAI_API_KEY= python manage.py test --noinput --keepdb chat.tests.test_query_rewriter.QueryRewriterPremiseTests
INFO chat.services.query_rewriter: 쿼리 재작성: '만약 5년 근무하면?' → '5년 근무 시 퇴직금 계산'
----------------------------------------------------------------------
Ran 2 tests in 0.004s
OK
```

> §4 의 `chat.services.query_rewriter` 로그 `쿼리 재작성: '만약 5년 근무하면?' → '5년 근무 시 퇴직금 계산'` 출현 = §3 표의 자동 가드가 cleanup pipeline 으로 premise 토큰을 깎아먹지 않음을 실증.
