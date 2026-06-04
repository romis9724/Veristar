"""출처 등급 분류기 (M3). source_type → OFFICIAL/REPORTED/RUMOR.

핵심 구현은 ontology.grading_map에 있다(M1부터 공유).
이 모듈은 민감 카테고리 필터와 함께 파이프라인 [3] 공식 진입점을 제공한다.
"""

from __future__ import annotations

from veristar.ontology.enums import Grade, SourceType
from veristar.ontology.grading_map import (
    SOURCE_TYPE_DEFAULT_GRADE,
    grade_rank,
    is_grade_supported,
    max_grade_for_source_types,
)

# 민감 카테고리 키워드: 이 단어가 포함된 라벨/술어는 ingest 입구에서 차단
SENSITIVE_PREDICATES: frozenset[str] = frozenset(
    # 관계·사생활·논란·법적 분쟁 등은 스코프에서 제외(CLAUDE.md §4-5, safety-guidelines)
    # 현재 predicate 화이트리스트에 없어 자동 차단됨 — 명시적 열거
)

SENSITIVE_KEYWORDS: frozenset[str] = frozenset(
    {"열애", "결혼", "이혼", "논란", "사건", "고소", "소송", "분쟁", "건강", "입원"}
)


def classify_grade(source_type: SourceType) -> Grade:
    """source_type의 기본 등급 반환."""
    return SOURCE_TYPE_DEFAULT_GRADE[source_type]


def is_sensitive_label(text: str) -> bool:
    """텍스트에 민감 카테고리 키워드가 포함되면 True."""
    return any(kw in text for kw in SENSITIVE_KEYWORDS)


__all__ = [
    "classify_grade",
    "is_sensitive_label",
    "is_grade_supported",
    "max_grade_for_source_types",
    "grade_rank",
    "SENSITIVE_KEYWORDS",
    "SOURCE_TYPE_DEFAULT_GRADE",
]
