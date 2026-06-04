"""나무위키 수집기.

저작권: CC BY-NC-SA 2.0 KR
- 비상업적 사용·출처 표기·동일 조건 배포 조건.
- raw 보관은 허용, 상업화 시 라이선스 검토 필요.

⚠️ 기술적 한계: 나무위키는 완전 클라이언트사이드 렌더링(CSR) 방식이라
일반 HTTP 요청으로는 본문 텍스트를 가져올 수 없다.
현재 수집기는 TOC(섹션 구조)와 메타데이터만 추출한다.
본문 전문 수집에는 Playwright 등 headless browser가 필요하다.

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


def _extract_namu_body(html: str) -> str:
    """나무위키 HTML → 본문 단락만 추출.

    나무위키는 서버사이드에서 다양한 클래스로 단락을 렌더링한다.
    시도 순서:
      1. <div class="wiki-paragraph"> (나무위키 주력 컨테이너)
      2. <p class="wiki-paragraph">
      3. 헤딩 + 일반 <p> 조합 (단락이 충분한 경우만)
      4. 전체 텍스트에서 '개요' 마커 이후 잘라내기 (최후 fallback)
    """
    import html as html_module

    def clean(raw: str) -> str:
        raw = re.sub(r"<[^>]+>", "", raw)
        raw = html_module.unescape(raw)
        return re.sub(r"\s+", " ", raw).strip()

    # 스크립트·스타일·nav·header 제거
    for tag in ("script", "style", "nav", "header", "footer"):
        html = re.sub(
            rf"<{tag}[^>]*>.*?</{tag}>", "", html, flags=re.DOTALL | re.IGNORECASE
        )

    # 1순위: <div class="wiki-paragraph"> (나무위키 본문 컨테이너)
    div_paras = [
        clean(m.group(1))
        for m in re.finditer(
            r'<div[^>]*class="[^"]*wiki-paragraph[^"]*"[^>]*>(.*?)</div>',
            html,
            flags=re.DOTALL | re.IGNORECASE,
        )
    ]
    div_paras = [p for p in div_paras if len(p) > 30]

    # 2순위: <p class="wiki-paragraph">
    p_paras = [
        clean(m.group(1))
        for m in re.finditer(
            r'<p[^>]*class="[^"]*wiki-paragraph[^"]*"[^>]*>(.*?)</p>',
            html,
            flags=re.DOTALL | re.IGNORECASE,
        )
    ]
    p_paras = [p for p in p_paras if len(p) > 30]

    paragraphs = div_paras or p_paras

    # 헤딩 추출 (위치 포함)
    heading_items = [
        (m.start(), f"{'#' * int(m.group(1))} {clean(m.group(2))}")
        for m in re.finditer(
            r"<h([2-5])[^>]*>(.*?)</h\1>", html, flags=re.DOTALL | re.IGNORECASE
        )
    ]

    if paragraphs:
        # 단락이 있으면 헤딩 + 단락 합산
        para_items = [
            (m.start(), clean(m.group(1)))
            for m in (
                re.finditer(
                    r'<div[^>]*class="[^"]*wiki-paragraph[^"]*"[^>]*>(.*?)</div>',
                    html,
                    flags=re.DOTALL | re.IGNORECASE,
                )
                if div_paras
                else re.finditer(
                    r'<p[^>]*class="[^"]*wiki-paragraph[^"]*"[^>]*>(.*?)</p>',
                    html,
                    flags=re.DOTALL | re.IGNORECASE,
                )
            )
            if len(clean(m.group(1))) > 30
        ]
        combined = sorted(heading_items + para_items, key=lambda x: x[0])
        parts = [text for _, text in combined if text]
        if parts:
            return "\n\n".join(parts[:300])

    # 3순위: 일반 <p> 태그가 충분히 긴 경우
    general_p = [
        clean(m.group(1))
        for m in re.finditer(r"<p[^>]*>(.*?)</p>", html, flags=re.DOTALL | re.IGNORECASE)
    ]
    general_p = [p for p in general_p if len(p) > 50]
    if len(general_p) >= 3:
        return "\n\n".join(general_p[:200])

    # 4순위 (최후 fallback): 전체 텍스트에서 '개요' 마커 이후 추출
    plain = re.sub(r"<[^>]+>", "", html)
    plain = html_module.unescape(plain)
    plain = re.sub(r"\s{2,}", " ", plain)

    for marker in ("1. 개요", "개요[편집]", "개요 [편집]"):
        idx = plain.find(marker)
        if idx > 0:
            plain = plain[idx:]
            break

    return plain[:10000].strip()


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
        """API 실패 시 일반 HTML에서 본문 추출 (개선된 파서 사용)."""
        encoded = urllib.parse.quote(target)
        url = f"{_NAMU_BASE}/w/{encoded}"
        html = self._get(url)
        if not html:
            return CollectResult(errors=1, messages=[f"namu fetch failed: {target}"])

        text = _extract_namu_body(html)

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
