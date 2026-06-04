"""Veristar query API (M6a) — 읽기전용 FastAPI + HTMX 탐색 UI."""

from __future__ import annotations

from .app import create_app, create_default_app

__all__ = ["create_app", "create_default_app"]
