# 2026-04-29 개발 로그 — 2.0.0 Phase 9: 안정화 및 배포 준비

## 배경

Phase 8-6 머지로 agent 운영화 (Phase 8) 6 PR 모두 closed. 그러나 로드맵 §3 의 본 Phase 8 의도 (안정화 + 배포 준비) 는 별 phase 로 미진행. 본 phase 가 release 직전 회귀 검증 / 라우팅 정합 / 프롬프트 점검 / 문서 정리 / 배포 체크리스트 을 처리.

코드 변경 최소 — 검증 layer + 문서 중심.

---

## 1. 대표 질문셋

각 질문에 기대 라우트 / `workflow_key` / 응답 형태 / sources / TokenUsage purpose 분포.

### single_shot ×3

| # | 질문 | 기대 라우트 | 기대 응답 | 기대 sources | TokenUsage purpose |
|---|---|---|---|---|---|
| S1 | `경조사 규정 알려줘` | single_shot (default — 키워드 미매치) | 자료 기반 답변 (경조사 규정 PDF 인용) | 1~3 (`복리후생.pdf` 등) | `query_rewriter` (history) + `single_shot_answer` |
| S2 | `복리후생 항목별로 정리해줘` | single_shot (default) | 항목별 표 / 리스트 형태 답변 | 1~3 | `query_rewriter` (history) + `single_shot_answer` |
| S3 | `회사 휴가 종류 알려줘` | single_shot (default — `WORKFLOW_KEYWORDS` / `AGENT_KEYWORDS` 모두 미매치) | 자료 기반 휴가 종류 정리 | 1~3 | `query_rewriter` (history) + `single_shot_answer` |

### workflow ×3

> **전제**: BO `/bo/router-rules/` 에 다음 RouterRule 등록 — 미등록 시 `workflow_node` 가 single_shot 으로 폴백 (Phase 4-1 정책).

| RouterRule pattern | route | workflow_key |
|---|---|---|
| `며칠` | workflow | `date_calculation` |
| `합계` 또는 `더하면` | workflow | `amount_calculation` |
| `복리후생 규정에서` (또는 도메인 별) | workflow | `table_lookup` |

| # | 질문 | 기대 라우트 | 기대 응답 | TokenUsage purpose |
|---|---|---|---|---|
| W1 | `2025-01-01부터 2025-04-11까지 며칠?` | workflow (`date_calculation`) | "100일" (`days_between` 기준 — `2025-01-01` ~ `2025-01-31` = 30일 패턴 동일) | `query_rewriter` (history + text schema 없음으로 미발생 가능) + `workflow_extractor` |
| W2 | `100 + 50 합계는?` | workflow (`amount_calculation`) | "150" (만 단위 배율 없는 단순 합계) | `workflow_extractor` |
| W3 | `복리후생 규정에서 본인 결혼 경조금은?` | workflow (`table_lookup`) | 표 셀 추출 (예: "50만원") | `query_rewriter` + `workflow_extractor` + `workflow_table_lookup` |

### agent ×3

| # | 질문 | 기대 라우트 | 기대 응답 | 기대 sources | TokenUsage purpose |
|---|---|---|---|---|---|
| A1 | `본인 결혼 경조금이랑 자녀 결혼 경조금 비교해줘` | agent (db_rule:비교) | 비교 답변 + 출처 1~2개 | 1~2 | `query_rewriter` + `agent_step` × N + `agent_final` |
| A2 | `복리후생 규정과 취업규칙의 휴가 항목 비교` | agent | 다중 retrieve 비교 (또는 NOT_FOUND broad) | 0~2 | `query_rewriter` + `agent_step` × N + (`agent_final` 또는 NOT_FOUND) |
| A3 | `우주여행 비용 비교` | agent | NOT_FOUND ("자료를 찾을 수 없었습니다" — Phase 8-4 가드) | 0 | `query_rewriter` + `agent_step` × 1~3 (모두 low_relevance) |

### edge ×3

| # | 질문 | 기대 동작 |
|---|---|---|
| E1 | (빈 입력) | view 가 무시 또는 INSUFFICIENT_EVIDENCE — agent 진입 전 차단 |
| E2 | (1000자+ 긴 질문) | 라우터 분류 따라 정상 처리. token 비용 ↑ 정상 |
| E3 | `안녕하세요` | single_shot → 자료 없음 안내 ("회사 자료에 해당 정보가 없습니다") — 현재 정책 |

---

## 2. 회귀 체크리스트

자동 smoke 와 사용자-facing smoke 두 layer.

### 자동 smoke

| 영역 | 테스트 | 케이스 |
|---|---|---|
| 라우팅 e2e | `chat/tests/test_routing_e2e.py` | 9 (S1~3 + W1~3 + A1~3) — `route_question` 직접 호출. RouterRule fixture setUp 명시. |
| 파이프라인 smoke | `chat/tests/test_pipeline_smoke.py` | 9 — `run_chat_graph` end-to-end 노드 mock. `_compiled_graph.cache_clear()` setUp/tearDown. |
| 프롬프트 정합 | `bo/tests.py::PromptRegistryConsistencyTests` | 1 — `prompt_registry.all_entries()` 의 `relative_path` 가 모두 파일 존재. |

총 19 cases 신규.

### 사용자-facing smoke (수동, release 직전)

12 대표 질문 (위 §1 의 S/W/A/E) 모두 브라우저로 보내고:
- 라우트 (서버 로그 `INFO chat.graph.nodes.router: 라우팅: ...`)
- 응답 (위 §1 의 기대값 일치)
- sources 패널 (개수 / 출처 PDF 정합)
- TokenUsage purpose 분포 (BO `/bo/` 대시보드 Purpose 별 사용량 섹션)

---

## 3. 프롬프트 디렉터리 점검

`assets/prompts/chat/` 의 8 파일:

| 파일 | 사용 위치 | 상태 |
|---|---|---|
| `system.md` | `single_shot/prompting.py` 의 system 프롬프트 | 사용 중 |
| `agent_react.md` | `agent/prompts.py` 의 agent ReAct system | 사용 중 |
| `no_sources_guard.md` | `single_shot/prompting.py` 의 no-source guard | 사용 중 |
| `qa_instruction.md` | `single_shot/prompting.py` 의 QA cache 안내 | 사용 중 |
| `query_rewriter.md` | `services/query_rewriter.py` system | 사용 중 |
| `source_instruction.md` | `single_shot/prompting.py` 의 출처 안내 | 사용 중 |
| `table_lookup.md` | `workflows/domains/general/table_lookup.py` | 사용 중 |
| `workflow_input_extractor.md` | `services/workflow_input_extractor.py` | 사용 중 |

미사용 파일 0건. `prompt_registry.all_entries()` 의 `relative_path` 8개 모두 파일 존재 (테스트로 회귀 가드).

---

## 4. 배포 체크리스트

### 4-1. 마이그레이션

- 적용 범위: `0001_*` ~ `0015_agentsettingsaudit` (총 15개).
- production 적용 명령: `python manage.py migrate`.
- 사전 검증: `python manage.py migrate --plan` 으로 적용 순서 / 사이드 이펙트 확인.
- 데이터 영향:
  - `0011_tokenusage_purpose` — 기존 row default `'unknown'`.
  - `0012_agentsettings` — RunPython 으로 초기 1행 (default).
  - `0013_tokenusage_cost_usd` — 기존 row default `0`.
  - `0014_agentsettings_extra_limits` — 기존 row default 3 / 3.
  - `0015_agentsettingsaudit` — 빈 테이블 신규.
- maintenance window: 거의 instant (PostgreSQL 의 `ALTER TABLE ... ADD COLUMN ... DEFAULT ...` 빠름). 5초 이내 예상.
- 롤백: `python manage.py migrate chat <previous>`. 다만 데이터 손실 (cost_usd / purpose 등) 발생 — release 후엔 forward-only 권장.

### 4-2. 환경변수

| 변수 | 필수 | 용도 |
|---|---|---|
| `OPENAI_API_KEY` | ✅ | 모든 chat / embedding / rerank 호출 |
| `OPENAI_ADMIN_KEY` | 선택 | Phase 4-4 OpenAI usage widget (외부 청구). 미설정 시 BO 모달 503 + 안내 |
| `DATABASE_URL` | ✅ | PostgreSQL (pgvector 확장 포함) |
| `SECRET_KEY` | ✅ | Django |
| `DEBUG` | ✅ | production 은 `False` |
| `ALLOWED_HOSTS` | ✅ | production 도메인 |
| `OPENAI_MODEL` | 선택 | 기본 `gpt-4o-mini` |

### 4-3. 빌드 / 배포

- `Dockerfile` 기준 GHCR 이미지 빌드.
- `.github/workflows/` 의 release pipeline (Phase 0.x 부터 운영) 그대로 재사용.
- 태그 push (`v2.0.0`) → GitHub Actions → GHCR push → 운영 호스트 SSH pull + `docker compose up -d --build`.
- 사전 점검: `docker compose config` 로 compose 정합성 확인.

### 4-4. 데이터 backfill

- `TokenUsage.purpose` / `cost_usd` 의 기존 row 는 default 값으로 분류 — backfill 0.
- `AgentSettings` / `AgentSettingsAudit` 는 신규 테이블 — backfill 0.
- 운영 환경 RouterRule 은 8-1~8-6 동안 운영자가 직접 등록 — 본 phase 무영향.

### 4-5. 롤백 절차

| 시나리오 | 절차 |
|---|---|
| 코드 / 동작 회귀 | 이전 GHCR 이미지 태그로 복귀 (`docker compose pull <prev_tag> && up -d`) |
| 마이그레이션 회귀 | `python manage.py migrate chat <previous>` (단 데이터 손실 위험) |
| 응급 incident | BO `/bo/agent/` 에서 `enabled=False` 저장 → agent 라우트가 single_shot 폴백 (Phase 8-3 kill switch). 코드 롤백 없이 즉시 대응. |

### 4-6. 운영 모니터링

| 항목 | 위치 | 빈도 |
|---|---|---|
| TokenUsage 일별 합계 | `/bo/` 대시보드 | 일 1회 |
| Purpose 분포 / cost | `/bo/` 대시보드 §Purpose 별 사용량 | 주 1회 |
| OpenAI 외부 청구 | `/bo/` API 사용량 모달 (Phase 4-4) | 월 1회 |
| AgentSettings 변경 | `/bo/agent/` §Settings 변경 이력 | 변경 시 |
| Agent 호출 통계 | `/bo/agent/` §최근 7일 호출 통계 | 주 1회 |
| 컨테이너 로그 | `docker compose logs -f web` | incident 시 |
| 마이그레이션 상태 | `docker compose exec -T web python manage.py showmigrations chat` | 배포 후 1회 |

---

## 5. 후속 (release 후)

- **Phase 8-7 후보** — embedder / reranker `record_token_usage` 통합 → BO cost 가 외부 청구에 더 근접.
- **장기 backlog** — audit dedicated page / BO observability v2 / agent step timeline / `MAX_REPEATED_CALL` 정책 통합 / 한국어 형태소 분석기 / 외부 SaaS observability.
- **release tag** — 사용자 명시 요청 시 develop → main PR + `v2.0.0` 태그.
