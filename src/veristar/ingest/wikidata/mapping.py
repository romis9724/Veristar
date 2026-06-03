"""Wikidata 속성·QID → Veristar 온톨로지 매핑 설정.

매핑을 주입 가능한 dataclass로 둔다:
- 테스트는 합성 QID로 자체 매핑을 만들어 실제 Wikidata QID 정확성에 의존하지 않는다.
- 운영 기본값(DEFAULT_MAPPING)은 best-effort이며, ⚠️ 라이브 Wikidata 대조로 검증·확장해야 한다.

화이트리스트에 없는 속성(배우자 P26·파트너 P451 등 관계·사생활)은 매핑하지 않는다 = 민감 필터.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from veristar.ontology.enums import EntityType, Predicate

WD_PREFIX = "wd:"


def qid_to_id(qid: str) -> str:
    """'Q42' → 'wd:Q42'. 이미 접두사가 있으면 그대로."""
    return qid if qid.startswith(WD_PREFIX) else f"{WD_PREFIX}{qid}"


@dataclass(frozen=True)
class WikidataMapping:
    """Wikidata 매핑 규칙. 모든 필드는 주입 가능."""

    instance_of: str = "P31"
    # P31 값 QID → EntityType (Q5=human은 확실, 나머지는 ⚠️ 검증 필요)
    type_by_qid: dict[str, EntityType] = field(
        default_factory=lambda: {
            "Q5": EntityType.PERSON,
            "Q215380": EntityType.GROUP,  # musical group
            "Q9212979": EntityType.GROUP,  # musical duo
            "Q2088357": EntityType.GROUP,  # musical ensemble
            "Q43229": EntityType.ORGANIZATION,  # organization
            "Q18127": EntityType.ORGANIZATION,  # record label
            "Q482994": EntityType.WORK,  # album
            "Q7366": EntityType.WORK,  # song
            "Q134556": EntityType.WORK,  # single
            "Q11424": EntityType.WORK,  # film
            "Q5398426": EntityType.WORK,  # television series
            "Q618779": EntityType.AWARD,  # award
            "Q4504495": EntityType.AWARD,  # award (category)
            "Q27968055": EntityType.EVENT,  # award ceremony edition
            "Q182832": EntityType.EVENT,  # concert
        }
    )
    # 관계 속성 → predicate (스키마 §2.1 화이트리스트 안만)
    statement_props: dict[str, Predicate] = field(
        default_factory=lambda: {
            "P463": Predicate.MEMBER_OF,  # member of
            "P527": Predicate.MEMBER_OF,  # has part(s)
            "P175": Predicate.APPEARED_IN,  # performer
            "P800": Predicate.RELEASED,  # notable work
            "P162": Predicate.PRODUCED_BY,  # producer
            "P264": Predicate.PRODUCED_BY,  # record label
            "P166": Predicate.WON_AWARD,  # award received
            "P1411": Predicate.NOMINATED_FOR,  # nominated for
        }
    )
    # Person 속성
    birth_date_prop: str = "P569"
    nationality_prop: str = "P27"
    occupation_prop: str = "P106"
    # Group / Work 속성
    inception_prop: str = "P571"
    publication_prop: str = "P577"
    # 시간 한정자
    start_qualifier: str = "P580"
    end_qualifier: str = "P582"


DEFAULT_MAPPING = WikidataMapping()
