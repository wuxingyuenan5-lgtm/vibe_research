# 后端统一化设计方案 · 市场总览 + 自选股

> 状态：待评审（未动代码）
> 目标：把「市场总览」「自选股」两个子页的数据生产流程统一到一套后端数据服务层上，同时消除后端不稳定的根源。
> 原则：**只改数据获取/缓存/降级，不动任何业务语义**（不出买卖建议、不改数据口径）。

---

## 0. 结论先行（TL;DR）

| 问题 | 现状 | 方案 |
|---|---|---|
| 市场总览页一次打 17 个请求 | 7 路主数据 + 10 路 K 线补丁并发 | 实时层聚合为 **1 个请求**，快照层独立 |
| 慢数据拖垮整页 | akshare 情绪/资金 + 东财涨停池 4 连挤在 `Promise.all` | 后端并发取 + 单源失败只降级、不拖垮 |
| 缓存散落 5 处、无合并 | `app.py` 4 个 dict + `market.py` 1 个 dict | 统一 `dataservice.py`（TTL + 合并 + 健康） |
| 自选股存储混乱 | focus 已在后端，但残留 localStorage 兜底 + 死代码 | 清理残留 + 修路由 bug |
| `/api/quote` 零缓存零合并 | 自选/持仓/个股各打各的腾讯 | 短 TTL（2-3s）+ single-flight 合并 |
| 无健康检查 | 上游挂了前端只知道 502 | `/api/health/providers` 暴露降级状态 |

---

## 1. 现状诊断

### 1.1 市场总览页（`/market-overview` → `MarketOverview.tsx`）数据流

页面 `load()` 用 `Promise.all` 并发 7 路请求：

| # | 请求 | 上游 | 稳定性 |
|---|---|---|---|
| 1 | `/api/indices` | 腾讯（标准库） | 稳 |
| 2 | `/api/global/indices` | 东财 push2 | 中（有 push2delay 降级） |
| 3 | `/api/market/overview` | akshare 乐咕乐股 + 行业资金 | **差**（~25% 空表，重试 3 次） |
| 4 | `/api/market/emotion` | 东财涨停板 4 池 | **慢**（全局 1s 限流 × 4 + 回溯交易日） |
| 5 | `/api/market/turnover-top` | 东财 clist | 中 |
| 6 | `/api/morning-brief` | 本地快照 | 稳（盘后固定） |
| 7 | `/api/market-monitor` | 本地快照 | 稳（盘后固定） |

外加两个 `useEffect` 各发 K 线请求：白银/铜/锂 3 个 + 海外/商品/汇率/国债 7 个 = **10 个 K 线请求**。

**合计：一次加载 ≈ 17 个 HTTP 请求。**

核心矛盾：
- 慢请求（#3 akshare、#4 涨停池）与快请求（#1 指数）挤在同一个 `Promise.all`，整页被最慢的拖住。
- #6/#7 是**盘后固定快照**，却和实时数据一起被「刷新」按钮反复拉取。
- 后端每个请求各自走缓存，`market.py` 的 `_CACHE` TTL 5 分钟对「情绪/资金」这种分钟级数据合理，但对「指数」这种秒级数据又太久。

### 1.2 自选股页（`/stock-pool` → `StockPool.tsx`）数据流

> 注意：路由 `/watchlist` 已被重定向到 `/stock-pool`。用户说的「自选股」子页，实际是 `StockPool.tsx`（页面标题「A股看板｜核心股票池」，注释「自选股 · 核心股票池 Dashboard」）。

页面里有两类「自选」概念，存储位置不同：

| 概念 | 真源 | 数据 | 频率 |
|---|---|---|---|
| **核心股票池** | `backend/data/stock-pool/pool.json`（→ GitHub backup） | 日度快照 `stocks.csv` | 每日 `daily_refresh.py` |
| **近期关注（focus）** | `backend/data/stock-pool/focus.json`（→ GitHub backup） | `/api/quote` 实时补全 | 页面加载时拉一次 |

**关键发现：自选股（近期关注 focus）的真源其实已经在后端了**（`focus.json` + GitHub 真源，`GET/POST /api/stock-pool/focus`），`localStorage` 里的 `vr-watchlist` 只是「后端挂了才兜底」的缓存副本（`StockPool.tsx` 第 133-149 行 `saveWatch` / `loadWatch`）。

### 1.3 稳定性问题根源（按影响排序）

1. **akshare 是最大不稳定源**：`market.py` 的 `_sentiment()` 用 `ak.stock_market_activity_legu()`（间歇 "No tables found"，`_sentiment` 里重试 3 次、每次 sleep 0.8s），`_sectors()` 用 `ak.stock_fund_flow_industry()`。已有东财兜底，但散落、无状态记录。
2. **东财全局 1 秒限流串行化**：`astock.py` 的 `em_get` 里 `_EM_MIN_INTERVAL = 1.0` 是全局共享的。`/api/market/emotion` 要串行调 4 个涨停池 + 回溯交易日，最坏拖到 5 秒+。
3. **无请求合并（single-flight）**：同一秒多点刷新 / 多标签页，上游被打多次。
4. **代理与直连的「补丁式」处理**：`astock.py` 的 `em_get`（直连→代理降级）、`market.py`（akshare→东财兜底）、`gstock.py`（push2→push2delay）各自为政，无统一健康视图。

### 1.4 已发现的 bug / 死代码

| 项 | 位置 | 问题 |
|---|---|---|
| **重复路由** | `frontend/src/router.tsx` 第 26 行 + 第 34 行 | `/watchlist` 定义了两次，第一个是 `<Navigate to="/stock-pool">`，第二个指向死代码 `Watchlist.tsx`。React Router 匹配第一个，所以 `Watchlist.tsx` 永远不可达 |
| 死代码 | `frontend/src/pages/Watchlist.tsx` | 旧自选股页（3 秒轮询），已被 StockPool 取代，无人引用 |
| 死代码 | `frontend/src/hooks/useLiveQuotes.ts` | 只被上面的 `Watchlist.tsx` 引用 |
| 残留兜底 | `frontend/src/lib/watchlist.ts` + `StockPool.tsx` | localStorage `vr-watchlist` 作为 focus 兜底，与后端真源并存，语义混乱 |

---

## 2. 目标架构

```
前端页面 ──1个请求──► 聚合端点 ──► DataService（统一 TTL + single-flight + 健康）
                        │
                        ├──► Provider 层：腾讯 / 东财 / akshare / 本地快照
                        └──► /api/health/providers（哪个源健康、哪个在降级）
```

新增一个模块 `backend/dataservice.py`，收编现在散落的 5 个缓存字典，提供三个能力：

1. **统一缓存 + 分级 TTL**：`get(key, ttl, fetch, valid)`，一行搞定。预设三档：
   - `live`（3 秒）：指数、个股 quote、全球指数 —— 实时行情
   - `minute`（60 秒）：市场情绪、板块资金、短线情绪、成交额榜 —— 分钟级
   - `snapshot`（不缓存 / 读文件）：晨报、市场监控 —— 盘后固定
2. **single-flight 合并**：同 key 并发请求只打一次上游，其余等同一结果（解决多标签页/重复刷新）。
3. **provider 健康状态**：每次上游调用记录 `{ok, latency_ms, last_error, last_success, degraded}`，供健康页与聚合响应的 `providers` 字段使用。

---

## 3. 分阶段实施方案

### 第 1 期：统一数据服务层 + 市场总览聚合（收益最大）

#### 3.1.1 新增 `backend/dataservice.py`

```python
# 核心接口（示意）
def get(key: str, ttl: int | None, fetch, valid=bool):
    """统一缓存 + single-flight 合并。
    - 命中且未过期 → 返回缓存
    - 未命中 → 同 key 并发只 fetch 一次，其余线程等同一结果
    - fetch 成功且 valid → 缓存 + record_provider(ok)
    - fetch 失败 → record_provider(fail) + 抛异常（由调用方降级）
    """

def record_provider(name: str, ok: bool, latency_ms: float, error: str | None = None): ...

def provider_health() -> dict: ...

# TTL 预设
TTL = {"live": 3, "minute": 60}
```

single-flight 实现要点：`dict[key] -> (threading.Event, result)`，第一个线程 fetch 后 `set()` 并广播结果，其余线程 `wait()` 后直接取。要处理 fetch 异常时也要 `set()` 并广播异常，避免其他线程永久阻塞。

#### 3.1.2 改造 `/api/market/overview` 为聚合端点

现在 `/api/market/overview` 只返回 `{sentiment, sectors}`。改造后**保持原字段兼容**，额外合并实时层全部数据：

```json
{
  "indices":        [ {name, price, change_pct, change_amt} ],
  "global_indices": [ {key, name, region, price, change_pct} ],
  "sentiment":      { up, down, flat, zt, zt_real, dt, dt_real, active, breadth, speculation, date } | null,
  "sectors":        [ {name, pct, net, inflow, outflow, firms} ],
  "emotion":        { date, zt_count, ... } | null,
  "turnover_top":   { stocks: [...], updated } | null,
  "updated":        "2026-08-14 15:00",
  "providers":      { "tencent": "ok", "eastmoney": "ok", "akshare": "degraded" }
}
```

后端实现（`app.py` 新增 `_market_overview_aggregate()`）：

- 用 `concurrent.futures.ThreadPoolExecutor` **并发**取 6 个子数据（indices / global_indices / sentiment / sectors / emotion / turnover_top）。
- 每个子数据独立走 `dataservice.get()`，**单个失败 → 该字段置 `null` + 标记降级，不抛 502**。
- `sentiment` 与 `sectors` 拆成两个独立 cache key（现在它们在 `get_overview()` 里共享一个 key，一个失败会连累另一个）。
- `market.py` 的 `get_overview()` / `get_short_term_emotion()` / `get_turnover_top()` / `get_global_indices()` 内部改走 `dataservice.get()`。

#### 3.1.3 前端 `MarketOverview.tsx` 改造

- `load()` 从 7 路请求 → **3 路**：
  1. `api.marketOverview()`（聚合，含全部实时层）
  2. `/api/morning-brief`（快照，独立，只在首次/手动刷新拉）
  3. `/api/market-monitor`（快照，独立）
- 删除 5 个实时层单独请求，改为从聚合结果解包。
- 10 个 K 线补丁请求合并为 **1 个批量 K 线调用**（新增 `GET /api/kline/batch?symbols=s:AG0,s:CU0,y:GC=F,...`，第 1 期末或第 2 期做，收益次要）。

#### 3.1.4 收益

- 请求数：17 → 3（实时层 1 + 快照层 2）。
- 慢数据不再阻塞快数据（后端并发 + 单源降级）。
- 降级有据可查（`providers` 字段，前端可显示「akshare 降级中」）。

---

### 第 2 期：自选股收编 + 行情节流

> 重要更正：自选股（近期关注 focus）**已经迁到后端了**（`focus.json` + GitHub 真源）。第 2 期实际工作是「清理残留 + 修 bug + 补节流」，不是从零迁移。

#### 3.2.1 清理死代码 + 修路由 bug

- `frontend/src/router.tsx`：删除第 26 行的重复 `/watchlist` 路由（保留重定向到 `/stock-pool`），或直接删除两行、让导航指向 `/stock-pool`。
- 删除 `frontend/src/pages/Watchlist.tsx`（死代码）。
- 删除 `frontend/src/hooks/useLiveQuotes.ts`（只被死代码引用）。
- `frontend/src/lib/watchlist.ts`：`loadWatch`/`saveWatch`/`addCodes` 保留 `addCodes`（代码解析工具），移除 localStorage 读写（见 3.2.2）。

#### 3.2.2 移除 localStorage 兜底，focus.json 为唯一真源

- `StockPool.tsx`：
  - 删除 `saveWatch(codes)`（第 141、147 行）和 `loadWatch()`（第 143 行）的 localStorage 读写。
  - focus 读写只走 `GET/POST /api/stock-pool/focus`。
  - 后端不可用时，focus 列表直接显示空 + 错误提示（不再静默回退 localStorage，避免双真源漂移）。
- `lib/watchlist.ts`：删除 `vr-watchlist` 的 localStorage 逻辑，只保留 `parseCodes`/`addCodes` 纯函数（供批量添加解析用）。
- 后端 `stock_pool.py` 的 `load_focus`/`save_focus` 已经是后端真源，无需改动。

> 说明：焦点从「localStorage vs 后端」收敛为「focus.json 唯一真源，GitHub backup 为异地备份」。这是你选择的「迁到后端」的实际形态——它已经在后端，本次是把它彻底做成唯一真源。

#### 3.2.3 `/api/quote` 短 TTL + 合并

- `app.py` 的 `/api/quote` 改为走 `dataservice.get(f"quote:{codes}", ttl=3, fetch=lambda: astock.tencent_quote(lst))`。
- 效果：自选股（focus 行情）、持仓页、个股页复用同一份 3 秒缓存；前端 3 秒轮询命中缓存时不再打腾讯；多标签页共享。

> 注意：腾讯 `qt.gtimg.cn` 一次可批量返回多只，`/api/quote` 的 cache key 应按「排序后的 codes 列表」归一化（避免 `600519,000858` 和 `000858,600519` 各打一次）。

#### 3.2.4 收益

- 自选股真源唯一化，清浏览器/换设备不再丢（已在后端）。
- 修复 `/watchlist` 重复路由 bug。
- 腾讯接口调用频率大幅下降（缓存 + 合并）。

---

### 第 3 期：稳定性可观测 + 配置收敛

#### 3.3.1 provider 健康检查

- `app.py` 新增 `GET /api/health/providers` → 返回 `dataservice.provider_health()`：
  ```json
  { "tencent": {"ok": true, "latency_ms": 120, "last_success": "..."},
    "eastmoney": {"ok": true, "latency_ms": 400, "degraded": false},
    "akshare": {"ok": false, "last_error": "No tables found", "degraded": true} }
  ```
- 前端加一个轻量「数据源状态」展示（可放 Settings 页或市场总览页角标），对应 ROADMAP 已计划的「数据源健康检查页」。

#### 3.3.2 配置收敛

把散落硬编码收进一个配置（`backend/config.py` 或环境变量）：
- 默认日期 `2026-08-14`（`app.py` 的 market-monitor / morning-brief 两处）
- `_EM_MIN_INTERVAL`（东财限流间隔）
- 各级 TTL（`live` / `minute`）
- `serve.sh` 里硬编码的 Python/Node 绝对路径 → 改为环境探测（`which python3` / `node`）

#### 3.3.3 akshare 统一降级为 provider

- 现有 `_ak_call` 重试（3 次退避）保留，但结果统一记入 `dataservice.record_provider("akshare", ...)`。
- `market.py` 的东财兜底逻辑保留，但「akshare 失败 → 东财」的切换状态写入 provider 健康，前端可见。

---

## 4. 风险与回滚

| 风险 | 缓解 |
|---|---|
| 聚合端点改动破坏现有 `/api/market/overview` 兼容 | 返回体**只增字段不改字段**，老前端仍可读原字段 |
| single-flight 实现出错导致请求永久阻塞 | fetch 异常也 `set()` 广播 + 设置超时上限 |
| 删除 localStorage 兜底后，后端偶发不可用导致 focus 显示空 | focus 读失败时明确报错提示（不再静默），并保留 `focus.json` 本地文件可手工恢复 |
| 删 Watchlist.tsx 影响未知引用 | 已确认只有 router.tsx 引用它（且是死路由），删除前再 grep 一次 |
| 腾讯 quote 缓存导致「3 秒内多次刷新看到旧价」 | TTL 3 秒与前端轮询周期一致，本就接受 3 秒粒度 |

回滚：每个阶段独立提交，单独可回退；第 1 期聚合端点可先加为 `/api/market/overview-v2`，验证后再切换前端。

---

## 5. 验收标准

1. 市场总览页加载时，浏览器 Network 面板请求数从 ~17 降到 ≤3（不含静态资源）。
2. 打开市场总览页，akshare 挂掉时页面其余数据（指数/成交额/短线情绪）仍正常显示，且有「降级」提示，不再整页报错。
3. `/api/health/providers` 能反映各数据源实时健康状态。
4. 自选股（近期关注）在无痕窗口/清 localStorage 后仍能读到（证明真源在后端）。
5. `/watchlist` 路由不再有重复定义告警；`Watchlist.tsx` / `useLiveQuotes.ts` 已移除且全项目无引用。
6. 自选股开实时行情（交易时段），连续 3 秒轮询时，腾讯接口实际请求频率明显低于轮询频率（缓存命中）。

---

## 附：涉及文件清单

**新增**
- `backend/dataservice.py` — 统一缓存/合并/健康

**后端修改**
- `backend/app.py` — 聚合端点、`/api/quote` 走缓存、`/api/health/providers`
- `backend/market.py` — 各 getter 改走 `dataservice.get`，sentiment/sectors 拆 cache key
- `backend/config.py`（可选）— 配置收敛

**前端修改**
- `frontend/src/pages/MarketOverview.tsx` — 聚合调用改造
- `frontend/src/pages/StockPool.tsx` — 移除 localStorage 兜底
- `frontend/src/lib/api.ts` — 新增聚合接口类型
- `frontend/src/lib/watchlist.ts` — 移除 localStorage，保留解析函数

**删除（死代码）**
- `frontend/src/pages/Watchlist.tsx`
- `frontend/src/hooks/useLiveQuotes.ts`
- `frontend/src/router.tsx` 第 26 行重复路由
