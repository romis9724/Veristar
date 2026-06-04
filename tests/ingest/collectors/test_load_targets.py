"""load_targets() — DB 우선 / YAML 폴백 분기 테스트."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

from veristar.ingest.collectors.runner import load_targets


def _write_yaml(tmp_path: Path) -> Path:
    p = tmp_path / "celebrities.yaml"
    p.write_text(
        "celebrities:\n"
        "  - name: 아이유\n"
        "    namu_title: 아이유\n"
        "  - name: BTS\n"
        "    namu_title: 방탄소년단\n",
        encoding="utf-8",
    )
    return p


# ─── load_targets 분기 ────────────────────────────────────────────────────────


def test_load_targets_yaml_fallback_when_db_unavailable(tmp_path: Path) -> None:
    """DB 연결 불가 → YAML 폴백."""
    with patch("veristar.db.connection.is_available", return_value=False):
        targets, db_mode = load_targets(_write_yaml(tmp_path))
    assert db_mode is False
    assert len(targets) == 2


def test_load_targets_db_mode(tmp_path: Path) -> None:
    """DB 가용 + pending 있음 → DB 모드, id 포함."""
    fake_pending = [
        {"id": "wd:Q1", "name": "아이유", "namu_title": "아이유", "youtube_channel": None},
        {"id": "wd:Q2", "name": "태양", "namu_title": "태양", "youtube_channel": None},
    ]

    class FakeRepo:
        def list_pending(self, limit=None):
            return fake_pending

    class FakeConn:
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    with (
        patch("veristar.db.connection.is_available", return_value=True),
        patch("veristar.db.connection.get_conn", return_value=FakeConn()),
        patch(
            "veristar.db.targets_repository.CollectionTargetsRepository",
            return_value=FakeRepo(),
        ),
    ):
        targets, db_mode = load_targets(_write_yaml(tmp_path))

    assert db_mode is True
    assert len(targets) == 2
    assert targets[0]["id"] == "wd:Q1"
    # None → 빈 문자열 정규화
    assert targets[0]["youtube_channel"] == ""


def test_load_targets_db_empty_falls_back_to_yaml(tmp_path: Path) -> None:
    """DB 가용하나 pending 없음 → YAML 폴백."""

    class FakeRepo:
        def list_pending(self, limit=None):
            return []

    class FakeConn:
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    with (
        patch("veristar.db.connection.is_available", return_value=True),
        patch("veristar.db.connection.get_conn", return_value=FakeConn()),
        patch(
            "veristar.db.targets_repository.CollectionTargetsRepository",
            return_value=FakeRepo(),
        ),
    ):
        targets, db_mode = load_targets(_write_yaml(tmp_path))

    assert db_mode is False
    assert len(targets) == 2  # YAML
