"""외부 검색 통합 — 수집 큐 보충 모델 (CLAUDE.md §4-1·§4-3 정합).

흐름:
    SearchProvider.search(query)
      → [SearchResult(url, title, snippet, ...)]
      → DomainGrading.classify(url) → (SourceType, Grade)
      → collection_targets upsert (status='pending')
      → 다음 cron 사이클에서 collectors.runner가 크롤링 → vault
      → verify/pipeline로 LLM cross-check
      → HIGH 통과 시 그래프 승격 → 답변 입력
"""

from .base import SearchProvider, SearchResult
from .domain_grading import DomainGrading

__all__ = ["SearchProvider", "SearchResult", "DomainGrading"]
