"""한국 연예인 대상 원본(raw) 콘텐츠 수집기 모음.

각 수집기는 VaultDoc을 생성해 VaultStore에 저장한다.
검증은 수집 후 별도 파이프라인(veristar.verify)이 담당한다.
"""

from .base import CollectorBase, CollectResult

__all__ = ["CollectorBase", "CollectResult"]
