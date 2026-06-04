"""HIGH confidence vault 문서 → JSONL 그래프 승격.

흐름:
    vault HIGH docs
      → LLM 사실 추출 (subject·predicate·object, 그래프 내 엔티티 한정)
      → Source + Statement 생성
      → 기존 JSONL 그래프에 병합

wikipedia → Grade.OFFICIAL
news      → Grade.REPORTED

사용법 (CLI):
    python -m veristar.verify.graph_sync \\
        --vault vault/ \\
        --seed data/seed/wikidata_seed.json
"""

from __future__ import annotations

import argparse
import hashlib
import json
import logging
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

from veristar.generate.llm import chat
from veristar.graph.merge import merge
from veristar.graph.repository import InMemoryGraphRepository
from veristar.ingest.wikidata.seed import write_seed
from veristar.ontology.enums import Grade, Predicate, SourceType, Status
from veristar.ontology.graph import GraphDocument, load_graph
from veristar.ontology.models import Source, Statement
from veristar.vault.store import ConfidenceLevel, VaultDoc, VaultStore

logger = logging.getLogger(__name__)

_VALID_PREDICATES = {p.value for p in Predicate}

_SYSTEM = (
    "당신은 K-pop/한국 연예 정보 사실 추출기다. "
    "문서에 명시적으로 적힌 사실만 JSON으로 추출한다. 추론·예측·평가 금지."
)

_PROMPT = """\
문서 제목: {title}
출처 유형: {source_type}
문서 주제 엔티티: {main_entity}

문서 내용 (처음 800자):
{content}

그래프에 있는 엔티티:
{entity_list}

추출 규칙:
1. subject와 object 모두 위 엔티티 목록의 id 값이어야 한다.
2. predicate 방향 규칙 (엄격히 준수):
   - memberOf      : 개인(Person) → 그룹/조직(Group/Org) [예: 멤버→그룹]
   - affiliatedWith: 그룹(Group) → 조직(Org) [예: 그룹→소속사]
   - wonAward      : 개인/그룹 → 상(Award) [예: 아티스트→수상]
   - nominatedFor  : 개인/그룹 → 상(Award)
   - appearedIn    : 개인 → 작품/이벤트(Work/Event)
   - released      : 개인/그룹 → 작품(Work)
   - collaboratedWith: 개인/그룹 ↔ 개인/그룹
3. 문서에 명시된 것만. 추론·예측 금지.
4. 사실이 없거나 엔티티 매칭 불가 → {{"facts": []}}
5. 그룹이 subject이고 개인이 object인 memberOf → 방향 반전해서 넣지 말 것 (그냥 제외)

JSON만 출력:
{{"facts": [{{"subject_id": "...", "predicate": "...", "object_id": "..."}}]}}
"""


@dataclass
class SyncReport:
    total_docs: int = 0
    extracted: int = 0
    new_sources: int = 0
    new_statements: int = 0
    errors: int = 0
    skipped: int = 0
    details: list[str] = field(default_factory=list)

    def summary(self) -> str:
        return (
            f"docs={self.total_docs} extracted={self.extracted} "
            f"src+{self.new_sources} stmt+{self.new_statements} "
            f"skip={self.skipped} err={self.errors}"
        )


def _source_id(vault_doc: VaultDoc) -> str:
    return "src_vault_" + hashlib.sha1(vault_doc.source_url.encode()).hexdigest()[:12]


def _stmt_id(subject: str, predicate: str, obj: str, source_id: str) -> str:
    key = f"{subject}|{predicate}|{obj}|{source_id}"
    return "stmt_vault_" + hashlib.sha1(key.encode()).hexdigest()[:12]


def _grade_for(vault_doc: VaultDoc) -> Grade:
    # vault 추출 사실은 LLM 추출 특성상 오류 가능성이 있으므로 항상 REPORTED.
    # 사람이 검토 후 별도로 OFFICIAL 승격 가능.
    return Grade.REPORTED


def _source_type_for(vault_doc: VaultDoc) -> SourceType:
    mapping = {
        "wikipedia": SourceType.WIKIDATA_VERIFIED,
        "namuwiki": SourceType.COMMUNITY_OR_ANON,
        "news": SourceType.PRESS,
        "youtube": SourceType.ARTIST_OFFICIAL_SNS,
        "instagram": SourceType.ARTIST_OFFICIAL_SNS,
        "twitter": SourceType.ARTIST_OFFICIAL_SNS,
    }
    return mapping.get(vault_doc.source_type, SourceType.PRESS)


def _build_entity_list(entities: list[Any]) -> str:
    lines = []
    for e in entities[:20]:
        etype = getattr(e, "type", "Unknown")
        lines.append(f'- id: "{e.id}", name: "{e.name}", type: {etype}')
    return "\n".join(lines)


def _is_valid_direction(
    subject_id: str, predicate: str, object_id: str, repo: InMemoryGraphRepository
) -> bool:
    """엔티티 타입 기반 사실 방향 검증."""
    from veristar.ontology.enums import EntityType

    subj = repo.get_entity(subject_id)
    obj = repo.get_entity(object_id)
    if subj is None or obj is None:
        return False
    stype = getattr(subj, "type", None)
    otype = getattr(obj, "type", None)
    # GROUP/ORG이 subject이고 PERSON이 object인 memberOf → 방향 반전 오류
    if (
        predicate == "memberOf"
        and stype in (EntityType.GROUP, EntityType.ORGANIZATION)
        and otype == EntityType.PERSON
    ):
        return False
    # PERSON이 subject이고 PERSON이 object인 affiliatedWith → 보통 틀림
    return not (
        predicate == "affiliatedWith" and stype == EntityType.PERSON and otype == EntityType.PERSON
    )


def _extract_facts(
    vault_doc: VaultDoc,
    repo: InMemoryGraphRepository,
    model: str | None = None,
) -> list[dict[str, str]]:
    """LLM으로 vault 문서에서 그래프 사실을 추출한다."""
    from veristar.graph.entity_linker import find_mentioned_with_vectors

    # 벡터 기반 entity linker로 후보 엔티티 탐색 (짧은 이름 false-positive 차단)
    search_text = vault_doc.title + " " + vault_doc.content[:500]
    mentioned = find_mentioned_with_vectors(search_text, repo, limit=12)
    if len(mentioned) < 2:
        return []

    # 주 엔티티 (제목에서 벡터 유사도 기준 1순위)
    main_entity_names = [
        e.name for e in find_mentioned_with_vectors(vault_doc.title, repo, limit=1)
    ]
    main_entity = main_entity_names[0] if main_entity_names else vault_doc.title

    prompt = _PROMPT.format(
        title=vault_doc.title,
        source_type=vault_doc.source_type,
        main_entity=main_entity,
        content=vault_doc.content[:800],
        entity_list=_build_entity_list(mentioned),
    )

    result = chat(_SYSTEM, prompt, model=model, max_tokens=300)
    if not result.ok:
        logger.warning("LLM error for %s: %s", vault_doc.id, result.error)
        return []

    raw = result.text.strip()
    start = raw.find("{")
    end = raw.rfind("}") + 1
    if start < 0 or end <= start:
        return []
    try:
        data = json.loads(raw[start:end])
    except json.JSONDecodeError:
        return []

    known_ids = {e.id for e in mentioned}
    valid: list[dict[str, str]] = []
    for fact in data.get("facts", []):
        s = str(fact.get("subject_id", ""))
        p = str(fact.get("predicate", ""))
        o = str(fact.get("object_id", ""))
        if not (s and p and o):
            continue
        if p not in _VALID_PREDICATES:
            logger.debug("invalid predicate: %s", p)
            continue
        if s not in known_ids or o not in known_ids:
            logger.debug("unknown entity: %s / %s", s, o)
            continue
        # 엔티티 타입 기반 방향 검증
        if not _is_valid_direction(s, p, o, repo):
            logger.debug("invalid direction rejected: %s -[%s]-> %s", s, p, o)
            continue
        valid.append({"subject_id": s, "predicate": p, "object_id": o})
    return valid


def sync_high_to_graph(
    vault: VaultStore,
    seed_path: Path,
    *,
    model: str | None = None,
    dry_run: bool = False,
) -> SyncReport:
    """HIGH vault 문서 → 그래프 승격."""
    if not seed_path.exists():
        logger.error("시드 파일 없음: %s", seed_path)
        return SyncReport()

    base_doc = load_graph(seed_path)
    repo = InMemoryGraphRepository(base_doc)

    high_docs = [d for d in vault.list_docs() if d.confidence == ConfidenceLevel.HIGH]
    report = SyncReport(total_docs=len(high_docs))

    all_sources: dict[str, Source] = {}
    all_statements: dict[str, Statement] = {}

    for vd in high_docs:
        src_id = _source_id(vd)
        grade = _grade_for(vd)

        src = Source(
            id=src_id,
            source_type=_source_type_for(vd),
            publisher=vd.source_type,
            url=vd.source_url,
            title=vd.title,
            published_at=vd.published,
            retrieved_at=vd.retrieved or datetime.now().date(),
            license=vd.license or None,
        )
        all_sources[src_id] = src

        facts = _extract_facts(vd, repo, model=model)
        if not facts:
            report.skipped += 1
            logger.info("%s: 추출된 사실 없음", vd.id)
            continue

        report.extracted += 1
        for fact in facts:
            stmt = Statement(
                id=_stmt_id(fact["subject_id"], fact["predicate"], fact["object_id"], src_id),
                subject=fact["subject_id"],
                predicate=Predicate(fact["predicate"]),
                object=fact["object_id"],
                grade=grade,
                status=Status.ACTIVE,
                sources=[src_id],
                sensitive=False,
            )
            all_statements[stmt.id] = stmt
            logger.info(
                "  %s --[%s]--> %s (%s)",
                fact["subject_id"],
                fact["predicate"],
                fact["object_id"],
                grade,
            )

        msg = f"{vd.id}: +{len(facts)} facts"
        report.details.append(msg)

    if not all_sources:
        logger.info("승격할 문서 없음")
        return report

    report.new_sources = len(all_sources)
    report.new_statements = len(all_statements)

    incoming = GraphDocument(
        entities=[],
        sources=list(all_sources.values()),
        statements=list(all_statements.values()),
    )
    merged_doc, merge_report = merge(base_doc, incoming)
    logger.info("병합 결과: %s", merge_report.summary())

    if not dry_run:
        write_seed(merged_doc, seed_path)
        logger.info("그래프 업데이트: %s", seed_path)

    return report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="HIGH vault 문서 → 그래프 승격")
    parser.add_argument("--vault", default="vault", help="vault 루트 디렉토리")
    parser.add_argument("--seed", default="data/seed/wikidata_seed.json", help="시드 JSON 경로")
    parser.add_argument("--model", default=None, help="LLM 모델 override")
    parser.add_argument("--dry-run", action="store_true", help="파일 쓰기 없이 출력만")
    args = parser.parse_args(argv)

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")

    store = VaultStore(args.vault)
    report = sync_high_to_graph(
        store,
        Path(args.seed),
        model=args.model,
        dry_run=args.dry_run,
    )
    logger.info("완료: %s", report.summary())
    for detail in report.details:
        logger.info("  %s", detail)
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
