"""Wikipedia MediaWiki API 클라이언트.

한국어 Wikipedia(kowiki) redirect 별칭 보완용 얇은 I/O 계층.
원문 본문은 요청하지 않는다 — 별칭(redirect 제목)만 가져온다.
"""

from __future__ import annotations

from typing import Any, Protocol

import httpx

_KOWIKI_API = "https://ko.wikipedia.org/w/api.php"
_WD_ENTITY_URL = "https://www.wikidata.org/wiki/Special:EntityData/{qid}.json"
_UA = "VeristarBot/0.1 (https://github.com/; alias supplement)"


class WikipediaClient(Protocol):
    """Wikipedia alias 조회 인터페이스 (테스트에서 Fake 주입용)."""

    def fetch_redirects(self, page_title: str) -> list[str]: ...
    def fetch_kowiki_title(self, qid: str) -> str | None: ...


class HttpWikipediaClient:
    """httpx 기반 실제 Wikipedia/Wikidata 구현."""

    def __init__(self, timeout: float = 20.0, client: httpx.Client | None = None) -> None:
        self._client = client or httpx.Client(
            timeout=timeout,
            headers={"User-Agent": _UA},
            follow_redirects=True,
        )

    def fetch_kowiki_title(self, qid: str) -> str | None:
        """Wikidata QID → 한국어 Wikipedia 페이지 제목 (sitelinks.kowiki)."""
        resp = self._client.get(_WD_ENTITY_URL.format(qid=qid))
        if resp.status_code != 200:
            return None
        sitelinks: dict[str, Any] = (
            resp.json().get("entities", {}).get(qid, {}).get("sitelinks", {})
        )
        kowiki = sitelinks.get("kowiki")
        return str(kowiki["title"]) if kowiki else None

    def fetch_redirects(self, page_title: str) -> list[str]:
        """Wikipedia 페이지로의 redirect 제목 목록 (별칭 후보)."""
        params: dict[str, str] = {
            "action": "query",
            "prop": "redirects",
            "rdlimit": "max",
            "titles": page_title,
            "format": "json",
        }
        resp = self._client.get(_KOWIKI_API, params=params)
        if resp.status_code != 200:
            return []
        pages: dict[str, Any] = resp.json().get("query", {}).get("pages", {})
        out: list[str] = []
        for page in pages.values():
            for rd in page.get("redirects", []):
                title = rd.get("title", "")
                if title:
                    out.append(title)
        return out

    def close(self) -> None:
        self._client.close()

    def __enter__(self) -> HttpWikipediaClient:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()
