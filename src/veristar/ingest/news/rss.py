"""공개 RSS 피드 읽기 (M4 파이프라인 [1]).

원문 본문은 요청하지 않는다 — 제목·URL·날짜만 가져온다.
네이버·다음 본문 크롤링은 약관·저작권 위반이므로 금지 (safety-guidelines.md §3).
"""

from __future__ import annotations

import logging
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from datetime import date, datetime
from email.utils import parsedate_to_datetime
from pathlib import Path
from typing import Protocol

import httpx

logger = logging.getLogger(__name__)

_UA = "VeristarBot/0.1 (https://github.com/; news rss ingest)"

# RSS 네임스페이스
_ATOM_NS = "http://www.w3.org/2005/Atom"
_MEDIA_NS = "http://search.yahoo.com/mrss/"


@dataclass(frozen=True)
class FeedItem:
    """RSS/Atom 피드 아이템. 원문은 담지 않는다."""

    title: str
    url: str
    published: date | None = None
    summary: str = ""  # 있으면 짧은 요약, 없으면 빈 문자열 (원문 X)
    feed_name: str = ""


class RssClient(Protocol):
    """RSS 조회 인터페이스 (테스트에서 Fake 주입용)."""

    def fetch_items(self, feed_url: str, feed_name: str) -> list[FeedItem]: ...


def _parse_date(text: str | None) -> date | None:
    if not text:
        return None
    try:
        return parsedate_to_datetime(text).date()
    except Exception:
        pass
    for fmt in ("%Y-%m-%dT%H:%M:%SZ", "%Y-%m-%d"):
        try:
            return datetime.strptime(text.strip(), fmt).date()
        except ValueError:
            continue
    return None


def _parse_rss2(root: ET.Element, feed_name: str) -> list[FeedItem]:
    items: list[FeedItem] = []
    for item in root.findall(".//item"):
        title = (item.findtext("title") or "").strip()
        link = (item.findtext("link") or "").strip()
        pub_date = _parse_date(item.findtext("pubDate"))
        description = (item.findtext("description") or "").strip()
        # 설명이 있어도 긴 본문은 버린다 — 100자 이하만 summary로 보관
        summary = description[:100] if len(description) <= 100 else ""
        if title and link:
            items.append(
                FeedItem(
                    title=title,
                    url=link,
                    published=pub_date,
                    summary=summary,
                    feed_name=feed_name,
                )
            )
    return items


def _parse_atom(root: ET.Element, feed_name: str) -> list[FeedItem]:
    items: list[FeedItem] = []
    for entry in root.findall(f"{{{_ATOM_NS}}}entry"):
        title_el = entry.find(f"{{{_ATOM_NS}}}title")
        title = (title_el.text or "").strip() if title_el is not None else ""
        link_el = entry.find(f"{{{_ATOM_NS}}}link")
        link = (link_el.get("href") or "").strip() if link_el is not None else ""
        pub_el = entry.find(f"{{{_ATOM_NS}}}published")
        if pub_el is None:
            pub_el = entry.find(f"{{{_ATOM_NS}}}updated")
        published = _parse_date(pub_el.text if pub_el is not None else None)
        if title and link:
            items.append(FeedItem(title=title, url=link, published=published, feed_name=feed_name))
    return items


def parse_feed(xml_text: str, feed_name: str = "") -> list[FeedItem]:
    """RSS 2.0 또는 Atom XML 텍스트 → FeedItem 목록."""
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError as exc:
        logger.warning("XML parse error (%s): %s", feed_name, exc)
        return []

    tag = root.tag.lower()
    if "feed" in tag or tag == f"{{{_ATOM_NS}}}feed":
        return _parse_atom(root, feed_name)
    return _parse_rss2(root, feed_name)


class HttpRssClient:
    """httpx 기반 실제 RSS 클라이언트."""

    def __init__(self, timeout: float = 20.0, client: httpx.Client | None = None) -> None:
        self._client = client or httpx.Client(
            timeout=timeout,
            headers={"User-Agent": _UA},
            follow_redirects=True,
        )

    def fetch_items(self, feed_url: str, feed_name: str = "") -> list[FeedItem]:
        try:
            resp = self._client.get(feed_url)
            resp.raise_for_status()
        except httpx.HTTPError as exc:
            logger.warning("RSS fetch failed (%s): %s", feed_url, exc)
            return []
        return parse_feed(resp.text, feed_name=feed_name or feed_url)

    def close(self) -> None:
        self._client.close()

    def __enter__(self) -> HttpRssClient:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()


@dataclass
class FeedConfig:
    """단일 RSS 피드 설정."""

    name: str
    url: str
    source_type: str = "PRESS"  # SourceType enum 값


def load_feed_configs(config_path: str | Path) -> list[FeedConfig]:
    """YAML 피드 설정 파일 파싱 (stdlib만 사용, 외부 의존성 없음).

    형식::

        feeds:
          - name: 연합뉴스 연예
            url: https://www.yna.co.kr/RSS/entertainment.xml
            source_type: PRESS
    """
    path = Path(config_path)
    if not path.exists():
        return []

    # YAML 대신 간단한 텍스트 파서 사용 (의존성 추가 없이)
    configs: list[FeedConfig] = []
    current: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if stripped.startswith("#") or not stripped:
            continue
        if stripped.startswith("- name:"):
            if current.get("url"):
                configs.append(
                    FeedConfig(
                        name=current.get("name", ""),
                        url=current["url"],
                        source_type=current.get("source_type", "PRESS"),
                    )
                )
            current = {"name": stripped[len("- name:") :].strip()}
        elif stripped.startswith("url:"):
            current["url"] = stripped[len("url:") :].strip()
        elif stripped.startswith("source_type:"):
            current["source_type"] = stripped[len("source_type:") :].strip()
    if current.get("url"):
        configs.append(
            FeedConfig(
                name=current.get("name", ""),
                url=current["url"],
                source_type=current.get("source_type", "PRESS"),
            )
        )
    return configs
