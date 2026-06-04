"""RSS 피드 파서 테스트."""

from __future__ import annotations

from datetime import date
from pathlib import Path

from veristar.ingest.news.rss import load_feed_configs, parse_feed

RSS2_SAMPLE = """\
<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0">
  <channel>
    <title>연예 뉴스</title>
    <item>
      <title>BTS, 새 앨범 발표</title>
      <link>https://news.example.com/bts-album</link>
      <pubDate>Mon, 01 Jan 2024 09:00:00 +0900</pubDate>
      <description>BTS가 새 앨범을 발표했다.</description>
    </item>
    <item>
      <title>블랙핑크 월드투어 확정</title>
      <link>https://news.example.com/bp-tour</link>
      <pubDate>Tue, 02 Jan 2024 10:00:00 +0900</pubDate>
    </item>
  </channel>
</rss>
"""

ATOM_SAMPLE = """\
<?xml version="1.0" encoding="UTF-8"?>
<feed xmlns="http://www.w3.org/2005/Atom">
  <entry>
    <title>aespa 컴백 확정</title>
    <link href="https://news.example.com/aespa-comeback"/>
    <published>2024-03-15T08:00:00Z</published>
  </entry>
</feed>
"""

MALFORMED_XML = "이건 XML이 아닙니다 <broken"


def test_parse_rss2_items() -> None:
    items = parse_feed(RSS2_SAMPLE, feed_name="테스트 피드")
    assert len(items) == 2
    assert items[0].title == "BTS, 새 앨범 발표"
    assert items[0].url == "https://news.example.com/bts-album"
    assert items[0].published == date(2024, 1, 1)
    assert items[0].feed_name == "테스트 피드"


def test_parse_rss2_no_pubdate() -> None:
    items = parse_feed(RSS2_SAMPLE)
    assert items[1].published == date(2024, 1, 2)


def test_parse_atom() -> None:
    items = parse_feed(ATOM_SAMPLE)
    assert len(items) == 1
    assert items[0].title == "aespa 컴백 확정"
    assert items[0].published == date(2024, 3, 15)


def test_parse_malformed_returns_empty() -> None:
    items = parse_feed(MALFORMED_XML)
    assert items == []


def test_parse_empty_xml() -> None:
    items = parse_feed("<rss><channel></channel></rss>")
    assert items == []


def test_description_truncated() -> None:
    """100자 초과 description은 summary에 포함되지 않는다."""
    long_desc = "A" * 200
    xml = f"""\
<rss version="2.0"><channel>
  <item>
    <title>Test</title>
    <link>https://example.com/test</link>
    <description>{long_desc}</description>
  </item>
</channel></rss>"""
    items = parse_feed(xml)
    assert items[0].summary == ""  # 너무 길어서 비움


def test_description_short_kept() -> None:
    xml = """\
<rss version="2.0"><channel>
  <item>
    <title>Test</title>
    <link>https://example.com/test</link>
    <description>짧은 요약</description>
  </item>
</channel></rss>"""
    items = parse_feed(xml)
    assert items[0].summary == "짧은 요약"


def test_load_feed_configs(tmp_path: Path) -> None:
    yaml_content = """\
feeds:
  - name: 연합뉴스 연예
    url: https://www.yna.co.kr/RSS/entertainment.xml
    source_type: PRESS
  - name: Soompi
    url: https://www.soompi.com/feed
    source_type: PRESS
"""
    cfg_file = tmp_path / "feeds.yaml"
    cfg_file.write_text(yaml_content, encoding="utf-8")
    configs = load_feed_configs(cfg_file)
    assert len(configs) == 2
    assert configs[0].name == "연합뉴스 연예"
    assert configs[0].source_type == "PRESS"
    assert configs[1].url == "https://www.soompi.com/feed"


def test_load_feed_configs_missing_file(tmp_path: Path) -> None:
    configs = load_feed_configs(tmp_path / "nonexistent.yaml")
    assert configs == []
