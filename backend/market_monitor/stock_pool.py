"""核心股票池 —— 池子定义（可编辑）+ payload builder + GitHub 真源同步。

数据流：
  data/stock-pool/pool.json         ← 池子定义（页面可增删，GitHub 真源的本地副本）
  data/market-monitor/stock-pool/*.csv ← 日更快照（行情数据）
  → build_stock_pool_payload()      → /api/stock-pool 返回 payload
  → sync_to_github()                → 增删后自动 push 到 vibe_research/data/stock-pool/pool.json
"""
from __future__ import annotations

import csv
import json
import os
import re
import threading
import urllib.request
from datetime import datetime
from pathlib import Path
from typing import Any

# 国内财经站直连 opener（绕过系统代理；qt.gtimg.cn 走代理会被 Clash CONNECT 掐掉）
# 注意：GitHub API 是国外域名，_push_github 仍走默认代理（直连反而更不稳）
_no_proxy_opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))

STOCK_FIELDS = (
    "instrument_id", "code", "exchange", "name", "industry", "price", "change",
    "change_5d", "change_20d", "ytd", "amount_yi", "mcap_yi", "turnover",
    "pe_ttm", "pb", "data_status",
)
LEADER_COUNT = 8
REPO = "wuxingyuenan5-lgtm/vibe_research"
GITHUB_PATH = "data/stock-pool/pool.json"
GITHUB_FOCUS_PATH = "data/stock-pool/focus.json"

BASE_DIR = Path(__file__).resolve().parent.parent
POOL_PATH = BASE_DIR / "data" / "stock-pool" / "pool.json"
FOCUS_PATH = BASE_DIR / "data" / "stock-pool" / "focus.json"
SNAPSHOT_DIR = BASE_DIR / "data" / "market-monitor" / "stock-pool"


def _read_csv(path: Path) -> list[dict[str, str]]:
    if not path.exists():
        return []
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def _num(value: Any) -> float | None:
    if value in (None, ""):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _str(value: Any) -> str | None:
    if value in (None, ""):
        return None
    return str(value)


# ---------------- 池子定义（可编辑） ----------------

def load_pool() -> dict:
    if POOL_PATH.exists():
        try:
            pool = json.loads(POOL_PATH.read_text(encoding="utf-8"))
            if isinstance(pool, dict) and isinstance(pool.get("stocks"), list):
                return pool
        except Exception:
            pass
    return {"pool_name": "核心股票池", "version": "", "count": 0, "stocks": []}


def save_pool(pool: dict) -> Path:
    POOL_PATH.parent.mkdir(parents=True, exist_ok=True)
    pool["count"] = len(pool.get("stocks", []))
    pool["updated_at"] = datetime.now().astimezone().isoformat(timespec="seconds")
    POOL_PATH.write_text(json.dumps(pool, ensure_ascii=False, indent=2), encoding="utf-8")
    return POOL_PATH


def add_stock(name: str, code: str | None = None, industry: str = "") -> dict:
    pool = load_pool()
    name = (name or "").strip()
    code = (code or "").strip() or None
    if not name:
        return {"ok": False, "error": "名称不能为空"}
    stocks = pool["stocks"]
    if any(s.get("name") == name for s in stocks):
        return {"ok": False, "error": f"「{name}」已在池中"}
    entry = {
        "instrument_id": code or f"legacy:{name}",
        "code": code,
        "exchange": None,
        "name": name,
        "industry": industry.strip() or "",
    }
    stocks.append(entry)
    save_pool(pool)
    _async_sync_github()
    return {"ok": True, "count": len(stocks)}


def lookup_name(code: str) -> str | None:
    """按证券代码从腾讯行情接口取名称（A 股 6 位 / 港股 5 位）。"""
    import re
    import urllib.request

    code = (code or "").strip()
    if not code:
        return None
    prefix = "hk" if len(code) == 5 else ("sh" if code.startswith(("6", "9")) else "sz")
    url = f"https://qt.gtimg.cn/q={prefix}{code}"
    try:
        with _no_proxy_opener.open(url, timeout=6) as r:
            raw = r.read().decode("gbk", errors="ignore")
        m = re.search(r'="\d+~([^~]+)~', raw)
        return m.group(1).strip() if m else None
    except Exception:  # noqa: BLE001
        return None


def add_stock_batch(codes: list[str]) -> dict:
    """批量添加：代码 → 行情接口补名称 → 入库（自动同步 GitHub）。"""
    pool = load_pool()
    added, failed, existing = [], [], []
    for code in codes:
        code = (code or "").strip()
        if not code:
            continue
        if any(s.get("code") == code for s in pool["stocks"]):
            existing.append(code)
            continue
        name = lookup_name(code)
        if not name:
            failed.append(code)
            continue
        pool["stocks"].append({
            "instrument_id": code, "code": code, "exchange": None,
            "name": name, "industry": "",
        })
        added.append(code)
    save_pool(pool)
    _async_sync_github()
    return {"ok": True, "added": added, "failed": failed, "existing": existing, "count": len(pool["stocks"])}


def remove_stock(instrument_id: str) -> dict:
    pool = load_pool()
    before = len(pool["stocks"])
    pool["stocks"] = [s for s in pool["stocks"] if s.get("instrument_id") != instrument_id]
    if len(pool["stocks"]) == before:
        return {"ok": False, "error": "未找到该标的"}
    save_pool(pool)
    _async_sync_github()
    return {"ok": True, "count": len(pool["stocks"])}


# ---------------- GitHub 真源同步 ----------------

def _github_token() -> str | None:
    creds = Path.home() / ".git-credentials"
    if creds.exists():
        line = creds.read_text(encoding="utf-8").strip()
        m = re.match(r"https://([^:]+):([^@]+)@", line)
        if m:
            return m.group(2)
    return os.environ.get("GITHUB_TOKEN")


def _push_github(github_path: str, content: str, message: str) -> dict:
    """把 content 推送到 GitHub 仓库的 github_path（存在则更新 sha，不存在则新建）。"""
    token = _github_token()
    if not token:
        return {"ok": False, "error": "未找到 GitHub 凭据"}
    import base64
    import urllib.request
    import urllib.error

    url = f"https://api.github.com/repos/{REPO}/contents/{github_path}"
    sha = None
    req = urllib.request.Request(url, headers={"Authorization": f"Bearer {token}", "Accept": "application/vnd.github+json"})
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            sha = json.loads(resp.read())["sha"]
    except urllib.error.HTTPError as e:
        if e.code != 404:
            return {"ok": False, "error": f"GitHub 读取失败: {e.code}"}
    body = {
        "message": message,
        "content": base64.b64encode(content.encode("utf-8")).decode("utf-8"),
    }
    if sha:
        body["sha"] = sha
    req = urllib.request.Request(
        url, data=json.dumps(body).encode("utf-8"), method="PUT",
        headers={"Authorization": f"Bearer {token}", "Accept": "application/vnd.github+json", "Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=20) as resp:
            result = json.loads(resp.read())
            return {"ok": True, "commit": result.get("commit", {}).get("sha", "")[:8]}
    except urllib.error.HTTPError as e:
        return {"ok": False, "error": f"GitHub 推送失败: {e.code} {e.read()[:200]!r}"}


def sync_to_github() -> dict:
    """把 pool.json 推送到 GitHub 真源（vibe_research/data/stock-pool/pool.json）。"""
    pool = load_pool()
    return _push_github(GITHUB_PATH, json.dumps(pool, ensure_ascii=False, indent=2), f"chore(data): 更新核心股票池 pool.json（{pool.get('count', 0)} 只）")


def _async_sync_github() -> None:
    """后台推送 pool.json 到 GitHub（不阻塞前端增删请求）。

    pool.json 是幂等全量状态：本次推送失败，下次任何写操作会再推一次，最终一致。
    失败只记录 backend/logs/github_sync.log，不打扰用户。
    """
    def _do() -> None:
        try:
            sync_to_github()
        except Exception as e:  # noqa: BLE001
            try:
                log_dir = BASE_DIR / "logs"
                log_dir.mkdir(exist_ok=True)
                with (log_dir / "github_sync.log").open("a", encoding="utf-8") as f:
                    f.write(f"{datetime.now().isoformat()} GitHub 同步失败: {e}\n")
            except Exception:
                pass

    threading.Thread(target=_do, daemon=True).start()


# ---------------- 近期关注（focus）独立存 GitHub ----------------

def load_focus() -> list[str]:
    """读近期关注代码列表（本地 focus.json 缓存；无则空）。"""
    if FOCUS_PATH.exists():
        try:
            data = json.loads(FOCUS_PATH.read_text(encoding="utf-8"))
            codes = data.get("codes", []) if isinstance(data, dict) else data
            return [str(c) for c in codes if c]
        except Exception:
            return []
    return []


def save_focus(codes: list[str], push: bool = True) -> dict:
    """保存近期关注列表到本地 focus.json（并可选同步 GitHub 真源）。独立于核心股票池 pool.json。"""
    clean = []
    for c in codes:
        c = str(c).strip()
        if c and c not in clean:
            clean.append(c)
    FOCUS_PATH.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "updated_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "count": len(clean),
        "codes": clean,
    }
    FOCUS_PATH.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    if push:
        return _push_github(GITHUB_FOCUS_PATH, json.dumps(payload, ensure_ascii=False, indent=2), f"chore(data): 更新近期关注 focus.json（{len(clean)} 只）")
    return {"ok": True, "count": len(clean)}


# ---------------- payload builder ----------------

def build_stock_pool_payload() -> dict[str, Any]:
    pool = load_pool()
    stocks_raw = _read_csv(SNAPSHOT_DIR / "stocks.csv")
    indices_raw = _read_csv(SNAPSHOT_DIR / "indices.csv")

    # 行情快照按 instrument_id / code 匹配
    quote_by_key: dict[str, dict[str, Any]] = {}
    for raw in stocks_raw:
        key = (raw.get("instrument_id") or "").strip() or (raw.get("code") or "").strip()
        if key:
            quote_by_key[key] = raw

    stocks: list[dict[str, Any]] = []
    for item in pool.get("stocks", []):
        iid = str(item.get("instrument_id") or "")
        code = str(item.get("code") or "").strip()
        raw = quote_by_key.get(iid) or (quote_by_key.get(code) if code else None) or {}
        row: dict[str, Any] = {
            "instrument_id": iid,
            "code": code or _str(raw.get("code")),
            "exchange": item.get("exchange") or _str(raw.get("exchange")),
            "name": item.get("name") or _str(raw.get("name")) or "",
            "industry": item.get("industry") or _str(raw.get("industry")) or "",
        }
        for field in ("price", "change", "change_5d", "change_20d", "ytd", "amount_yi",
                      "mcap_yi", "turnover", "pe_ttm", "pb"):
            row[field] = _num(raw.get(field))
        row["data_status"] = _str(raw.get("data_status")) or ("ok" if raw else "no_snapshot")
        stocks.append(row)

    indices: list[dict[str, Any]] = []
    for raw in indices_raw:
        row: dict[str, Any] = {"code": _str(raw.get("code")) or "", "name": _str(raw.get("name")) or ""}
        for field in ("price", "change", "change_5d", "change_20d", "change_60d", "ytd",
                      "amount_yi", "turnover", "pe_ttm", "pb", "mcap_yi"):
            row[field] = _num(raw.get(field))
        row["data_status"] = _str(raw.get("data_status")) or ""
        row["source"] = _str(raw.get("source")) or ""
        indices.append(row)

    changes = [s["change"] for s in stocks if s["change"] is not None]
    up = sum(1 for c in changes if c > 0)
    down = sum(1 for c in changes if c < 0)
    flat = sum(1 for c in changes if c == 0)
    sorted_changes = sorted(changes)
    n = len(sorted_changes)
    median = sorted_changes[n // 2] if n else None
    avg_change = sum(changes) / n if n else None
    total_amount = sum(s["amount_yi"] for s in stocks if s["amount_yi"] is not None)

    summary = {
        "tracked_count": len(stocks),
        "breadth": {"count": n, "up": up, "down": down, "flat": flat, "median": median},
        "avg_change": avg_change,
        "total_amount_yi": round(total_amount, 2),
        "pending_refresh": sum(1 for s in stocks if s["data_status"] == "no_snapshot"),
        "legacy_missing_code": sum(1 for s in stocks if not s.get("code")),
    }

    heatmap = [
        {"instrument_id": s["instrument_id"], "name": s["name"], "industry": s["industry"],
         "change": s["change"], "change_5d": s["change_5d"], "change_20d": s["change_20d"],
         "ytd": s["ytd"], "weight": s["mcap_yi"] or 1}
        for s in stocks if s["change"] is not None
    ]
    # 多周期最强 / 最弱：今日 + 5 日 + 20 日，分别按对应涨幅字段排序
    def _top(field: str, reverse: bool = True) -> list[dict[str, Any]]:
        rows = [s for s in stocks if isinstance(s.get(field), (int, float))]
        rows.sort(key=lambda s: s[field], reverse=reverse)
        return rows[:LEADER_COUNT]

    leaders_today_up = _top("change", True)
    leaders_today_down = list(reversed(_top("change", False)))
    leaders_5d_up = _top("change_5d", True)
    leaders_5d_down = list(reversed(_top("change_5d", False)))
    leaders_20d_up = _top("change_20d", True)
    leaders_20d_down = list(reversed(_top("change_20d", False)))

    return {
        "meta": {
            "report_date": pool.get("version") or datetime.now().astimezone().strftime("%Y-%m-%d"),
            "generated_at": datetime.now().astimezone().isoformat(timespec="seconds"),
            "version": "0.1.0",
            "percent_contract": "decimal_ratio",
            "pool": pool.get("pool_name", "核心股票池"),
        },
        "summary": summary,
        "stocks": stocks,
        "indices": indices,
        "heatmap": heatmap,
        "industry_ranking": indices,
        "leaders": {
            # 向后兼容：旧的「今日最强 / 最弱」扁平 key
            "up": leaders_today_up,
            "down": leaders_today_down,
            # 新结构：按周期分组
            "today": {"up": leaders_today_up, "down": leaders_today_down},
            "5d": {"up": leaders_5d_up, "down": leaders_5d_down},
            "20d": {"up": leaders_20d_up, "down": leaders_20d_down},
        },
        "default_index_selfselect": [i["code"] for i in indices if i["code"]],
    }
