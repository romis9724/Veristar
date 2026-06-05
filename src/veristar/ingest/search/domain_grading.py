"""URL 도메인 → SourceType + Grade 매핑.

config/source_grading.yaml의 화이트리스트를 로드해 URL의 도메인을
키로 등급을 결정한다. 정확 매칭 → 서브도메인 매칭 → 기본값(RUMOR) 순.

CLAUDE.md §4-1·§4-3:
- 모든 statement는 source 필수 (URL이 곧 출처)
- OFFICIAL만 답변 입력 → 화이트리스트가 정책의 가드
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlparse

from veristar.ontology.enums import Grade, SourceType


def _load_yaml(path: Path) -> dict[str, list[str]]:
    """PyYAML이 있으면 사용, 없으면 단순 파서 (official/reported/blocked 리스트만)."""
    try:
        import yaml  # type: ignore[import-untyped]

        with path.open(encoding="utf-8") as f:
            return yaml.safe_load(f) or {}
    except ImportError:
        return _simple_list_yaml(path.read_text(encoding="utf-8"))


def _simple_list_yaml(text: str) -> dict[str, list[str]]:
    """PyYAML 없이 'key:\\n  - item' 구조를 파싱하는 최소 폴백."""
    result: dict[str, list[str]] = {}
    current: str | None = None
    for raw_line in text.splitlines():
        line = raw_line.rstrip()
        if not line or line.lstrip().startswith("#"):
            continue
        stripped = line.lstrip()
        if line[0] != " " and stripped.endswith(":"):
            current = stripped[:-1]
            result[current] = []
        elif current and stripped.startswith("- "):
            item = stripped[2:].strip().strip('"').strip("'")
            if item:
                result[current].append(item)
    return result


@dataclass(frozen=True)
class DomainVerdict:
    """도메인 분류 결과."""

    domain: str
    grade: Grade
    source_type: SourceType
    blocked: bool = False


class DomainGrading:
    """yaml 화이트리스트 기반 도메인 분류기.

    Args:
        config_path: source_grading.yaml 경로. 기본값은 프로젝트 config/.
    """

    def __init__(self, config_path: Path | None = None) -> None:
        if config_path is None:
            # src/veristar/ingest/search/domain_grading.py
            #   → ../../../../config/source_grading.yaml
            config_path = Path(__file__).resolve().parents[4] / "config" / "source_grading.yaml"
        self._path = config_path
        self._official: set[str] = set()
        self._reported: set[str] = set()
        self._blocked: set[str] = set()
        self._load()

    def _load(self) -> None:
        if not self._path.exists():
            return
        data = _load_yaml(self._path)
        self._official = {d.lower() for d in (data.get("official") or [])}
        self._reported = {d.lower() for d in (data.get("reported") or [])}
        self._blocked = {d.lower() for d in (data.get("blocked") or [])}

    @staticmethod
    def _extract_domain(url: str) -> str:
        try:
            parsed = urlparse(url if "://" in url else f"https://{url}")
            host = (parsed.netloc or parsed.path).lower()
            # 포트 제거
            if ":" in host:
                host = host.split(":", 1)[0]
            # www. 정규화
            if host.startswith("www."):
                host = host[4:]
            return host
        except Exception:
            return ""

    def _match(self, domain: str, allow: set[str]) -> bool:
        """정확 매칭 → 서브도메인 매칭."""
        if not domain:
            return False
        if domain in allow:
            return True
        # 서브도메인 매칭: 'sub.foo.com'이 'foo.com'에 포함되는지
        parts = domain.split(".")
        for i in range(1, len(parts)):
            candidate = ".".join(parts[i:])
            if candidate in allow:
                return True
        return False

    def classify(self, url: str) -> DomainVerdict:
        """URL을 도메인 분류해 등급·소스타입을 반환한다."""
        domain = self._extract_domain(url)

        if self._match(domain, self._blocked):
            return DomainVerdict(
                domain=domain,
                grade=Grade.RUMOR,
                source_type=SourceType.COMMUNITY_OR_ANON,
                blocked=True,
            )

        if self._match(domain, self._official):
            # 방송사·기획사·공식 채널
            return DomainVerdict(
                domain=domain,
                grade=Grade.OFFICIAL,
                source_type=SourceType.ARTIST_OFFICIAL_SNS,
            )

        if self._match(domain, self._reported):
            return DomainVerdict(
                domain=domain,
                grade=Grade.REPORTED,
                source_type=SourceType.PRESS,
            )

        # 기본값: RUMOR (vault 저장은 가능, 답변 입력 금지)
        return DomainVerdict(
            domain=domain,
            grade=Grade.RUMOR,
            source_type=SourceType.COMMUNITY_OR_ANON,
        )
