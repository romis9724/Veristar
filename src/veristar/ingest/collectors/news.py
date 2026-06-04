"""뉴스 수집기 — RSS 피드 + 본문 저장.

기존 M4 파이프라인(제목만 추출)과 달리, 이 수집기는 원문 본문도 raw vault에 저장한다.
단, 저작권 표시 필수 (원문 복제이므로 라이선스 명시). 상업화 시 별도 검토 필요.

소스:
- 연합뉴스: 공개 RSS, 내용 CC BY (약관 확인 필요)
- Soompi: 공개 RSS
- Billboard Korea: 공개 RSS
- 추가 피드는 config/news_feeds.yaml에 설정
"""

from __future__ import annotations

import hashlib
import logging
import re
import xml.etree.ElementTree as ET
from datetime import date, datetime
from email.utils import parsedate_to_datetime

from veristar.grading import is_sensitive_label
from veristar.vault.store import ConfidenceLevel, VaultDoc, VaultStore

from .base import CollectorBase, CollectResult

logger = logging.getLogger(__name__)

_ATOM_NS = "http://www.w3.org/2005/Atom"


class NewsCollector(CollectorBase):
    """RSS 피드에서 뉴스를 수집해 vault에 저장한다."""

    def __init__(
        self,
        store: VaultStore,
        max_body_chars: int = 5000,
        timeout: float = 30.0,
    ) -> None:
        super().__init__(store, timeout)
        self.max_body_chars = max_body_chars

    def collect(self, target: str, **kwargs: object) -> CollectResult:
        """target: RSS 피드 URL."""
        feed_name = str(kwargs.get("feed_name", target))
        source_type_str = str(kwargs.get("source_type", "PRESS"))

        feed_text = self._get(target)
        if not feed_text:
            return CollectResult(errors=1, messages=[f"feed fetch failed: {target}"])

        items = _parse_feed(feed_text)
        result = CollectResult()
        for item in items:
            r = self._process_item(item, feed_name, source_type_str)
            result = result.merge(r)
        return result

    def _process_item(
        self, item: dict[str, str], feed_name: str, source_type: str
    ) -> CollectResult:
        title = item.get("title", "")
        url = item.get("url", "")
        if not title or not url:
            return CollectResult(skipped=1)

        # 민감 정보 플래그 (저장은 하되 sensitive=True로 표시)
        sensitive = is_sensitive_label(title)

        # 본문 fetch (실패해도 제목만으로 저장)
        body = self._fetch_article_body(url)
        content = f"# {title}\n\n**출처**: {url}\n**피드**: {feed_name}\n\n{body}"

        published = _parse_date(item.get("date", ""))
        doc_id = "news-" + hashlib.sha1(url.encode()).hexdigest()[:14]

        doc = VaultDoc(
            id=doc_id,
            title=title,
            content=content,
            source_type="news",
            source_url=url,
            published=published,
            retrieved=datetime.now().date(),
            confidence=ConfidenceLevel.UNVERIFIED,
            license="",  # 뉴스 저작권은 각 언론사 귀속
            sensitive=sensitive,
            extra={"feed_name": feed_name, "news_source_type": source_type},
        )
        saved = self._save(doc)
        return CollectResult(saved=1 if saved else 0, skipped=0 if saved else 1)

    def _fetch_article_body(self, url: str) -> str:
        """기사 본문을 가져온다. 실패하거나 본문이 짧으면 빈 문자열."""
        html = self._get(url)
        if not html:
            return ""
        # 스크립트·스타일 제거 후 p 태그 텍스트 추출
        html = re.sub(r"<script[^>]*>.*?</script>", "", html, flags=re.DOTALL | re.IGNORECASE)
        html = re.sub(r"<style[^>]*>.*?</style>", "", html, flags=re.DOTALL | re.IGNORECASE)
        paragraphs = re.findall(r"<p[^>]*>(.*?)</p>", html, flags=re.DOTALL | re.IGNORECASE)
        text = "\n\n".join(re.sub(r"<[^>]+>", "", p).strip() for p in paragraphs if len(p) > 30)
        return text[: self.max_body_chars]


def _parse_feed(xml_text: str) -> list[dict[str, str]]:
    """RSS 2.0 / Atom → item dict 목록."""
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError:
        return []

    tag = root.tag.lower()
    if "feed" in tag:
        return _parse_atom(root)
    return _parse_rss2(root)


def _parse_rss2(root: ET.Element) -> list[dict[str, str]]:
    items = []
    for item in root.findall(".//item"):
        items.append(
            {
                "title": (item.findtext("title") or "").strip(),
                "url": (item.findtext("link") or "").strip(),
                "date": (item.findtext("pubDate") or "").strip(),
            }
        )
    return items


def _parse_atom(root: ET.Element) -> list[dict[str, str]]:
    items = []
    for entry in root.findall(f"{{{_ATOM_NS}}}entry"):
        title_el = entry.find(f"{{{_ATOM_NS}}}title")
        link_el = entry.find(f"{{{_ATOM_NS}}}link")
        pub_el = entry.find(f"{{{_ATOM_NS}}}published")
        if pub_el is None:
            pub_el = entry.find(f"{{{_ATOM_NS}}}updated")
        items.append(
            {
                "title": (title_el.text or "").strip() if title_el is not None else "",
                "url": (link_el.get("href") or "").strip() if link_el is not None else "",
                "date": (pub_el.text or "").strip() if pub_el is not None else "",
            }
        )
    return items


def _parse_date(text: str) -> date | None:
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
