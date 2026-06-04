"""검증 파이프라인 테스트 (LLM 모킹)."""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path
from unittest.mock import patch

import pytest

from veristar.vault.store import ConfidenceLevel, VaultDoc, VaultStore
from veristar.verify.pipeline import VerifyPipeline, VerifyResult, PipelineReport
from veristar.generate.llm import LLMResult


@pytest.fixture
def vault(tmp_path: Path) -> VaultStore:
    return VaultStore(tmp_path / "vault")


def _doc(doc_id: str = "doc-1", source_type: str = "wikipedia") -> VaultDoc:
    return VaultDoc(
        id=doc_id,
        title="아이유 (IU)",
        content="# 아이유\n\n대한민국의 가수이자 배우.",
        source_type=source_type,
        source_url="https://ko.wikipedia.org/wiki/아이유",
        confidence=ConfidenceLevel.UNVERIFIED,
    )


def _mock_llm(confidence: str, sensitive: bool = False) -> LLMResult:
    text = json.dumps({"confidence": confidence, "sensitive": sensitive, "reason": "test"})
    return LLMResult(ok=True, text=text, model="test", error=None)


def test_verify_high(vault: VaultStore) -> None:
    vault.write(_doc())
    pipeline = VerifyPipeline(vault)
    with patch("veristar.verify.pipeline.chat", return_value=_mock_llm("HIGH")):
        report = pipeline.run()
    assert report.high == 1
    assert report.total == 1
    updated = vault.read("doc-1")
    assert updated is not None
    assert updated.confidence == ConfidenceLevel.HIGH


def test_verify_medium(vault: VaultStore) -> None:
    vault.write(_doc())
    pipeline = VerifyPipeline(vault)
    with patch("veristar.verify.pipeline.chat", return_value=_mock_llm("MEDIUM")):
        report = pipeline.run()
    assert report.medium == 1


def test_verify_low(vault: VaultStore) -> None:
    vault.write(_doc())
    pipeline = VerifyPipeline(vault)
    with patch("veristar.verify.pipeline.chat", return_value=_mock_llm("LOW")):
        report = pipeline.run()
    assert report.low == 1


def test_verify_sensitive_flag(vault: VaultStore) -> None:
    vault.write(_doc())
    pipeline = VerifyPipeline(vault)
    with patch("veristar.verify.pipeline.chat", return_value=_mock_llm("HIGH", sensitive=True)):
        pipeline.run()
    updated = vault.read("doc-1")
    assert updated is not None
    assert updated.sensitive is True


def test_verify_llm_failure(vault: VaultStore) -> None:
    vault.write(_doc())
    pipeline = VerifyPipeline(vault)
    fail_result = LLMResult(ok=False, text="", model="test", error="timeout")
    with patch("veristar.verify.pipeline.chat", return_value=fail_result):
        report = pipeline.run()
    assert report.errors == 1
    assert report.high == 0


def test_verify_invalid_json(vault: VaultStore) -> None:
    vault.write(_doc())
    pipeline = VerifyPipeline(vault)
    bad_result = LLMResult(ok=True, text="이건 JSON이 아님", model="test", error=None)
    with patch("veristar.verify.pipeline.chat", return_value=bad_result):
        report = pipeline.run()
    assert report.errors == 1


def test_run_with_explicit_docs(vault: VaultStore) -> None:
    """명시적 docs 리스트를 넘기면 해당 문서만 처리."""
    doc1 = _doc("doc-1")
    doc2 = _doc("doc-2")
    vault.write(doc1)
    vault.write(doc2)

    pipeline = VerifyPipeline(vault)
    with patch("veristar.verify.pipeline.chat", return_value=_mock_llm("HIGH")):
        report = pipeline.run(docs=[doc1])  # doc1만
    assert report.total == 1
    assert report.high == 1


def test_report_summary() -> None:
    report = PipelineReport(total=5, high=2, medium=2, low=1, errors=0)
    summary = report.summary()
    assert "HIGH=2" in summary
    assert "MED=2" in summary


def test_verify_empty_vault(vault: VaultStore) -> None:
    pipeline = VerifyPipeline(vault)
    report = pipeline.run()
    assert report.total == 0
    assert report.high == 0
