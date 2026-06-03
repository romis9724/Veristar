"""Wikidata 접근 클라이언트.

매핑(mapper)과 분리된 얇은 I/O 계층. Protocol로 추상화해 테스트에서 Fake를 주입한다.
M2 시드는 루트 QID 확장 방식이라 entity fetch만 필요하다(SPARQL 불요 — YAGNI).
"""

from __future__ import annotations

from typing import Any, Protocol

import httpx

_ENTITY_DATA_URL = "https://www.wikidata.org/wiki/Special:EntityData/{qid}.json"
# Wikidata는 식별 가능한 User-Agent를 요구한다.
_USER_AGENT = "VeristarBot/0.1 (https://github.com/; seed ingest)"


class WikidataClient(Protocol):
    """Wikidata 아이템 조회 인터페이스."""

    def fetch_entity(self, qid: str) -> dict[str, Any]:
        """`qid`('Q###')의 아이템 dict를 반환 (EntityData의 entities[qid])."""
        ...


class HttpWikidataClient:
    """httpx 기반 실제 구현."""

    def __init__(self, timeout: float = 30.0, client: httpx.Client | None = None) -> None:
        # client 주입은 테스트(MockTransport)용. 미지정 시 기본 클라이언트 생성.
        self._client = client or httpx.Client(
            timeout=timeout,
            headers={"User-Agent": _USER_AGENT},
            follow_redirects=True,
        )

    def fetch_entity(self, qid: str) -> dict[str, Any]:
        resp = self._client.get(_ENTITY_DATA_URL.format(qid=qid))
        resp.raise_for_status()
        entities = resp.json().get("entities", {})
        if qid not in entities:
            raise KeyError(f"entity {qid!r} not in Wikidata response")
        return dict(entities[qid])

    def close(self) -> None:
        self._client.close()

    def __enter__(self) -> HttpWikidataClient:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()
