"""统一交易晨报 —— payload 读取与 HTML/PDF 下载。

数据：data/market-monitor/morning-brief/<date>.json（冻结 payload）
产物：同目录 <date>.html / <date>.pdf（同一份 payload 的渲染/打印产物）
Dashboard 只做读取、展示、下载；晨报正文由研究管线生产。
"""
from __future__ import annotations

import json
from pathlib import Path

BRIEF_DIR = Path(__file__).resolve().parent.parent / "data" / "market-monitor" / "morning-brief"


def list_dates() -> list[str]:
    dates = []
    if BRIEF_DIR.exists():
        dates = sorted(p.stem for p in BRIEF_DIR.glob("*.json"))
    return dates


def load_payload(date: str) -> dict | None:
    path = BRIEF_DIR / f"{date}.json"
    if not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def resolve_artifact(date: str, kind: str) -> Path | None:
    ext = "html" if kind == "html" else "pdf"
    path = BRIEF_DIR / f"{date}.{ext}"
    return path if path.exists() else None
