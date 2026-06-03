"""온톨로지 열거형. `docs/ontology-schema.md` §1~3 정의를 그대로 옮긴다."""

from __future__ import annotations

from enum import StrEnum


class EntityType(StrEnum):
    """엔티티 타입 (스키마 §1). Source는 별도 모델이라 여기 포함하지 않는다."""

    PERSON = "Person"
    GROUP = "Group"
    ORGANIZATION = "Organization"
    WORK = "Work"
    EVENT = "Event"
    AWARD = "Award"


class Predicate(StrEnum):
    """관계 어휘 (스키마 §2.1). 공식 활동 사실로 한정된 화이트리스트."""

    MEMBER_OF = "memberOf"
    AFFILIATED_WITH = "affiliatedWith"
    APPEARED_IN = "appearedIn"
    RELEASED = "released"
    PRODUCED_BY = "producedBy"
    COLLABORATED_WITH = "collaboratedWith"
    NOMINATED_FOR = "nominatedFor"
    WON_AWARD = "wonAward"
    PRESENTED_AT = "presentedAt"
    HAS_ROLE = "hasRole"


class Grade(StrEnum):
    """신뢰 등급 (스키마 §2.2). 진실 여부가 아니라 출처의 성격."""

    OFFICIAL = "OFFICIAL"
    REPORTED = "REPORTED"
    RUMOR = "RUMOR"


class Status(StrEnum):
    """Statement 상태 (스키마 §2.3). 지우지 않고 상태로 표시한다."""

    ACTIVE = "ACTIVE"
    SUPERSEDED = "SUPERSEDED"
    RETRACTED = "RETRACTED"


class SourceType(StrEnum):
    """출처 유형 (스키마 §3). 기본 등급 매핑은 grading_map.py."""

    OFFICIAL_ANNOUNCEMENT = "OFFICIAL_ANNOUNCEMENT"
    ARTIST_OFFICIAL_SNS = "ARTIST_OFFICIAL_SNS"
    GOV_OR_AWARD_BODY = "GOV_OR_AWARD_BODY"
    WIKIDATA_VERIFIED = "WIKIDATA_VERIFIED"
    PRESS = "PRESS"
    COMMUNITY_OR_ANON = "COMMUNITY_OR_ANON"
