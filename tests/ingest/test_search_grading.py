"""DomainGrading 단위 테스트 — yaml 화이트리스트 정확/서브도메인 매칭."""

from __future__ import annotations

from pathlib import Path

import pytest

from veristar.ingest.search.domain_grading import DomainGrading
from veristar.ontology.enums import Grade, SourceType


@pytest.fixture
def grading(tmp_path: Path) -> DomainGrading:
    """테스트용 yaml — 최소 도메인 셋."""
    cfg = tmp_path / "g.yaml"
    cfg.write_text(
        "official:\n"
        "  - smtown.com\n"
        "  - bighitmusic.com\n"
        "reported:\n"
        "  - news.naver.com\n"
        "  - yna.co.kr\n"
        "blocked:\n"
        "  - badsite.example\n",
        encoding="utf-8",
    )
    return DomainGrading(cfg)


def test_official_exact_match(grading: DomainGrading) -> None:
    v = grading.classify("https://smtown.com/artist/aespa")
    assert v.grade == Grade.OFFICIAL
    assert v.source_type == SourceType.ARTIST_OFFICIAL_SNS
    assert v.domain == "smtown.com"
    assert v.blocked is False


def test_official_subdomain_match(grading: DomainGrading) -> None:
    v = grading.classify("https://shop.smtown.com/item/123")
    assert v.grade == Grade.OFFICIAL, "서브도메인이 화이트리스트 도메인을 포함하면 매칭되어야 함"


def test_reported_match(grading: DomainGrading) -> None:
    v = grading.classify("https://news.naver.com/article/001")
    assert v.grade == Grade.REPORTED
    assert v.source_type == SourceType.PRESS


def test_www_prefix_normalized(grading: DomainGrading) -> None:
    v = grading.classify("https://www.yna.co.kr/view/x")
    assert v.grade == Grade.REPORTED, "www. 접두사는 정규화되어야 함"


def test_unknown_domain_defaults_rumor(grading: DomainGrading) -> None:
    v = grading.classify("https://blog.naver.com/random_user/post")
    # blog.naver.com은 화이트리스트에 없음 → RUMOR
    assert v.grade == Grade.RUMOR
    assert v.source_type == SourceType.COMMUNITY_OR_ANON


def test_blocked_domain(grading: DomainGrading) -> None:
    v = grading.classify("https://badsite.example/foo")
    assert v.blocked is True
    assert v.grade == Grade.RUMOR


def test_malformed_url(grading: DomainGrading) -> None:
    v = grading.classify("not a url at all")
    assert v.grade == Grade.RUMOR
    # 도메인 추출 실패 시에도 예외 없이 RUMOR 반환


def test_missing_config_file(tmp_path: Path) -> None:
    """설정 파일이 없어도 예외 없이 RUMOR로 폴백."""
    g = DomainGrading(tmp_path / "nope.yaml")
    v = g.classify("https://smtown.com/x")
    assert v.grade == Grade.RUMOR


def test_real_config_loads() -> None:
    """프로젝트 실제 config/source_grading.yaml이 로드되는지 회귀 가드."""
    g = DomainGrading()  # 기본 경로
    v = g.classify("https://smtown.com/")
    assert v.grade == Grade.OFFICIAL
    v2 = g.classify("https://yna.co.kr/article")
    assert v2.grade == Grade.REPORTED
