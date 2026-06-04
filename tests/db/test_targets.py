"""collection_targets 저장소 통합 테스트.

PostgreSQL 연결이 가능할 때만 실행 (db 모듈은 coverage omit 대상).
"""

from __future__ import annotations

import pytest

from veristar.db.connection import get_conn, init_schema, is_available

pytestmark = pytest.mark.skipif(not is_available(), reason="PostgreSQL 연결 불가")


@pytest.fixture
def repo():
    from pgvector.psycopg import register_vector

    from veristar.db.targets_repository import CollectionTargetsRepository

    init_schema()
    conn = get_conn()
    register_vector(conn)
    # 테스트 격리: 테스트 전용 prefix 정리
    conn.execute("DELETE FROM collection_targets WHERE id LIKE 'test:%'")
    conn.commit()
    yield CollectionTargetsRepository(conn)
    conn.execute("DELETE FROM collection_targets WHERE id LIKE 'test:%'")
    conn.commit()
    conn.close()


def _target(tid: str, **kw) -> dict:
    base = {"id": tid, "name": "테스트", "category": "singer"}
    base.update(kw)
    return base


def test_upsert_and_list_pending(repo) -> None:
    repo.upsert(_target("test:1", name="아이유"))
    repo.commit()
    pending = repo.list_pending()
    ids = {t["id"] for t in pending}
    assert "test:1" in ids


def test_upsert_preserves_status(repo) -> None:
    repo.upsert(_target("test:2", name="태양"))
    repo.commit()
    repo.mark_done("test:2")
    # 재발견(upsert)해도 done 유지
    repo.upsert(_target("test:2", name="태양 (갱신)"))
    repo.commit()
    all_rows = {t["id"]: t for t in repo.list_all()}
    assert all_rows["test:2"]["status"] == "done"
    assert all_rows["test:2"]["name"] == "태양 (갱신)"


def test_mark_collecting_done_failed(repo) -> None:
    repo.upsert(_target("test:3"))
    repo.commit()
    repo.mark_collecting("test:3")
    rows = {t["id"]: t for t in repo.list_all()}
    assert rows["test:3"]["status"] == "collecting"

    repo.mark_done("test:3")
    rows = {t["id"]: t for t in repo.list_all()}
    assert rows["test:3"]["status"] == "done"
    assert rows["test:3"]["last_collected_at"] is not None


def test_list_pending_excludes_done(repo) -> None:
    repo.upsert(_target("test:4"))
    repo.upsert(_target("test:5"))
    repo.commit()
    repo.mark_done("test:4")
    pending_ids = {t["id"] for t in repo.list_pending()}
    assert "test:4" not in pending_ids
    assert "test:5" in pending_ids


def test_list_pending_category_filter(repo) -> None:
    repo.upsert(_target("test:6", category="singer"))
    repo.upsert(_target("test:7", category="actor"))
    repo.commit()
    actors = {t["id"] for t in repo.list_pending(category="actor")}
    assert "test:7" in actors
    assert "test:6" not in actors


def test_list_pending_limit(repo) -> None:
    for i in range(5):
        repo.upsert(_target(f"test:lim{i}"))
    repo.commit()
    limited = repo.list_pending(limit=2)
    assert len(limited) <= 2


def test_stats(repo) -> None:
    repo.upsert(_target("test:8"))
    repo.commit()
    stats = repo.stats()
    assert "pending" in stats
    assert stats["pending"] >= 1
