"""核心股票池 —— 本地池子定义 + 日更行情缓存 + GitHub 备份同步。

数据流：
  data/stock-pool/pool.json         ← 池子定义（核心股票池 + 近期关注 + 研究篮子）
  data/stock-pool/stocks.csv        ← 日更快照（行情数据）
  → build_stock_pool_payload()      → /api/stock-pool 返回 payload
  → sync_to_github()                → 本地增删后同步备份到 GitHub
"""
from __future__ import annotations

import csv
import json
import os
import re
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

BASE_DIR = Path(__file__).resolve().parent.parent
PROJECT_ROOT = BASE_DIR.parent
# 股票池定义、日度母表和最新快照只保留在仓库根 data/stock-pool。
# backend/data 下的旧副本不再参与读取或生产。
POOL_PATH = PROJECT_ROOT / "data" / "stock-pool" / "pool.json"
LEGACY_FOCUS_PATH = PROJECT_ROOT / "data" / "stock-pool" / "focus.json"
SNAPSHOT_DIR = PROJECT_ROOT / "data" / "stock-pool"
DEFINITION_STOCK_FIELDS = ("instrument_id", "code", "exchange", "name", "industry")

DEFAULT_RESEARCH_BASKETS = (
    {"key": "ai_semiconductor", "name": "AI算力/半导体", "codes": [
        "00981", "01347", "688012", "688041", "688256", "603986", "688008", "600584",
        "002156", "300373", "688234", "300666", "688037", "300604", "688372", "688820",
        "688825", "688521", "688141", "688048", "300857", "688702", "688146", "600330",
    ]},
    {"key": "ai_pcb_optical", "name": "AI PCB/光通信", "codes": [
        "300476", "002916", "002463", "600183", "688183", "002384", "01888", "300903",
        "301377", "688300", "301217", "300308", "300502", "300394", "002281", "300620",
        "688313", "688143", "300548", "601869", "600487", "688498", "688502", "002484",
        "300408",
    ]},
    {"key": "robotics_datacenter", "name": "机器人/自动化/数据中心", "codes": [
        "601689", "002050", "688017", "09880", "09660", "601100", "688777", "002851",
        "002008", "301200", "688025", "603308", "301018", "002837", "688630", "300757",
        "300776", "300870", "688808", "600875",
    ]},
    {"key": "resources_cycle", "name": "资源品/黄金/周期", "codes": [
        "601899", "600988", "000426", "603993", "601168", "000807", "600549", "000657",
        "600301", "002428", "000688", "001203", "603799", "600938", "601225", "600188",
        "600309", "002648", "600346", "600989", "600141", "000893", "600160", "605376",
    ]},
    {"key": "innovative_drug", "name": "创新药/CXO/AI医疗", "codes": [
        "600276", "06160", "01801", "09926", "06990", "603259", "02269", "02268", "02228",
    ]},
    {"key": "new_energy", "name": "新能源", "codes": [
        "300750", "300274", "600438", "600732", "605117", "002709", "301358", "688778",
        "300450", "300776", "002487", "301511", "688676",
    ]},
    {"key": "consumer_internet", "name": "消费/互联网/出海", "codes": [
        "600519", "000333", "600690", "00700", "09988", "01810", "02020", "09992",
        "605499", "300866", "689009", "02015", "01364", "301498", "002832", "688775", "300209",
    ]},
    {"key": "core_assets", "name": "金融/红利/核心资产", "codes": [
        "601398", "601318", "601336", "601628", "600030", "300059", "600941", "600900",
        "600031", "000338", "600066", "600233", "601058", "002714",
    ]},
)


def _read_csv(path: Path) -> list[dict[str, str]]:
    if not path.exists():
        return []
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def _snapshot_date(path: Path) -> str:
    """行情缓存的日期来自文件写入时间，不复用池子定义版本。"""
    if not path.exists():
        return ""
    return datetime.fromtimestamp(path.stat().st_mtime).astimezone().strftime("%Y-%m-%d")


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


def _clean_codes(codes: Any) -> list[str]:
    clean: list[str] = []
    for code in codes or []:
        value = str(code or "").strip()
        if value and value not in clean:
            clean.append(value)
    return clean


def _load_legacy_focus_codes() -> list[str]:
    if not LEGACY_FOCUS_PATH.exists():
        return []
    try:
        data = json.loads(LEGACY_FOCUS_PATH.read_text(encoding="utf-8"))
    except Exception:
        return []
    return _clean_codes(data.get("codes", []) if isinstance(data, dict) else data)


def _clean_stock_definition(raw: dict[str, Any]) -> dict[str, Any]:
    item = {
        "instrument_id": str(raw.get("instrument_id") or "").strip() or str(raw.get("code") or "").strip(),
        "code": str(raw.get("code") or "").strip() or None,
        "exchange": _str(raw.get("exchange")),
        "name": str(raw.get("name") or "").strip(),
        "industry": str(raw.get("industry") or "").strip(),
    }
    if not item["instrument_id"] and item["name"]:
        item["instrument_id"] = f"legacy:{item['name']}"
    return item


def _default_research_baskets(valid_codes: set[str]) -> list[dict[str, Any]]:
    return [
        {
            "key": item["key"],
            "name": item["name"],
            "codes": [code for code in item["codes"] if code in valid_codes],
        }
        for item in DEFAULT_RESEARCH_BASKETS
    ]


def _normalize_research_baskets(raw: Any, valid_codes: set[str]) -> list[dict[str, Any]]:
    if not isinstance(raw, list) or not raw:
        return _default_research_baskets(valid_codes)
    baskets: list[dict[str, Any]] = []
    for index, item in enumerate(raw):
        if not isinstance(item, dict):
            continue
        name = str(item.get("name") or "").strip()
        if not name:
            continue
        key = str(item.get("key") or f"basket_{index + 1}").strip()
        codes = [code for code in _clean_codes(item.get("codes")) if code in valid_codes]
        baskets.append({"key": key, "name": name, "codes": codes})
    return baskets or _default_research_baskets(valid_codes)


def _normalize_pool(raw_pool: dict[str, Any] | None) -> dict[str, Any]:
    raw_pool = raw_pool if isinstance(raw_pool, dict) else {}
    stocks_raw = raw_pool.get("stocks") if isinstance(raw_pool.get("stocks"), list) else []
    stocks: list[dict[str, Any]] = []
    seen_ids: set[str] = set()
    for item in stocks_raw:
        if not isinstance(item, dict):
            continue
        cleaned = _clean_stock_definition(item)
        if not cleaned["name"] or not cleaned["instrument_id"] or cleaned["instrument_id"] in seen_ids:
            continue
        seen_ids.add(cleaned["instrument_id"])
        stocks.append(cleaned)
    valid_codes = {str(item.get("code") or "").strip() for item in stocks if str(item.get("code") or "").strip()}
    focus_raw = raw_pool.get("focus")
    focus_codes = _clean_codes((focus_raw or {}).get("codes") if isinstance(focus_raw, dict) else focus_raw)
    if not focus_codes:
        focus_codes = _load_legacy_focus_codes()
    return {
        "pool_name": str(raw_pool.get("pool_name") or "核心股票池").strip() or "核心股票池",
        "version": str(raw_pool.get("version") or "").strip(),
        "count": len(stocks),
        "focus": {
            "updated_at": str((focus_raw or {}).get("updated_at") or raw_pool.get("updated_at") or "").strip(),
            "codes": focus_codes,
        },
        "research_baskets": _normalize_research_baskets(raw_pool.get("research_baskets"), valid_codes),
        "stocks": stocks,
        "updated_at": str(raw_pool.get("updated_at") or "").strip(),
    }


# ---------------- 池子定义（可编辑） ----------------

def load_pool() -> dict:
    if POOL_PATH.exists():
        try:
            pool = json.loads(POOL_PATH.read_text(encoding="utf-8"))
            return _normalize_pool(pool)
        except Exception:
            pass
    return _normalize_pool({"pool_name": "核心股票池", "version": "", "count": 0, "stocks": []})


def save_pool(pool: dict) -> Path:
    pool = _normalize_pool(pool)
    POOL_PATH.parent.mkdir(parents=True, exist_ok=True)
    pool["count"] = len(pool.get("stocks", []))
    pool["updated_at"] = datetime.now().astimezone().isoformat(timespec="seconds")
    focus = pool.get("focus") if isinstance(pool.get("focus"), dict) else {}
    pool["focus"] = {
        "updated_at": str(focus.get("updated_at") or pool["updated_at"]),
        "codes": _clean_codes(focus.get("codes")),
    }
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
    sync = sync_to_github()
    if not sync.get("ok"):
        return {"ok": False, "error": f"本地已保存，但 GitHub 备份失败：{sync.get('error', '未知错误')}"}
    return {"ok": True, "count": len(stocks), "commit": sync.get("commit")}


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
    sync = sync_to_github()
    if not sync.get("ok"):
        return {"ok": False, "error": f"本地已保存，但 GitHub 备份失败：{sync.get('error', '未知错误')}"}
    return {
        "ok": True, "added": added, "failed": failed, "existing": existing,
        "count": len(pool["stocks"]), "commit": sync.get("commit"),
    }


def remove_stock(instrument_id: str) -> dict:
    pool = load_pool()
    before = len(pool["stocks"])
    removed_codes = [str(s.get("code") or "").strip() for s in pool["stocks"] if s.get("instrument_id") == instrument_id]
    pool["stocks"] = [s for s in pool["stocks"] if s.get("instrument_id") != instrument_id]
    if len(pool["stocks"]) == before:
        return {"ok": False, "error": "未找到该标的"}
    removed_set = {code for code in removed_codes if code}
    if removed_set:
        focus = pool.get("focus") if isinstance(pool.get("focus"), dict) else {}
        focus["codes"] = [code for code in _clean_codes(focus.get("codes")) if code not in removed_set]
        pool["focus"] = focus
        baskets = []
        for basket in pool.get("research_baskets", []):
            if not isinstance(basket, dict):
                continue
            current = dict(basket)
            current["codes"] = [code for code in _clean_codes(current.get("codes")) if code not in removed_set]
            baskets.append(current)
        pool["research_baskets"] = baskets
    save_pool(pool)
    sync = sync_to_github()
    if not sync.get("ok"):
        return {"ok": False, "error": f"本地已保存，但 GitHub 备份失败：{sync.get('error', '未知错误')}"}
    return {"ok": True, "count": len(pool["stocks"]), "commit": sync.get("commit")}


# ---------------- GitHub 备份同步 ----------------

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
    """把本地 pool.json 同步备份到 GitHub。"""
    pool = load_pool()
    return _push_github(GITHUB_PATH, json.dumps(pool, ensure_ascii=False, indent=2), f"chore(data): 更新核心股票池 pool.json（{pool.get('count', 0)} 只）")


# ---------------- 近期关注（focus）并入 pool.json ----------------

def load_focus() -> list[str]:
    """读近期关注代码列表（现存于 pool.json；若还没迁移则回退 legacy focus.json）。"""
    pool = load_pool()
    focus = pool.get("focus") if isinstance(pool.get("focus"), dict) else {}
    codes = _clean_codes(focus.get("codes"))
    return codes or _load_legacy_focus_codes()


def save_focus(codes: list[str], push: bool = True) -> dict:
    """保存近期关注列表到 pool.json；focus 属于定义层，不属于日更行情缓存。"""
    clean = _clean_codes(codes)
    pool = load_pool()
    pool["focus"] = {
        "updated_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "codes": clean,
    }
    save_pool(pool)
    if push:
        return sync_to_github()
    return {"ok": True, "count": len(clean)}


# ---------------- payload builder ----------------

def build_stock_pool_payload() -> dict[str, Any]:
    pool = load_pool()
    stocks_raw = _read_csv(SNAPSHOT_DIR / "stocks.csv")
    indices_raw = _read_csv(SNAPSHOT_DIR / "indices.csv")
    focus = pool.get("focus") if isinstance(pool.get("focus"), dict) else {}
    focus_codes = _clean_codes(focus.get("codes"))
    research_baskets = pool.get("research_baskets") if isinstance(pool.get("research_baskets"), list) else []
    basket_names_by_code: dict[str, list[str]] = {}
    for basket in research_baskets:
        if not isinstance(basket, dict):
            continue
        basket_name = str(basket.get("name") or "").strip()
        if not basket_name:
            continue
        for code in _clean_codes(basket.get("codes")):
            names = basket_names_by_code.setdefault(code, [])
            if basket_name not in names:
                names.append(basket_name)

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
            "research_baskets": basket_names_by_code.get(code, []) if code else [],
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
            "report_date": _snapshot_date(SNAPSHOT_DIR / "stocks.csv"),
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
        "definitions": {
            "focus_codes": focus_codes,
            "research_baskets": [
                {
                    "key": str(item.get("key") or ""),
                    "name": str(item.get("name") or ""),
                    "codes": _clean_codes(item.get("codes")),
                    "count": len(_clean_codes(item.get("codes"))),
                }
                for item in research_baskets
                if isinstance(item, dict) and str(item.get("name") or "").strip()
            ],
        },
        "default_index_selfselect": [i["code"] for i in indices if i["code"]],
    }
