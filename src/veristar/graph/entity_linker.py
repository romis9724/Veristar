"""엔티티 링킹 — 벡터 유사도 기반 (InMemoryGraphRepository 향상).

PostgreSQL 환경에서는 VectorStore.find_similar_entities()를 사용.
파일 기반(InMemory) 환경에서는 nomic-embed-text로 직접 유사도 계산.

현재 InMemoryGraphRepository.find_mentioned()의 문제:
  - 부분 문자열 매칭 → '한', '뷔' 같은 짧은 이름 과매칭
  - 해결: cosine threshold 필터 추가
"""

from __future__ import annotations

import logging
import math
from typing import TYPE_CHECKING

from veristar.db.vector_store import _LINK_THRESHOLD, embed_text
from veristar.ontology.models import Entity

if TYPE_CHECKING:
    from veristar.graph.repository import InMemoryGraphRepository

logger = logging.getLogger(__name__)

_SHORT_NAME_LEN = 3  # 이 이하 길이의 이름은 벡터 검증 필수


def _cosine(a: list[float], b: list[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b, strict=True))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(x * x for x in b))
    if na == 0 or nb == 0:
        return 0.0
    return dot / (na * nb)


def find_mentioned_with_vectors(
    text: str,
    repo: InMemoryGraphRepository,
    limit: int = 5,
    threshold: float | None = None,
) -> list[Entity]:
    """벡터 유사도로 text에 언급된 엔티티를 탐색한다.

    흐름:
      1. 기존 substring 매칭으로 후보를 뽑는다.
      2. 짧은 이름(≤ SHORT_NAME_LEN) 후보는 벡터 cosine 검증을 추가한다.
      3. threshold 미달이면 제거한다.

    이렇게 하면 '한' → 모든 '한 음절 포함 이름' 매칭 문제를 방지하면서
    추가 의존성(NER 모델) 없이 정확도를 높인다.
    """
    th = threshold if threshold is not None else _LINK_THRESHOLD
    t = text.strip().lower()
    if not t:
        return []

    # 1) 기존 substring 후보
    candidates: list[Entity] = []
    seen: set[str] = set()
    for term, entity_id in sorted(repo._name_index, key=lambda x: len(x[0]), reverse=True):
        if term and term in t and entity_id not in seen:
            e = repo._by_id.get(entity_id)
            if e:
                candidates.append(e)
                seen.add(entity_id)
            if len(candidates) >= limit * 3:
                break

    if not candidates:
        return []

    # 2) 짧은 이름 후보는 벡터 검증
    query_vec = embed_text(text[:200])  # 문서 시작부만 임베딩 (속도)
    if query_vec is None:
        # 임베딩 실패 → 길이 기준 필터만 적용 (짧은 이름 제거)
        return [c for c in candidates if len(c.name) > _SHORT_NAME_LEN][:limit]

    verified: list[tuple[float, Entity]] = []
    for entity in candidates:
        name_len = len(entity.name)
        if name_len > _SHORT_NAME_LEN:
            # 긴 이름은 substring 일치만으로 신뢰
            verified.append((1.0, entity))
        else:
            # 짧은 이름은 엔티티 이름 임베딩과 쿼리 임베딩 유사도 확인
            entity_vec = embed_text(entity.name + " " + " ".join(entity.aliases))
            if entity_vec is None:
                continue  # 임베딩 실패 시 제외
            sim = _cosine(query_vec, entity_vec)
            logger.debug(
                "entity linker: '%s' sim=%.3f threshold=%.2f %s",
                entity.name,
                sim,
                th,
                "✓" if sim >= th else "✗",
            )
            if sim >= th:
                verified.append((sim, entity))

    # 유사도 내림차순, 긴 이름 우선으로 정렬
    verified.sort(key=lambda x: (x[0], len(x[1].name)), reverse=True)
    return [e for _, e in verified[:limit]]
