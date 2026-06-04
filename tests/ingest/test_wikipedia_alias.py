"""Wikipedia 별칭 보완기 테스트 (HTTP 모킹, 실제 API 미사용)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from veristar.ingest.wikipedia.alias_supplement import supplement_seed, _patch_aliases
from veristar.ingest.wikipedia.client import WikipediaClient
from veristar.ontology.graph import GraphDocument, load_graph
from veristar.ontology.models import Group


class FakeWikipediaClient:
    """테스트용 Fake — 실제 HTTP 호출 없음."""

    def __init__(self, title_map: dict[str, str | None], redirect_map: dict[str, list[str]]) -> None:
        self._titles = title_map        # qid → kowiki title
        self._redirects = redirect_map  # page title → list[redirect title]

    def fetch_kowiki_title(self, qid: str) -> str | None:
        return self._titles.get(qid)

    def fetch_redirects(self, page_title: str) -> list[str]:
        return self._redirects.get(page_title, [])


@pytest.fixture
def minimal_seed(tmp_path: Path) -> Path:
    """최소 시드 파일 픽스처 — 엔티티 1개, 별칭 없음."""
    from datetime import datetime

    doc = GraphDocument(
        entities=[
            Group(
                id="wd:Q46134670",
                name="스트레이 키즈",
                aliases=[],
                created_at=datetime(2024, 1, 1),
            )
        ],
        sources=[],
        statements=[],
    )
    seed = tmp_path / "seed.json"
    seed.write_text(doc.model_dump_json(indent=2), encoding="utf-8")
    return seed


def test_supplement_adds_aliases(minimal_seed: Path) -> None:
    client = FakeWikipediaClient(
        title_map={"Q46134670": "스트레이 키즈"},
        redirect_map={"스트레이 키즈": ["Stray Kids", "SKZ"]},
    )
    added = supplement_seed(minimal_seed, client, sleep_sec=0)

    assert "wd:Q46134670" in added
    assert "Stray Kids" in added["wd:Q46134670"]
    assert "SKZ" in added["wd:Q46134670"]


def test_supplement_skips_existing_aliases(minimal_seed: Path) -> None:
    # 시드에 이미 'Stray Kids' alias 있음 → 중복 추가 안 함
    doc = load_graph(minimal_seed)
    entity = doc.entities[0]
    patched = _patch_aliases(entity, ["Stray Kids"])
    updated_doc = doc.model_copy(update={"entities": [patched]})
    minimal_seed.write_text(updated_doc.model_dump_json(indent=2), encoding="utf-8")

    client = FakeWikipediaClient(
        title_map={"Q46134670": "스트레이 키즈"},
        redirect_map={"스트레이 키즈": ["Stray Kids", "SKZ"]},
    )
    added = supplement_seed(minimal_seed, client, sleep_sec=0)

    aliases = added.get("wd:Q46134670", [])
    assert "Stray Kids" not in aliases  # 이미 있음
    assert "SKZ" in aliases             # 새로 추가


def test_supplement_skips_no_kowiki(minimal_seed: Path) -> None:
    # kowiki 링크 없는 엔티티 → 변경 없음
    client = FakeWikipediaClient(title_map={}, redirect_map={})
    added = supplement_seed(minimal_seed, client, sleep_sec=0)
    assert added == {}


def test_dry_run_does_not_write(minimal_seed: Path) -> None:
    client = FakeWikipediaClient(
        title_map={"Q46134670": "스트레이 키즈"},
        redirect_map={"스트레이 키즈": ["SKZ"]},
    )
    original_text = minimal_seed.read_text()
    supplement_seed(minimal_seed, client, sleep_sec=0, dry_run=True)
    assert minimal_seed.read_text() == original_text


def test_supplement_writes_file(minimal_seed: Path) -> None:
    client = FakeWikipediaClient(
        title_map={"Q46134670": "스트레이 키즈"},
        redirect_map={"스트레이 키즈": ["SKZ"]},
    )
    supplement_seed(minimal_seed, client, sleep_sec=0, dry_run=False)

    updated = load_graph(minimal_seed)
    entity = updated.entities[0]
    assert "SKZ" in entity.aliases


def test_patch_aliases_is_immutable() -> None:
    from datetime import datetime

    original = Group(id="wd:Q1", name="G", aliases=["A"], created_at=datetime(2024, 1, 1))
    patched = _patch_aliases(original, ["B"])
    assert "B" in patched.aliases
    assert "B" not in original.aliases  # 불변성 확인
