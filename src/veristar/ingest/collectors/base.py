"""수집기 추상 기반 클래스."""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass, field

import httpx

from veristar.vault.store import VaultDoc, VaultStore

logger = logging.getLogger(__name__)

_UA = "VeristarBot/0.1 (https://github.com/; content collection)"


@dataclass
class CollectResult:
    """수집 결과 요약."""

    saved: int = 0
    skipped: int = 0
    errors: int = 0
    messages: list[str] = field(default_factory=list)

    def merge(self, other: CollectResult) -> CollectResult:
        return CollectResult(
            saved=self.saved + other.saved,
            skipped=self.skipped + other.skipped,
            errors=self.errors + other.errors,
            messages=self.messages + other.messages,
        )


class CollectorBase(ABC):
    """모든 수집기의 공통 인터페이스.

    하위 클래스는 `collect()` 메서드를 구현하고
    `_save(doc)` 를 통해 vault에 저장한다.
    """

    def __init__(self, store: VaultStore, timeout: float = 30.0) -> None:
        self.store = store
        self._client = httpx.Client(
            timeout=timeout,
            headers={"User-Agent": _UA},
            follow_redirects=True,
        )

    @abstractmethod
    def collect(self, target: str, **kwargs: object) -> CollectResult:
        """단일 대상(이름·URL·QID 등)에 대해 수집을 실행한다."""
        ...

    def _save(self, doc: VaultDoc) -> bool:
        """vault에 저장. 성공이면 True, 중복이면 False."""
        existing = self.store.read(doc.id)
        if existing is not None and existing.source_url == doc.source_url:
            logger.debug("skipped (already exists): %s", doc.id)
            return False
        self.store.write(doc)
        logger.info("saved: %s (%s)", doc.id, doc.source_type)
        return True

    def _get(self, url: str) -> str | None:
        """HTTP GET. 실패 시 None."""
        try:
            resp = self._client.get(url)
            resp.raise_for_status()
            return resp.text
        except httpx.HTTPError as exc:
            logger.warning("HTTP error (%s): %s", url, exc)
            return None

    def close(self) -> None:
        self._client.close()

    def __enter__(self) -> CollectorBase:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()
