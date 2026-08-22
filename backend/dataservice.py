"""统一数据服务层：TTL 缓存 + single-flight 请求合并 + provider 健康状态。

收编 app.py / market.py 里散落的缓存字典，提供三件事：

1. get(key, ttl, fetch, valid, provider)
   统一缓存读取：命中且未过期直接返回；未命中则「同 key 并发只 fetch 一次」，
   其余线程等同一结果（single-flight），避免多标签页 / 重复刷新打爆上游。

2. record_provider / provider_health
   每次上游调用记录健康状态（ok / 耗时 / 最近错误 / 是否降级），
   供 `/api/health/providers` 与聚合响应的 `providers` 字段使用。

3. TTL 分级预设
   live=3s（实时行情）、minute=60s（情绪/资金/成交额等分钟级）。

约束：本模块是**进程内**缓存（uvicorn 单 worker），不跨进程共享；
单 worker 部署下足够，若将来多 worker 需换共享缓存。
"""
from __future__ import annotations

import threading
import time
from typing import Any, Callable

# ---------------------------------------------------------------------------
# TTL 分级预设（秒）
# ---------------------------------------------------------------------------
TTL = {
    "live": 3,       # 实时行情：指数 / 个股 quote / 全球指数
    "minute": 60,    # 分钟级：市场情绪 / 板块资金 / 短线情绪 / 成交额榜
}

# ---------------------------------------------------------------------------
# provider 健康状态
# ---------------------------------------------------------------------------
_PROVIDERS: dict[str, dict] = {}
_PROV_LOCK = threading.Lock()


def record_provider(name: str, ok: bool, latency_ms: float = 0.0, error: str | None = None) -> None:
    """记录一次上游调用结果。name 用上游名（tencent / eastmoney / akshare）。"""
    with _PROV_LOCK:
        p = _PROVIDERS.setdefault(name, {})
        p["ok"] = ok
        if ok:
            p["latency_ms"] = round(latency_ms, 1)
            p["last_success"] = time.time()
            p["degraded"] = False
        else:
            p["last_error"] = error
            p["last_fail"] = time.time()
            p["degraded"] = True


def provider_health() -> dict:
    """返回当前各 provider 健康快照（浅拷贝，避免外部改内部状态）。"""
    with _PROV_LOCK:
        return {k: dict(v) for k, v in _PROVIDERS.items()}


# ---------------------------------------------------------------------------
# TTL 缓存 + single-flight
# ---------------------------------------------------------------------------
_CACHE: dict[str, tuple[float, Any]] = {}   # key -> (expire_ts, value)
_FLIGHTS: dict[str, "_Flight"] = {}          # key -> 正在进行的 fetch
_LOCK = threading.Lock()


class _Flight:
    """一次 in-flight 请求的共享载体。owner 线程 fetch，waiter 线程等 event。"""

    __slots__ = ("event", "value", "error")

    def __init__(self) -> None:
        self.event = threading.Event()
        self.value: Any = None
        self.error: Exception | None = None


def get(
    key: str,
    ttl: float | None,
    fetch: Callable[[], Any],
    valid: Callable[[Any], bool] = bool,
    provider: str | None = None,
) -> Any:
    """统一缓存读取。

    参数：
      key      —— 缓存键（建议带命名空间，如 "market:sentiment"）
      ttl      —— 缓存秒数；None 表示不缓存（每次现取，但仍走 single-flight 去重）
      fetch    —— 拉数据的函数
      valid    —— 结果有效性判定；False（空结果）不缓存，下次请求直接重试
      provider —— 上游名，用于健康记录；None 则不记录

    行为：
      - 命中且未过期 → 返回缓存
      - 未命中 → 同 key 并发只 fetch 一次，其余线程等同一结果
      - fetch 成功且 valid → 写缓存；fetch 失败 → 抛异常（由调用方降级），并记录 provider 失败
    """
    now = time.time()

    # 1) 缓存命中
    if ttl is not None:
        with _LOCK:
            hit = _CACHE.get(key)
            if hit and now < hit[0]:
                return hit[1]

    # 2) single-flight 注册：同 key 只有一个 owner
    with _LOCK:
        flight = _FLIGHTS.get(key)
        if flight is None:
            flight = _Flight()
            _FLIGHTS[key] = flight
            owner = True
        else:
            owner = False

    if owner:
        # 3) owner 执行 fetch，广播结果
        try:
            start = time.time()
            try:
                val = fetch()
            except Exception as e:  # noqa: BLE001 —— 上游错误五花八门，统一转抛
                flight.error = e
                if provider:
                    record_provider(provider, False, error=str(e))
                raise
            else:
                flight.value = val
                if provider:
                    record_provider(provider, True, latency_ms=(time.time() - start) * 1000)
                if ttl is not None and valid(val):
                    with _LOCK:
                        _CACHE[key] = (time.time() + ttl, val)
                return val
        finally:
            flight.event.set()
            with _LOCK:
                _FLIGHTS.pop(key, None)
    else:
        # 4) waiter 等 owner 完成（60s 兜底：上游请求均有 10-15s 超时，足够）
        flight.event.wait(timeout=60)
        if flight.error is not None:
            raise flight.error
        return flight.value


def invalidate(key: str) -> None:
    """主动清掉某 key 的缓存（下次请求强制重取）。"""
    with _LOCK:
        _CACHE.pop(key, None)


def clear() -> None:
    """清空全部缓存（测试 / 运维用）。"""
    with _LOCK:
        _CACHE.clear()
