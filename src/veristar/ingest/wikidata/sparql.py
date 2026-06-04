"""Wikidata SPARQL 클라이언트 — 한국 연예인 대량 발견.

기존 client.py(HttpWikidataClient)는 개별 QID EntityData fetch 전용이다.
이 모듈은 "한국 국적(P27=Q884) + 연예 직업" 인물·그룹을 WDQS로 한 번에 발견한다.

발견 결과는 수집 대상(collection_targets)으로만 쓰이고,
실제 그래프 적재는 기존 build_seed / collectors 파이프라인이 담당한다.

WDQS rate-limit 대응: 쿼리 간 sleep + 429 지수 백오프(Retry-After 존중).
"""

from __future__ import annotations

import logging
import time
import urllib.parse
from dataclasses import dataclass, field
from typing import Protocol

import httpx

logger = logging.getLogger(__name__)

_WDQS_ENDPOINT = "https://query.wikidata.org/sparql"
_USER_AGENT = "VeristarBot/0.1 (https://github.com/; celebrity discovery)"
_KOREA_QID = "Q884"  # 대한민국
_MUSICAL_GROUP_QID = "Q215380"  # musical group (P31/P279* 루트)

# 직업 카테고리 → Wikidata occupation QID (라이브 검증: singer 그룹 4930명 확인)
OCCUPATION_GROUPS: dict[str, list[str]] = {
    "singer": ["Q177220", "Q63970319"],  # singer, idol
    "actor": ["Q33999", "Q10800557", "Q2405480"],  # actor, film actor, voice actor
    "entertainer": ["Q947873", "Q245068"],  # TV presenter, comedian
    "creator": ["Q17125263", "Q2066131"],  # YouTuber, streamer
}


@dataclass(frozen=True)
class DiscoveredEntity:
    """SPARQL로 발견한 수집 대상."""

    qid: str  # "Q12345" (bare)
    name: str
    kowiki_title: str  # 나무위키 제목 추정·entity_refs용
    category: str  # singer | actor | entertainer | creator | group
    occupation_qids: list[str] = field(default_factory=list)


class SparqlRunner(Protocol):
    """SPARQL 실행 인터페이스 (테스트에서 Fake 주입용)."""

    def run(self, query: str) -> dict: ...


class HttpSparqlRunner:
    """httpx 기반 WDQS 실행기 (429 백오프 포함)."""

    def __init__(
        self,
        timeout: float = 60.0,
        max_retries: int = 5,
        client: httpx.Client | None = None,
    ) -> None:
        self._client = client or httpx.Client(
            timeout=timeout,
            headers={
                "User-Agent": _USER_AGENT,
                "Accept": "application/sparql-results+json",
            },
            follow_redirects=True,
        )
        self.max_retries = max_retries

    def run(self, query: str) -> dict:
        params = urllib.parse.urlencode({"query": query, "format": "json"})
        url = f"{_WDQS_ENDPOINT}?{params}"
        backoff = 5.0
        for attempt in range(self.max_retries):
            resp = self._client.get(url)
            if resp.status_code == 429:
                wait = float(resp.headers.get("Retry-After", backoff))
                logger.warning(
                    "WDQS 429 rate-limit, %.0fs 대기 (시도 %d/%d)",
                    wait,
                    attempt + 1,
                    self.max_retries,
                )
                time.sleep(wait)
                backoff = min(backoff * 2, 120.0)
                continue
            resp.raise_for_status()
            return dict(resp.json())
        raise RuntimeError(f"WDQS rate-limit 초과: {self.max_retries}회 재시도 실패")

    def close(self) -> None:
        self._client.close()

    def __enter__(self) -> HttpSparqlRunner:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()


def _person_query(occupation_qids: list[str], require_kowiki: bool) -> str:
    values = " ".join(f"wd:{q}" for q in occupation_qids)
    kowiki = (
        "?article schema:about ?p ; schema:isPartOf <https://ko.wikipedia.org/> ."
        if require_kowiki
        else ""
    )
    article_sel = "?article" if require_kowiki else ""
    return f"""
SELECT DISTINCT ?p ?pLabel {article_sel} WHERE {{
  ?p wdt:P27 wd:{_KOREA_QID} ; wdt:P106 ?occ .
  VALUES ?occ {{ {values} }}
  {kowiki}
  SERVICE wikibase:label {{ bd:serviceParam wikibase:language "ko,en" }}
}}
"""


def _group_query(require_kowiki: bool) -> str:
    kowiki = (
        "?article schema:about ?g ; schema:isPartOf <https://ko.wikipedia.org/> ."
        if require_kowiki
        else ""
    )
    return f"""
SELECT DISTINCT ?g ?gLabel WHERE {{
  ?g wdt:P31/wdt:P279* wd:{_MUSICAL_GROUP_QID} .
  ?g wdt:P495 wd:{_KOREA_QID} .
  {kowiki}
  SERVICE wikibase:label {{ bd:serviceParam wikibase:language "ko,en" }}
}}
"""


def _qid_from_uri(uri: str) -> str:
    return uri.rsplit("/", 1)[-1]


def _kowiki_title(binding: dict, key: str = "article") -> str:
    art = binding.get(key, {}).get("value", "")
    if not art:
        return ""
    # https://ko.wikipedia.org/wiki/%EC%95%84%EC%9D%B4%EC%9C%A0 → 디코딩 제목
    path = art.rsplit("/wiki/", 1)[-1]
    return urllib.parse.unquote(path).replace("_", " ")


def discover_korean_celebrities(
    runner: SparqlRunner,
    occupations: list[str],
    *,
    require_kowiki: bool = True,
    sleep_sec: float = 2.0,
) -> list[DiscoveredEntity]:
    """직업 그룹별로 SPARQL을 실행해 한국 연예인을 발견한다.

    Args:
        runner: SPARQL 실행기.
        occupations: OCCUPATION_GROUPS 키 목록 + 'group'(음악 그룹).
        require_kowiki: kowiki sitelink 있는 인물만(유명 인물 필터).
        sleep_sec: 쿼리 간 대기(WDQS 부하 완화).

    Returns:
        DiscoveredEntity 목록(qid 기준 중복 제거).
    """
    seen: dict[str, DiscoveredEntity] = {}

    for category in occupations:
        if category == "group":
            query = _group_query(require_kowiki)
            label_key, uri_key = "gLabel", "g"
        elif category in OCCUPATION_GROUPS:
            query = _person_query(OCCUPATION_GROUPS[category], require_kowiki)
            label_key, uri_key = "pLabel", "p"
        else:
            logger.warning("알 수 없는 직업 카테고리: %s", category)
            continue

        logger.info("SPARQL 발견: %s", category)
        try:
            data = runner.run(query)
        except Exception as exc:
            logger.error("SPARQL 실패 (%s): %s", category, exc)
            continue

        bindings = data.get("results", {}).get("bindings", [])
        added = 0
        for b in bindings:
            qid = _qid_from_uri(b.get(uri_key, {}).get("value", ""))
            if not qid.startswith("Q") or qid in seen:
                continue
            name = b.get(label_key, {}).get("value", qid)
            title = _kowiki_title(b) if require_kowiki else name
            seen[qid] = DiscoveredEntity(
                qid=qid,
                name=name,
                kowiki_title=title or name,
                category=category,
                occupation_qids=([] if category == "group" else OCCUPATION_GROUPS[category]),
            )
            added += 1
        logger.info("%s: %d명 발견 (누적 %d)", category, added, len(seen))
        time.sleep(sleep_sec)

    return list(seen.values())
