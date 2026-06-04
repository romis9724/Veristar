"""LLM cross-check 검증 파이프라인.

흐름:
    raw vault (UNVERIFIED) → LLM cross-check → confidence score
    HIGH  → 자동 승인 (그래프 승격 대상)
    MEDIUM → 큐에 쌓기 (사람 검토 또는 재검증)
    LOW   → 폐기 (confidence=LOW로 표시)

사용법 (CLI):
    python -m veristar.verify.pipeline \\
        --vault vault/ --seed data/seed/wikidata_seed.json
"""

from __future__ import annotations

import argparse
import json
import logging
from dataclasses import dataclass, field

from veristar.generate.llm import chat
from veristar.vault.store import ConfidenceLevel, VaultDoc, VaultStore

logger = logging.getLogger(__name__)

_SYSTEM = (
    "당신은 한국 연예 정보의 사실 검증 전문가다. "
    "주어진 문서의 핵심 사실이 신뢰할 수 있는지 평가한다. "
    "평가 기준: (1) 공식 출처 언급 여부, (2) 구체적 날짜·수치 포함 여부, "
    "(3) 단정적 vs 추측성 표현 비율. "
    "JSON만 출력한다."
)

_USER_TMPL = """\
다음 문서를 평가해주세요.

제목: {title}
출처 유형: {source_type}
내용 (처음 500자):
{content_preview}

평가 항목:
1. 이 문서가 신뢰할 수 있는 사실을 담고 있습니까?
2. 민감 정보(열애·사건·건강·논란)가 포함돼 있습니까?
3. 신뢰도 점수를 HIGH/MEDIUM/LOW로 평가해주세요.
   - HIGH: 공식 출처, 구체적 사실, 교차 검증 가능
   - MEDIUM: 부분적으로 신뢰, 확인 필요
   - LOW: 루머, 추측, 미확인 정보

JSON 형식으로만 출력:
{{"confidence": "HIGH"|"MEDIUM"|"LOW", "sensitive": true|false, "reason": "..."}}
"""


@dataclass
class VerifyResult:
    """단일 문서 검증 결과."""

    doc_id: str
    confidence: ConfidenceLevel
    sensitive: bool
    reason: str
    previously: ConfidenceLevel = ConfidenceLevel.UNVERIFIED


@dataclass
class PipelineReport:
    """파이프라인 전체 실행 결과."""

    total: int = 0
    high: int = 0
    medium: int = 0
    low: int = 0
    errors: int = 0
    results: list[VerifyResult] = field(default_factory=list)

    def summary(self) -> str:
        return (
            f"total={self.total} HIGH={self.high} MED={self.medium} "
            f"LOW={self.low} err={self.errors}"
        )


class VerifyPipeline:
    """raw vault 문서를 LLM으로 검증하는 파이프라인."""

    def __init__(
        self,
        store: VaultStore,
        *,
        high_threshold: float = 0.0,   # HIGH면 자동 승인
        model: str | None = None,
    ) -> None:
        self.store = store
        self.model = model

    def run(self, docs: list[VaultDoc] | None = None) -> PipelineReport:
        """검증 실행. docs가 None이면 vault의 UNVERIFIED 전체를 처리."""
        targets = docs if docs is not None else self.store.list_unverified()
        report = PipelineReport(total=len(targets))

        for doc in targets:
            result = self._verify_one(doc)
            if result is None:
                report.errors += 1
                continue

            # confidence 업데이트
            self.store.update_confidence(doc.id, result.confidence)
            # sensitive 플래그도 업데이트 (문서 재저장)
            if result.sensitive != doc.sensitive:
                updated = VaultDoc(
                    id=doc.id, title=doc.title, content=doc.content,
                    source_type=doc.source_type, source_url=doc.source_url,
                    entity_refs=doc.entity_refs, published=doc.published,
                    retrieved=doc.retrieved, confidence=result.confidence,
                    license=doc.license, sensitive=result.sensitive, extra=doc.extra,
                )
                self.store.write(updated)

            report.results.append(result)
            if result.confidence == ConfidenceLevel.HIGH:
                report.high += 1
            elif result.confidence == ConfidenceLevel.MEDIUM:
                report.medium += 1
            else:
                report.low += 1

            logger.info(
                "%s → %s (sensitive=%s): %s",
                doc.id, result.confidence, result.sensitive, result.reason[:60],
            )

        return report

    def _verify_one(self, doc: VaultDoc) -> VerifyResult | None:
        prompt = _USER_TMPL.format(
            title=doc.title,
            source_type=doc.source_type,
            content_preview=doc.content[:500],
        )
        llm_result = chat(_SYSTEM, prompt, model=self.model, max_tokens=200)
        if not llm_result.ok:
            logger.warning("LLM error for %s: %s", doc.id, llm_result.error)
            return None

        raw = llm_result.text.strip()
        # JSON 추출
        start = raw.find("{")
        end = raw.rfind("}") + 1
        if start < 0 or end <= start:
            logger.warning("no JSON in LLM response for %s", doc.id)
            return None
        try:
            data = json.loads(raw[start:end])
        except json.JSONDecodeError:
            return None

        confidence_str = str(data.get("confidence", "LOW")).upper()
        confidence_map = {
            "HIGH": ConfidenceLevel.HIGH,
            "MEDIUM": ConfidenceLevel.MEDIUM,
            "MED": ConfidenceLevel.MEDIUM,
            "LOW": ConfidenceLevel.LOW,
        }
        confidence = confidence_map.get(confidence_str, ConfidenceLevel.LOW)
        sensitive = bool(data.get("sensitive", False))
        reason = str(data.get("reason", ""))

        return VerifyResult(
            doc_id=doc.id,
            confidence=confidence,
            sensitive=sensitive,
            reason=reason,
            previously=doc.confidence,
        )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="raw vault 검증 파이프라인")
    parser.add_argument("--vault", default="vault", help="vault 루트 디렉토리")
    parser.add_argument("--model", default=None, help="LLM 모델 override")
    parser.add_argument(
        "--source-type",
        default=None,
        help="특정 source_type만 처리 (예: namuwiki)",
    )
    args = parser.parse_args(argv)

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")

    store = VaultStore(args.vault)
    pipeline = VerifyPipeline(store, model=args.model)

    if args.source_type:
        docs = [d for d in store.list_unverified() if d.source_type == args.source_type]
    else:
        docs = None  # 전체

    report = pipeline.run(docs)
    logger.info("검증 완료: %s", report.summary())
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
