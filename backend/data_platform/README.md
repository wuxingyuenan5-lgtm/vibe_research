# 数据平台数据库

当前 CSV/JSON 仍是正式生产输入。本目录提供 PostgreSQL 的可版本化结构、导入对账和页面只读模型。

启用前提：本机或服务器已有 PostgreSQL，设置不提交到 Git 的 `VR_DATABASE_URL`，例如：

```bash
export VR_DATABASE_URL='postgresql://vibe:password@127.0.0.1:5432/vibe_research'
```

执行迁移：

```bash
cd backend
python -c 'from data_platform.migrations import apply_migrations; print(apply_migrations())'
```

生产原则：CSV 先写成功，再导入数据库并严格对账；市场总览和自选股日度行情读取数据库，自选股定义仍读取本地 `pool.json`。

## 本机开发实例

本机实例使用 `127.0.0.1:54329`，避免占用默认 PostgreSQL 端口。每日任务在两条 CSV 生产链成功后导入数据库并对账；导入失败会使当日生产明确失败，网页保留上一份已验证快照。
