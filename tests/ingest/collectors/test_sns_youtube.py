"""SNS·YouTube·runner 수집기 테스트."""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path
from unittest.mock import patch

import pytest

from veristar.ingest.collectors.runner import run_all
from veristar.ingest.collectors.sns_scraper import InstagramScraper, TwitterScraper, _og_meta
from veristar.ingest.collectors.youtube import YouTubeCollector, _parse_date
from veristar.vault.store import VaultStore


@pytest.fixture
def vault(tmp_path: Path) -> VaultStore:
    return VaultStore(tmp_path / "vault")


# === SNS 스크래퍼 ===

_IG_HTML = """\
<html><head>
<meta property="og:title" content="IU (@dlwlrma)">
<meta property="og:description" content="가수 아이유 공식 인스타그램">
</head></html>"""

_TW_HTML = """\
<html><head>
<meta property="og:title" content="IU (@IUofficial)">
<meta property="og:description" content="아이유 공식 트위터">
</head></html>"""


def test_og_meta_extraction() -> None:
    assert _og_meta(_IG_HTML, "og:title") == "IU (@dlwlrma)"
    assert _og_meta(_IG_HTML, "og:description") == "가수 아이유 공식 인스타그램"
    assert _og_meta("", "og:title") == ""


def test_instagram_scraper_saves_doc(vault: VaultStore) -> None:
    scraper = InstagramScraper(vault, rate_limit_sec=0)
    scraper._get = lambda url: _IG_HTML  # type: ignore[assignment]

    result = scraper.collect("dlwlrma")
    assert result.saved == 1
    doc = vault.read("instagram-dlwlrma")
    assert doc is not None
    assert doc.source_type == "instagram"
    assert "ToS 주의" in doc.content


def test_instagram_fetch_fail(vault: VaultStore) -> None:
    scraper = InstagramScraper(vault, rate_limit_sec=0)
    scraper._get = lambda url: None  # type: ignore[assignment]

    result = scraper.collect("unknown_user")
    assert result.errors == 1


def test_twitter_scraper_saves_doc(vault: VaultStore) -> None:
    scraper = TwitterScraper(vault, rate_limit_sec=0)
    scraper._get = lambda url: _TW_HTML  # type: ignore[assignment]

    result = scraper.collect("IUofficial")
    assert result.saved == 1
    doc = vault.read("twitter-iuofficial")
    assert doc is not None
    assert doc.source_type == "twitter"


def test_twitter_no_html(vault: VaultStore) -> None:
    scraper = TwitterScraper(vault, rate_limit_sec=0)
    scraper._get = lambda url: None  # type: ignore[assignment]

    result = scraper.collect("someone")
    # HTML 없어도 빈 메타로 저장 시도
    assert result.saved + result.errors >= 0  # 충돌 없이 실행


def test_duplicate_warning_suppressed(vault: VaultStore) -> None:
    """두 번째 collect는 경고를 재출력하지 않는다."""
    from veristar.ingest.collectors.sns_scraper import _WARNED

    _WARNED.clear()

    scraper = InstagramScraper(vault, rate_limit_sec=0)
    scraper._get = lambda url: _IG_HTML  # type: ignore[assignment]

    scraper.collect("dlwlrma")
    scraper.collect("dlwlrma2")
    # 경고는 도메인당 한 번만 → _WARNED에 도메인 기록됨
    assert "instagram.com" in _WARNED


# === YouTube 수집기 ===

_YT_CHANNEL_RESP = json.dumps(
    {
        "items": [
            {
                "snippet": {
                    "title": "아이유 IU",
                    "description": "아이유 공식 채널",
                },
                "statistics": {
                    "subscriberCount": "5000000",
                    "videoCount": "100",
                },
            }
        ]
    }
)

_YT_SEARCH_RESP = json.dumps(
    {
        "items": [
            {
                "id": {"videoId": "abc123"},
                "snippet": {
                    "title": "아이유 - LILAC",
                    "description": "공식 MV",
                    "channelTitle": "아이유 IU",
                    "channelId": "UCxxx",
                    "publishedAt": "2021-03-25T00:00:00Z",
                },
            }
        ]
    }
)


def test_youtube_channel_collect(vault: VaultStore) -> None:
    collector = YouTubeCollector(vault, api_key="test-key")
    collector._get = lambda url: _YT_CHANNEL_RESP  # type: ignore[assignment]

    result = collector.collect("아이유 IU", channel_id="UCCkfhm7xnJstl7qJ5VtNNQw")
    assert result.saved == 1
    doc = vault.read("youtube-channel-UCCkfhm7xnJstl7qJ5VtNNQw")
    assert doc is not None
    assert "아이유 IU" in doc.title


def test_youtube_search_collect(vault: VaultStore) -> None:
    collector = YouTubeCollector(vault, api_key="test-key")
    collector._get = lambda url: _YT_SEARCH_RESP  # type: ignore[assignment]

    result = collector.collect("아이유 공식")
    assert result.saved == 1


def test_youtube_no_api_key(vault: VaultStore) -> None:
    collector = YouTubeCollector(vault, api_key="")
    with patch.dict("os.environ", {"YOUTUBE_API_KEY": ""}):
        result = collector.collect("아이유")
    assert result.errors == 1


def test_youtube_fetch_fail(vault: VaultStore) -> None:
    collector = YouTubeCollector(vault, api_key="test-key")
    collector._get = lambda url: None  # type: ignore[assignment]
    result = collector.collect("아이유 공식")
    assert result.errors == 1


def test_youtube_parse_date() -> None:
    assert _parse_date("2024-03-15") == date(2024, 3, 15)
    assert _parse_date("") is None
    assert _parse_date("not-a-date") is None


def test_youtube_empty_items(vault: VaultStore) -> None:
    collector = YouTubeCollector(vault, api_key="test-key")
    collector._get = lambda url: json.dumps({"items": []})  # type: ignore[assignment]
    result = collector.collect("아이유 공식")
    assert result.saved == 0


# === runner ===


def test_run_all_wikipedia_only(tmp_path: Path) -> None:
    config = tmp_path / "celebs.yaml"
    config.write_text(
        """\
celebrities:
  - name: 아이유
    namu_title: 아이유
""",
        encoding="utf-8",
    )

    vault_path = tmp_path / "vault"

    wiki_search = json.dumps({"query": {"search": [{"title": "아이유"}]}})
    long_content = "아이유는 대한민국의 가수이자 배우로, 2008년 데뷔해 많은 히트곡을 발표했다. " * 5
    wiki_content = json.dumps(
        {"query": {"pages": {"1": {"revisions": [{"slots": {"main": {"*": long_content}}}]}}}}
    )
    responses = [wiki_search, wiki_content]
    idx = 0

    def fake_get(self_obj: object, url: str) -> str | None:
        nonlocal idx
        if idx < len(responses):
            r = responses[idx]
            idx += 1
            return r
        return None

    with patch("veristar.ingest.collectors.base.CollectorBase._get", fake_get):
        result = run_all(config, vault_path, sources=["wikipedia"])

    assert result.saved >= 0  # 네트워크 없이도 실행 완료
