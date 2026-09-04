"""有序、幂等的 PostgreSQL 架构迁移执行器。"""
from __future__ import annotations

import hashlib
from pathlib import Path

from data_platform.config import load_database_settings

MIGRATIONS_DIR = Path(__file__).with_name("migrations")


def migration_files() -> list[Path]:
    return sorted(MIGRATIONS_DIR.glob("*.sql"))


def migration_checksum(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def apply_migrations() -> list[str]:
    """应用未执行迁移；已执行迁移的校验和变化会直接拒绝启动。"""
    settings = load_database_settings()
    if not settings.url:
        raise RuntimeError("未配置 VR_DATABASE_URL，数据库影子层尚未启用")

    import psycopg  # noqa: PLC0415

    applied: list[str] = []
    with psycopg.connect(settings.url) as conn:
        with conn.cursor() as cur:
            cur.execute(
                "CREATE TABLE IF NOT EXISTS schema_migrations ("
                "version TEXT PRIMARY KEY, checksum TEXT NOT NULL, "
                "applied_at TIMESTAMPTZ NOT NULL DEFAULT now())"
            )
            cur.execute("SELECT version, checksum FROM schema_migrations")
            known = dict(cur.fetchall())
            for path in migration_files():
                version = path.stem
                checksum = migration_checksum(path)
                if version in known:
                    if known[version] != checksum:
                        raise RuntimeError(f"已执行迁移的内容发生变化: {version}")
                    continue
                cur.execute(path.read_text(encoding="utf-8"))
                cur.execute(
                    "INSERT INTO schema_migrations(version, checksum) VALUES (%s, %s)",
                    (version, checksum),
                )
                applied.append(version)
        conn.commit()
    return applied
