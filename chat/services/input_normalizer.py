"""v0.5.2 — BO 등록 규칙 기반 입력 정규화 서비스.

설계 요약 (plan §6):
- raw 질문은 절대 덮어쓰지 않는다 (caller 는 raw 와 normalized 를 둘 다 들고 다님).
- single best rule 정책: 한 번의 normalize() 호출에서 최대 1개 규칙만 적용.
  exact 매치가 1건이라도 있으면 (priority DESC, id ASC) 1건 적용 후 즉시 종료.
  exact 가 없을 때만 contains 후보 중 (priority DESC, id ASC) 1건을 첫 1회 치환.
- 비교 키는 모두 `canonicalize()` (NFKC + strip + casefold). model.save() 가
  pattern 을 canonical 형태로 저장하므로 service 는 question 만 canonicalize 하고
  rule.pattern 은 그대로 비교.

다중 적용 / fixed-point / MAX_APPLIES 는 v0.5.2 스코프 비포함 — 후속 이슈.
"""

from dataclasses import dataclass, field, asdict
from typing import List

from chat.utils.text_normalization import canonicalize


@dataclass(frozen=True)
class AppliedRule:
    """matched rule 한 건의 메타 (debug/log 용)."""
    id: int
    pattern: str
    replacement: str
    match_type: str


@dataclass
class NormalizationResult:
    raw: str
    normalized: str
    applied: List[AppliedRule] = field(default_factory=list)
    changed: bool = False

    def applied_as_dicts(self) -> list[dict]:
        return [asdict(a) for a in self.applied]


def normalize(question: str) -> NormalizationResult:
    """BO 규칙으로 question 정규화. 매치 없으면 raw 그대로 반환.

    빈 입력/공백 only → no-op. 활성 규칙 0건 → no-op.
    """
    raw = question or ''
    if not raw.strip():
        return NormalizationResult(raw=raw, normalized=raw)

    # lazy import — Django app registry 순서 영향 방지 (RouterRule 패턴 동일).
    from chat.models import InputNormalizationRule

    rules = list(
        InputNormalizationRule.objects
        .filter(enabled=True)
        .order_by('-priority', 'id')
    )
    if not rules:
        return NormalizationResult(raw=raw, normalized=raw)

    q_canon = canonicalize(raw)

    # Step 1 — exact 우선. 매치 1건 발견 시 즉시 종료.
    for rule in rules:
        if rule.match_type != InputNormalizationRule.MatchType.EXACT:
            continue
        if not (rule.replacement or '').strip():
            # 2중 가드 — model.clean() 에서 막지만 비활성 우회 케이스 대비.
            continue
        if q_canon == rule.pattern:
            return NormalizationResult(
                raw=raw,
                normalized=rule.replacement,
                applied=[_to_applied(rule)],
                changed=True,
            )

    # Step 2 — contains (exact 미매치 일 때만).
    for rule in rules:
        if rule.match_type != InputNormalizationRule.MatchType.CONTAINS:
            continue
        if not (rule.replacement or '').strip():
            continue
        if rule.pattern and rule.pattern in q_canon:
            normalized = q_canon.replace(rule.pattern, rule.replacement, 1)
            return NormalizationResult(
                raw=raw,
                normalized=normalized,
                applied=[_to_applied(rule)],
                changed=True,
            )

    return NormalizationResult(raw=raw, normalized=raw)


def _to_applied(rule) -> AppliedRule:
    return AppliedRule(
        id=rule.pk,
        pattern=rule.pattern,
        replacement=rule.replacement,
        match_type=rule.match_type,
    )
