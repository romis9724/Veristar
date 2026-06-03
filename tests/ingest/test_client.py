"""HttpWikidataClient 테스트 — httpx MockTransport (실호출 없음)."""

from __future__ import annotations

import httpx
import pytest

from veristar.ingest.wikidata.client import HttpWikidataClient


def _make_client(handler: httpx.MockTransport) -> HttpWikidataClient:
    return HttpWikidataClient(client=httpx.Client(transport=handler))


def test_fetch_entity_parses_entities_block() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert "Special:EntityData/Q42.json" in str(request.url)
        return httpx.Response(200, json={"entities": {"Q42": {"id": "Q42"}}})

    client = _make_client(httpx.MockTransport(handler))
    assert client.fetch_entity("Q42") == {"id": "Q42"}


def test_fetch_entity_missing_qid_raises() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"entities": {}})

    client = _make_client(httpx.MockTransport(handler))
    with pytest.raises(KeyError):
        client.fetch_entity("Q1")


def test_fetch_entity_http_error_raises() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(404)

    client = _make_client(httpx.MockTransport(handler))
    with pytest.raises(httpx.HTTPStatusError):
        client.fetch_entity("Q1")
