# 2026-04-24 개발 로그 — 0.4.0 Phase 6-3: table_lookup + 남은 정책 다듬기

## 배경

Phase 6-1 이 dispatch 인프라 + `date_calculation` 을, Phase 6-2 가 `workflow_input_extractor` + `amount_calculation` 을 올려 자연어 질문이 workflow 경로까지 가고 답이 돌아오는 구조가 완성됐다. Phase 6-3 는 Phase 6 의 마지막 sub-phase로 두 가지를 묶어 처리한다:

1. **세 번째 generic workflow `table_lookup`** — 업로드된 문서의 표에서 사용자가 묻는 셀 값을 찾는다. 앞 두 workflow 와 달리 (a) retrieval 로 문서를 탐색하고 (b) LLM 이 후보 표 중에서 셀을 고른다. 출력은 여전히 결정적(문자열 하나)이라 workflow 범주.
2. **결과 status 정리** — Phase 6-1 의 `UNSUPPORTED` 하나가 "지원 안 함 / 자료 없음 / 일시 장애" 세 가지를 뭉뚱그리고 있어 reply · 관측 · 향후 재시도 정책에서 구분이 안 됐다. `NOT_FOUND` / `UPSTREAM_ERROR` 를 추가해 세 갈래를 나눈다.

아울러 retrieval 이 필요한 workflow 에 Phase 4-3 `query_rewriter` 를 재사용해 "그 표에서 제일 큰 금액" 같은 지시어 의존 후속 질문이 single_shot 과 동일한 맥락화를 받도록 했다.

---

## 1. 패키지 구조 변화

```
chat/
  graph/nodes/workflow.py                 # _schema_needs_retrieval + rewriter 통합
  services/
    prompt_registry.py                    # chat-table-lookup 프롬프트 등록
    workflow_input_extractor.py           # 'text' 필드 fallback
  workflows/
    core/
      result.py                           # NOT_FOUND / UPSTREAM_ERROR + 팩토리
      tables.py                           # 신규 — parse_markdown_tables / serialize_table
      __init__.py                         # parse_markdown_tables / serialize_table 재노출
    domains/
      field_spec.py                       # SUPPORTED_TYPES += ('text',)
      general/
        table_lookup.py                   # 신규 — 세 번째 generic workflow
        __init__.py                       # table_lookup import
      reply.py                            # NOT_FOUND / UPSTREAM_ERROR / _ok_table_lookup

assets/prompts/chat/
  table_lookup.md                         # 신규 — "표에서 셀 하나만 JSON 으로"
```

---

## 2. `FieldSpec.type = 'text'`

`SUPPORTED_TYPES` 에 `'text'` 를 추가했다. 의미:

- regex 단계에서는 아무 일도 하지 않는다. `'text'` 는 "질문 안에서 뽑을 부분" 이 아니라 "질문 자체" 를 담는 용도.
- extractor 는 date / number / money / enum / number_list 처리 직후, 그리고 LLM fallback **전에** `'text'` 필드를 처리한다. 아직 비어있으면 **질문 원문(strip)** 을 그대로 채움. 그 덕에 LLM fallback 은 required 필드가 더 없다고 판단하고 호출 자체를 스킵 → 추가 비용 0.
- `enum_values` 는 여전히 금지 (일관성).

`table_lookup` 이 이 타입을 최초 사용자. 스키마:

```python
INPUT_SCHEMA = {
    'query': FieldSpec(
        type='text',
        required=True,
        aliases=('query', '질문', '찾을 항목'),
    ),
}
```

---

## 3. 마크다운 표 파서 (`core/tables.py`)

Phase 5 core 의존 방향 원칙(순수 함수) 을 유지하는 새 헬퍼:

```python
def parse_markdown_tables(text: str) -> list[dict]:
    # [{'headers': [...], 'rows': [{h: cell, ...}, ...]}, ...]

def serialize_table(table: dict) -> str:
    # 재직렬화해 LLM 프롬프트에 canonical markdown 으로 넣음
```

- 구분자(`|---|---|`) 가 있는 블록만 표로 인정. 파이프만 들어간 산문은 무시.
- 셀 수 불일치는 빈 문자열로 패딩 → 호출측 KeyError 차단.
- 안전판: 한 입력에서 표 10 개, 한 표에서 행 200 개까지만.
- 파싱 결과는 workflow 내부 필터링·로그 용도, LLM 에는 `serialize_table` 로 재직렬화해 넣는다.

---

## 4. `WorkflowStatus` 확장

```python
class WorkflowStatus(str, Enum):
    OK = 'ok'
    MISSING_INPUT = 'missing_input'
    INVALID_INPUT = 'invalid_input'
    UNSUPPORTED = 'unsupported'
    NOT_FOUND = 'not_found'        # Phase 6-3
    UPSTREAM_ERROR = 'upstream_error'  # Phase 6-3
```

정리된 의미:

- `UNSUPPORTED` — 이 workflow 범위 밖의 요청 (미등록 key 등). `table_lookup` 은 이 status 를 쓰지 않는다.
- `NOT_FOUND` — workflow 는 정상 실행됐지만 질문에 맞는 데이터가 없음. **다음 행동 = 자료 추가 / 검색어 변경**.
- `UPSTREAM_ERROR` — LLM / 네트워크 / JSON 파싱 일시 실패. **다음 행동 = 재시도**. 향후 자동 재시도·모니터링 hook 이 이 status 를 기준으로 붙는다.

`WorkflowResult.not_found(reason)` / `.upstream_error(reason)` 팩토리도 함께 도입. 기존 호출처는 모두 불변.

---

## 5. `table_lookup.execute` 흐름

```
query
  ↓
retrieve_documents(query)      # single_shot 의 하이브리드 + reranker 재사용
  ↓
parse_markdown_tables(chunk)   # 표가 있는 청크만 남김
  ↓
표 0건? ──Yes──→ NOT_FOUND ('관련 문서 확인해 주세요')
  ↓ No
LLM cell picker                # {answer, source_document, matched_row, matched_column}
  ↓
예외?        ──Yes──→ UPSTREAM_ERROR ('잠시 후 다시 시도해 주세요')
JSON 파싱 실패? Yes→ UPSTREAM_ERROR
answer 없음? Yes→ NOT_FOUND ('항목 이름 / 질문 조금 바꿔 보세요')
  ↓ No
OK(value=<cell>, details={source_document, matched_row, matched_column})
```

**설계 의도 3 가지**

1. **retrieval 공용화**. raw `search_chunks` 가 아니라 single_shot 이 이미 외부 진입점처럼 쓰는 `retrieve_documents` 를 재사용. rerank 품질이 LLM 의 셀 선택 정확도에 직결된다. (장기적으로 `chat/services/retrieval.py` 승격 후보 — 이번 PR 은 import 경로 공유.)
2. **status 분리**. 위 도식의 세 실패 경로가 각기 다른 status 로 흘러간다 — reply 층에서 다른 문구를 만들고, 장래 재시도 정책이나 대시보드 지표가 붙을 자리가 생긴다.
3. **Reply 는 pass-through**. workflow 가 `details['reason']` 에 담은 친절한 문구를 reply 가 그대로 전달. reply.py 는 reason 없을 때만 status 별 generic 문구로 채운다 — "친절함의 책임을 workflow 쪽에 둔다" 원칙.

---

## 6. LLM 프롬프트 & 토큰 기록

프롬프트 파일: `assets/prompts/chat/table_lookup.md`. `prompt_registry` 에 `chat-table-lookup` 으로 등록돼 BO Prompt 페이지에서 바로 편집 가능.

핵심 규약:
- 출력은 **한 줄 JSON**, 스키마 키 `answer / source_document / matched_row / matched_column` 만 허용.
- 찾을 수 없으면 정확히 `{}` 반환 — 추정 금지.
- 셀 값은 **표 셀 그대로 복사**, 번역·패러프레이즈·문단 정보 사용 금지.

`TokenUsage` 는 LLM 호출이 실제로 일어나면 무조건 기록 (OK · 빈 응답 모두). 기록 자체가 실패해도 답변은 실패로 오염시키지 않는다.

---

## 7. history-aware rewrite 재사용

workflow_node 에 `_schema_needs_retrieval(schema)` 헬퍼를 추가했다. 정책:

- schema 에 `'text'` 타입 필드가 하나라도 있으면 retrieval-backed workflow 로 간주.
- **history 비면** rewriter 의 자체 short-circuit 이 LLM 호출 스킵.
- **history 있음 + text 필드 있음** → Phase 4-3 `rewrite_query_with_history` 가 한 번 돌아 자립 검색어로 변환. rewritten 질문이 extractor 로 들어가 `query` 에 주입되고, 곧 `retrieve_documents(rewritten)` 에 그대로 전달된다.
- `record_token_usage` 는 rewriter 가 실제 LLM 을 돌렸을 때만 호출.
- `date_calculation` / `amount_calculation` 은 text 필드가 없어 rewriter 호출 0 — 추가 비용 없음.

이후 workflow 수가 늘어 판정 기준이 복잡해지면 `WorkflowEntry.needs_retrieval: bool` 같은 명시 flag 로 리팩터 후보.

---

## 8. Reply 표 (Phase 6-3)

| status | 기본 문구 (reason 없을 때) | 사용자 다음 행동 |
|---|---|---|
| `OK` (`table_lookup`) | `"본인 상 · 금액: 500만원\n\n(출처: 경조사_규정.pdf)"` (또는 value 단독) | — |
| `MISSING_INPUT` | `"계산하려면 query 정보가 필요합니다."` | 질문 다시 |
| `INVALID_INPUT` | `"입력이 올바르지 않습니다.\n- {errors}"` | 입력 수정 |
| `NOT_FOUND` | `"요청에 맞는 자료를 찾지 못했습니다. 관련 문서가 업로드되어 있는지 확인해 주세요."` | 자료 추가 / 검색어 변경 |
| `UPSTREAM_ERROR` | `"일시적인 오류로 이번 요청을 처리하지 못했습니다. 잠시 후 다시 시도해 주세요."` | 재시도 |
| `UNSUPPORTED` | `"이 질문은 지원하는 workflow 에 해당하지 않습니다. 다른 방식으로 물어봐 주세요."` | BO 운영자가 rule 재검토 |

`details['reason']` 이 있으면 그걸 우선 사용. `table_lookup` 은 전 실패 경로에서 문구를 직접 제공하고 있어 실질적으로 reply 의 pass-through 만 쓴다.

---

## 9. 테스트

신규/확장 케이스 **24 개** 추가. 전체 `chat.tests` 는 **226/226 green**.

| 파일 | 추가 케이스 |
|---|---|
| `test_workflows_result.py` | 3 (not_found / upstream_error 팩토리 + 새 status 문자열 값) |
| `test_workflow_field_spec.py` | 2 (text 타입 + enum_values 금지) |
| `test_workflow_input_extractor.py` | 4 (text 필드 fallback · trim · default · mixed schema) |
| `test_workflow_tables.py` | 11 (빈 / 단일 / 다중 / 구분자 없음 / alignment / 셀 수 불일치 / limit / unicode / serialize round-trip) |
| `test_workflow_table_lookup.py` | 9 (MISSING_INPUT · registry · 표 없음 · 빈 hits · happy path · 빈 JSON · answer 없음 · LLM 예외 · JSON 파싱 실패) |
| `test_workflow_reply.py` | 6 (NOT_FOUND / UPSTREAM_ERROR / UNSUPPORTED 각 reason 유무 + table_lookup OK 포맷 2) |
| `test_workflow_node.py` | 6 (rewriter on/off 분기 4 + table_lookup e2e OK / NOT_FOUND 2) |

---

## 10. 수동 smoke 시나리오

- BO `/bo/router-rules/new/` → Workflow 도메인 드롭다운에 `"표 조회 (table_lookup)"` 노출.
- RouterRule `pattern='표' / route='workflow' / workflow_key='table_lookup'` 등록 후:
  - 표가 포함된 문서가 업로드된 상태에서 `"표에서 본인 상 경조금 알려줘"` → `"본인 상 · 경조금: 500만원\n\n(출처: 경조사_규정.pdf)"` 류.
  - 관련 문서 없을 때 → `"질문에 맞는 표를 찾지 못했습니다. 관련 문서가 업로드되어 있는지 확인해 주세요."`.
  - 같은 세션에서 앞서 경조사 얘기 후 `"그 표에서 제일 큰 금액"` → rewriter 가 자립 검색어로 변환 → retrieval 결과 정상.
  - 일시적으로 `OPENAI_API_KEY` 제거 → `"일시적인 오류로..."` 안내 + 크래시 없음.

---

## 11. 회귀 체크 포인트

- `date_calculation` / `amount_calculation` 응답 / 토큰 동작 변화 없음 — rewriter 호출 0.
- 기존 workflow_key 비어있는 RouterRule 의 single_shot 폴백 회귀 0.
- `UNSUPPORTED` 사용처 변화 없음 (dispatch 가 미등록 key 일 때만 사용).
- TokenUsage 기록은 rewriter 실제 호출 + extractor LLM fallback + table_lookup LLM 호출 세 경로 각각에서 독립적으로.

---

## 12. 남은 것 / Phase 6 이후

Phase 6 는 이 PR 로 완료한다. Phase 7 / 후속 Phase 에서 다룰 것:

- `document_compare` / `conditional_reasoning` / `multi_source_summary` 구현.
- Excel / 이미지 기반 표 OCR.
- 상대 날짜(`오늘 / 어제 / 이번 달`), 한글 수사(`천만 / 3억`).
- 멀티-턴 clarify loop ("어떤 행·열이요?").
- `UPSTREAM_ERROR` 에 대한 자동 재시도·관측 hook.
- `UNSUPPORTED` 전용 별도 route 타입 (현재는 결과 status 로만 표현).
- 회사 전용 도메인(`domains/company/*`).
- retrieval 을 `chat/services/retrieval.py` 공용 레벨로 승격 리팩터.
- Agent ReAct / tool calling (Phase 7).

---

## 13. Phase 6 완료 노트

- **6-1**: dispatch 인프라 + `date_calculation`.
- **6-2**: `workflow_input_extractor` (regex + LLM) + `amount_calculation`.
- **6-3**: `table_lookup` + `'text'` FieldSpec + `WorkflowStatus` 확장 + reply 세 분기 + Phase 4-3 query_rewriter 재사용.

Phase 6 설계 §5-1 (core vs domain 경계), §5-3 (workflow / agent / unsupported 경계), §7-3 (unsupported 메시지) 모두 실제 코드에서 의미를 갖게 됐다. history-aware retrieval 도 single_shot / workflow 양쪽에서 일관 동작.
