# 数据平台影子库

当前 CSV/JSON 仍是正式生产真源。本目录只提供 PostgreSQL 的可版本化结构和后续一向导入边界。

启用前提：本机或服务器已有 PostgreSQL，设置不提交到 Git 的 `VR_DATABASE_URL`，例如：

```bash
export VR_DATABASE_URL='postgresql://vibe:password@127.0.0.1:5432/vibe_research'
```

执行迁移：

```bash
cd backend
python -c 'from data_platform.migrations import apply_migrations; print(apply_migrations())'
```

迁移原则：CSV 先写成功，再镜像导入数据库；页面继续读现有正式路径，直到逐日对账连续通过后再按模块切换。
