# v0.5.5 — Retrieval Context Expansion (#91)

- Issue: #91 feat: Expand retrieval context for complete table answers
- Milestone: v0.5.5: Retrieval Context Expansion
- Plan: `resources/plans/v_0_x/v_0_5_5/detail/0.5.5_retrieval_context_expansion_개발_플랜.md`

## 무엇을 바꿨나

긴 표/목록 질문에서 상위 청크 일부만 답변에 들어가 행이 누락되던 문제를 줄이기 위해, single-shot retrieval 후 같은 문서의 인접 청크를 안전한 budget 안에서 확장하도록 했다.

- `retrieve_documents(question, *, expand_neighbors=True)` 로 확장 옵션을 추가했다.
- 표/목록형·전체 나열형·금액 비교형 질문에서만 document-local neighbor chunk 를 붙인다.
- agent tool 과 `table_lookup` workflow 는 기존 top-N/window 정책 유지를 위해 `expand_neighbors=False` 로 고정했다.
- `경조사에서 지급하는 모든 종류 알려줘` 류 질문이 범용어(`모든`, `종류`)에 끌려 엉뚱한 문서를 잡지 않도록 retriever keyword 정규화를 보강했다.

## 테스트 결과

- `docker exec ai_chat-web-1 python manage.py check` — 통과.
- focused tests — 123 tests OK.
- 전체 회귀 — 722 tests OK.
- 수동 QA — 경조사 전체 나열 / 금액 기준 비교 / 2번째 금액 비교 통과.
