"""네이버 검색 API 클라이언트 (한국어 K-pop 도메인 최적).

자격증명: developers.naver.com에서 애플리케이션 등록 후
  NAVER_CLIENT_ID, NAVER_CLIENT_SECRET 환경변수로 주입.
무료 한도: 일 25,000 호출 (개발자센터 정책 기준).

API 종류 (모두 GET, JSON 응답):
  /v1/search/news.json    : 뉴스 (보도)
  /v1/search/blog.json    : 블로그 (REPORTED 또는 RUMOR)
  /v1/search/webkr.json   : 일반 웹 (잡종)
"""

from __future__ import annotations

import logging
import os
import re
from datetime import datetime
from typing import Any

import httpx

from .base import SearchResult

logger = logging.getLogger(__name__)

_API_BASE = "https://openapi.naver.com/v1/search"
_TAG_RE = re.compile(r"<[^>]+>")
_HTML_ENTITY = {"&amp;": "&", "&lt;": "<", "&gt;": ">", "&quot;": '"', "&#39;": "'"}


def _strip_html(text: str) -> str:
    """네이버 API 응답의 <b>강조 태그</b>와 엔티티 제거."""
    text = _TAG_RE.sub("", text or "")
    for k, v in _HTML_ENTITY.items():
        text = text.replace(k, v)
    return text.strip()


def _parse_pubdate(s: str | None) -> datetime | None:
    """RFC 822 형식 (예: 'Wed, 04 Jun 2026 10:23:00 +0900') 파싱."""
    if not s:
        return None
    try:
        from email.utils import parsedate_to_datetime

        return parsedate_to_datetime(s)
    except Exception:
        return None


class NaverSearchProvider:
    """네이버 검색 API 백엔드.

    Args:
        client_id:     없으면 NAVER_CLIENT_ID 환경변수
        client_secret: 없으면 NAVER_CLIENT_SECRET 환경변수
        kinds:         사용할 API ('news', 'blog', 'webkr'). 기본 모두.
        timeout:       HTTP 타임아웃 (초)
    """

    name = "naver"

    def __init__(
        self,
        client_id: str | None = None,
        client_secret: str | None = None,
        kinds: tuple[str, ...] = ("news", "blog", "webkr"),
        timeout: float = 10.0,
    ) -> None:
        self._cid = client_id or os.environ.get("NAVER_CLIENT_ID", "")
        self._csec = client_secret or os.environ.get("NAVER_CLIENT_SECRET", "")
        self._kinds = kinds
        self._timeout = timeout

    def is_configured(self) -> bool:
        """자격증명 보유 여부."""
        return bool(self._cid and self._csec)

    def _call(self, kind: str, query: str, display: int) -> list[dict[str, Any]]:
        """단일 API 호출. 실패 시 빈 리스트."""
        url = f"{_API_BASE}/{kind}.json"
        headers = {
            "X-Naver-Client-Id": self._cid,
            "X-Naver-Client-Secret": self._csec,
        }
        try:
            r = httpx.get(
                url,
                params={"query": query, "display": min(display, 100), "sort": "sim"},
                headers=headers,
                timeout=self._timeout,
            )
            r.raise_for_status()
            return list(r.json().get("items", []))
        except Exception as exc:
            logger.warning("naver %s 검색 실패: %s", kind, exc)
            return []

    def search(self, query: str, *, limit: int = 10) -> list[SearchResult]:
        """모든 kind를 호출해 결과를 합친다. limit은 kind당 적용."""
        if not self.is_configured():
            logger.warning("NAVER_CLIENT_ID/SECRET 미설정 — 빈 결과")
            return []
        if not query.strip():
            return []

        results: list[SearchResult] = []
        for kind in self._kinds:
            items = self._call(kind, query, display=limit)
            for it in items:
                url = it.get("link") or it.get("originallink") or ""
                if not url:
                    continue
                results.append(
                    SearchResult(
                        url=url,
                        title=_strip_html(it.get("title", "")),
                        snippet=_strip_html(it.get("description", "")),
                        published=_parse_pubdate(it.get("pubDate")),
                        source=f"naver_{kind}",
                        raw=it,
                    )
                )
        return results
