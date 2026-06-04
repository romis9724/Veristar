"""나무위키 수집기.

저작권: CC BY-NC-SA 2.0 KR
- 비상업적 사용·출처 표기·동일 조건 배포 조건.
- raw 보관은 허용, 상업화 시 라이선스 검토 필요.
- 나무위키 API(namu.wiki/api)는 비공개 — 공개 위키텍스트 파싱 사용.

경고: 나무위키는 이용자 편집 기반으로 미검증 내용이 포함될 수 있다.
confidence는 항상 UNVERIFIED로 시작한다.
"""

from __future__ import annotations

import json
import logging
import re
import urllib.parse
from datetime import datetime

from veristar.vault.store import ConfidenceLevel, VaultDoc

from .base import CollectorBase, CollectResult

logger = logging.getLogger(__name__)

_NAMU_API = "https://namu.wiki/api/v1"
_NAMU_BASE = "https://namu.wiki"
_LICENSE = "CC BY-NC-SA 2.0 KR"


def _namu_to_markdown(text: str) -> str:
    """나무위키 문법 → 단순 Markdown."""
    # 접기
    text = re.sub(r"\|\|.*?\|\|", "", text, flags=re.DOTALL)
    # 링크 [text](url) or [[문서]]
    text = re.sub(r"\[\[([^\]|]+)\|([^\]]+)\]\]", r"\2", text)
    text = re.sub(r"\[\[([^\]]+)\]\]", r"\1", text)
    # 헤딩 == 헤딩 ==
    text = re.sub(r"={5}(.+?)={5}", r"##### \1", text)
    text = re.sub(r"={4}(.+?)={4}", r"#### \1", text)
    text = re.sub(r"={3}(.+?)={3}", r"### \1", text)
    text = re.sub(r"={2}(.+?)={2}", r"## \1", text)
    # 볼드·이탤릭
    text = re.sub(r"'''(.+?)'''", r"**\1**", text)
    text = re.sub(r"''(.+?)''", r"*\1*", text)
    # 각주
    text = re.sub(r"\[각주\]|\[주\d+\]|\[.*?\]", "", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


class NamuWikiCollector(CollectorBase):
    """나무위키 문서를 수집해 vault에 저장한다."""

    def collect(self, target: str, **kwargs: object) -> CollectResult:
        """target: 수집할 나무위키 문서 제목 (한국어)."""
        # 나무위키 문서 직접 접근 (API 대신 w/{title}.json)
        encoded = urllib.parse.quote(target)
        api_url = f"{_NAMU_BASE}/w/{encoded}.json"
        text = self._get(api_url)

        if not text:
            # 일반 페이지 scraping fallback
            return self._scrape_fallback(target)

        try:
            data = json.loads(text)
        except json.JSONDecodeError:
            return self._scrape_fallback(target)

        content_raw = data.get("text", "") or data.get("content", "")
        if not content_raw:
            return CollectResult(skipped=1)

        content_md = _namu_to_markdown(content_raw)
        page_url = f"{_NAMU_BASE}/w/{encoded}"

        doc = VaultDoc(
            id=f"namuwiki-{_slug(target)}",
            title=f"{target} (나무위키)",
            content=f"> ⚠️ 나무위키: {_LICENSE}. 비상업적·출처 표기 필수.\n\n{content_md}",
            source_type="namuwiki",
            source_url=page_url,
            entity_refs=[_slug(target)],
            retrieved=datetime.now().date(),
            confidence=ConfidenceLevel.UNVERIFIED,
            license=_LICENSE,
            extra={"namu_title": target},
        )
        saved = self._save(doc)
        return CollectResult(saved=1 if saved else 0, skipped=0 if saved else 1)

    def _scrape_fallback(self, target: str) -> CollectResult:
        """API 실패 시 일반 HTML에서 본문 추출."""
        encoded = urllib.parse.quote(target)
        url = f"{_NAMU_BASE}/w/{encoded}"
        html = self._get(url)
        if not html:
            return CollectResult(errors=1, messages=[f"namu fetch failed: {target}"])

        # 본문 텍스트만 추출 (스크립트·스타일 제거)
        text = re.sub(r"<script[^>]*>.*?</script>", "", html, flags=re.DOTALL | re.IGNORECASE)
        text = re.sub(r"<style[^>]*>.*?</style>", "", text, flags=re.DOTALL | re.IGNORECASE)
        text = re.sub(r"<[^>]+>", "", text)
        text = re.sub(r"\n{3,}", "\n\n", text).strip()

        if len(text) < 100:
            return CollectResult(skipped=1)

        doc = VaultDoc(
            id=f"namuwiki-{_slug(target)}",
            title=f"{target} (나무위키)",
            content=f"> ⚠️ 나무위키: {_LICENSE}. 비상업적·출처 표기 필수.\n\n{text[:10000]}",
            source_type="namuwiki",
            source_url=url,
            entity_refs=[_slug(target)],
            retrieved=datetime.now().date(),
            confidence=ConfidenceLevel.UNVERIFIED,
            license=_LICENSE,
            extra={"namu_title": target, "method": "scrape"},
        )
        saved = self._save(doc)
        return CollectResult(saved=1 if saved else 0, skipped=0 if saved else 1)


def _slug(text: str) -> str:
    s = text.lower().replace(" ", "-")
    s = re.sub(r"[^\w\-]", "", s)
    return s[:80]
