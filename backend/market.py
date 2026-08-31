from __future__ import annotations

import time
from collections import Counter
from datetime import datetime, timezone, timedelta

import astock
import gstock
from dataservice import TTL, get as _ds_get, record_provider

BEIJING = timezone(timedelta(hours=8))


def _num(v) -> int:
    try:
        return int(float(v))
    except (ValueError, TypeError):
        return 0


def _sentiment_breadth_speculation(up: int, down: int, zt_real: int) -> tuple[str, str]:
    """市场宽度 / 题材投机分档（客观数据机械分档，与前端弹窗口径一致）。"""
    r = up / max(down, 1)
    if up < 600:
        breadth = "冰点"
    elif r < 0.7:
        breadth = "偏弱"
    elif r < 1.2:
        breadth = "中性"
    elif r < 2.5:
        breadth = "偏强"
    else:
        breadth = "普涨"
    speculation = "亢奋" if zt_real >= 100 else "活跃" if zt_real >= 60 else "普通" if zt_real >= 30 else "冰点"
    return breadth, speculation


def _sentiment_fallback() -> dict:
    """akshare（乐咕乐股）不可达时的东财备用源：涨跌家数（ulist f104/f105/f106）+ 涨跌停家数（复用涨停池）。

    乐咕乐股页面偶发反爬/空表（No tables found），且 launchd/守护环境直连可能持续失败；
    东财 push2 在国内网络普遍可达，作为兜底保证「市场情绪」不空。
    """
    import json  # noqa: PLC0415
    import urllib.request  # noqa: PLC0415
    try:
        url = "https://push2delay.eastmoney.com/api/qt/ulist.np/get?fltt=2&secids=1.000001,0.399001&fields=f104,f105,f106"
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0", "Referer": "https://quote.eastmoney.com/"})
        # 国内财经站直连（绕系统/WorkBuddy 代理）；push2 常被掐断，用 push2delay 延迟行情兜底
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        d = json.loads(opener.open(req, timeout=8).read().decode("utf-8"))
        diffs = (d.get("data") or {}).get("diff") or []
        up = sum(int(x.get("f104") or 0) for x in diffs)
        down = sum(int(x.get("f105") or 0) for x in diffs)
        flat = sum(int(x.get("f106") or 0) for x in diffs)
        if not (up or down):
            record_provider("eastmoney", False, error="涨跌家数为空")
            return {}
        # 涨跌停家数：复用东财涨停池（emotion 同源，守护环境下同样可达）
        zt = dt = zt_real = dt_real = 0
        try:
            emo = get_short_term_emotion()
            zt = int(emo.get("zt_count") or 0)
            dt = int(emo.get("dt_count") or 0)
            zt_real = zt
            dt_real = dt
        except Exception:  # noqa: BLE001
            pass
        breadth, speculation = _sentiment_breadth_speculation(up, down, zt_real)
        record_provider("eastmoney", True)
        return {
            "up": up, "down": down, "flat": flat,
            "zt": zt, "zt_real": zt_real, "dt": dt, "dt_real": dt_real,
            "active": "",
            "breadth": breadth, "speculation": speculation,
            "date": datetime.now(BEIJING).strftime("%Y-%m-%d"),
        }
    except Exception as e:  # noqa: BLE001
        record_provider("eastmoney", False, error=str(e))
        return {}


def _sentiment() -> dict:
    """市场情绪：涨跌家数/涨停跌停/活跃度 + 大盘宽度、题材投机（客观数据机械分档）。

    数据源：akshare 乐咕乐股（全量字段）→ 失败时降级东财（涨跌家数 + 涨停池计数）。
    """
    start = time.time()
    try:
        ak = astock._akshare()
        df = None
        for _ in range(3):  # 乐咕乐股接口间歇性 "No tables found"（~25%），重试提高成功率
            try:
                df = ak.stock_market_activity_legu()
                break
            except Exception:
                time.sleep(0.8)
        if df is None or len(df) == 0:
            record_provider("akshare", False, error="乐咕乐股空表/持续失败")
            return _sentiment_fallback()  # 乐咕乐股持续失败 → 东财兜底
        d = {row["item"]: row["value"] for _, row in df.iterrows()}
    except Exception as e:  # noqa: BLE001
        record_provider("akshare", False, error=str(e))
        return _sentiment_fallback()
    record_provider("akshare", True, latency_ms=(time.time() - start) * 1000)
    up, down, flat = _num(d.get("上涨")), _num(d.get("下跌")), _num(d.get("平盘"))
    zt, zt_real = _num(d.get("涨停")), _num(d.get("真实涨停"))
    dt, dt_real = _num(d.get("跌停")), _num(d.get("真实跌停"))
    breadth, speculation = _sentiment_breadth_speculation(up, down, zt_real)
    return {
        "up": up, "down": down, "flat": flat,
        "zt": zt, "zt_real": zt_real, "dt": dt, "dt_real": dt_real,
        "active": str(d.get("活跃度", "")),
        "breadth": breadth, "speculation": speculation,
        "date": str(d.get("统计日期", "")),
    }


def _sectors_fallback() -> list[dict]:
    """akshare 行业资金流失败时的东财 push2delay 直连兜底。"""
    import json  # noqa: PLC0415
    import urllib.request  # noqa: PLC0415
    try:
        url = ("https://push2delay.eastmoney.com/api/qt/clist/get?pn=1&pz=50&po=1&np=1&fltt=2&invt=2"
               "&fid=f62&fs=m:90+t:2&fields=f12,f14,f3,f62,f104,f105,f106")
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0", "Referer": "https://quote.eastmoney.com/"})
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        d = json.loads(opener.open(req, timeout=8).read().decode("utf-8"))
        diffs = (d.get("data") or {}).get("diff") or []
        out = []
        for x in diffs:
            net = float(x.get("f62") or 0)
            if net == 0:
                continue
            out.append({
                "name": str(x.get("f14") or ""),
                "pct": round(float(x.get("f3") or 0), 2),
                "net": round(net / 1e8, 2),
                "inflow": round(max(net, 0) / 1e8, 2),
                "outflow": round(-min(net, 0) / 1e8, 2),
                "firms": int(x.get("f104") or 0) + int(x.get("f105") or 0) + int(x.get("f106") or 0),
            })
        record_provider("eastmoney", True)
        return out
    except Exception as e:  # noqa: BLE001
        record_provider("eastmoney", False, error=str(e))
        return []


def _sectors() -> list[dict]:
    """行业资金流（按净额降序）。不含领涨股等个股字段。"""
    start = time.time()
    try:
        f = astock._akshare().stock_fund_flow_industry(symbol="即时")
        f = f.sort_values("净额", ascending=False)
    except Exception as e:  # noqa: BLE001
        record_provider("akshare", False, error=str(e))
        return _sectors_fallback()
    record_provider("akshare", True, latency_ms=(time.time() - start) * 1000)
    out = []
    for _, row in f.iterrows():
        net = float(row.get("净额", 0) or 0)
        inflow = float(row.get("流入资金", 0) or 0)
        outflow = float(row.get("流出资金", 0) or 0)
        out.append({
            "name": str(row["行业"]),
            "pct": round(float(row.get("行业-涨跌幅", 0) or 0), 2),
            "net": round(net / 1e8, 2),
            "inflow": round(inflow / 1e8, 2),
            "outflow": round(outflow / 1e8, 2),
            "firms": _num(row.get("公司家数")),
        })
    return out


def get_sentiment() -> dict:
    """市场情绪（独立缓存；akshare 主源 + 东财兜底）。空结果不缓存。
    provider 健康由 _sentiment 内部精确记录（akshare 失败会记 akshare=degraded + eastmoney 兜底）。"""
    return _ds_get("market:sentiment", TTL["minute"], _sentiment, valid=bool)


def get_sectors() -> list[dict]:
    """板块资金流（独立缓存；akshare 主源 + 东财兜底）。空结果不缓存。
    provider 健康由 _sectors 内部精确记录。"""
    return _ds_get("market:sectors", TTL["minute"], _sectors, valid=bool)


def get_a_indices() -> list[dict]:
    """A股大盘指数实时行情（短 TTL，秒级）。空结果不缓存。"""
    return _ds_get("market:a_indices", TTL["live"], astock.index_quote, valid=bool, provider="tencent")


def get_overview() -> dict:
    """市场情绪 + 板块资金（兼容旧接口：两个独立缓存各自降级，不再一荣俱荣一损俱损）。"""
    return {
        "sentiment": get_sentiment(),
        "sectors": get_sectors(),
        "updated": datetime.now(BEIJING).strftime("%Y-%m-%d %H:%M"),
    }


def _emotion() -> dict:
    """短线情绪（聚合口径，**零个股名**）：连板梯队 / 最高连板 / 炸板率 / 封板率 / 晋级率 / 涨跌停家数。

    数据源＝东财涨停板四池（push2ex）。只把池子聚合成计数与比率，
    **不输出任何个股 code/name**——守产品「零标的」红线（个股清单是甩名单，不做）。
    """
    # 定位最近交易日：从今天往前回溯，第一日有涨停池即取（非交易日/盘前返空则继续回溯）。
    today = datetime.now(BEIJING).date()
    resolved, zt = "", []
    for back in range(8):
        d = (today - timedelta(days=back)).strftime("%Y%m%d")
        zt = astock.em_zt_topic_pool("getTopicZTPool", d, "fbt:asc")
        if zt:
            resolved = d
            break
    if not resolved:
        return {}

    zb = astock.em_zt_topic_pool("getTopicZBPool", resolved, "fbt:asc")    # 炸板池
    dt = astock.em_zt_topic_pool("getTopicDTPool", resolved, "fund:asc")   # 跌停池
    yzt = astock.em_zt_topic_pool("getYesterdayZTPool", resolved, "zs:desc")  # 昨涨停池

    boards = [_num(p.get("lbc")) or 1 for p in zt]      # 每只连板数（缺省按 1 板）
    lianban = [b for b in boards if b >= 2]             # 2 板及以上（连板）
    # 连板梯队：2/3/4/5+ 各多少家（5 代表 5 板及以上），只保留有家数的档
    tiers = Counter(min(b, 5) for b in lianban)
    ladder = [{"boards": b, "count": tiers[b], "plus": b >= 5} for b in sorted(tiers)]

    # 连板股清单（2 板+，客观公开榜单数据；按连板数、成交额降序）。
    # 产品定位调整（2026-07-05）：从「零标的」→「展示客观榜单但不推荐/不预测/不评分」。
    lianban_stocks = sorted(
        ({
            "code": str(p.get("c", "")), "name": p.get("n", ""),
            "boards": _num(p.get("lbc")) or 1,
            "price": round((astock._numf(p.get("p")) or 0) / 1000, 2),
            "pct": round(astock._numf(p.get("zdp")) or 0, 2),
            "amount": astock._numf(p.get("amount")),      # 成交额,元（'-' 占位归一为 None，防排序对 str 取负崩溃）
            "float_cap": astock._numf(p.get("ltsz")),     # 流通市值,元
            "industry": p.get("hybk", ""),  # 概念/行业
        } for p in zt if (_num(p.get("lbc")) or 1) >= 2),
        key=lambda x: (-x["boards"], -(x["amount"] or 0)),
    )

    zt_count, zb_count, yzt_count = len(zt), len(zb), len(yzt)
    attempts = zt_count + zb_count                       # 尝试涨停 = 封住 + 炸板
    seal_rate = round(zt_count / attempts, 3) if attempts else None      # 封板率
    break_rate = round(zb_count / attempts, 3) if attempts else None     # 炸板率
    # 晋级率＝今日 2 板+（＝昨涨停今又停）÷ 昨日涨停家数
    promotion_rate = round(len(lianban) / yzt_count, 3) if yzt_count else None

    return {
        "date": f"{resolved[:4]}-{resolved[4:6]}-{resolved[6:]}",
        "zt_count": zt_count,
        "dt_count": len(dt),
        "zb_count": zb_count,
        "max_boards": max(boards) if boards else 0,
        "lianban_count": len(lianban),
        "ladder": ladder,
        "lianban_stocks": lianban_stocks,
        "seal_rate": seal_rate,
        "break_rate": break_rate,
        "promotion_rate": promotion_rate,
        "yzt_count": yzt_count,
    }


def get_short_term_emotion() -> dict:
    """短线情绪（含缓存，分钟级）。"""
    return _ds_get("market:emotion", TTL["minute"], _emotion, valid=bool, provider="eastmoney")


def get_turnover_top() -> dict:
    """全市场成交额榜 Top20（客观公开榜单，含缓存，分钟级）。"""
    def build():
        return {
            "stocks": astock.market_turnover_rank(20),
            "updated": datetime.now(BEIJING).strftime("%Y-%m-%d %H:%M"),
        }
    return _ds_get("market:turnover_top", TTL["minute"], build, valid=lambda v: bool(v.get("stocks")), provider="eastmoney")


def get_global_indices() -> list[dict]:
    """全球指数快照（美股 / 港股，含缓存，分钟级）。空结果不缓存。"""
    return _ds_get("market:global_indices", TTL["minute"], gstock.global_indices, valid=bool, provider="eastmoney")
