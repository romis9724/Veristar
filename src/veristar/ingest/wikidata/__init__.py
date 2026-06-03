"""Wikidata 시드 수집기 (M2)."""

from __future__ import annotations

from .client import HttpWikidataClient, WikidataClient
from .mapper import MappedRecords, map_item
from .mapping import DEFAULT_MAPPING, WikidataMapping, qid_to_id
from .seed import build_seed, write_seed

__all__ = [
    "WikidataClient",
    "HttpWikidataClient",
    "MappedRecords",
    "map_item",
    "WikidataMapping",
    "DEFAULT_MAPPING",
    "qid_to_id",
    "build_seed",
    "write_seed",
]
