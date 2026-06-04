"""뉴스 제목 → 그래프 사실 추출 (M4 파이프라인 [2]).

제목에 문자 그대로 적힌 것만 추출한다. 추론·해석 금지 (safety-guidelines.md §2).
원문 본문은 절대 요청하지 않는다.

흐름:
    제목 → 민감 필터 → 엔티티 링크 → LLM 추출 → 검증 → ExtractedFact
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from datetime import date

from veristar.generate.llm import chat
from veristar.grading import is_sensitive_label
from veristar.graph.repository import InMemoryGraphRepository
from veristar.ontology.enums import Predicate
from veristar.ontology.models import Entity

from .rss import FeedItem

logger = logging.getLogger(__name__)

_VALID_PREDICATES = {p.value for p in Predicate}

_SYSTEM = (
    "당신은 K-pop 뉴스 사실 추출기다. 뉴스 제목에 문자 그대로 적힌 것만 JSON으로 추출한다. "
    "추론·해석·예측은 절대 금지. 엔티티 이름과 관계가 제목에 명확히 없으면 facts: []로 답한다."
)

_USER_TMPL = """\
뉴스 제목: "{title}"

알려진 엔티티 목록:
{entity_list}

사용 가능한 predicate:
- memberOf: 소속(멤버 → 그룹/회사)
- wonAward: 수상
- nominatedFor: 노미네이트
- appearedIn: 출연·참여(작품/이벤트)
- released: 발매(음반/노래)
- collaboratedWith: 협업

규칙:
1. subject와 object 모두 알려진 엔티티 목록에 있어야 한다.
2. 제목에 명확히 적힌 사실만. 추론 금지.
3. 민감 정보(열애·이혼·논란·건강·사건 등) 추출 금지.

JSON만 출력 (다른 텍스트 없이):
{{"facts": [{{"subject_id": "...", "predicate": "...", "object_id": "..."}}]}}
"""


@dataclass(frozen=True)
class ExtractedFact:
    """LLM이 뉴스 제목에서 추출한 단일 사실."""

    subject_id: str
    predicate: str
    object_id: str
    article_title: str
    article_url: str
    published: date | None
    feed_name: str


def _build_entity_list(entities: list[Entity]) -> str:
    lines = [f'- id: "{e.id}", name: "{e.name}"' for e in entities]
    return "\n".join(lines) if lines else "(없음)"


def extract_facts(
    item: FeedItem,
    repo: InMemoryGraphRepository,
    *,
    max_entities: int = 10,
    model: str | None = None,
) -> list[ExtractedFact]:
    """단일 FeedItem에서 그래프 사실을 추출한다.

    Returns:
        추출된 사실 목록. 민감 제목이거나 추출 실패면 빈 리스트.
    """
    if is_sensitive_label(item.title):
        logger.info("sensitive title skipped: %s", item.title[:60])
        return []

    # 제목에 언급된 엔티티 탐색 (긴 이름 우선)
    mentioned = repo.find_mentioned(item.title, limit=max_entities)
    if len(mentioned) < 2:
        # subject + object 최소 2개 엔티티가 있어야 statement 생성 가능
        return []

    prompt = _USER_TMPL.format(
        title=item.title,
        entity_list=_build_entity_list(mentioned),
    )

    result = chat(_SYSTEM, prompt, model=model, max_tokens=256)
    if not result.ok:
        logger.warning("LLM extraction failed for '%s': %s", item.title[:60], result.error)
        return []

    # JSON 파싱
    raw = result.text.strip()
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        # JSON 블록 추출 시도
        start = raw.find("{")
        end = raw.rfind("}") + 1
        if start < 0 or end <= start:
            logger.warning("no JSON in LLM response: %s", raw[:100])
            return []
        try:
            data = json.loads(raw[start:end])
        except json.JSONDecodeError:
            logger.warning("JSON parse failed: %s", raw[:100])
            return []

    facts: list[ExtractedFact] = []
    known_ids = {e.id for e in mentioned}

    for raw_fact in data.get("facts", []):
        subject_id = str(raw_fact.get("subject_id", ""))
        predicate = str(raw_fact.get("predicate", ""))
        object_id = str(raw_fact.get("object_id", ""))

        if not (subject_id and predicate and object_id):
            continue
        if predicate not in _VALID_PREDICATES:
            logger.debug("invalid predicate from LLM: %s", predicate)
            continue
        # 두 엔티티 모두 반드시 그래프에 있어야 한다
        if subject_id not in known_ids or object_id not in known_ids:
            logger.debug("unknown entity in fact: %s / %s", subject_id, object_id)
            continue

        facts.append(
            ExtractedFact(
                subject_id=subject_id,
                predicate=predicate,
                object_id=object_id,
                article_title=item.title,
                article_url=item.url,
                published=item.published,
                feed_name=item.feed_name,
            )
        )

    if facts:
        logger.info("extracted %d fact(s) from: %s", len(facts), item.title[:60])
    return facts
