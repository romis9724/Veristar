"""엔티티·Source·Statement Pydantic 모델 (스키마 §1~3).

모델 레벨에서 강제하는 validation:
- 규칙 1: Statement.sources ≥ 1개 (`min_length=1`)
- 규칙 4: predicate는 화이트리스트 (`Predicate` enum)
- 규칙 6: valid_to 있으면 valid_from ≤ valid_to (model_validator)

교차참조가 필요한 규칙 2·3은 graph.py, 규칙 5는 query.py에서 다룬다.
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Annotated, Literal

from pydantic import BaseModel, Field, model_validator

from .enums import EntityType, Grade, Predicate, SourceType, Status


class _EntityBase(BaseModel):
    """모든 엔티티 공통 필드 (스키마 §1)."""

    id: str
    name: str
    aliases: list[str] = Field(default_factory=list)
    created_at: datetime


class Person(_EntityBase):
    type: Literal[EntityType.PERSON] = EntityType.PERSON
    # 민감 속성(사생활·건강·관계)은 스키마에 두지 않는다 (§1 주의). 공개 정보만.
    birth_year: int | None = None
    occupation: list[str] = Field(default_factory=list)
    nationality: str | None = None


class Group(_EntityBase):
    type: Literal[EntityType.GROUP] = EntityType.GROUP
    debut_date: date | None = None
    group_type: str | None = None


class Organization(_EntityBase):
    type: Literal[EntityType.ORGANIZATION] = EntityType.ORGANIZATION
    org_role: str | None = None


class Work(_EntityBase):
    type: Literal[EntityType.WORK] = EntityType.WORK
    work_type: str | None = None
    release_date: date | None = None


class Event(_EntityBase):
    type: Literal[EntityType.EVENT] = EntityType.EVENT
    event_type: str | None = None
    event_date: date | None = None


class Award(_EntityBase):
    type: Literal[EntityType.AWARD] = EntityType.AWARD
    award_category: str | None = None


#: `type` 필드로 구분하는 discriminated union.
Entity = Annotated[
    Person | Group | Organization | Work | Event | Award,
    Field(discriminator="type"),
]


class Source(BaseModel):
    """출처 레코드 (스키마 §3). 원문 본문은 담지 않고 링크·제목까지만."""

    id: str
    source_type: SourceType
    publisher: str
    url: str
    title: str
    published_at: date | None = None
    retrieved_at: date | None = None
    license: str | None = None


class Statement(BaseModel):
    """reified edge — 그래프의 1급 시민 (스키마 §2)."""

    id: str
    subject: str
    predicate: Predicate  # 규칙 4: enum이 화이트리스트를 강제
    object: str
    grade: Grade
    status: Status = Status.ACTIVE
    sources: list[str] = Field(min_length=1)  # 규칙 1: 출처 최소 1개
    valid_from: date | None = None
    valid_to: date | None = None
    asserted_at: date | None = None
    sensitive: bool = False

    @model_validator(mode="after")
    def _check_validity_window(self) -> Statement:
        # 규칙 6: valid_to가 있으면 valid_from ≤ valid_to
        if (
            self.valid_to is not None
            and self.valid_from is not None
            and self.valid_from > self.valid_to
        ):
            raise ValueError(f"valid_from({self.valid_from}) must be <= valid_to({self.valid_to})")
        return self
