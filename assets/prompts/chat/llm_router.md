사용자 질문을 3가지 의도 중 하나로 분류하세요.

- single_shot: 사실/정의/조회 질문. 자료 검색 후 단발 답변으로 충분.
- workflow: 정형 계산·산정. 날짜 차이, 금액 합계, 표 조회 등 결정적 절차.
- agent: 비교·추천·예외·가설 시뮬레이션. 탐색 또는 도구 호출 필요.

JSON 으로만 출력:
{"route": "single_shot|workflow|agent", "reason": "한 줄 근거"}

workflow_key 는 출력하지 마세요. 운영자가 BO RouterRule 로 매핑합니다.
이전 대화가 주어지면 의도 판단에만 참고하세요.
