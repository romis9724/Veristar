"""source_type → 기본/허용 등급 매핑 (스키마 §3).

validation 규칙 3과 이후 M3 등급 분류기가 공유한다.
핵심 원칙(§2.2): 보수적 하향은 언제나 허용, 출처가 받쳐주지 않는 상향만 금지.
"""

from __future__ import annotations

from .enums import Grade, SourceType

#: source_type이 기본으로 부여하는 등급 (스키마 §3 매핑표).
SOURCE_TYPE_DEFAULT_GRADE: dict[SourceType, Grade] = {
    SourceType.OFFICIAL_ANNOUNCEMENT: Grade.OFFICIAL,
    SourceType.ARTIST_OFFICIAL_SNS: Grade.OFFICIAL,
    SourceType.GOV_OR_AWARD_BODY: Grade.OFFICIAL,
    SourceType.WIKIDATA_VERIFIED: Grade.OFFICIAL,
    SourceType.PRESS: Grade.REPORTED,
    SourceType.COMMUNITY_OR_ANON: Grade.RUMOR,
}

#: 등급의 "공식성" 순위 (클수록 공식). 등급 비교에 쓴다.
_GRADE_RANK: dict[Grade, int] = {
    Grade.RUMOR: 1,
    Grade.REPORTED: 2,
    Grade.OFFICIAL: 3,
}


def grade_rank(grade: Grade) -> int:
    """등급의 공식성 순위. OFFICIAL(3) > REPORTED(2) > RUMOR(1)."""
    return _GRADE_RANK[grade]


def max_grade_for_source_types(source_types: list[SourceType]) -> Grade | None:
    """주어진 출처 유형들이 받쳐줄 수 있는 최고 등급. 빈 목록이면 None."""
    if not source_types:
        return None
    return max(
        (SOURCE_TYPE_DEFAULT_GRADE[st] for st in source_types),
        key=grade_rank,
    )


def is_grade_supported(grade: Grade, source_types: list[SourceType]) -> bool:
    """statement 등급이 출처들로 정당화되는가 (규칙 3).

    출처가 받쳐주는 최고 등급보다 높은 등급을 주장하면 거짓(False).
    더 보수적인(낮은) 등급은 항상 허용.
    """
    ceiling = max_grade_for_source_types(source_types)
    if ceiling is None:
        return False
    return grade_rank(grade) <= grade_rank(ceiling)
