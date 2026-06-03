"""Veristar 온톨로지: 데이터 모델 + validation (스키마 §1~5)."""

from __future__ import annotations

from .enums import EntityType, Grade, Predicate, SourceType, Status
from .grading_map import (
    SOURCE_TYPE_DEFAULT_GRADE,
    is_grade_supported,
    max_grade_for_source_types,
)
from .graph import GraphDocument, GraphValidationError, Violation, load_graph
from .models import (
    Award,
    Entity,
    Event,
    Group,
    Organization,
    Person,
    Source,
    Statement,
    Work,
)
from .query import official_nonsensitive

__all__ = [
    "EntityType",
    "Predicate",
    "Grade",
    "Status",
    "SourceType",
    "Person",
    "Group",
    "Organization",
    "Work",
    "Event",
    "Award",
    "Entity",
    "Source",
    "Statement",
    "GraphDocument",
    "GraphValidationError",
    "Violation",
    "load_graph",
    "SOURCE_TYPE_DEFAULT_GRADE",
    "is_grade_supported",
    "max_grade_for_source_types",
    "official_nonsensitive",
]
