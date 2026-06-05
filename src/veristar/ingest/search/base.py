"""검색 제공자 추상화 — Protocol 기반 (백엔드 교체 가능)."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Protocol


@dataclass(frozen=True)
class SearchResult:
    """단일 검색 결과 (provider-agnostic).

    Attributes:
        url:        결과 URL (수집 큐의 1차 키)
        title:      제목 (HTML 태그 제거된 평문)
        snippet:    요약 스니펫 (HTML 태그 제거된 평문)
        published:  보도/게시 시각 (가능한 경우)
        source:     검색 제공자 식별자 ('naver_news', 'naver_blog', 등)
        raw:        원본 응답 (디버깅·재처리용)
    """

    url: str
    title: str
    snippet: str
    published: datetime | None = None
    source: str = ""
    raw: dict[str, object] | None = None


class SearchProvider(Protocol):
    """검색 백엔드 인터페이스.

    구현체는 query 문자열을 받아 SearchResult 리스트를 반환한다.
    실패 시 빈 리스트 반환 (예외 발생 금지) — 호출자가 fallback 가능하도록.
    """

    name: str

    def search(self, query: str, *, limit: int = 10) -> list[SearchResult]:
        """쿼리로 검색해 결과 목록을 반환한다."""
        ...
