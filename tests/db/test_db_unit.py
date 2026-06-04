"""DB 레이어 단위 테스트 (PostgreSQL 연결 없이 실행 가능한 것)."""

from __future__ import annotations

from veristar.db.connection import is_available
from veristar.db.vector_store import embed_text, _LINK_THRESHOLD


def test_link_threshold_default() -> None:
    assert 0 < _LINK_THRESHOLD < 1


def test_embed_text_returns_none_on_error(monkeypatch) -> None:
    """HTTP 오류 시 embed_text는 None을 반환한다."""
    import httpx
    from unittest.mock import patch

    with patch("veristar.db.vector_store.httpx.post", side_effect=httpx.ConnectError("connection refused")):
        result = embed_text("test")
    assert result is None


def test_is_available_type() -> None:
    """is_available은 bool을 반환한다."""
    result = is_available()
    assert isinstance(result, bool)
