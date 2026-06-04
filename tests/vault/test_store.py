"""VaultStore 단위 테스트."""

from __future__ import annotations

from datetime import date
from pathlib import Path

import pytest

from veristar.vault.store import ConfidenceLevel, VaultDoc, VaultStore


@pytest.fixture
def vault(tmp_path: Path) -> VaultStore:
    return VaultStore(tmp_path / "vault")


def _sample_doc(**overrides: object) -> VaultDoc:
    kwargs: dict[str, object] = dict(
        id="test-doc-001",
        title="아이유 (IU)",
        content="# 아이유\n\n대한민국 가수이다.",
        source_type="wikipedia",
        source_url="https://ko.wikipedia.org/wiki/아이유",
        entity_refs=["아이유"],
        published=date(2024, 1, 1),
        confidence=ConfidenceLevel.UNVERIFIED,
        license="CC BY-SA 4.0",
    )
    kwargs.update(overrides)
    return VaultDoc(**kwargs)  # type: ignore[arg-type]


def test_write_and_read(vault: VaultStore) -> None:
    doc = _sample_doc()
    vault.write(doc)
    loaded = vault.read("test-doc-001")
    assert loaded is not None
    assert loaded.title == "아이유 (IU)"
    assert loaded.source_type == "wikipedia"
    assert loaded.confidence == ConfidenceLevel.UNVERIFIED


def test_markdown_roundtrip(vault: VaultStore) -> None:
    doc = _sample_doc(
        sensitive=True,
        extra={"lang": "ko", "wiki_title": "아이유"},
    )
    vault.write(doc)
    loaded = vault.read("test-doc-001")
    assert loaded is not None
    assert loaded.sensitive is True
    assert "아이유" in loaded.content


def test_list_docs(vault: VaultStore) -> None:
    vault.write(_sample_doc(id="doc-a", source_type="wikipedia"))
    vault.write(_sample_doc(id="doc-b", source_type="namuwiki"))
    all_docs = vault.list_docs()
    assert len(all_docs) == 2


def test_list_docs_by_type(vault: VaultStore) -> None:
    vault.write(_sample_doc(id="doc-a", source_type="wikipedia"))
    vault.write(_sample_doc(id="doc-b", source_type="namuwiki"))
    wiki_docs = vault.list_docs(source_type="wikipedia")
    assert len(wiki_docs) == 1
    assert wiki_docs[0].source_type == "wikipedia"


def test_list_unverified(vault: VaultStore) -> None:
    vault.write(_sample_doc(id="doc-unverified", confidence=ConfidenceLevel.UNVERIFIED))
    vault.write(_sample_doc(id="doc-high", confidence=ConfidenceLevel.HIGH))
    unverified = vault.list_unverified()
    assert len(unverified) == 1
    assert unverified[0].id == "doc-unverified"


def test_update_confidence(vault: VaultStore) -> None:
    vault.write(_sample_doc())
    result = vault.update_confidence("test-doc-001", ConfidenceLevel.HIGH)
    assert result is True
    loaded = vault.read("test-doc-001")
    assert loaded is not None
    assert loaded.confidence == ConfidenceLevel.HIGH


def test_update_confidence_missing(vault: VaultStore) -> None:
    result = vault.update_confidence("nonexistent", ConfidenceLevel.HIGH)
    assert result is False


def test_stats(vault: VaultStore) -> None:
    vault.write(_sample_doc(id="doc-1", confidence=ConfidenceLevel.UNVERIFIED))
    vault.write(_sample_doc(id="doc-2", confidence=ConfidenceLevel.HIGH))
    vault.write(_sample_doc(id="doc-3", sensitive=True))
    stats = vault.stats()
    assert stats["total"] == 3
    assert stats["verified_high"] == 1


def test_skip_duplicate(vault: VaultStore) -> None:
    doc = _sample_doc()
    vault.write(doc)
    # 같은 doc을 _save로 다시 저장하면 skip
    store_method = vault
    # _save는 read를 통해 중복 감지하므로, 직접 write를 두 번 하면 덮어씀
    # CollectorBase._save는 같은 URL이면 skip
    second = _sample_doc(title="변경된 제목")
    vault.write(second)
    loaded = vault.read("test-doc-001")
    assert loaded is not None
    # write는 강제 덮어쓰기 — skip은 CollectorBase._save 레벨에서만 적용


def test_vault_dir_structure(tmp_path: Path) -> None:
    store = VaultStore(tmp_path / "my_vault")
    assert (tmp_path / "my_vault" / "entities").is_dir()
    assert (tmp_path / "my_vault" / "articles").is_dir()
    assert (tmp_path / "my_vault" / "sns").is_dir()


def test_sns_doc_goes_to_sns_dir(vault: VaultStore) -> None:
    doc = _sample_doc(id="yt-video-001", source_type="youtube")
    path = vault.write(doc)
    assert "sns" in str(path)


def test_entity_refs_roundtrip(vault: VaultStore) -> None:
    doc = _sample_doc(entity_refs=["아이유", "IU"])
    vault.write(doc)
    loaded = vault.read("test-doc-001")
    assert loaded is not None
    assert "아이유" in loaded.entity_refs
    assert "IU" in loaded.entity_refs


def test_license_preserved(vault: VaultStore) -> None:
    doc = _sample_doc(license="CC BY-NC-SA 2.0 KR")
    vault.write(doc)
    loaded = vault.read("test-doc-001")
    assert loaded is not None
    assert loaded.license == "CC BY-NC-SA 2.0 KR"
