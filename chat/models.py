from django.db import models

from pgvector.django import HnswIndex, VectorField

# 임베딩 차원 (text-embedding-3-small 기준)
EMBEDDING_DIM = 1536


class ChatLog(models.Model):
    """모든 채팅 대화 기록.

    - 회사 자료 기반으로 답변한 모든 Q&A가 여기에 쌓임.
    - 사용자 엄지 피드백이 연결됨.
    - RAG 검색 대상은 아니다 (CanonicalQA만 검색됨).
    - 관리자가 이 중 "좋은 답변"을 CanonicalQA로 승격시킨다.
    """

    question = models.TextField()
    question_embedding = VectorField(dimensions=EMBEDDING_DIM)
    answer = models.TextField()
    # 답변 생성 시 참조했던 Document id 목록
    sources = models.JSONField(default=list, blank=True)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        ordering = ['-created_at']
        indexes = [
            HnswIndex(
                name='chatlog_q_emb_hnsw',
                fields=['question_embedding'],
                m=16,
                ef_construction=64,
                opclasses=['vector_cosine_ops'],
            ),
        ]

    def __str__(self):
        return self.question[:50]


class CanonicalQA(models.Model):
    """관리자가 큐레이션한 공식 Q&A.

    - RAG 검색 대상: search_canonical_qa가 여기서 유사 질문을 찾는다.
    - ChatLog에서 "승격" 액션으로 생성되거나, 직접 만들 수도 있다.
    - source_chatlog: 어떤 ChatLog에서 승격됐는지 (nullable, SET_NULL로 유지)
    """

    question = models.TextField()
    question_embedding = VectorField(dimensions=EMBEDDING_DIM)
    answer = models.TextField()
    sources = models.JSONField(default=list, blank=True)
    source_chatlog = models.ForeignKey(
        ChatLog,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name='promotions',
    )
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        ordering = ['-created_at']
        indexes = [
            HnswIndex(
                name='canonical_q_emb_hnsw',
                fields=['question_embedding'],
                m=16,
                ef_construction=64,
                opclasses=['vector_cosine_ops'],
            ),
        ]

    def __str__(self):
        return self.question[:50]


class Feedback(models.Model):
    """사용자의 엄지 피드백 (ChatLog 단위로 누적)."""

    class Rating(models.TextChoices):
        UP = 'up', '좋음'
        DOWN = 'down', '나쁨'

    chat_log = models.ForeignKey(
        ChatLog,
        null=True,
        on_delete=models.CASCADE,
        related_name='feedbacks',
    )
    rating = models.CharField(max_length=10, choices=Rating.choices)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f'{self.rating} for ChatLog {self.chat_log_id}'


class TokenUsage(models.Model):
    """OpenAI 호출별 토큰 사용량 로그 (대시보드 집계 원천)."""

    model = models.CharField(max_length=100)
    prompt_tokens = models.PositiveIntegerField(default=0)
    completion_tokens = models.PositiveIntegerField(default=0)
    total_tokens = models.PositiveIntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f'{self.model} / {self.total_tokens} tok @ {self.created_at:%Y-%m-%d %H:%M}'


class RouterRule(models.Model):
    """2.0.0 Phase 4-2 — 운영자가 BO에서 관리하는 라우팅 rule.

    question_router.route_question 은 이 모델을 먼저 조회하고, 매치가 없을 때만
    코드 상수(WORKFLOW_KEYWORDS / AGENT_KEYWORDS)로 fallback 한다. DB 가
    비어있으면 Phase 4-1 동작 그대로.

    Route.choices 값은 chat.graph.routes 의 ROUTE_* 상수와 **동일한 리터럴**
    ('single_shot' / 'workflow' / 'agent'). 둘 중 하나를 바꾸면 다른 쪽도 반드시
    맞춰야 한다.
    """

    class Route(models.TextChoices):
        SINGLE_SHOT = 'single_shot', 'single-shot'
        WORKFLOW = 'workflow', 'workflow'
        AGENT = 'agent', 'agent'

    class MatchType(models.TextChoices):
        CONTAINS = 'contains', '포함 (contains)'
        # regex / exact / negative 는 Phase 4-2 이후 확장 후보.

    name = models.CharField(
        max_length=100,
        help_text='운영자 식별용 이름 (예: "며칠 보강", "복지포인트 오분류 제외")',
    )
    route = models.CharField(
        max_length=20,
        choices=Route.choices,
        help_text='매치 시 보낼 route',
    )
    match_type = models.CharField(
        max_length=20,
        choices=MatchType.choices,
        default=MatchType.CONTAINS,
    )
    pattern = models.CharField(
        max_length=256,
        help_text='매칭할 키워드/패턴 (match_type 에 따라 해석)',
    )
    priority = models.IntegerField(
        default=100,
        help_text='숫자가 클수록 먼저 평가. 기본값 100, 매우 중요한 rule 은 200+ 권장',
    )
    enabled = models.BooleanField(
        default=True,
        help_text='체크 해제하면 router 가 이 rule 을 건너뜀 (삭제 없이 무력화)',
    )
    description = models.TextField(
        blank=True,
        help_text='이 rule 을 추가한 이유·배경 메모',
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-priority', '-updated_at']

    def __str__(self):
        flag = '' if self.enabled else ' [off]'
        return f'[{self.route}] {self.name} · "{self.pattern}"{flag}'
