"""个人工作区文件到 PostgreSQL 的显式、非破坏性导入。"""
from __future__ import annotations

import hashlib
import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from data_platform.config import load_database_settings


@dataclass(frozen=True)
class WorkspaceData:
    holdings: list[dict[str, Any]]
    closed: list[dict[str, Any]]
    reports: list[dict[str, Any]]
    reports_dir: Path


def load_workspace(data_dir: Path | None = None) -> WorkspaceData:
    root = data_dir or Path(os.environ.get("VR_DATA_DIR") or Path.home() / ".vibe-research")
    portfolio_path = root / "portfolio.json"
    portfolio = json.loads(portfolio_path.read_text(encoding="utf-8")) if portfolio_path.exists() else {}
    reports_dir = root / "myreports"
    index_path = reports_dir / "index.json"
    reports = json.loads(index_path.read_text(encoding="utf-8")) if index_path.exists() else []
    return WorkspaceData(
        holdings=portfolio.get("holdings", []) if isinstance(portfolio, dict) else [],
        closed=portfolio.get("closed", []) if isinstance(portfolio, dict) else [],
        reports=reports if isinstance(reports, list) else [],
        reports_dir=reports_dir,
    )


def import_workspace(data_dir: Path | None = None) -> dict[str, int]:
    data = load_workspace(data_dir)
    settings = load_database_settings()
    if not settings.url:
        raise RuntimeError("未配置 VR_DATABASE_URL，不能导入个人工作区")
    import psycopg  # noqa: PLC0415

    with psycopg.connect(settings.url) as conn:
        with conn.cursor() as cur:
            for item in data.holdings:
                code = str(item.get("code") or "").strip()
                if not code:
                    raise ValueError("持仓记录缺少证券代码")
                cur.execute(
                    "INSERT INTO portfolio_positions(position_key, instrument_id, shares, cost, payload) "
                    "VALUES (%s, %s, %s, %s, %s) ON CONFLICT (position_key) DO UPDATE "
                    "SET instrument_id=EXCLUDED.instrument_id, shares=EXCLUDED.shares, cost=EXCLUDED.cost, payload=EXCLUDED.payload, imported_at=now()",
                    (code, code, item.get("shares") or 0, item.get("cost") or 0, json.dumps(item, ensure_ascii=False)),
                )
            for index, item in enumerate(data.closed):
                raw = json.dumps(item, ensure_ascii=False, sort_keys=True)
                key = hashlib.sha256(f"{index}:{raw}".encode()).hexdigest()
                cur.execute(
                    "INSERT INTO portfolio_closed_positions(closed_key, payload) VALUES (%s, %s) "
                    "ON CONFLICT (closed_key) DO UPDATE SET payload=EXCLUDED.payload, imported_at=now()",
                    (key, raw),
                )
            for item in data.reports:
                report_id = str(item.get("id") or "").strip()
                if not report_id:
                    raise ValueError("研报索引缺少 id")
                storage_path = data.reports_dir / f"{report_id}{item.get('ext', '')}"
                cur.execute(
                    "INSERT INTO research_reports(report_id, display_name, storage_path, metadata) "
                    "VALUES (%s, %s, %s, %s) ON CONFLICT (report_id) DO UPDATE "
                    "SET display_name=EXCLUDED.display_name, storage_path=EXCLUDED.storage_path, metadata=EXCLUDED.metadata, imported_at=now()",
                    (report_id, item.get("name") or report_id, str(storage_path), json.dumps(item, ensure_ascii=False)),
                )
        conn.commit()
    return {"holdings": len(data.holdings), "closed": len(data.closed), "reports": len(data.reports)}
