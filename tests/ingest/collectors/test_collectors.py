"""수집기 단위 테스트 (HTTP 모킹)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from veristar.ingest.collectors.base import CollectResult
from veristar.ingest.collectors.namuwiki import NamuWikiCollector
from veristar.ingest.collectors.news import NewsCollector
from veristar.ingest.collectors.runner import load_celebrity_list
from veristar.ingest.collectors.wikipedia import WikipediaCollector
from veristar.vault.store import VaultStore


@pytest.fixture
def vault(tmp_path: Path) -> VaultStore:
    return VaultStore(tmp_path / "vault")


# === Wikipedia 수집기 ===

_WIKI_SEARCH_RESP = json.dumps({"query": {"search": [{"title": "아이유"}]}})
_WIKI_CONTENT_RESP = json.dumps(
    {
        "query": {
            "pages": {
                "12345": {
                    "revisions": [
                        {
                            "slots": {
                                "main": {
                                    "*": (
                                        "== 생애 ==\n"
                                        "아이유(본명 이지은, 1993년 5월 16일~)는 "
                                        "대한민국의 가수이자 배우이다. "
                                        "2008년 데뷔해 '불후의 명곡', "
                                        "'나의 아저씨' 등으로 활동 중이다.\n\n"
                                        "== 음악 ==\n"
                                        "국내외 음원 차트에서 다수의 1위를 기록했다."
                                    )
                                }
                            }
                        }
                    ]
                }
            }
        }
    }
)


def test_wikipedia_collect_saves_doc(vault: VaultStore) -> None:
    collector = WikipediaCollector(vault, langs=("ko",))

    responses = [_WIKI_SEARCH_RESP, _WIKI_CONTENT_RESP]
    idx = 0

    def fake_get(url: str) -> str | None:
        nonlocal idx
        if idx < len(responses):
            r = responses[idx]
            idx += 1
            return r
        return None

    collector._get = fake_get  # type: ignore[assignment]

    result = collector.collect("아이유")
    assert result.saved == 1
    assert result.errors == 0


def test_wikipedia_not_found(vault: VaultStore) -> None:
    collector = WikipediaCollector(vault, langs=("ko",))
    collector._get = lambda url: json.dumps({"query": {"search": []}})  # type: ignore[assignment]

    result = collector.collect("없는인물xyzxyz")
    assert result.saved == 0
    assert result.skipped == 1


def test_wikipedia_fetch_failure(vault: VaultStore) -> None:
    collector = WikipediaCollector(vault, langs=("ko",))
    calls = [_WIKI_SEARCH_RESP, None]
    idx = 0

    def fake_get(url: str) -> str | None:
        nonlocal idx
        r = calls[idx] if idx < len(calls) else None
        idx += 1
        return r

    collector._get = fake_get  # type: ignore[assignment]
    result = collector.collect("아이유")
    assert result.errors == 1


# === 나무위키 수집기 ===


def test_namuwiki_collect_json_api(vault: VaultStore) -> None:
    collector = NamuWikiCollector(vault)
    namu_json = json.dumps({"text": "== 개요 ==\n아이유(본명 이지은)는 가수이다."})
    collector._get = lambda url: namu_json  # type: ignore[assignment]

    result = collector.collect("아이유")
    assert result.saved == 1
    doc = vault.read("namuwiki-아이유")
    assert doc is not None
    assert "CC BY-NC-SA" in doc.content


def test_namuwiki_scrape_fallback(vault: VaultStore) -> None:
    """JSON API 실패 시 HTML fallback."""
    collector = NamuWikiCollector(vault)
    # 본문 길이가 100자 이상이어야 저장됨
    long_para = "<p>아이유(본명 이지은)는 대한민국의 가수이자 배우로 2008년 데뷔했다.</p>"
    calls: list[str | None] = [
        None,  # JSON API 실패
        "<html><body>" + long_para * 5 + "</body></html>",
    ]
    idx = 0

    def fake_get(url: str) -> str | None:
        nonlocal idx
        r = calls[idx] if idx < len(calls) else None
        idx += 1
        return r

    collector._get = fake_get  # type: ignore[assignment]
    result = collector.collect("아이유")
    assert result.saved == 1


def test_namuwiki_both_fail(vault: VaultStore) -> None:
    # Playwright 비활성화 + HTTP fallback도 실패 → errors=1
    collector = NamuWikiCollector(vault, use_playwright=False)
    collector._get = lambda url: None  # type: ignore[assignment]
    result = collector.collect("없는항목")
    assert result.errors == 1


# === 뉴스 수집기 ===

_RSS_FEED = """\
<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0">
  <channel>
    <item>
      <title>아이유 새 앨범 발매</title>
      <link>https://news.example.com/iu-album</link>
      <pubDate>Mon, 01 Jan 2024 09:00:00 +0900</pubDate>
    </item>
    <item>
      <title>BTS 월드투어</title>
      <link>https://news.example.com/bts-tour</link>
    </item>
  </channel>
</rss>
"""

_ARTICLE_HTML = "<html><body>" + "<p>아이유가 새 앨범을 발매했다.</p>" * 10 + "</body></html>"


def test_news_collect_saves_articles(vault: VaultStore) -> None:
    collector = NewsCollector(vault)
    calls: dict[str, str] = {
        "https://feed.example.com/rss": _RSS_FEED,
        "https://news.example.com/iu-album": _ARTICLE_HTML,
        "https://news.example.com/bts-tour": _ARTICLE_HTML,
    }
    collector._get = lambda url: calls.get(url)  # type: ignore[assignment]

    result = collector.collect("https://feed.example.com/rss", feed_name="테스트")
    assert result.saved == 2


def test_news_sensitive_flagged(vault: VaultStore) -> None:
    rss = """\
<?xml version="1.0"?><rss version="2.0"><channel>
<item><title>아이돌 열애설 포착</title><link>https://x.com/1</link></item>
</channel></rss>"""
    collector = NewsCollector(vault)
    collector._get = lambda url: rss if "feed" in url else "<p>내용</p>"  # type: ignore[assignment]

    result = collector.collect("https://feed.example.com/rss")
    assert result.saved == 1
    docs = vault.list_docs(source_type="news")
    assert docs[0].sensitive is True


def test_news_feed_fetch_fail(vault: VaultStore) -> None:
    collector = NewsCollector(vault)
    collector._get = lambda url: None  # type: ignore[assignment]
    result = collector.collect("https://broken.example.com/feed")
    assert result.errors == 1


# === runner 설정 파싱 ===


def test_load_celebrity_list(tmp_path: Path) -> None:
    yaml = tmp_path / "celebs.yaml"
    yaml.write_text(
        """\
celebrities:
  - name: 아이유
    namu_title: 아이유
    youtube_channel: UCxxx
  - name: BTS
    namu_title: 방탄소년단
""",
        encoding="utf-8",
    )
    celebs = load_celebrity_list(yaml)
    assert len(celebs) == 2
    assert celebs[0]["name"] == "아이유"
    assert celebs[0]["youtube_channel"] == "UCxxx"
    assert celebs[1]["namu_title"] == "방탄소년단"


def test_load_celebrity_list_missing(tmp_path: Path) -> None:
    result = load_celebrity_list(tmp_path / "no_file.yaml")
    assert result == []


def test_collect_result_merge() -> None:
    a = CollectResult(saved=1, skipped=2, errors=0)
    b = CollectResult(saved=3, skipped=0, errors=1)
    merged = a.merge(b)
    assert merged.saved == 4
    assert merged.skipped == 2
    assert merged.errors == 1
