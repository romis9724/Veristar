"""재구성형 콘텐츠 생성 — 입력 statement를 요약·연표화한다.

규칙(CLAUDE.md §5, service-design §6):
- 입력은 반드시 official_nonsensitive() 게이트를 통과한 statement만.
- 출력에 입력 statement에 없던 사실이 생기면 안 된다(추론·평가·예측 금지).
- 새 정보 추가 없음 — 요약·정리·연표화·번역(형식 변환)만.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from veristar.graph import InMemoryGraphRepository, StatementFilter, timeline
from veristar.ontology.enums import Grade, Predicate, Status
from veristar.ontology.query import official_nonsensitive  # noqa: F401 (게이트 원칙 명시)

_PREDICATE_LABELS: dict[str, str] = {
    "memberOf": "소속",
    "affiliatedWith": "제휴",
    "appearedIn": "출연/참여",
    "released": "발매",
    "producedBy": "제작",
    "collaboratedWith": "협업",
    "nominatedFor": "후보",
    "wonAward": "수상",
    "presentedAt": "시상식",
    "hasRole": "역할",
}


@dataclass(frozen=True)
class SummaryResult:
    entity_id: str
    entity_name: str
    timeline_text: str
    summary_text: str
    statement_count: int
    source_ids: list[str] = field(default_factory=list)


def generate_timeline_text(
    repo: InMemoryGraphRepository,
    entity_id: str,
) -> str:
    """OFFICIAL 비민감 관계를 시간순 텍스트 연표로 재구성."""
    filt = StatementFilter(grades=frozenset({Grade.OFFICIAL}), statuses=frozenset({Status.ACTIVE}))
    views = timeline(repo, entity_id, filt)
    # official_nonsensitive gate: sensitive 제거
    views = [v for v in views if not v.statement.sensitive]
    if not views:
        return ""
    lines: list[str] = []
    for v in views:
        s = v.statement
        date_str = str(s.valid_from.year) if s.valid_from else "시기 미상"
        pred_label = _PREDICATE_LABELS.get(s.predicate.value, s.predicate.value)
        other_name = v.other.name if v.other else v.other_id
        qualifier_str = f" ({s.qualifier})" if s.qualifier else ""
        if s.valid_to:
            period = (
                f"{s.valid_from.year}~{s.valid_to.year}" if s.valid_from else f"~{s.valid_to.year}"
            )
        else:
            period = date_str
        lines.append(f"- {period}: {pred_label} — {other_name}{qualifier_str}")
    return "\n".join(lines)


def generate_summary(
    repo: InMemoryGraphRepository,
    entity_id: str,
) -> SummaryResult | None:
    """엔티티의 OFFICIAL 비민감 statement를 요약·연표로 재구성."""
    entity = repo.get_entity(entity_id)
    if entity is None:
        return None

    filt = StatementFilter(grades=frozenset({Grade.OFFICIAL}), statuses=frozenset({Status.ACTIVE}))
    views = timeline(repo, entity_id, filt)
    views = [v for v in views if not v.statement.sensitive]

    source_ids = sorted({sid for v in views for sid in v.statement.sources})
    timeline_text = generate_timeline_text(repo, entity_id)

    # 요약: 가장 중요한 사실들을 한 단락으로 재구성 (추론 없음 — 사실 나열)
    parts: list[str] = [f"{entity.name}({entity.type.value})의 공식 확인 정보."]

    members = [
        v for v in views if v.statement.predicate == Predicate.MEMBER_OF and v.direction == "in"
    ]
    if members:
        names = [v.other.name for v in members[:5] if v.other]
        if names:
            parts.append(f"멤버: {', '.join(names)}{'외' if len(members) > 5 else ''}.")

    awards = [v for v in views if v.statement.predicate == Predicate.WON_AWARD]
    if awards:
        award_list = []
        for v in awards[:5]:
            n = v.other.name if v.other else v.other_id
            yr = f"({v.statement.valid_from.year})" if v.statement.valid_from else ""
            ql = f" {v.statement.qualifier}" if v.statement.qualifier else ""
            award_list.append(f"{n}{ql}{yr}")
        parts.append(f"수상: {', '.join(award_list)}{'외' if len(awards) > 5 else ''}.")

    works = [
        v for v in views if v.statement.predicate in (Predicate.APPEARED_IN, Predicate.RELEASED)
    ]
    if works:
        work_names = [v.other.name for v in works[:4] if v.other]
        if work_names:
            parts.append(f"주요 작품: {', '.join(work_names)}{'외' if len(works) > 4 else ''}.")

    summary_text = " ".join(parts)
    return SummaryResult(
        entity_id=entity_id,
        entity_name=entity.name,
        timeline_text=timeline_text,
        summary_text=summary_text,
        statement_count=len(views),
        source_ids=source_ids,
    )
