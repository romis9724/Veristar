"""Statement 탐색 필터 (등급·상태·predicate·기간).

생성 게이트(`ontology.query.official_nonsensitive`)와 별개다. 탐색은 등급을
*보여주되* 필터로 선택하게 한다. 기본은 ACTIVE 상태만, 등급·predicate는 전체.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date

from veristar.ontology.enums import Grade, Predicate, Status
from veristar.ontology.models import Statement


@dataclass(frozen=True)
class StatementFilter:
    grades: frozenset[Grade] | None = None  # None = 전체
    statuses: frozenset[Status] = field(default_factory=lambda: frozenset({Status.ACTIVE}))
    predicates: frozenset[Predicate] | None = None  # None = 전체
    date_from: date | None = None
    date_to: date | None = None

    def matches(self, stmt: Statement) -> bool:
        if self.grades is not None and stmt.grade not in self.grades:
            return False
        if self.statuses and stmt.status not in self.statuses:
            return False
        if self.predicates is not None and stmt.predicate not in self.predicates:
            return False
        return self._overlaps_period(stmt)

    def _overlaps_period(self, stmt: Statement) -> bool:
        # statement 유효구간 [valid_from, valid_to] 와 필터 구간 [date_from, date_to] 겹침.
        # None은 무한대로 취급 (valid_from None = -inf, valid_to None = +inf).
        starts_after_window = (
            self.date_to is not None
            and stmt.valid_from is not None
            and stmt.valid_from > self.date_to
        )
        ends_before_window = (
            self.date_from is not None
            and stmt.valid_to is not None
            and stmt.valid_to < self.date_from
        )
        return not (starts_after_window or ends_before_window)
