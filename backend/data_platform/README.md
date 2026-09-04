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

## 本机开发实例

本机实例使用 `127.0.0.1:54329`，避免占用默认 PostgreSQL 端口。它是影子库，正式网页仍读取 CSV；每日任务会在两条 CSV 生产链均成功后执行一次镜像导入。影子导入失败只产生告警，不会撤销或污染已经完成的正式 CSV 更新。
