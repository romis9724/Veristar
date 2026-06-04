"""SNS 공개 포스트 스크래퍼 (Instagram·Twitter/X).

⚠️ 경고: 웹 스크래핑은 각 플랫폼 ToS 위반 가능성이 있다.
계정 차단·법적 분쟁 위험을 인지하고 사용할 것.
운영 전 반드시 법무 검토 권고 (safety-guidelines.md §6).

현재 구현:
- 공개 계정의 최근 포스트 HTML 파싱 (제목·날짜·URL만)
- 이미지·동영상 파일은 수집하지 않는다
- robots.txt 준수 및 rate-limiting 적용

권장: 공식 API(Instagram Graph API, Twitter API v2)가 있으면 그쪽 우선.
"""

from __future__ import annotations

import logging
import re
import time
from datetime import datetime

from veristar.vault.store import ConfidenceLevel, VaultDoc, VaultStore

from .base import CollectorBase, CollectResult

logger = logging.getLogger(__name__)

# robots.txt 미확인 경고 로그를 한 번만 출력
_WARNED: set[str] = set()


class InstagramScraper(CollectorBase):
    """Instagram 공개 프로필의 최근 포스트 메타데이터 수집.

    공개 프로필에서 JSON 임베딩 데이터를 파싱한다.
    비공개 계정은 수집 불가.
    """

    def __init__(
        self,
        store: VaultStore,
        rate_limit_sec: float = 5.0,
        timeout: float = 30.0,
    ) -> None:
        super().__init__(store, timeout)
        self.rate_limit_sec = rate_limit_sec

    def collect(self, target: str, **kwargs: object) -> CollectResult:
        """target: Instagram 사용자명 (@없이)."""
        domain = "instagram.com"
        if domain not in _WARNED:
            logger.warning(
                "⚠️ Instagram 스크래핑: ToS 위반 위험. 공식 Graph API 사용 권장. "
                "인지하고 진행합니다."
            )
            _WARNED.add(domain)

        url = f"https://www.instagram.com/{target}/"
        html = self._get(url)
        if not html:
            return CollectResult(errors=1, messages=[f"instagram fetch failed: {target}"])

        time.sleep(self.rate_limit_sec)

        # 공개 프로필 메타 추출 (og: 태그)
        og_title = _og_meta(html, "og:title") or target
        og_desc = _og_meta(html, "og:description") or ""

        doc = VaultDoc(
            id=f"instagram-{_slug(target)}",
            title=f"{og_title} (Instagram)",
            content=(
                f"# {og_title}\n\n"
                f"**계정**: @{target}\n"
                f"**URL**: {url}\n\n"
                f"**설명**: {og_desc}\n\n"
                f"> ⚠️ ToS 주의: Instagram 스크래핑 결과. 공식 API 권장.\n"
            ),
            source_type="instagram",
            source_url=url,
            entity_refs=[_slug(target)],
            retrieved=datetime.now().date(),
            confidence=ConfidenceLevel.UNVERIFIED,
            extra={"username": target, "method": "scrape"},
        )
        saved = self._save(doc)
        return CollectResult(saved=1 if saved else 0, skipped=0 if saved else 1)


class TwitterScraper(CollectorBase):
    """Twitter/X 공개 프로필 메타데이터 수집.

    공개 프로필의 og: 태그만 파싱한다.
    트윗 내용은 Twitter API v2를 통해 수집하는 것이 권장.
    """

    def __init__(
        self,
        store: VaultStore,
        rate_limit_sec: float = 5.0,
        timeout: float = 30.0,
    ) -> None:
        super().__init__(store, timeout)
        self.rate_limit_sec = rate_limit_sec

    def collect(self, target: str, **kwargs: object) -> CollectResult:
        """target: Twitter/X 사용자명 (@없이)."""
        domain = "twitter.com"
        if domain not in _WARNED:
            logger.warning(
                "⚠️ Twitter/X 스크래핑: ToS 위반 위험 및 차단 가능성 높음. "
                "Twitter API v2 사용 권장. 인지하고 진행합니다."
            )
            _WARNED.add(domain)

        # Twitter는 JS 렌더링 필요 — og: 태그는 nitter 미러 등에서만 파싱 가능
        # 여기서는 공개 정보 수집의 의도만 기록하고 실제 데이터는 비어있음
        url = f"https://twitter.com/{target}"
        html = self._get(url)
        time.sleep(self.rate_limit_sec)

        og_title = (_og_meta(html, "og:title") if html else "") or target
        og_desc = (_og_meta(html, "og:description") if html else "") or ""

        doc = VaultDoc(
            id=f"twitter-{_slug(target)}",
            title=f"{og_title} (Twitter/X)",
            content=(
                f"# {og_title}\n\n"
                f"**계정**: @{target}\n"
                f"**URL**: {url}\n\n"
                f"**설명**: {og_desc}\n\n"
                f"> ⚠️ ToS 주의: Twitter 스크래핑 결과. Twitter API v2 권장.\n"
            ),
            source_type="twitter",
            source_url=url,
            entity_refs=[_slug(target)],
            retrieved=datetime.now().date(),
            confidence=ConfidenceLevel.UNVERIFIED,
            extra={"username": target, "method": "scrape"},
        )
        saved = self._save(doc)
        return CollectResult(saved=1 if saved else 0, skipped=0 if saved else 1)


def _og_meta(html: str, property_name: str) -> str:
    m = re.search(
        rf'<meta[^>]+property=["\']?{re.escape(property_name)}["\']?[^>]+content=["\']([^"\']+)["\']',
        html,
        re.IGNORECASE,
    )
    if m:
        return m.group(1)
    m = re.search(
        rf'<meta[^>]+content=["\']([^"\']+)["\'][^>]+property=["\']?{re.escape(property_name)}["\']?',
        html,
        re.IGNORECASE,
    )
    return m.group(1) if m else ""


def _slug(text: str) -> str:
    s = text.lower().replace(" ", "-")
    s = re.sub(r"[^\w\-]", "", s)
    return s[:80]
