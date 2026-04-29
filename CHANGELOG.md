# Changelog

본 프로젝트의 변경 이력을 [Keep a Changelog](https://keepachangelog.com/ko/1.1.0/) 규칙에 따라 정리한다.

버전은 [SemVer](https://semver.org/lang/ko/) 정책. release 는 `release on demand` (사용자 명시 요청 시 develop → main + tag).

## [Unreleased] — 2026-04-29 시점 develop

### Phase 9 — 안정화 및 배포 준비 (in progress)

- **자동 회귀 가드** 신규 — 라우팅 e2e (`test_routing_e2e.py`) + 파이프라인 smoke (`test_pipeline_smoke.py`) + prompt registry 정합 (`PromptRegistryConsistencyTests`).
- 12 대표 질문셋 + 회귀 체크리스트 + 배포 체크리스트 dev log 정리.
- Phase 1~8 의 모든 dev log 인용한 본 CHANGELOG 신규.

---

## [0.4.0] — 미배포

> 0.3.x → 0.4.0 의 핵심 변화는 "단일 single-shot RAG → LangGraph 기반 3분류 (single_shot / workflow / agent) 운영 가능 구조" 로의 전환.

### Added (사용자 가시 변화)

- **3분류 라우팅** — 질문이 자동으로 `single_shot / workflow / agent` 중 하나로 분류되어 각자 최적화된 경로로 처리.
- **Workflow 답변** — 정형 계산형 질문 (날짜 / 금액 / 표 셀 조회) 이 LLM 추론 대신 결정론적 계산으로 답변. `date_calculation` / `amount_calculation` / `table_lookup` 세 도메인.
- **Agent 답변** — 비교형 / 다중 출처 통합형 질문이 ReAct loop 로 자료 다중 검색 후 합성. 출처 패널이 답변과 함께 노출 (Phase 8-1 — status 무관 노출 정책으로 NOT_FOUND 종료에도 검색된 출처 단서 유지).
- **Query rewriter** — 후속 질문 ("그 규정 자세히") 이 직전 대화 맥락을 반영해 self-contained 검색어로 자동 변환.
- **Snippet windowing** — 긴 청크에서 답이 401자+ 위치에 있어도 query 키워드 주변 윈도우를 LLM 에 전달 (Phase 7-3).
- **Retrieval relevance 강화** — 시간/숫자 토큰 (`2025년` / `100일` / `1일부터` / `날짜는`) 이 무관 PDF 와 매치돼 sources 에 잡음으로 노출되는 false positive 차단 (Phase 8-4).

### Added (운영자 가시 변화 — BO)

- **Prompt 관리 페이지** (`/bo/prompts/`) — `assets/prompts/chat/` 8 파일을 BO 에서 직접 편집 (Phase 1).
- **Router Rule 관리 페이지** (`/bo/router-rules/`) — RouterRule CRUD + bulk 액션 (활성화 / 비활성화 / 삭제) + 10건 단위 페이지네이션 (Phase 4-2 + Phase 8-3).
- **OpenAI 사용량 위젯** — `/bo/` 대시보드 우측 상단 `API 사용량` 모달 (외부 청구 기준, OpenAI Admin API) (Phase 4-4).
- **Agent 운영 제어** (`/bo/agent/`) — agent kill switch (`enabled`) / `max_iterations` / `max_low_relevance_retrieves` / `max_consecutive_failures` / `max_repeated_call` 5 한도 + tool catalog (읽기 전용) + 최근 7일 호출 통계 + Settings 변경 audit 로그 (Phase 8-3 + 8-6).
- **TokenUsage purpose 분리 + 비용 추적** — 7 호출 사이트별 purpose 분류 + 모델 단가 매핑 × 토큰으로 자체 추정 비용 (USD) 자동 저장 (Phase 8-2 + 8-5). BO 대시보드 `Purpose 별 사용량` 섹션 (5건 단위 페이지네이션).
- **공용 BO JS** — shake / auto-dismiss / bulk action 패턴이 `bo/static/bo/bo.js` 단일 파일로 통합 (Phase 8-4). `data-bulk-*` 마크업 규약으로 새 BO 페이지가 boilerplate 0.

### Changed

- **검색 진입점** — 기존 `answer_question()` → LangGraph `run_chat_graph(question, history)`. view / service 가 한 함수만 호출 (Phase 2).
- **프롬프트** — 코드 하드코딩 → `assets/prompts/chat/*.md` 외부 파일 + `prompt_loader` (Phase 1).
- **Workflow / agent 결과 구조** — `WorkflowResult` 외에 `AgentResult` 1급 dataclass 도입. `BaseResult` Protocol 로 공통 인터페이스 (Phase 8-1).
- **TokenUsage 모델** — `purpose` (CharField, 8-2) / `cost_usd` (DecimalField, 8-5) 두 필드 추가. 마이그레이션 `0011` / `0013`.
- **AgentSettings 모델** — Phase 8-3 도입 + 8-6 의 `max_consecutive_failures` / `max_repeated_call` 두 필드 추가. 마이그레이션 `0012` / `0014`.
- **AgentSettingsAudit 모델** — Phase 8-6 신규. 마이그레이션 `0015`.

### Fixed (0.3.x 회귀)

- **후속 질문 잡음** — `비싼거` 같이 맥락 의존 질문이 무관 PDF 와 매치되던 문제. Phase 4-3 query rewriter 로 해소.
- **인사말 잡음** — `안녕하세요` 같은 짧은 답변에 출처 / 피드백 / ChatLog 가 잘못 표시되던 문제. `classify_reply` 의 `_CASUAL_MARKERS` 분류로 해소.

### Migration / Deployment

- 마이그레이션 누계: `0001` ~ `0015` (15개).
- 환경변수 추가: `OPENAI_ADMIN_KEY` (선택, Phase 4-4 의 widget 용).
- pgvector 확장 필요 (Phase 0 시점부터).

### Out of scope (0.4.0 release 이후)

- Phase 8-7 후보 — embedder / reranker `record_token_usage` 통합 → BO cost 가 외부 청구에 더 근접.
- 장기 backlog — audit dedicated page / BO observability v2 / agent step timeline / `MAX_REPEATED_CALL` 정책 통합 / 한국어 형태소 분석기 / 외부 SaaS observability.

---

## [0.3.x] — 이전 버전

0.3.x 시리즈는 단일 single-shot RAG 챗봇. 변경 이력은 git history 참조.

- 대표 일자별 dev log: `resources/documents/2026-04-22-deploy.md` 등.
