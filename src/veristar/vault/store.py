"""Obsidian 호환 Markdown vault 저장소.

디렉토리 구조::

    vault/
    ├── entities/          # 인물·그룹 프로필 (1파일 = 1엔티티)
    ├── articles/          # 뉴스·위키 기사
    ├── sns/               # SNS 포스트·영상 메타데이터
    └── sources/           # 출처 레퍼런스

각 파일은 YAML frontmatter + Markdown 본문.
frontmatter에 수집 메타데이터, 본문에 원문 콘텐츠.
민감 정보는 `sensitive: true` 플래그로 표시하되 저장은 허용 (서비스 레이어에서 차단).
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date
from enum import StrEnum
from pathlib import Path
from typing import Any


class ConfidenceLevel(StrEnum):
    UNVERIFIED = "unverified"
    LOW = "low"       # LLM cross-check 실패 또는 단일 소스
    MEDIUM = "medium"  # 부분 교차검증
    HIGH = "high"     # 다중 소스 교차검증 완료


@dataclass
class VaultDoc:
    """Vault에 저장되는 단일 문서."""

    # --- 필수 ---
    id: str                       # 고유 ID (slug). 파일명 기반.
    title: str
    content: str                  # Markdown 본문 (원문 또는 처리 후)
    source_type: str              # wikipedia | namuwiki | news | youtube | instagram | twitter
    source_url: str

    # --- 선택 ---
    entity_refs: list[str] = field(default_factory=list)   # 연관 엔티티 slug
    published: date | None = None
    retrieved: date | None = None
    confidence: ConfidenceLevel = ConfidenceLevel.UNVERIFIED
    license: str = ""             # e.g. "CC BY-SA 4.0", "CC BY-NC-SA 2.0 KR"
    sensitive: bool = False       # 민감 정보 포함 여부 (저장은 허용, 서비스에서 필터)
    extra: dict[str, Any] = field(default_factory=dict)    # 소스별 추가 필드

    def to_markdown(self) -> str:
        """Obsidian 호환 Markdown 직렬화."""
        lines = ["---"]
        lines.append(f"id: {self.id}")
        lines.append(f"title: {_yaml_str(self.title)}")
        lines.append(f"source_type: {self.source_type}")
        lines.append(f"source_url: {_yaml_str(self.source_url)}")
        if self.entity_refs:
            refs = ", ".join(f'"{r}"' for r in self.entity_refs)
            lines.append(f"entity_refs: [{refs}]")
        if self.published:
            lines.append(f"published: {self.published}")
        if self.retrieved:
            lines.append(f"retrieved: {self.retrieved}")
        lines.append(f"confidence: {self.confidence}")
        if self.license:
            lines.append(f"license: {_yaml_str(self.license)}")
        if self.sensitive:
            lines.append("sensitive: true")
        for k, v in self.extra.items():
            lines.append(f"{k}: {_yaml_str(str(v)) if isinstance(v, str) else v}")
        lines.append("---")
        lines.append("")
        lines.append(self.content)
        return "\n".join(lines)

    @classmethod
    def from_markdown(cls, text: str, doc_id: str) -> VaultDoc:
        """Markdown 텍스트에서 VaultDoc 복원."""
        fm, body = _split_frontmatter(text)
        return cls(
            id=fm.get("id", doc_id),
            title=str(fm.get("title", "")),
            content=body.strip(),
            source_type=str(fm.get("source_type", "")),
            source_url=str(fm.get("source_url", "")),
            entity_refs=_parse_list(fm.get("entity_refs", [])),
            published=_parse_date(fm.get("published")),
            retrieved=_parse_date(fm.get("retrieved")),
            confidence=ConfidenceLevel(fm.get("confidence", "unverified")),
            license=str(fm.get("license", "")),
            sensitive=bool(fm.get("sensitive", False)),
            extra={k: v for k, v in fm.items() if k not in _KNOWN_KEYS},
        )


_KNOWN_KEYS = {
    "id", "title", "source_type", "source_url", "entity_refs",
    "published", "retrieved", "confidence", "license", "sensitive",
}

_CATEGORY_DIR: dict[str, str] = {
    "wikipedia": "articles",
    "namuwiki": "articles",
    "news": "articles",
    "youtube": "sns",
    "instagram": "sns",
    "twitter": "sns",
    "profile": "entities",
}


class VaultStore:
    """Markdown vault 읽기/쓰기 인터페이스."""

    def __init__(self, vault_root: str | Path) -> None:
        self.root = Path(vault_root)
        for sub in ("entities", "articles", "sns", "sources"):
            (self.root / sub).mkdir(parents=True, exist_ok=True)

    def _path_for(self, doc: VaultDoc) -> Path:
        sub = _CATEGORY_DIR.get(doc.source_type, "articles")
        slug = _slugify(doc.id)
        return self.root / sub / f"{slug}.md"

    def write(self, doc: VaultDoc) -> Path:
        """문서를 vault에 저장. 기존 파일이 있으면 덮어쓴다."""
        path = self._path_for(doc)
        path.write_text(doc.to_markdown(), encoding="utf-8")
        return path

    def read(self, doc_id: str, source_type: str = "") -> VaultDoc | None:
        """ID로 문서를 읽는다."""
        slug = _slugify(doc_id)
        for sub in ("entities", "articles", "sns", "sources"):
            path = self.root / sub / f"{slug}.md"
            if path.exists():
                return VaultDoc.from_markdown(path.read_text(encoding="utf-8"), doc_id)
        return None

    def list_docs(self, source_type: str | None = None) -> list[VaultDoc]:
        """모든 문서(또는 특정 type) 목록."""
        results: list[VaultDoc] = []
        for md_file in self.root.rglob("*.md"):
            text = md_file.read_text(encoding="utf-8")
            doc = VaultDoc.from_markdown(text, md_file.stem)
            if source_type is None or doc.source_type == source_type:
                results.append(doc)
        return results

    def list_unverified(self) -> list[VaultDoc]:
        """검증 안 된 문서 목록 (검증 파이프라인 입력용)."""
        return [d for d in self.list_docs() if d.confidence == ConfidenceLevel.UNVERIFIED]

    def update_confidence(self, doc_id: str, confidence: ConfidenceLevel) -> bool:
        """문서의 confidence 필드만 업데이트한다."""
        doc = self.read(doc_id)
        if doc is None:
            return False
        updated = VaultDoc(
            id=doc.id, title=doc.title, content=doc.content,
            source_type=doc.source_type, source_url=doc.source_url,
            entity_refs=doc.entity_refs, published=doc.published,
            retrieved=doc.retrieved, confidence=confidence,
            license=doc.license, sensitive=doc.sensitive, extra=doc.extra,
        )
        self.write(updated)
        return True

    def stats(self) -> dict[str, int]:
        docs = self.list_docs()
        return {
            "total": len(docs),
            "unverified": sum(1 for d in docs if d.confidence == ConfidenceLevel.UNVERIFIED),
            "verified_high": sum(1 for d in docs if d.confidence == ConfidenceLevel.HIGH),
            "sensitive": sum(1 for d in docs if d.sensitive),
        }


# --- 헬퍼 ---


def _yaml_str(s: str) -> str:
    if any(c in s for c in (':', '"', "'", '\n', '#')):
        escaped = s.replace('"', '\\"')
        return f'"{escaped}"'
    return s


_FRONTMATTER_RE = re.compile(r"^---\n(.*?)\n---\n?(.*)", re.DOTALL)


def _split_frontmatter(text: str) -> tuple[dict[str, Any], str]:
    m = _FRONTMATTER_RE.match(text)
    if not m:
        return {}, text
    try:
        import yaml  # type: ignore[import-untyped]
        fm = yaml.safe_load(m.group(1)) or {}
    except ImportError:
        fm = _simple_yaml_parse(m.group(1))
    return fm, m.group(2)


def _simple_yaml_parse(text: str) -> dict[str, Any]:
    """PyYAML 없이 단순 key: value 파싱 (fallback)."""
    result: dict[str, Any] = {}
    for line in text.splitlines():
        if ":" not in line:
            continue
        k, _, v = line.partition(":")
        k = k.strip()
        v = v.strip().strip('"')
        result[k] = v
    return result


def _parse_list(val: Any) -> list[str]:
    if isinstance(val, list):
        return [str(x) for x in val]
    if isinstance(val, str):
        return [x.strip().strip('"') for x in val.strip("[]").split(",") if x.strip()]
    return []


def _parse_date(val: Any) -> date | None:
    if val is None:
        return None
    if isinstance(val, date):
        return val
    try:
        return date.fromisoformat(str(val))
    except ValueError:
        return None


_NON_SLUG = re.compile(r"[^\w\-]", re.UNICODE)
_MULTI_DASH = re.compile(r"-{2,}")


def _slugify(text: str) -> str:
    slug = text.lower().replace(" ", "-").replace("/", "-")
    slug = _NON_SLUG.sub("", slug)
    slug = _MULTI_DASH.sub("-", slug)
    return slug[:120]  # 파일명 길이 제한
