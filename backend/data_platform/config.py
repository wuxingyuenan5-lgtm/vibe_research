"""数据库连接配置。未配置时，影子库功能保持关闭。"""
from __future__ import annotations

import os
from dataclasses import dataclass


@dataclass(frozen=True)
class DatabaseSettings:
    url: str | None

    @property
    def enabled(self) -> bool:
        return bool(self.url)


def load_database_settings() -> DatabaseSettings:
    """读取本地环境变量；绝不将密码或连接串提交到仓库。"""
    value = os.environ.get("VR_DATABASE_URL", "").strip()
    if value and not value.startswith(("postgresql://", "postgres://")):
        raise ValueError("VR_DATABASE_URL 必须是 PostgreSQL 连接串")
    return DatabaseSettings(url=value or None)
