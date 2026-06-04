"""Wikidata 속성·QID → Veristar 온톨로지 매핑 설정.

매핑을 주입 가능한 dataclass로 둔다:
- 테스트는 합성 QID로 자체 매핑을 만들어 실제 Wikidata QID 정확성에 의존하지 않는다.
- 운영 기본값(DEFAULT_MAPPING)은 best-effort이며, ⚠️ 라이브 Wikidata 대조로 검증·확장해야 한다.

화이트리스트에 없는 속성(배우자 P26·파트너 P451 등 관계·사생활)은 매핑하지 않는다 = 민감 필터.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from veristar.ontology.enums import EntityType, Predicate

# 확장(discovery)에만 쓰는 속성: statement를 만들지 않고 object QID를 따라가 노드를 발견.
# P527(has part)은 그룹↔멤버 방향이 반대고 award-group 등에도 붙어 과적용되므로,
# statement로 만들지 않고 확장 힌트로만 쓴다. memberOf 엣지는 멤버 본인의 P463에서 나온다.

WD_PREFIX = "wd:"


def qid_to_id(qid: str) -> str:
    """'Q42' → 'wd:Q42'. 이미 접두사가 있으면 그대로."""
    return qid if qid.startswith(WD_PREFIX) else f"{WD_PREFIX}{qid}"


@dataclass(frozen=True)
class WikidataMapping:
    """Wikidata 매핑 규칙. 모든 필드는 주입 가능."""

    instance_of: str = "P31"
    # P31 값 QID → EntityType.
    # [verified]는 2026-06-04 라이브 Wikidata로 확인. 나머지는 best-effort(⚠️ 검증 권장).
    type_by_qid: dict[str, EntityType] = field(
        default_factory=lambda: {
            # --- Person ---
            "Q5": EntityType.PERSON,  # [verified] human
            # --- Group ---
            "Q215380": EntityType.GROUP,  # [verified] musical group
            "Q216337": EntityType.GROUP,  # [verified] boy band
            "Q641066": EntityType.GROUP,  # [verified] girl group
            "Q9212979": EntityType.GROUP,  # musical duo (best-effort)
            "Q2088357": EntityType.GROUP,  # musical ensemble (best-effort)
            # --- Organization ---
            "Q43229": EntityType.ORGANIZATION,  # organization (best-effort)
            "Q18127": EntityType.ORGANIZATION,  # record label (best-effort)
            # --- Work ---
            "Q105543609": EntityType.WORK,  # [verified] musical work/composition
            "Q7302866": EntityType.WORK,  # [verified] audio track
            "Q134556": EntityType.WORK,  # [verified] single
            "Q15416": EntityType.WORK,  # [verified] television program
            "Q482994": EntityType.WORK,  # album (best-effort)
            "Q7366": EntityType.WORK,  # song (best-effort)
            "Q11424": EntityType.WORK,  # film (best-effort)
            # --- Award ---
            "Q1364556": EntityType.AWARD,  # [verified] music award
            "Q38033430": EntityType.AWARD,  # [verified] class of award
            "Q23719064": EntityType.AWARD,  # [verified] annual prize
            "Q29788158": EntityType.AWARD,  # [verified] award for best newcomer
            "Q107655869": EntityType.AWARD,  # [verified] group of awards
            "Q618779": EntityType.AWARD,  # award (best-effort)
            # --- Event ---
            "Q483271": EntityType.EVENT,  # [verified] music awards ceremony (MAMA)
            "Q27968055": EntityType.EVENT,  # award ceremony edition (best-effort)
            "Q182832": EntityType.EVENT,  # concert (best-effort)
        }
    )
    # 직접 관계 속성 → predicate (Wikidata subject = Veristar subject).
    # 스키마 §2.1 화이트리스트 안에서, 방향이 확실한 것만. (방향 모호한
    # P175/P162/P264 등은 per-property 방향 분석 후 추가 — 정확성 우선.)
    statement_props: dict[str, Predicate] = field(
        default_factory=lambda: {
            "P463": Predicate.MEMBER_OF,  # member of: Person → Group
            "P800": Predicate.APPEARED_IN,  # notable work: Person → Work
            "P166": Predicate.WON_AWARD,  # award received: → Award
            "P1411": Predicate.NOMINATED_FOR,  # nominated for: → Award
        }
    )
    # 확장 힌트 속성: 이 속성의 object QID를 fetch 대상에 넣되 statement는 만들지 않는다.
    expansion_props: tuple[str, ...] = ("P527",)  # has part(s) → 멤버 발견용
    # Person 속성
    birth_date_prop: str = "P569"
    nationality_prop: str = "P27"
    occupation_prop: str = "P106"
    # Group / Work 속성
    inception_prop: str = "P571"
    publication_prop: str = "P577"
    # 시간 한정자
    start_qualifier: str = "P580"  # start time
    end_qualifier: str = "P582"  # end time
    point_in_time_qualifier: str = "P585"  # 단발 사건(수상 등) 시점 → valid_from 폴백
    # 같은 관계를 구분하는 라벨 한정자 (예: 수상 부문). P1810=subject named as.
    label_qualifier: str = "P1810"


DEFAULT_MAPPING = WikidataMapping()
