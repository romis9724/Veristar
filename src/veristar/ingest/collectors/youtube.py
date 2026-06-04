"""YouTube Data API v3 수집기.

공식 API를 통해 채널·영상 메타데이터(제목·설명·날짜)를 수집한다.
영상 파일 자체는 다운로드하지 않는다.

환경변수:
    YOUTUBE_API_KEY: YouTube Data API v3 키 (필수)

무료 할당량: 하루 10,000 unit. search 1회 = 100 unit.
"""

from __future__ import annotations

import logging
import os
import urllib.parse
from datetime import date, datetime

from veristar.vault.store import ConfidenceLevel, VaultDoc, VaultStore

from .base import CollectorBase, CollectResult

logger = logging.getLogger(__name__)

_YT_SEARCH_URL = "https://www.googleapis.com/youtube/v3/search"
_YT_CHANNEL_URL = "https://www.googleapis.com/youtube/v3/channels"
_YT_VIDEOS_URL = "https://www.googleapis.com/youtube/v3/videos"


class YouTubeCollector(CollectorBase):
    """YouTube Data API v3로 채널·영상 메타데이터를 수집한다."""

    def __init__(
        self,
        store: VaultStore,
        api_key: str | None = None,
        max_results: int = 20,
        timeout: float = 30.0,
    ) -> None:
        super().__init__(store, timeout)
        self.api_key = api_key or os.environ.get("YOUTUBE_API_KEY", "")
        self.max_results = max_results

    def collect(self, target: str, **kwargs: object) -> CollectResult:
        """target: 채널 ID (UCxxx) 또는 검색 키워드.

        channel_id가 있으면 채널 동영상 목록, 없으면 키워드 검색.
        """
        if not self.api_key:
            logger.warning("YOUTUBE_API_KEY 환경변수가 설정되지 않았습니다.")
            return CollectResult(errors=1, messages=["no API key"])

        channel_id = str(kwargs.get("channel_id", ""))
        if channel_id:
            return self._collect_channel(channel_id)
        return self._search(target)

    def _collect_channel(self, channel_id: str) -> CollectResult:
        # 채널 기본 정보
        params = {
            "key": self.api_key,
            "id": channel_id,
            "part": "snippet,statistics",
        }
        url = f"{_YT_CHANNEL_URL}?{urllib.parse.urlencode(params)}"
        import json
        text = self._get(url)
        if not text:
            return CollectResult(errors=1)

        data = json.loads(text)
        items = data.get("items", [])
        if not items:
            return CollectResult(skipped=1)

        ch = items[0]
        snippet = ch.get("snippet", {})
        stats = ch.get("statistics", {})

        channel_doc = VaultDoc(
            id=f"youtube-channel-{channel_id}",
            title=f"{snippet.get('title', channel_id)} (YouTube 채널)",
            content=(
                f"# {snippet.get('title', '')}\n\n"
                f"**설명**: {snippet.get('description', '')[:500]}\n\n"
                f"**구독자**: {stats.get('subscriberCount', '비공개')}\n"
                f"**동영상 수**: {stats.get('videoCount', '?')}\n"
                f"**채널 ID**: {channel_id}\n"
            ),
            source_type="youtube",
            source_url=f"https://www.youtube.com/channel/{channel_id}",
            retrieved=datetime.now().date(),
            confidence=ConfidenceLevel.UNVERIFIED,
            extra={"channel_id": channel_id},
        )
        saved = self._save(channel_doc)
        return CollectResult(saved=1 if saved else 0)

    def _search(self, query: str) -> CollectResult:
        params = {
            "key": self.api_key,
            "q": query,
            "part": "snippet",
            "type": "video",
            "maxResults": min(self.max_results, 50),
            "relevanceLanguage": "ko",
        }
        url = f"{_YT_SEARCH_URL}?{urllib.parse.urlencode(params)}"
        import json
        text = self._get(url)
        if not text:
            return CollectResult(errors=1)

        data = json.loads(text)
        result = CollectResult()
        for item in data.get("items", []):
            snippet = item.get("snippet", {})
            video_id = item.get("id", {}).get("videoId", "")
            if not video_id:
                continue

            title = snippet.get("title", "")
            description = snippet.get("description", "")[:300]
            published = snippet.get("publishedAt", "")[:10]

            doc = VaultDoc(
                id=f"youtube-video-{video_id}",
                title=f"{title} (YouTube)",
                content=(
                    f"# {title}\n\n"
                    f"**채널**: {snippet.get('channelTitle', '')}\n"
                    f"**날짜**: {published}\n\n"
                    f"**설명**:\n{description}\n"
                ),
                source_type="youtube",
                source_url=f"https://www.youtube.com/watch?v={video_id}",
                entity_refs=[],
                published=_parse_date(published),
                retrieved=datetime.now().date(),
                confidence=ConfidenceLevel.UNVERIFIED,
                extra={"video_id": video_id, "channel_id": snippet.get("channelId", "")},
            )
            saved = self._save(doc)
            result = result.merge(CollectResult(saved=1 if saved else 0, skipped=0 if saved else 1))
        return result


def _parse_date(text: str) -> date | None:
    if not text:
        return None
    try:
        return datetime.strptime(text, "%Y-%m-%d").date()
    except ValueError:
        return None
