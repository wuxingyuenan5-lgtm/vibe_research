"""个人工作区 PostgreSQL 仓储。"""
from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from data_platform.config import load_database_settings


def _connect():
    settings = load_database_settings()
    if not settings.url:
        raise RuntimeError("个人工作区数据库未配置 VR_DATABASE_URL")
    import psycopg  # noqa: PLC0415

    return psycopg.connect(settings.url)


def load_portfolio() -> dict[str, Any]:
    with _connect() as conn, conn.cursor() as cur:
        cur.execute("SELECT payload FROM portfolio_positions ORDER BY instrument_id")
        holdings = [row[0] for row in cur.fetchall()]
        cur.execute("SELECT payload FROM portfolio_closed_positions ORDER BY ordinal NULLS LAST, imported_at, closed_key")
        closed = [row[0] for row in cur.fetchall()]
        cur.execute("SELECT payload FROM workspace_metadata WHERE metadata_key='portfolio'")
        meta = cur.fetchone()
    payload = meta[0] if meta else {}
    return {"holdings": holdings, "closed": closed, "last_refresh": payload.get("last_refresh")}


def save_portfolio(data: dict[str, Any]) -> None:
    with _connect() as conn, conn.cursor() as cur:
        cur.execute("DELETE FROM portfolio_positions")
        for item in data.get("holdings", []):
            code = str(item.get("code") or "").strip()
            cur.execute(
                "INSERT INTO portfolio_positions(position_key,instrument_id,shares,cost,payload) VALUES (%s,%s,%s,%s,%s)",
                (code, code, item.get("shares") or 0, item.get("cost") or 0, json.dumps(item, ensure_ascii=False)),
            )
        cur.execute("DELETE FROM portfolio_closed_positions")
        for ordinal, item in enumerate(data.get("closed", [])):
            cur.execute(
                "INSERT INTO portfolio_closed_positions(closed_key,payload,ordinal) VALUES (%s,%s,%s)",
                (uuid.uuid4().hex, json.dumps(item, ensure_ascii=False), ordinal),
            )
        cur.execute(
            "INSERT INTO workspace_metadata(metadata_key,payload) VALUES ('portfolio',%s) "
            "ON CONFLICT (metadata_key) DO UPDATE SET payload=EXCLUDED.payload,updated_at=now()",
            (json.dumps({"last_refresh": data.get("last_refresh")}, ensure_ascii=False),),
        )
        conn.commit()


def load_reports() -> list[dict[str, Any]]:
    with _connect() as conn, conn.cursor() as cur:
        cur.execute("SELECT metadata FROM research_reports ORDER BY (metadata->>'ts')::bigint DESC")
        return [row[0] for row in cur.fetchall()]


def save_reports(items: list[dict[str, Any]], reports_dir: Path) -> None:
    with _connect() as conn, conn.cursor() as cur:
        cur.execute("DELETE FROM research_reports")
        for item in items:
            report_id = str(item.get("id") or "")
            storage_path = reports_dir / f"{report_id}{item.get('ext', '')}"
            cur.execute(
                "INSERT INTO research_reports(report_id,display_name,storage_path,metadata) VALUES (%s,%s,%s,%s)",
                (report_id, item.get("name") or report_id, str(storage_path), json.dumps(item, ensure_ascii=False)),
            )
        conn.commit()


def list_notes() -> list[dict[str, Any]]:
    with _connect() as conn, conn.cursor() as cur:
        cur.execute("SELECT note_id,note_kind,title,content,created_at FROM research_notes ORDER BY created_at DESC")
        return [{"id": row[0], "kind": row[1], "title": row[2], "content": row[3], "ts": int(row[4].timestamp() * 1000)} for row in cur.fetchall()]


def add_note(kind: str, title: str, content: str, ts: int | None = None, note_id: str | None = None) -> dict[str, Any]:
    created = datetime.fromtimestamp(ts / 1000, timezone.utc) if ts else datetime.now(timezone.utc)
    identifier = note_id or uuid.uuid4().hex
    with _connect() as conn, conn.cursor() as cur:
        cur.execute(
            "INSERT INTO research_notes(note_id,note_kind,title,content,created_at,updated_at) VALUES (%s,%s,%s,%s,%s,%s) "
            "ON CONFLICT (note_id) DO NOTHING",
            (identifier, kind, title, content, created, created),
        )
        conn.commit()
    return {"id": identifier, "kind": kind, "title": title, "content": content, "ts": int(created.timestamp() * 1000)}


def delete_note(note_id: str) -> bool:
    with _connect() as conn, conn.cursor() as cur:
        cur.execute("DELETE FROM research_notes WHERE note_id=%s", (note_id,))
        deleted = cur.rowcount > 0
        conn.commit()
    return deleted


def clear_notes() -> int:
    with _connect() as conn, conn.cursor() as cur:
        cur.execute("DELETE FROM research_notes")
        count = cur.rowcount
        conn.commit()
    return count
