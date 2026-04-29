from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models
from django.db.models import CheckConstraint, Q

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
    """OpenAI 호출별 토큰 사용량 로그 (대시보드 집계 원천).

    Phase 8-2: `purpose` 필드 추가 — 호출 목적을 코드 상수 (`chat.services.token_purpose`)
    기준으로 구분. CharField + db_index 라 분해 집계가 가벼움. 8-2 머지 이전 row 는
    default='unknown' 으로 일괄 분류. validate_purpose 방어망이 알 수 없는 값을
    'unknown' 으로 절감해 호출부 오타가 데이터 오염으로 직결되지 않게.
    """

    model = models.CharField(max_length=100)
    prompt_tokens = models.PositiveIntegerField(default=0)
    completion_tokens = models.PositiveIntegerField(default=0)
    total_tokens = models.PositiveIntegerField(default=0)
    purpose = models.CharField(max_length=32, default='unknown', db_index=True)
    # Phase 8-5: 채팅 LLM 호출 비용의 자체 추정치 (USD). 단가 매핑 × 토큰.
    # 시점 cost 보존 정책 — 단가가 후에 바뀌어도 과거 row 는 옛 값 그대로.
    cost_usd = models.DecimalField(max_digits=12, decimal_places=6, default=0)
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
        help_text=(
            '이 규칙을 알아볼 수 있는 이름을 적어주세요.\n'
            '예) "며칠 질문 보강", "복지포인트 오분류 제외"'
        ),
    )
    route = models.CharField(
        max_length=20,
        choices=Route.choices,
        help_text=(
            '이 규칙에 걸린 질문을 어떤 방식으로 처리할지 선택하세요.\n'
            '• single-shot — 바로 답변\n'
            '• workflow — 정해진 계산 흐름\n'
            '• agent — 상황 판단·비교'
        ),
    )
    match_type = models.CharField(
        max_length=20,
        choices=MatchType.choices,
        default=MatchType.CONTAINS,
        help_text=(
            '키워드를 질문과 어떻게 비교할지 정합니다.\n'
            '\n'
            '• 포함 — 질문 안에 키워드가 조각으로라도 들어 있으면 매치\n'
            '• 정확히 일치 — 질문이 키워드와 글자 그대로 똑같을 때만 매치\n'
            '• 정규식 — 키워드를 패턴 문법으로 해석해 매치\n'
            '• 제외 — 이 키워드가 있으면 오히려 규칙을 적용하지 않음'
        ),
    )
    pattern = models.CharField(
        max_length=256,
        help_text=(
            '질문에 포함되어 있으면 규칙이 걸리는 단어/문구를 적으세요.\n'
            '예) "퇴직금" → "퇴직금 얼마야?" 매치\n'
            '\n'
            '※ 앞뒤에 /, #, 따옴표 같은 기호를 붙이지 마세요.\n'
            '※ 띄어쓰기도 그대로 비교합니다 ("연차 계산"과 "연차계산"은 다름).\n'
            '※ 변형이 많으면 짧게 쪼개서 여러 규칙으로 등록하는 편이 안전합니다.'
        ),
    )
    workflow_key = models.CharField(
        max_length=64,
        blank=True,
        default='',
        help_text=(
            'route 가 "workflow" 일 때만 의미가 있습니다.\n'
            '어떤 generic workflow 로 보낼지 선택하세요 (Phase 6 부터).\n'
            '비워두면 workflow 경로이더라도 기존처럼 single_shot 으로 응답합니다.'
        ),
    )
    priority = models.IntegerField(
        default=100,
        help_text=(
            '숫자가 클수록 먼저 평가됩니다.\n'
            '• 일반 규칙: 100\n'
            '• 반드시 우선 적용할 규칙: 200 이상'
        ),
    )
    enabled = models.BooleanField(
        default=True,
        help_text=(
            '체크를 풀면 이 규칙을 무시합니다.\n'
            '(삭제하지 않고 잠시 꺼두는 용도)'
        ),
    )
    description = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-priority', '-updated_at']

    def __str__(self):
        flag = '' if self.enabled else ' [off]'
        return f'[{self.route}] {self.name} · "{self.pattern}"{flag}'


class AgentSettingsManager(models.Manager):
    """AgentSettings 의 hard singleton 접근 manager.

    `get_solo()` 가 pk=1 row 를 반환 — 없으면 default 로 생성. 어떤 환경에서도
    "settings 가 비어있다" 상태가 노출되지 않게 한다 (Phase 8-3 의 incident
    대응 가치 — runtime 이 항상 설정값을 갖고 있어야 함).
    """

    def get_solo(self) -> 'AgentSettings':
        obj, _ = self.get_or_create(pk=1)
        return obj


class AgentSettings(models.Model):
    """Agent runtime 의 BO 제어 설정 (Phase 8-3, hard singleton).

    pk=1 강제: `save()` override 가 `self.pk = 1` 로 덮어쓰므로 어떤 호출 경로
    (admin / shell / `objects.create(pk=N, ...)`) 도 결국 pk=1 으로 정렬되거나
    PK 충돌 IntegrityError 로 실패. extra row 는 절대 생성되지 않는다.

    `Meta.constraints` 의 두 `CheckConstraint` 가 DB-level guard — raw SQL /
    `.save()` 직접 호출도 범위 위반 시 IntegrityError. Form validators 는
    사용자-facing 한국어 에러 메시지 담당. runtime sanity check 는 마이그레이션
    누락 / 외부 데이터 dump 같은 극단 상황의 마지막 안전망.
    """

    enabled = models.BooleanField(
        default=True,
        help_text='체크를 풀면 agent 경로 진입 시 single_shot 으로 폴백합니다 (incident 대응용 kill switch).',
    )
    max_iterations = models.PositiveSmallIntegerField(
        default=6,
        validators=[MinValueValidator(1), MaxValueValidator(12)],
        help_text='ReAct loop 의 최대 iteration 수 (1~12). 작을수록 응답 빠르고 비용 절감, 클수록 복잡한 비교 질문 처리 가능.',
    )
    max_low_relevance_retrieves = models.PositiveSmallIntegerField(
        default=3,
        validators=[MinValueValidator(1), MaxValueValidator(10)],
        help_text='retrieve_documents 의 low_relevance 누적 한도 (1~10). 도달하면 NOT_FOUND 로 종료해 무관 자료 무한 재검색 차단.',
    )
    # Phase 8-6: 추가 한도 두 개 BO 노출.
    max_consecutive_failures = models.PositiveSmallIntegerField(
        default=3,
        validators=[MinValueValidator(1), MaxValueValidator(10)],
        help_text='연속 실패 한도 (1~10). 도달 시 NO_MORE_USEFUL_TOOLS 종료.',
    )
    max_repeated_call = models.PositiveSmallIntegerField(
        default=3,
        validators=[MinValueValidator(2), MaxValueValidator(10)],
        help_text=(
            '동일 (tool, args) 반복 호출 한도 (2~10). '
            '※ 현재는 8-3 의 즉시 차단 정책으로 동일 호출이 1회만 record 되어 '
            '본 값은 호환/기록용 — 변경해도 실제 동작 변화 거의 없음. '
            '정책 통합은 후속 Phase.'
        ),
    )
    updated_at = models.DateTimeField(auto_now=True)

    objects = AgentSettingsManager()

    class Meta:
        constraints = [
            CheckConstraint(
                check=Q(max_iterations__gte=1) & Q(max_iterations__lte=12),
                name='agentsettings_max_iterations_range',
            ),
            CheckConstraint(
                check=(
                    Q(max_low_relevance_retrieves__gte=1)
                    & Q(max_low_relevance_retrieves__lte=10)
                ),
                name='agentsettings_max_low_relevance_range',
            ),
            # Phase 8-6
            CheckConstraint(
                check=(
                    Q(max_consecutive_failures__gte=1)
                    & Q(max_consecutive_failures__lte=10)
                ),
                name='agentsettings_max_consecutive_failures_range',
            ),
            CheckConstraint(
                check=(
                    Q(max_repeated_call__gte=2)
                    & Q(max_repeated_call__lte=10)
                ),
                name='agentsettings_max_repeated_call_range',
            ),
        ]

    def save(self, *args, **kwargs):
        # Hard singleton — 어떤 호출 경로도 결국 pk=1 으로 정렬.
        # objects.create(pk=N, ...) 는 force_insert=True 로 진입 → pk=1 INSERT
        # 시도 → 기존 row 있으면 IntegrityError. 첫 호출이면 pk=1 INSERT 성공.
        # obj = AgentSettings(pk=99); obj.save() 는 force_insert=False 라 pk=1
        # 으로 UPDATE 또는 INSERT 자동 분기.
        self.pk = 1
        super().save(*args, **kwargs)

    def __str__(self):
        on = 'ON' if self.enabled else 'OFF'
        return f'AgentSettings({on}, max_iter={self.max_iterations}, max_low_rel={self.max_low_relevance_retrieves})'
