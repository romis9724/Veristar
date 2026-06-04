"""raw vault — Obsidian 호환 Markdown 저장소.

수집기가 원본 콘텐츠를 여기 쓰고, 검증기가 읽어서 JSONL 그래프로 승격한다.
"""

from .store import ConfidenceLevel, VaultDoc, VaultStore

__all__ = ["VaultStore", "VaultDoc", "ConfidenceLevel"]
