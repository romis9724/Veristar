"""GraphRAG Q&A 테스트 — LLM(chat)을 monkeypatch해 네트워크 없이 근거·게이트 검증."""

from __future__ import annotations

from datetime import datetime

import pytest

from veristar.generate import answer_question
from veristar.generate.llm import LLMResult
from veristar.graph import InMemoryGraphRepository
from veristar.ontology.enums import Grade, Predicate, SourceType, Status
from veristar.ontology.graph import GraphDocument
from veristar.ontology.models import Group, Person, Source, Statement


def _repo() -> InMemoryGraphRepository:
    p = Person(id="wd:QP", name="아티스트 A", created_at=datetime(2026, 1, 1))
    g = Group(id="wd:QG", name="그룹 G", created_at=datetime(2026, 1, 1))
    src = Source(
        id="s1",
        source_type=SourceType.WIKIDATA_VERIFIED,
        publisher="Wikidata",
        url="https://www.wikidata.org/wiki/QP",
        title="A",
        license="CC0",
    )
    official = Statement(
        id="ok",
        subject="wd:QP",
        predicate=Predicate.MEMBER_OF,
        object="wd:QG",
        grade=Grade.OFFICIAL,
        status=Status.ACTIVE,
        sources=["s1"],
    )
    reported = Statement(
        id="rep",
        subject="wd:QP",
        predicate=Predicate.AFFILIATED_WITH,
        object="wd:QORG",
        grade=Grade.REPORTED,  # 게이트에서 제외돼야 함
        status=Status.ACTIVE,
        sources=["s1"],
    )
    doc = GraphDocument(entities=[p, g], sources=[src], statements=[official, reported])
    return InMemoryGraphRepository(doc)


def test_qa_grounds_on_official_only(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, str] = {}

    def fake_chat(system: str, user: str, **kw: object) -> LLMResult:
        captured["user"] = user
        return LLMResult(text="아티스트 A는 그룹 G의 멤버입니다.", model="qwen3", ok=True)

    monkeypatch.setattr("veristar.generate.qa.chat", fake_chat)
    result = answer_question(_repo(), "아티스트 A", entity_id="wd:QP")

    assert result.model_used == "qwen3"
    assert "그룹 G" in result.answer
    # OFFICIAL statement만 근거에 포함, REPORTED 제외
    assert result.grounded_in == ["ok"]
    assert "memberOf" in captured["user"]
    assert "affiliatedWith" not in captured["user"]


def test_qa_graceful_when_ollama_unavailable(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_chat(system: str, user: str, **kw: object) -> LLMResult:
        return LLMResult(text="", model="qwen3", ok=False, error="Ollama 연결 실패")

    monkeypatch.setattr("veristar.generate.qa.chat", fake_chat)
    result = answer_question(_repo(), "아티스트 A", entity_id="wd:QP")

    assert "[오류]" in result.answer
    assert "Ollama" in result.answer
    assert result.grounded_in == ["ok"]  # 근거는 여전히 수집됨


def test_qa_no_facts_still_calls_model(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_chat(system: str, user: str, **kw: object) -> LLMResult:
        return LLMResult(text="해당 정보는 그래프에 없습니다.", model="qwen3", ok=True)

    monkeypatch.setattr("veristar.generate.qa.chat", fake_chat)
    result = answer_question(_repo(), "존재하지 않는 인물", entity_id="wd:QUNKNOWN")
    assert result.grounded_in == []
    assert result.model_used == "qwen3"
