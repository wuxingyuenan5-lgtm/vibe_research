"""宏观速览 + 重大要闻自动采集（AI 当日复盘数据源）。

- 中国宏观：akshare（CPI/PPI/PMI/M2/社融），倒序数据取最新一行，带统计期 + 发布日期
- 美国宏观：暂用静态快照（akshare 美宏观接口格式不稳定），由前端 macro_brief.ts 提供
- 重大要闻：财联社电报 + 东财全球快讯（当天实时，覆盖政策/央行/财政等全市场事件）

采集成本高（akshare 每次秒级），接口层做 30 分钟缓存。
"""
from __future__ import annotations

import os
import time

# 中国宏观：akshare 接口名 → {indicator 显示名, 最新行取值列, 统计期列, 发布日期规则}
_CN_MACRO = [
    # (接口, indicator, 取值列, 统计期列, 发布日文本, 说明)
    ("macro_china_cpi", "CPI 同比", "全国-同比增长", "月份", "8/9发布", "7月数据8/9发布"),
    ("macro_china_ppi", "PPI 同比", "当月同比增长", "月份", "8/9发布", "7月数据8/9发布"),
    ("macro_china_pmi", "制造业 PMI", "制造业-指数", "月份", "7/31发布", "7月数据7/31公布"),
    ("macro_china_money_supply", "M2 / M1 同比", None, "月份", "8/13发布", "7月末数据8/13发布"),
    ("macro_china_shrzgm", "社融增量", None, "月份", "8月中旬发布", "7月数据8月中旬发布"),
]

_CACHE_TTL = 1800  # 30 分钟缓存（采集有 akshare 秒级成本）
_cache: dict = {"t": 0.0, "data": None}


def _ak():
    try:
        import akshare as ak
        return ak
    except ImportError:
        return None


def _call(fn, tries: int = 2):
    last = None
    for i in range(tries):
        try:
            return fn()
        except Exception as e:  # noqa: BLE001
            last = e
            if i < tries - 1:
                time.sleep(0.8)
    if last is not None:
        raise last
    return None


def _cn_macro() -> list[dict]:
    """自动采集中国宏观（akshare 倒序数据取最新一行；失败单项跳过，不阻塞）。"""
    ak = _ak()
    if ak is None:
        return []
    out: list[dict] = []
    for (func_name, indicator, val_col, period_col, release, note) in _CN_MACRO:
        try:
            fn = getattr(ak, func_name)
            df = _call(fn)
            if df is None or len(df) == 0:
                continue
            # akshare 宏观多为倒序（最新在 index 0）；正序取末尾兜底
            row = df.iloc[0] if "月份" in df.columns and "2026" in str(df.iloc[0].get(period_col, "")) else df.iloc[-1]
            period = str(row.get(period_col, "")).strip() or "最近"
            if val_col:
                v = row.get(val_col)
                out.append({"indicator": indicator, "value": f"{v}", "period": period, "release": release, "note": note})
            else:
                # 特殊处理：M2 / 社融 多列取值
                if func_name == "macro_china_money_supply":
                    m2 = row.get("货币和准货币(M2)-同比增长")
                    m1 = row.get("货币(M1)-同比增长")
                    out.append({"indicator": indicator, "value": f"M2 {m2}%、M1 {m1}%", "period": period, "release": release, "note": note})
                elif func_name == "macro_china_shrzgm":
                    # 社会融资规模增量：取最新一行的增量列（列名不稳定，取数值列）
                    num_cols = [c for c in df.columns if c not in ("月份", "月份-同比", "月份-环比") and df[c].dtype in ("float64", "int64", "object")]
                    v = row.get(num_cols[0]) if num_cols else None
                    out.append({"indicator": indicator, "value": f"{v}", "period": period, "release": release, "note": note})
        except Exception as e:  # noqa: BLE001
            print(f"[macro_brief] {func_name} 采集失败: {e}")
            continue
    return out


_UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0 Safari/537.36"


def _wallstreetcn() -> list[dict]:
    """华尔街见闻 7x24 快讯（HTTP API，主源：专业媒体已做筛选，质量高）。"""
    import json as _json
    import re as _re
    import urllib.request

    url = "https://api-one.wallstcn.com/apiv1/content/lives?channel=global-channel&limit=40"
    req = urllib.request.Request(url, headers={"User-Agent": _UA})
    with urllib.request.urlopen(req, timeout=8) as r:
        data = _json.loads(r.read().decode("utf-8"))
    items = (data.get("data") or {}).get("items") or []
    out: list[dict] = []
    for it in items:
        html = it.get("content") or ""
        text = _re.sub(r"<[^>]+>", "", html).replace("&nbsp;", " ").strip()
        if not text:
            continue
        dt = it.get("display_time") or it.get("created_at") or ""
        try:
            dt = time.strftime("%Y-%m-%d %H:%M", time.localtime(int(dt) / 1000 if int(dt) > 1e12 else int(dt)))
        except Exception:  # noqa: BLE001
            dt = str(dt)
        out.append({"title": text[:60], "content": text, "time": dt, "source": "华尔街见闻"})
    return out


def _ak_headlines(ak) -> list[dict]:
    """akshare 快讯源（财联社/东财/富途/同花顺），统一字段。"""
    items: list[dict] = []
    for name, fn, title_col, content_col, time_col in (
        ("财联社", lambda: ak.stock_info_global_cls(), "标题", "内容", None),
        ("东财快讯", lambda: ak.stock_info_global_em(), "标题", "摘要", "发布时间"),
        ("富途快讯", lambda: ak.stock_info_global_futu(), "标题", "内容", "发布时间"),
        ("同花顺快讯", lambda: ak.stock_info_global_ths(), "标题", "内容", "发布时间"),
    ):
        try:
            df = _call(fn)
            if df is None or len(df) == 0:
                continue
            for _, r in df.head(40).iterrows():
                title = str(r.get(title_col, "") or "").strip()
                content = str(r.get(content_col, "") or "").strip()
                if not title and not content:
                    continue
                if time_col and time_col in df.columns:
                    t = str(r.get(time_col, "") or "").strip()
                else:  # 财联社：发布日期 + 发布时间 两列
                    t = f"{str(r.get('发布日期', '') or '').strip()} {str(r.get('发布时间', '') or '').strip()}".strip()
                items.append({"title": title or content[:60], "content": content, "time": t, "source": name})
        except Exception as e:  # noqa: BLE001
            print(f"[macro_brief] {name} 快讯失败: {e}")
            continue
    return items


def _headlines() -> list[dict]:
    """重大要闻：华尔街见闻（HTTP）+ 财联社/东财/富途/同花顺（akshare）多源合并，去重，政策/宏观/地缘优先。"""
    items: list[dict] = []
    try:
        items += _wallstreetcn()
    except Exception as e:  # noqa: BLE001
        print(f"[macro_brief] 华尔街见闻失败: {e}")
    ak = _ak()
    if ak is not None:
        items += _ak_headlines(ak)

    # 去重：跨源标题归一化（去【】、来源名、标点空白）后比对
    import re as _re
    def _norm(s: str) -> str:
        s = _re.sub(r"^【[^】]*】", "", s)          # 去【财联社】类前缀
        s = _re.sub(r"(财联社|华尔街见闻|金十数据|富途|同花顺|东方财富|快讯|电|讯)$", "", s)
        return _re.sub(r"[^\w\u4e00-\u9fff]", "", s)[:40]
    KEY = ("央行", "财政部", "证监会", "国务院", "发改委", "利率", "降准", "降息", "回购", "LPR", "货币政策",
           "国债", "专项债", "发布会", "政治局", "关税", "CPI", "PPI", "PMI", "社融", "美联储", "FOMC", "GDP",
           "伊朗", "胡塞", "地缘", "制裁", "战争", "冲突", "原油", "油价", "OPEC", "中东",
           "选举", "中期选举", "支持率", "特朗普", "贝森特", "沃什", "鲍威尔",
           "财报", "净利", "营收", "盈利", "收益率", "通胀", "就业", "非农", "黄金", "比特币",
           "汇率", "人民币", "美元", "外资", "北向")
    seen: set[str] = set()
    uniq: list[dict] = []
    for it in items:
        t = it["title"]
        if not t:
            continue
        key = _norm(t)
        if key in seen:
            continue
        seen.add(key)
        uniq.append(it)
    uniq.sort(key=lambda x: (any(k in x["title"] for k in KEY), x["time"]), reverse=True)
    return uniq[:20]


def get_macro_brief(force: bool = False) -> dict:
    """返回 { china: [...], headlines: [...], fetched_at }；30 分钟缓存。"""
    now = time.time()
    if not force and _cache["data"] and now - _cache["t"] < _CACHE_TTL:
        return _cache["data"]
    data = {
        "china": _cn_macro(),
        "headlines": _headlines(),
        "fetched_at": time.strftime("%Y-%m-%d %H:%M"),
    }
    _cache.update(t=now, data=data)
    return data
