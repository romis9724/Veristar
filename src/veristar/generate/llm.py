"""로컬 LLM 클라이언트 — Ollama(qwen3) via httpx.

앤트로픽 API 대신 로컬 Ollama를 쓴다. 추가 의존성 없이 httpx로 호출.
설정(환경변수):
- OLLAMA_HOST (기본 http://localhost:11434)
- VERISTAR_LLM_MODEL (기본 qwen3)

연결 실패/미설치는 예외 대신 ok=False 결과로 graceful 반환한다.
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass

import httpx

_DEFAULT_HOST = "http://localhost:11434"
_DEFAULT_MODEL = "qwen3:14b"  # `ollama list`에 맞춤. VERISTAR_LLM_MODEL로 변경.
_THINK_RE = re.compile(r"<think>.*?</think>", re.DOTALL)


@dataclass(frozen=True)
class LLMResult:
    text: str
    model: str
    ok: bool
    error: str | None = None


def _strip_think(text: str) -> str:
    """qwen3 등 추론형 모델의 <think>…</think> 블록 제거."""
    return _THINK_RE.sub("", text).strip()


def chat(
    system: str,
    user: str,
    *,
    model: str | None = None,
    max_tokens: int = 512,
    timeout: float = 120.0,
) -> LLMResult:
    """Ollama chat 호출. temperature=0(결정론적·근거 충실), thinking 비활성."""
    host = os.environ.get("OLLAMA_HOST", _DEFAULT_HOST).rstrip("/")
    model = model or os.environ.get("VERISTAR_LLM_MODEL", _DEFAULT_MODEL)
    payload = {
        "model": model,
        "stream": False,
        "think": False,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        "options": {"temperature": 0, "num_predict": max_tokens},
    }
    try:
        resp = httpx.post(f"{host}/api/chat", json=payload, timeout=timeout)
        resp.raise_for_status()
        content = resp.json().get("message", {}).get("content", "")
        return LLMResult(text=_strip_think(content), model=model, ok=True)
    except (httpx.HTTPError, OSError) as exc:
        return LLMResult(
            text="",
            model=model,
            ok=False,
            error=(
                f"Ollama 연결 실패({host}): {exc}. "
                f"'ollama serve' 실행과 'ollama pull {model}' 확인."
            ),
        )
