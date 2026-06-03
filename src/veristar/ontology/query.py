"""콘텐츠 생성 입력 게이트 (스키마 §5 규칙 5, service-design §6).

규칙 5는 적재 시점 검증이 아니라 **쿼리 단계의 게이트**다. sensitive·비OFFICIAL
statement는 그래프에 저장은 되지만 생성 입력 쿼리에서 자동 제외된다.
"""

from __future__ import annotations

from .enums import Grade, Status
from .graph import GraphDocument
from .models import Statement


def official_nonsensitive(doc: GraphDocument) -> list[Statement]:
    """생성 재료로 쓸 수 있는 statement만 반환.

    조건: grade == OFFICIAL AND sensitive == False AND status == ACTIVE.
    REPORTED/RUMOR·민감·대체/철회된 statement는 절대 포함하지 않는다.
    """
    return [
        s
        for s in doc.statements
        if s.grade == Grade.OFFICIAL and not s.sensitive and s.status == Status.ACTIVE
    ]
