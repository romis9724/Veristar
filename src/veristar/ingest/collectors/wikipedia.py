"""Wikipedia 전문 수집기 (한국어·영어).

MediaWiki API로 본문 Wikitext → 마크다운 변환 후 vault에 저장.
저작권: CC BY-SA 4.0 (한국어), CC BY-SA 4.0 (영어).
"""

from __future__ import annotations

import logging
import re
import time
import urllib.parse
from datetime import datetime

from veristar.vault.store import ConfidenceLevel, VaultDoc, VaultStore

from .base import CollectorBase, CollectResult

logger = logging.getLogger(__name__)

_WIKI_APIS = {
    "ko": "https://ko.wikipedia.org/w/api.php",
    "en": "https://en.wikipedia.org/w/api.php",
}
_LICENSE = {
    "ko": "CC BY-SA 4.0",
    "en": "CC BY-SA 4.0",
}


def _wikitext_to_markdown(wikitext: str) -> str:
    """Wikitext → 단순 Markdown 변환 (완전하지 않지만 LLM 가독 수준)."""
    text = wikitext
    # 인포박스·템플릿 제거
    text = re.sub(r"\{\{[^}]*\}\}", "", text, flags=re.DOTALL)
    # 파일/이미지 링크 제거
    text = re.sub(r"\[\[파일:[^\]]*\]\]", "", text)
    text = re.sub(r"\[\[File:[^\]]*\]\]", "", text)
    # 위키링크 → 텍스트만
    text = re.sub(r"\[\[([^|\]]+)\|([^\]]+)\]\]", r"\2", text)
    text = re.sub(r"\[\[([^\]]+)\]\]", r"\1", text)
    # 외부 링크
    text = re.sub(r"\[https?://\S+ ([^\]]+)\]", r"\1", text)
    text = re.sub(r"\[https?://\S+\]", "", text)
    # 헤딩
    text = re.sub(r"={4}(.+?)={4}", r"#### \1", text)
    text = re.sub(r"={3}(.+?)={3}", r"### \1", text)
    text = re.sub(r"={2}(.+?)={2}", r"## \1", text)
    # 볼드·이탤릭
    text = re.sub(r"'''(.+?)'''", r"**\1**", text)
    text = re.sub(r"''(.+?)''", r"*\1*", text)
    # 빈 줄 정리
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


class WikipediaCollector(CollectorBase):
    """Wikipedia 한국어/영어 문서를 수집해 vault에 저장한다."""

    def __init__(
        self,
        store: VaultStore,
        langs: tuple[str, ...] = ("ko", "en"),
        timeout: float = 30.0,
        request_delay: float = 1.0,
    ) -> None:
        super().__init__(store, timeout)
        self.langs = langs
        self.request_delay = request_delay

    def collect(self, target: str, **kwargs: object) -> CollectResult:
        """target: 수집할 인물/그룹 이름 (한국어 또는 영어)."""
        result = CollectResult()
        for lang in self.langs:
            r = self._collect_lang(target, lang)
            result = result.merge(r)
            time.sleep(self.request_delay)
        return result

    def _collect_lang(self, query: str, lang: str) -> CollectResult:
        api = _WIKI_APIS.get(lang)
        if api is None:
            return CollectResult(errors=1, messages=[f"unsupported lang: {lang}"])

        # 1) 검색으로 정확한 페이지 제목 찾기
        title = self._search_title(query, api)
        if not title:
            logger.info("wikipedia[%s]: not found for '%s'", lang, query)
            return CollectResult(skipped=1)

        # 2) 본문 가져오기
        content_raw, page_url = self._fetch_content(title, api, lang)
        if not content_raw:
            return CollectResult(errors=1, messages=[f"fetch failed: {title}"])

        content_md = _wikitext_to_markdown(content_raw)
        if len(content_md) < 50:
            return CollectResult(skipped=1)

        doc_id = f"wikipedia-{lang}-{_slug(title)}"
        doc = VaultDoc(
            id=doc_id,
            title=f"{title} (Wikipedia {lang.upper()})",
            content=content_md,
            source_type="wikipedia",
            source_url=page_url,
            entity_refs=[_slug(query)],
            retrieved=datetime.now().date(),
            confidence=ConfidenceLevel.UNVERIFIED,
            license=_LICENSE[lang],
            extra={"lang": lang, "wiki_title": title},
        )
        saved = self._save(doc)
        return CollectResult(saved=1 if saved else 0, skipped=0 if saved else 1)

    def _search_title(self, query: str, api: str) -> str | None:
        params = {
            "action": "query",
            "list": "search",
            "srsearch": query,
            "srlimit": 1,
            "format": "json",
        }
        url = f"{api}?{urllib.parse.urlencode(params)}"
        text = self._get(url)
        if not text:
            return None
        import json
        data = json.loads(text)
        results = data.get("query", {}).get("search", [])
        return results[0]["title"] if results else None

    def _fetch_content(self, title: str, api: str, lang: str) -> tuple[str, str]:
        params = {
            "action": "query",
            "prop": "revisions",
            "rvprop": "content",
            "rvslots": "main",
            "titles": title,
            "format": "json",
        }
        url = f"{api}?{urllib.parse.urlencode(params)}"
        text = self._get(url)
        if not text:
            return "", ""
        import json
        data = json.loads(text)
        pages = data.get("query", {}).get("pages", {})
        for page in pages.values():
            content = (
                page.get("revisions", [{}])[0]
                .get("slots", {})
                .get("main", {})
                .get("*", "")
            )
            page_url = f"https://{lang}.wikipedia.org/wiki/{urllib.parse.quote(title)}"
            return content, page_url
        return "", ""


def _slug(text: str) -> str:
    s = text.lower().replace(" ", "-")
    s = re.sub(r"[^\w\-]", "", s)
    return s[:80]
