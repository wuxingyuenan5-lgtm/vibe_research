from __future__ import annotations

import math
import os
import random
import re
import time
import urllib.request
from datetime import datetime, timedelta
from pathlib import Path

UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"

# 全局默认：绕开系统代理直连所有外网 requests（包括 akshare / 同花顺 / 东财 / chat LLM 等）。
# 解决 launchd 拉起进程继承 HTTP(S)_PROXY=127.0.0.1:<端口> 但代理进程已挂 → Connection refused。
# 需要走代理时：显式 session.proxies = {...}（覆盖默认）；或设 VR_HTTP_PROXY=1 关闭本 patch。
try:
    import requests as _req  # 轻依赖，随后端一起装
    _orig_session_init = _req.Session.__init__
    def _session_init(self, *a, **kw):
        _orig_session_init(self, *a, **kw)
        if os.getenv("VR_HTTP_PROXY", "0") != "1":
            self.trust_env = False  # 默认不读环境代理
    _req.Session.__init__ = _session_init
except ImportError:
    pass

# 直连 opener：国内财经站（qt.gtimg.cn / push2.eastmoney.com 等）若走系统代理常被 Clash CONNECT 掐掉，
# 这里用一个空 ProxyHandler 强制直连。注意只影响 urllib.request 数据层调用，不影响 requests 库 / AI 层代理。
_no_proxy_opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))


def get_prefix(code: str) -> str:
    """6 位代码 → 交易所前缀。5 开头是沪市基金/ETF（51/56/58 等），深市基金 15/16 开头走默认 sz。"""
    if code.startswith(("6", "9", "5")):
        return "sh"
    if code.startswith("8"):
        return "bj"
    return "sz"


class DependencyMissing(RuntimeError):
    """惰性依赖未安装时抛出，前端据此提示 pip install。"""


# ---------------------------------------------------------------------------
# Layer 1 · 行情（腾讯财经，仅标准库，不封 IP）
# ---------------------------------------------------------------------------

def _fetch_gtimg(prefixed_codes: list[str]) -> str:
    url = "https://qt.gtimg.cn/q=" + ",".join(prefixed_codes)
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with _no_proxy_opener.open(req, timeout=10) as resp:
        return resp.read().decode("gbk")


def _parse_gtimg(data: str) -> dict[str, dict]:
    result: dict[str, dict] = {}
    for line in data.strip().split(";"):
        if not line.strip() or "=" not in line or '"' not in line:
            continue
        key = line.split("=")[0].split("_")[-1]
        vals = line.split('"')[1].split("~")
        if len(vals) < 53:
            continue
        code = key[2:]

        def num(i: int) -> float:
            try:
                return float(vals[i]) if vals[i] else 0.0
            except (ValueError, IndexError):
                return 0.0

        result[code] = {
            "name": vals[1],
            "price": num(3),
            "last_close": num(4),
            "open": num(5),
            "change_amt": num(31),
            "change_pct": num(32),
            "high": num(33),
            "low": num(34),
            "amount_wan": num(37),
            "turnover_pct": num(38),
            "pe_ttm": num(39),
            "amplitude_pct": num(43),
            "mcap_yi": num(44),
            "float_mcap_yi": num(45),
            "pb": num(46),
            "limit_up": num(47),
            "limit_down": num(48),
            "vol_ratio": num(49),
            "pe_static": num(52),
        }
    return result


def tencent_quote(codes: list[str]) -> dict[str, dict]:
    """批量个股实时行情：现价 / 涨跌 / PE / PB / 市值 / 换手 / 涨跌停。"""
    prefixed = [f"{get_prefix(c)}{c}" for c in codes]
    return _parse_gtimg(_fetch_gtimg(prefixed))


# A股大盘指数（前缀规则与个股不同，固定带前缀代码）；含中证1000（页面实时展示需要）
A_INDICES = ["sh000001", "sz399001", "sz399006", "sh000300", "sh000016", "sh000688", "sh000852"]


def index_quote() -> list[dict]:
    """A股大盘指数实时行情（上证/深证成指/创业板指/沪深300）。"""
    parsed = _parse_gtimg(_fetch_gtimg(A_INDICES))
    out = []
    for full in A_INDICES:
        q = parsed.get(full[2:])
        if q:
            out.append({"name": q["name"], "price": q["price"], "change_pct": q["change_pct"], "change_amt": q["change_amt"]})
    return out


# ---------------------------------------------------------------------------
# Layer 2 · 研报（东财 reportapi，仅 requests）
# ---------------------------------------------------------------------------

_REPORT_API = "https://reportapi.eastmoney.com/report/list"
_PDF_TPL = "https://pdf.dfcfw.com/pdf/H3_{info_code}_1.pdf"


def _report_session():
    import requests  # 轻依赖，随后端一起装

    s = requests.Session()
    s.headers.update({"User-Agent": UA, "Referer": "https://data.eastmoney.com/"})
    return s


def eastmoney_reports(code: str, max_pages: int = 3) -> list[dict]:
    """按个股代码拉研报列表（qType=0）。"""
    session = _report_session()
    out: list[dict] = []
    for page in range(1, max_pages + 1):
        params = {
            "industryCode": "*", "pageSize": "100", "industry": "*",
            "rating": "*", "ratingChange": "*",
            "beginTime": "2000-01-01", "endTime": "2030-01-01",
            "pageNo": str(page), "fields": "", "qType": "0",
            "orgCode": "", "code": code, "rcode": "",
            "p": str(page), "pageNum": str(page), "pageNumber": str(page),
        }
        r = session.get(_REPORT_API, params=params, timeout=30)
        d = r.json()
        rows = d.get("data") or []
        if not rows:
            break
        out.extend(rows)
        if page >= (d.get("TotalPage", 1) or 1):
            break
        time.sleep(0.3)
    return out


def eastmoney_industry_reports(keywords: list[str] | None = None, days: int = 90, max_pages: int = 3) -> list[dict]:
    """按行业拉研报（qType=1）——适合产业链 / 主题级检索。keywords 在标题上过滤。"""
    from datetime import date, timedelta

    session = _report_session()
    end = date.today()
    begin = end - timedelta(days=days)
    out: list[dict] = []
    for page in range(1, max_pages + 1):
        params = {
            "industryCode": "*", "pageSize": "100", "industry": "*",
            "rating": "*", "ratingChange": "*",
            "beginTime": begin.isoformat(), "endTime": end.isoformat(),
            "pageNo": str(page), "fields": "", "qType": "1",
            "orgCode": "", "code": "", "rcode": "",
        }
        r = session.get(_REPORT_API, params=params, timeout=30)
        rows = r.json().get("data") or []
        if not rows:
            break
        out.extend(rows)
        time.sleep(0.3)
    if keywords:
        out = [r for r in out if any(k in r.get("title", "") for k in keywords)]
    return out


def pdf_url(info_code: str) -> str:
    return _PDF_TPL.format(info_code=info_code)


# ---------------------------------------------------------------------------
# Layer 3/4/5 · akshare 惰性封装（一致预期 / 新闻 / 公告 / 基本面）
# ---------------------------------------------------------------------------

def _akshare():
    try:
        import akshare as ak
        return ak
    except ImportError as e:
        raise DependencyMissing("akshare 未安装：pip install akshare") from e


def _ak_call(func, *args, tries: int = 3, delay: float = 1.2, **kwargs):
    """akshare 调用统一重试：上游（东财/同花顺/乐咕）间歇失败（No tables found /
    RemoteDisconnected / 连接被掐）→ 指数退避重试，都失败抛最后一次异常。"""
    last = None
    for i in range(tries):
        try:
            return func(*args, **kwargs)
        except Exception as e:  # noqa: BLE001 —— akshare 上游错误五花八门，统一重试
            last = e
            if i < tries - 1:
                time.sleep(delay * (i + 1))
    if last is not None:
        raise last
    return None


def profit_forecast(code: str) -> list[dict]:
    """机构一致预期 EPS（同花顺）。"""
    ak = _akshare()
    df = _ak_call(ak.stock_profit_forecast_ths, symbol=code, indicator="预测年报每股收益")
    return df.to_dict("records") if df is not None and not df.empty else []


def consensus_forecast(code: str, year: int | None = None) -> dict:
    """机构一致预期净利润（同花顺盈利预测，网页公开数据，非付费 API）。

    单位：亿元（同花顺预测年报净利润 均值/最小/最大 均为亿元）。
    返回 {year, n_inst, mean, min, max, raw}；接口失败或无数据时返回 {}。
    """
    if year is None:
        year = datetime.now().year
    ak = _akshare()
    df = _ak_call(ak.stock_profit_forecast_ths, symbol=code, indicator="预测年报净利润")
    if df is None or df.empty:
        return {}
    row = next((r for r in df.to_dict("records") if str(r.get("年度")) == str(year)), None)
    if not row:
        return {}
    try:
        return {
            "year": int(row["年度"]),
            "n_inst": int(row.get("预测机构数") or 0),
            "mean": float(row["均值"]),
            "min": float(row.get("最小值") or 0) or None,
            "max": float(row.get("最大值") or 0) or None,
            "raw": row,
        }
    except (TypeError, ValueError):
        return {}


def stock_news(code: str, limit: int = 20) -> list[dict]:
    """个股新闻（东财）。"""
    ak = _akshare()
    df = _ak_call(ak.stock_news_em, symbol=code)
    return df.head(limit).to_dict("records") if df is not None and not df.empty else []


def individual_info(code: str) -> dict:
    """个股基本面（东财）：行业 / 总股本 / 上市时间等。"""
    ak = _akshare()
    df = _ak_call(ak.stock_individual_info_em, symbol=code)
    if df is None or df.empty:
        return {}
    return {str(row["item"]): row["value"] for _, row in df.iterrows()}


def disclosure(code: str) -> list[dict]:
    """巨潮公告全文列表（akshare cninfo，本环境不稳，保留作备用）。"""
    ak = _akshare()
    market = "沪市" if code.startswith("6") else ("北交所" if code.startswith("8") else "深市")
    df = _ak_call(ak.stock_zh_a_disclosure_report_cninfo, symbol=code, market=market)
    return df.head(30).to_dict("records") if df is not None and not df.empty else []


def sina_spot(codes: list[str]) -> dict[str, dict]:
    """新浪实时行情（国内期货主力连续 nf_ / 国际商品原油 hf_）：现价 vs 昨收。
    兼容三种字段布局：
    - nf_ 商品期货（44 字段）：[0]名称 [2]现价 [3]昨收（如 nf_AG0/CU0/LC0）
    - nf_ 国债期货（50 字段）：[0]现价 [1]昨收（如 nf_T0）
    - hf_ 国际（15 字段）：[0]现价 [1]或[7]昨收 [6]时间 [12]日期 [13]名称（如 hf_CL/OIL/XAU）
    返回 {code: {name, price, prev_close, change_pct, time}}。"""
    url = "https://hq.sinajs.cn/list=" + ",".join(codes)
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Referer": "https://finance.sina.com.cn"})
    raw = _no_proxy_opener.open(req, timeout=10).read().decode("gbk", "ignore")
    out: dict[str, dict] = {}
    for line in raw.split(";"):
        m = re.search(r'hq_str_(\w+)="(.*)"', line)
        if not m:
            continue
        sym, f = m.group(1), m.group(2).split(",")
        try:
            if sym.startswith("nf_"):
                # 44 字段商品期货：[0]=名称 [2]=现价 [3]=昨收；50 字段国债期货：[0]=现价 [1]=昨收
                if len(f) >= 44 and f[0] and not re.fullmatch(r"\d+(\.\d+)?", f[0]):
                    price, prev = float(f[2]), float(f[3]) if f[3] else 0.0
                    name = f[0]
                else:
                    price = float(f[0])
                    prev = float(f[1]) if len(f) > 1 and f[1] else 0.0
                    name = sym
            else:
                price = float(f[0])
                prev = float(f[1]) if len(f) > 1 and f[1] else (float(f[7]) if len(f) > 7 and f[7] else 0.0)
                name = f[13] if len(f) > 13 else sym
        except (ValueError, IndexError):
            continue
        if not price:
            continue
        out[sym] = {
            "name": name,
            "price": price,
            "prev_close": prev,
            "change_pct": (price - prev) / prev if prev else 0.0,
            "time": f"{f[12]} {f[6]}" if len(f) > 12 and f[6] else "",
        }
    return out


def gold_spot() -> dict:
    """伦敦金现货（XAU/USD，美元/盎司）实时价：新浪 hf_XAU。返回 {price, prev_close, change_pct, time, name}。"""
    url = "https://hq.sinajs.cn/list=hf_XAU"
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Referer": "https://finance.sina.com.cn"})
    raw = _no_proxy_opener.open(req, timeout=10).read().decode("gbk", "ignore")
    m = re.search(r'"(.*)"', raw)
    if not m:
        return {}
    f = m.group(1).split(",")
    if len(f) < 6 or not f[0]:
        return {}
    price = float(f[0])
    prev = float(f[1]) if f[1] else price
    return {
        "price": price,
        "prev_close": prev,
        "change_pct": (price - prev) / prev if prev else 0.0,
        "time": f"{f[12]} {f[6]}" if len(f) > 12 else "",
        "name": f[-1] if f else "现货黄金",
    }


def announcements(code: str, limit: int = 15) -> list[dict]:
    """个股近期公告（东财公开接口，仅 requests，稳定）。返回 日期/标题/类型/详情链接。"""
    import requests

    r = requests.get(
        "https://np-anotice-stock.eastmoney.com/api/security/ann",
        params={"sr": -1, "page_size": limit, "page_index": 1, "ann_type": "A",
                "client_source": "web", "stock_list": code, "f_node": 0, "s_node": 0},
        headers={"User-Agent": UA}, timeout=20,
    )
    lst = (r.json().get("data") or {}).get("list") or []
    out = []
    for a in lst:
        cols = [c.get("column_name") for c in (a.get("columns") or []) if c.get("column_name")]
        art = a.get("art_code", "")
        out.append({
            "date": (a.get("notice_date", "") or "")[:10],
            "title": a.get("title", ""),
            "type": cols[0] if cols else "",
            "url": f"https://data.eastmoney.com/notices/detail/{code}/{art}.html" if art else "",
        })
    return out


def announcements_batch(
    codes: list[str],
    since_date,
    *,
    batch_size: int = 50,
    page_size: int = 100,
    max_pages: int = 50,
) -> tuple[list[dict], dict]:
    """批量扫描自选股公告，并返回可审计的扫描统计。

    东财公告接口支持逗号分隔的股票列表。按 50 只一组分页，比逐股请求快很多；
    任一批次失败或在达到时间边界前触及分页上限都会直接报错，避免把漏抓伪装成
    “没有半年报”。
    """
    import requests

    valid_codes = list(dict.fromkeys(
        str(code).strip() for code in codes if re.fullmatch(r"\d{6}", str(code).strip())
    ))
    session = requests.Session()
    session.trust_env = False
    session.headers.update({"User-Agent": UA})
    output: list[dict] = []
    request_count = 0
    scanned_batches = 0

    for offset in range(0, len(valid_codes), max(1, batch_size)):
        batch = valid_codes[offset:offset + max(1, batch_size)]
        batch_set = set(batch)
        scanned_batches += 1
        reached_boundary = False
        for page in range(1, max_pages + 1):
            params = {
                "sr": -1,
                "page_size": page_size,
                "page_index": page,
                "ann_type": "A",
                "client_source": "web",
                "stock_list": ",".join(batch),
                "f_node": 0,
                "s_node": 0,
            }

            def _request_page():
                response = session.get(
                    "https://np-anotice-stock.eastmoney.com/api/security/ann",
                    params=params,
                    timeout=(4, 20),
                )
                response.raise_for_status()
                payload = response.json()
                if payload.get("success") is False:
                    raise RuntimeError(f"Eastmoney announcement API error: {payload.get('error')}")
                return payload.get("data") or {}

            data = _ak_call(_request_page, tries=3, delay=0.8)
            request_count += 1
            rows = data.get("list") or []
            if not rows:
                reached_boundary = True
                break

            page_dates = []
            for item in rows:
                raw_date = (item.get("notice_date") or "")[:10]
                try:
                    item_date = datetime.strptime(raw_date, "%Y-%m-%d").date()
                    page_dates.append(item_date)
                except (TypeError, ValueError):
                    continue
                if item_date < since_date:
                    continue
                columns = [
                    col.get("column_name") for col in (item.get("columns") or [])
                    if col.get("column_name")
                ]
                art_code = item.get("art_code", "")
                for code_info in item.get("codes") or []:
                    code = str(code_info.get("stock_code") or "")
                    if code not in batch_set:
                        continue
                    output.append({
                        "code": code,
                        "date": raw_date,
                        "title": item.get("title", ""),
                        "type": columns[0] if columns else "",
                        "url": (
                            f"https://data.eastmoney.com/notices/detail/{code}/{art_code}.html"
                            if art_code else ""
                        ),
                    })

            total_hits = int(data.get("total_hits") or 0)
            if (page_dates and min(page_dates) < since_date) or page * page_size >= total_hits:
                reached_boundary = True
                break

        if not reached_boundary:
            raise RuntimeError(
                f"公告批量扫描达到分页上限仍未覆盖时间窗: batch={offset // batch_size + 1}"
            )

    output.sort(key=lambda row: (row["date"], row["code"]), reverse=True)
    return output, {
        "scan_complete": True,
        "requested_codes": len(valid_codes),
        "scanned_batches": scanned_batches,
        "announcement_requests": request_count,
        "announcement_rows": len(output),
    }


# ---------------------------------------------------------------------------
# mootdx 惰性封装（K线 / 财务 / F10）
# ---------------------------------------------------------------------------

def _mootdx_client():
    try:
        from mootdx.quotes import Quotes
        return Quotes.factory(market="std")
    except ImportError as e:
        raise DependencyMissing("mootdx 未安装：pip install mootdx") from e


def kline(code: str, category: int = 4, offset: int = 60) -> list[dict]:
    """K线：category 4=日 5=周 6=月 11=60分钟。"""
    client = _mootdx_client()
    df = client.bars(symbol=code, category=category, offset=offset)
    return df.to_dict("records") if df is not None and not df.empty else []


def finance(code: str) -> dict:
    """季报财务快照（37 字段）。"""
    client = _mootdx_client()
    df = client.finance(symbol=code)
    if df is None or (hasattr(df, "empty") and df.empty):
        return {}
    return df.to_dict("records")[0] if hasattr(df, "to_dict") else dict(df)


# ---------------------------------------------------------------------------
# 估值计算
# ---------------------------------------------------------------------------

def calc_peg(pe: float, cagr: float) -> float:
    if cagr <= 0:
        return float("inf")
    return pe / (cagr * 100)


def pe_digestion(current_pe: float, cagr: float, target_pe: float = 30) -> float:
    if current_pe <= target_pe:
        return 0.0
    if cagr <= 0:
        return float("inf")
    return math.log(current_pe / target_pe) / math.log(1 + cagr)


def financials(code: str) -> dict:
    """财务关键指标（同花顺财务摘要，最新报告期）—— 干净可靠的营收/净利/ROE/毛利率等。

    注：mootdx finance() 的营收/净利数值不可靠(实测放大数倍)，故财务摘要走此源。
    """
    ak = _akshare()
    df = _ak_call(ak.stock_financial_abstract_ths, symbol=code, indicator="按报告期")
    if df is None or df.empty:
        return {}
    row = df.iloc[-1].to_dict()  # 最新报告期（按报告期升序，取末行）

    def g(k):
        v = row.get(k)
        return None if v in (False, "false", "", None) else v

    return {
        "period": g("报告期"),
        "revenue": g("营业总收入"), "revenue_yoy": g("营业总收入同比增长率"),
        "net_profit": g("净利润"), "net_profit_yoy": g("净利润同比增长率"),
        "eps": g("基本每股收益"), "bvps": g("每股净资产"),
        "roe": g("净资产收益率"), "gross_margin": g("销售毛利率"), "net_margin": g("销售净利率"),
        "op_cf_ps": g("每股经营现金流"),
    }


def half_year_report(codes: list[str], window_days: int = 1, max_workers: int = 8) -> dict:
    """关注股池中近 window_days 内发布半年报的公司（H1 实际净利 + 一致预期 + 完成度），按完成度分组。

    数据源（全部为网页公开数据，无付费 API）：
        公告列表：东方财富公告接口批量分页扫描
        实际净利：akshare stock_financial_abstract_ths financials()（慢、有 30 分钟缓存）
        一致预期：akshare stock_profit_forecast_ths 预测年报净利润 consensus_forecast()
                  （同花顺盈利预测，网页公开数据；无 gangtise / kimi_search 依赖）

    完成度 = 实际 H1 净利 / 2026 全年一致预期净利润均值。
    分组（贴合示例报告的"三段式"）：
        big_beat 大幅超预期：完成度 ≥ 70%
        meet     符合预期  ：有完成度但 < 70%（含亏损预期公司，如猪周期底部的牧原）
        pending  预期待验证：无一致预期 / 财务摘要缺失（同花顺无覆盖或接口失败）

    入参：
        codes:       6 位 A 股代码列表（来自自选股池）
        window_days: 时间窗天数，默认 1（近 24h）；常用 1 / 7 / 30
        max_workers: 并发拉数据的线程数（akshare 单次 ~1-2s）

    返回：
        {
          "window_days": 1, "scanned": N, "published": N, "covered": N,
          "fetched_at": ISO 时间戳,
          "groups": {
            "big_beat": [{code, name, period, net_profit_yi, yoy_pct,
                          consensus_mean, consensus_n, completion_pct, ann_date, ann_title, ann_url, ...}],
            "meet":     [...],
            "pending":  [...],   # 无一致预期/数据缺失，_note 标注原因
          },
        }
    """
    from concurrent.futures import ThreadPoolExecutor, as_completed

    def _is_half_year_title(title: str) -> bool:
        # 只接受报告正文/摘要。旧逻辑仅检查“半年度报告”子串，会把业绩说明会、
        # 业绩快报、披露提示性公告误判成正式半年报。
        short = str(title or "").split(":", 1)[-1].strip()
        return bool(re.search(
            r"(?:20\d{2}年)?(?:半年度报告|中期报告)(?:摘要)?(?:[（(].*?[）)])?$",
            short,
        ))

    def _parse_yi(v) -> float | None:
        """net_profit 文本 → 数值（亿元）。形态：'13.21亿' / '1380万' / '7200000000' / '-60.84亿'"""
        if v in (None, "", False, "false"): return None
        s = str(v).replace(",", "").strip()
        neg = s.startswith("-")
        s = s.lstrip("-")
        try:
            if s.endswith("亿"):   n = float(s[:-1])
            elif s.endswith("万"): n = float(s[:-1]) / 1e4
            else:                 n = float(s) / 1e8
            return -n if neg else n
        except ValueError:
            return None

    def _parse_pct(v) -> float | None:
        """'净利同比' 文本 → 百分比数字。形态：'+1504.2%' / '-156.4%' / '67.2%'"""
        if v in (None, "", False, "false"): return None
        try:
            return float(str(v).replace("%", "").replace("+", "").replace(",", "").strip())
        except ValueError:
            return None

    # ---- 1) 批量分页扫公告：覆盖性可审计，失败不再静默跳过 ----
    unique_codes = list(dict.fromkeys(codes))
    deadline = (datetime.now() - timedelta(days=window_days)).date()
    announcements_all, scan_audit = announcements_batch(unique_codes, deadline)
    hit_map: dict[str, dict] = {}
    for announcement in announcements_all:
        if not _is_half_year_title(announcement.get("title", "")):
            continue
        code = announcement["code"]
        candidate = {
            "code": code,
            "ann_date": announcement["date"],
            "ann_type": announcement.get("type", ""),
            "ann_title": announcement["title"],
            "ann_url": announcement.get("url", ""),
        }
        previous = hit_map.get(code)
        if previous is None:
            hit_map[code] = candidate
            continue
        # 同日同时发布摘要和正文时优先正文；跨日保留最新公告。
        if candidate["ann_date"] > previous["ann_date"] or (
            candidate["ann_date"] == previous["ann_date"]
            and "摘要" in previous["ann_title"] and "摘要" not in candidate["ann_title"]
        ):
            hit_map[code] = candidate
    hits = sorted(hit_map.values(), key=lambda row: (row["ann_date"], row["code"]), reverse=True)

    # ---- 2) 对命中的代码拉 financials + 一致预期：并发 + 每只超时 ----
    def _fetch_one(code: str) -> tuple[str, dict | None, str | None]:
        try:
            f = financials(code)
        except Exception as e:
            return code, None, f"akshare: {str(e)[:80]}"
        period = str(f.get("period") or "")
        if "-06-30" not in period:
            return code, None, f"非半年报期 ({period})"
        net_profit_yi = _parse_yi(f.get("net_profit"))
        yoy_pct = _parse_pct(f.get("net_profit_yoy"))
        # 一致预期（同花顺盈利预测，网页公开数据；失败不影响主数据，仅归 pending）
        cons: dict = {}
        try:
            cons = consensus_forecast(code)
        except Exception:
            cons = {}
        data = {
            "period": period,
            "net_profit_yi": net_profit_yi,
            "net_profit_raw": f.get("net_profit"),
            "yoy_pct": yoy_pct,
            "yoy_raw": f.get("net_profit_yoy"),
            "eps": f.get("eps"),
            "roe": f.get("roe"),
            "consensus_mean": cons.get("mean") if cons else None,
            "consensus_n": cons.get("n_inst") if cons else None,
            "consensus_year": cons.get("year") if cons else None,
        }
        # 完成度：仅当实际净利与预期同向且预期>0 时有意义
        cm = data["consensus_mean"]
        if cm is not None and cm > 0 and net_profit_yi is not None and net_profit_yi >= 0:
            data["completion_pct"] = round(net_profit_yi / cm * 100, 1)
        else:
            data["completion_pct"] = None
        return code, data, None

    fin_map: dict[str, dict] = {}
    fin_err: dict[str, str] = {}
    if hits:
        with ThreadPoolExecutor(max_workers=max(1, min(max_workers, 16))) as ex:
            futs = {ex.submit(_fetch_one, h["code"]): h["code"] for h in hits}
            for fut in as_completed(futs, timeout=300):
                code, data, err = fut.result()
                if data is not None:
                    fin_map[code] = data
                else:
                    fin_err[code] = err or "数据缺失"

    # ---- 3) 拼装 + 分组（完成度三段：大幅超预期 / 符合预期 / 预期待验证）----
    groups: dict[str, list] = {"big_beat": [], "meet": [], "pending": []}
    covered = 0
    for h in hits:
        code = h["code"]
        fin = fin_map.get(code)
        row = {
            "code": code,
            "ann_date": h["ann_date"],
            "ann_title": h["ann_title"],
            "ann_url": h["ann_url"],
            "period": fin["period"] if fin else None,
            "net_profit_yi": fin["net_profit_yi"] if fin else None,
            "net_profit_raw": fin["net_profit_raw"] if fin else None,
            "yoy_pct": fin["yoy_pct"] if fin else None,
            "yoy_raw": fin["yoy_raw"] if fin else None,
            "eps": fin["eps"] if fin else None,
            "roe": fin["roe"] if fin else None,
            "consensus_mean": fin["consensus_mean"] if fin else None,
            "consensus_n": fin["consensus_n"] if fin else None,
            "consensus_year": fin["consensus_year"] if fin else None,
            "completion_pct": fin["completion_pct"] if fin else None,
            "_note": None if fin else (fin_err.get(code) or "数据缺失"),
        }
        if not fin:
            # 财务摘要缺失（akshare 失败 / 非 H1 报告期）→ 预期待验证
            groups["pending"].append(row)
            continue
        covered += 1
        cp = row["completion_pct"]
        if cp is None:
            # 有财务但无一致预期（或无意义的预期）→ 预期待验证，注明原因
            if row["consensus_mean"] is None:
                row["_note"] = "一致预期暂缺（同花顺未覆盖），待验证"
            elif row["consensus_mean"] < 0:
                row["_note"] = "2026 年一致预期为亏损，完成度不适用"
                groups["meet"].append(row)
                continue
            else:
                row["_note"] = "完成度口径不适用（净利为负）"
            groups["pending"].append(row)
            continue
        if cp >= 70:
            groups["big_beat"].append(row)
        else:
            if cp < 40:
                row["_note"] = f"完成度 {cp:.1f}%，低于季节性中枢（H1 通常占全年 40-70%）"
            groups["meet"].append(row)

    # 排序：大幅超预期按完成度降序；符合预期按完成度降序；待验证按同比绝对值降序
    groups["big_beat"].sort(key=lambda x: -(x["completion_pct"] or 0))
    groups["meet"].sort(key=lambda x: -(x["completion_pct"] or 0))
    groups["pending"].sort(key=lambda x: -(abs(x["yoy_pct"] or 0)))

    return {
        "window_days": window_days,
        "scanned": len(unique_codes),
        "published": len(hits),
        "covered": covered,
        **scan_audit,
        "fetched_at": datetime.now().strftime("%Y-%m-%dT%H:%M:%S"),
        "groups": groups,
    }


def valuation_percentile(code: str, period: str = "近五年") -> dict:
    """历史估值分位（百度股市通）：PE-TTM / PB 的当前值 + 历史 20/50/80 分位带 + 所处分位。

    只表达"处于历史什么位置"，不划买卖线（理杏仁式中立呈现）。
    """
    ak = _akshare()

    def _q(vals: list, p: float) -> float:
        if not vals:
            return 0.0
        idx = p * (len(vals) - 1)
        lo = int(idx)
        if lo + 1 >= len(vals):
            return vals[-1]
        frac = idx - lo
        return vals[lo] * (1 - frac) + vals[lo + 1] * frac

    metrics = {}
    for key, ind in (("pe_ttm", "市盈率(TTM)"), ("pb", "市净率")):
        try:
            df = _ak_call(ak.stock_zh_valuation_baidu, symbol=code, indicator=ind, period=period)
            raw = df.iloc[:, 1].dropna().astype(float).tolist()
            if not raw:
                continue
            cur = float(raw[-1])
            s = sorted(raw)
            below = sum(1 for x in s if x < cur)
            metrics[key] = {
                "current": round(cur, 2),
                "percentile": round(below / max(len(s) - 1, 1) * 100, 1),
                "min": round(s[0], 2), "max": round(s[-1], 2),
                "p20": round(_q(s, 0.2), 2), "p50": round(_q(s, 0.5), 2), "p80": round(_q(s, 0.8), 2),
                "n": len(s),
            }
        except Exception:
            continue
    return {"period": "近5年", "metrics": metrics}


def full_valuation(code: str) -> dict:
    """单票完整估值：腾讯行情 + 一致预期 EPS + 前向PE/PEG/消化年数。"""
    quotes = tencent_quote([code])
    q = quotes.get(code)
    if not q:
        raise ValueError(f"未取到 {code} 的行情")

    price = q["price"]
    out = {
        "name": q["name"], "code": code, "price": price,
        "mcap_yi": q["mcap_yi"], "pe_ttm": q["pe_ttm"], "pb": q["pb"],
        "eps_26e": None, "eps_27e": None, "pe_26e": None,
        "cagr_pct": None, "peg": None, "digest_years": None, "analyst_count": 0,
    }

    try:
        rows = profit_forecast(code)
    except DependencyMissing:
        out["forecast_note"] = "一致预期需安装 akshare"
        return out

    def _eps(row: dict):
        # 同花顺对覆盖不全的股票会缺「均值」或给 '-' 占位，硬取会让整只票的估值接口 502
        try:
            return float(str(row.get("均值", "")).replace(",", ""))
        except ValueError:
            return None

    eps_26 = eps_27 = None
    for row in rows:
        y = str(row.get("年度", ""))
        if "2026" in y:
            eps_26 = _eps(row)
            try:
                out["analyst_count"] = int(float(row.get("预测机构数") or 0))
            except (TypeError, ValueError):
                pass
        elif "2027" in y:
            eps_27 = _eps(row)

    out["eps_26e"], out["eps_27e"] = eps_26, eps_27
    if eps_26 and eps_26 > 0:
        pe_26e = price / eps_26
        out["pe_26e"] = round(pe_26e, 1)
        if eps_27:
            cagr = eps_27 / eps_26 - 1
            out["cagr_pct"] = round(cagr * 100, 0)
            peg = calc_peg(pe_26e, cagr)
            out["peg"] = round(peg, 2) if peg != float("inf") else None
            dig = pe_digestion(pe_26e, cagr)
            out["digest_years"] = round(dig, 1) if dig != float("inf") else None
    return out


# ===========================================================================
# Layer 3/4/10 · 资金面 / 筹码 / 信号（东财数据中心，移植自 a-stock-data v3.3）
#
# 合规：以下端点全部按【用户传入的单个代码】返回该股的客观公开数据（龙虎榜记录、
# 融资融券、大宗交易、股东户数、分红、资金流、解禁、板块归属、投资者问答），
# 不预置标的、不做主观评分、不给买卖建议。
# 定位调整（2026-07-05）：涨停池 / 全市场成交额榜等【客观公开榜单】现已用于产品 UI
# （每日复盘的连板股 + 成交额 TOP20）——如实展示公开榜单≠荐股，只要不附推荐/评分/预测。
# 仍不做：主观评分排名、买卖点位、涨跌预测；龙虎榜个股名单/强势股/人气榜等带隐性倾向的甩单暂不进 UI。
# ===========================================================================

_DATACENTER_URL = "https://datacenter-web.eastmoney.com/api/data/v1/get"
_EM_MIN_INTERVAL = 1.0          # 两次东财请求最小间隔（秒），内置防封节流
_em_last_call = [0.0]
_EM_SESSIONS: dict = {}         # {direct(bool): requests.Session}

# 数据层连接模式：国内财经站（东财/腾讯/新浪）本应「直连」——很多用户开着 Clash/V2Ray
# 科学上网，系统代理会把东财这类国内站路由挂掉（典型：push2.eastmoney.com 的 CONNECT 被掐）。
# 默认 auto：先试直连、失败再降级走系统代理；探测一次后固定，避免每次都重试。
# 只有少数「必须靠代理才能出网」的环境需要 VR_DATA_PROXY=1 强制走代理。
# 注意：这只影响数据层；AI 层（可能要调国外模型）仍走各自的系统代理，不受影响。
_em_mode = ["proxy" if os.environ.get("VR_DATA_PROXY", "").strip().lower() in ("1", "true", "yes") else "auto"]


def _em_session(direct: bool):
    """东财专用会话。direct=True → `trust_env=False` 忽略 HTTP(S)_PROXY 环境变量、直连。

    直连会话不重试（探测要快，失败即降级）；代理会话保留瞬态错误退避重试。惰性构建、复用。
    """
    if direct in _EM_SESSIONS:
        return _EM_SESSIONS[direct]
    import requests

    s = requests.Session()
    s.headers.update({"User-Agent": UA})
    s.trust_env = not direct     # 直连会话不读环境里的代理配置
    try:
        from requests.adapters import HTTPAdapter
        from urllib3.util.retry import Retry

        retry = Retry(total=0) if direct else Retry(
            total=3, connect=3, backoff_factor=0.6,
            status_forcelist=[429, 500, 502, 503, 504], allowed_methods=["GET"])
        adapter = HTTPAdapter(max_retries=retry)
        s.mount("https://", adapter)
        s.mount("http://", adapter)
    except Exception:
        pass  # 老版本 urllib3 缺参数时降级为无重试
    _EM_SESSIONS[direct] = s
    return s


def em_get(url: str, params: dict | None = None, headers: dict | None = None, timeout: int = 15):
    """东财统一请求入口：串行限流 + **直连优先、失败降级系统代理**（避免科学上网代理挂掉国内站）。

    第一次请求探测：先直连（短超时、不重试），成功即固定走直连；失败则降级走系统代理并固定。
    探测结果整个进程复用，避免每次重试。`VR_DATA_PROXY=1` 可跳过探测、强制走代理。
    """
    wait = _EM_MIN_INTERVAL - (time.time() - _em_last_call[0])
    if wait > 0:
        time.sleep(wait + random.uniform(0.1, 0.5))
    try:
        mode = _em_mode[0]
        if mode != "auto":
            return _em_session(mode == "direct").get(url, params=params, headers=headers, timeout=timeout)
        # auto：先直连，成功固定 direct；直连失败再走系统代理、成功固定 proxy。
        try:
            r = _em_session(True).get(url, params=params, headers=headers, timeout=min(timeout, 8))
            _em_mode[0] = "direct"
            return r
        except Exception:
            r = _em_session(False).get(url, params=params, headers=headers, timeout=timeout)
            _em_mode[0] = "proxy"
            return r
    finally:
        _em_last_call[0] = time.time()


# ---------------------------------------------------------------------------
# 打板层 · 涨停/炸板/跌停/昨涨停 原始池（东财 push2ex，走 em_get 限流）
# ⚠️ 合规：原始池含个股 code/name —— 仅供 market.py 聚合成【不含个股名】的短线情绪指标。
#    切勿把原始池直接接成 API/UI（会甩个股名单、破产品「零标的」红线）。
# ---------------------------------------------------------------------------
_ZTB_UT = "7eea3edcaed734bea9cbfc24409ed989"


def em_zt_topic_pool(endpoint: str, date: str, sort: str = "fbt:asc") -> list[dict]:
    """东财涨停板行情中心原始池（push2ex）。
    endpoint: getTopicZTPool(涨停) / getTopicZBPool(炸板) / getTopicDTPool(跌停) / getYesterdayZTPool(昨涨停)
    date: YYYYMMDD 交易日。非交易日 / 参数错 → []。
    池内每项字段含 lbc(连板数) / zbc(炸板次数) / hybk(行业) 等。"""
    url = f"https://push2ex.eastmoney.com/{endpoint}"
    params = {"ut": _ZTB_UT, "dpt": "wz.ztzt", "Pageindex": 0,
              "pagesize": 10000, "sort": sort, "date": date}
    headers = {"User-Agent": UA, "Referer": "https://quote.eastmoney.com/"}
    try:
        r = em_get(url, params=params, headers=headers, timeout=10)
        return (r.json().get("data") or {}).get("pool") or []
    except Exception:
        return []


def _numf(v):
    """东财数值字段可能是 '-'（停牌/无数据）→ 归一成 float 或 None。"""
    return v if isinstance(v, (int, float)) else None


def market_turnover_rank(n: int = 20) -> list[dict]:
    """全市场成交额榜（沪深京 A 股按成交额降序 TopN）。

    东财行情中心 clist。**push2(实时) 不可达时降级 push2delay(延迟行情，日榜场景足够)**。
    返回每只: code / name / price / pct / amount(成交额,元) / mcap(总市值,元) /
    float_cap(流通市值,元) / industry。
    ⚠️ 这是客观公开榜单数据（东财/同花顺同款），产品侧只做客观展示——非推荐、非预测、不评分。
    """
    params = {"pn": 1, "pz": n, "po": 1, "np": 1, "fltt": 2, "invt": 2, "fid": "f6",
              "fs": "m:0 t:6,m:0 t:80,m:1 t:2,m:1 t:23,m:0 t:81 s:2048",
              "fields": "f12,f14,f2,f3,f6,f20,f21,f100"}
    diff: list[dict] = []
    for host in ("push2.eastmoney.com", "push2delay.eastmoney.com"):
        try:
            r = em_get(f"https://{host}/api/qt/clist/get", params=params,
                       headers={"User-Agent": UA}, timeout=12)
            diff = (r.json().get("data") or {}).get("diff") or []
            if diff:
                break
        except Exception:
            continue
    return [{
        "code": str(d.get("f12", "")), "name": d.get("f14", ""),
        "price": _numf(d.get("f2")), "pct": _numf(d.get("f3")),
        "amount": _numf(d.get("f6")), "mcap": _numf(d.get("f20")),
        "float_cap": _numf(d.get("f21")), "industry": d.get("f100", "") or "",
    } for d in diff]


def eastmoney_datacenter(report_name: str, columns: str = "ALL", filter_str: str = "",
                         page_size: int = 50, sort_columns: str = "", sort_types: str = "-1") -> list[dict]:
    """东财数据中心统一查询 —— 龙虎榜/解禁/融资融券/大宗交易/股东户数/分红 共用（已内置限流）。"""
    params = {
        "reportName": report_name, "columns": columns, "filter": filter_str,
        "pageNumber": "1", "pageSize": str(page_size),
        "sortColumns": sort_columns, "sortTypes": sort_types, "source": "WEB", "client": "WEB",
    }
    try:
        d = em_get(_DATACENTER_URL, params=params, timeout=15).json()
    except Exception:
        return []
    if d.get("result") and d["result"].get("data"):
        return d["result"]["data"]
    return []


def margin_trading(code: str, page_size: int = 30) -> list[dict]:
    """融资融券明细（日级）：融资余额 / 融资买入 / 融券余额 / 两融合计。"""
    data = eastmoney_datacenter(
        "RPTA_WEB_RZRQ_GGMX", filter_str=f'(SCODE="{code}")',
        page_size=page_size, sort_columns="DATE", sort_types="-1")
    return [{
        "date": str(r.get("DATE", ""))[:10],
        "rzye": r.get("RZYE", 0), "rzmre": r.get("RZMRE", 0), "rzche": r.get("RZCHE", 0),
        "rqye": r.get("RQYE", 0), "rqmcl": r.get("RQMCL", 0),
        "rzrqye": r.get("RZRQYE", 0),
    } for r in data]


def block_trade(code: str, page_size: int = 20) -> list[dict]:
    """大宗交易：成交价 / 折溢价率 / 量 / 买卖方营业部。"""
    data = eastmoney_datacenter(
        "RPT_DATA_BLOCKTRADE", filter_str=f'(SECURITY_CODE="{code}")',
        page_size=page_size, sort_columns="TRADE_DATE", sort_types="-1")
    rows = []
    for r in data:
        close = r.get("CLOSE_PRICE") or 0
        deal = r.get("DEAL_PRICE") or 0
        rows.append({
            "date": str(r.get("TRADE_DATE", ""))[:10],
            "price": deal, "close": close,
            "premium_pct": round((deal / close - 1) * 100, 2) if close else 0,
            "vol": r.get("DEAL_VOLUME", 0), "amount": r.get("DEAL_AMT", 0),
            "buyer": r.get("BUYER_NAME", ""), "seller": r.get("SELLER_NAME", ""),
        })
    return rows


def holder_num_change(code: str, page_size: int = 10) -> list[dict]:
    """股东户数变化（季度级）：户数 / 环比 / 户均持股。持续减少 = 筹码集中。"""
    data = eastmoney_datacenter(
        "RPT_HOLDERNUMLATEST", filter_str=f'(SECURITY_CODE="{code}")',
        page_size=page_size, sort_columns="END_DATE", sort_types="-1")
    return [{
        "date": str(r.get("END_DATE", ""))[:10],
        "holder_num": r.get("HOLDER_NUM", 0),
        "change_ratio": r.get("HOLDER_NUM_RATIO", 0),
        "avg_shares": r.get("AVG_FREE_SHARES", 0),
    } for r in data]


def dividend_history(code: str, page_size: int = 20) -> list[dict]:
    """分红送转历史：每股派息（税前）/ 每10股转增 / 每10股送股 / 进度。"""
    data = eastmoney_datacenter(
        "RPT_SHAREBONUS_DET", filter_str=f'(SECURITY_CODE="{code}")',
        page_size=page_size, sort_columns="EX_DIVIDEND_DATE", sort_types="-1")
    return [{
        "date": str(r.get("EX_DIVIDEND_DATE", ""))[:10],
        "bonus_rmb": r.get("PRETAX_BONUS_RMB", 0),
        "transfer_ratio": r.get("TRANSFER_RATIO", 0),
        "bonus_ratio": r.get("BONUS_RATIO", 0),
        "plan": r.get("ASSIGN_PROGRESS", ""),
    } for r in data]


def stock_fund_flow_120d(code: str) -> list[dict]:
    """个股资金流（日级，最近 120 交易日）：主力 / 小单 / 中单 / 大单 / 超大单净流入（元）。"""
    market_code = 1 if code.startswith("6") else 0
    params = {
        "secid": f"{market_code}.{code}",
        "fields1": "f1,f2,f3,f7",
        "fields2": "f51,f52,f53,f54,f55,f56,f57,f58,f59,f60,f61,f62,f63,f64,f65",
        "lmt": "120",
    }
    headers = {"User-Agent": UA, "Referer": "https://quote.eastmoney.com/", "Origin": "https://quote.eastmoney.com"}
    try:
        d = em_get("https://push2his.eastmoney.com/api/qt/stock/fflow/daykline/get",
                   params=params, headers=headers, timeout=15).json()
    except Exception:
        return []
    rows = []
    for line in d.get("data", {}).get("klines", []):
        p = line.split(",")
        if len(p) >= 6:
            def _f(x):
                try:
                    return float(x) if x not in ("-", "") else 0.0
                except ValueError:
                    return 0.0
            rows.append({
                "date": p[0], "main_net": _f(p[1]), "small_net": _f(p[2]),
                "mid_net": _f(p[3]), "large_net": _f(p[4]), "super_net": _f(p[5]),
            })
    return rows


def dragon_tiger_board(code: str, trade_date: str | None = None, look_back: int = 30) -> dict:
    """龙虎榜：该股近期上榜记录 + 最近一次买卖席位 TOP5 + 机构专用席位净买。"""
    trade_date = trade_date or datetime.now().strftime("%Y-%m-%d")
    start = (datetime.strptime(trade_date, "%Y-%m-%d") - timedelta(days=look_back)).strftime("%Y-%m-%d")
    records = []
    data = eastmoney_datacenter(
        "RPT_DAILYBILLBOARD_DETAILSNEW",
        filter_str=f'(TRADE_DATE>=\'{start}\')(TRADE_DATE<=\'{trade_date}\')(SECURITY_CODE="{code}")',
        page_size=50, sort_columns="TRADE_DATE", sort_types="-1")
    for r in data:
        records.append({
            "date": str(r.get("TRADE_DATE", ""))[:10],
            "reason": r.get("EXPLANATION", ""),
            "net_buy": round((r.get("BILLBOARD_NET_AMT") or 0) / 10000, 1),  # 万元
            "turnover": round(float(r.get("TURNOVERRATE") or 0), 2),
        })

    seats = {"buy": [], "sell": []}
    institution = {"buy_amt": 0.0, "sell_amt": 0.0, "net_amt": 0.0}
    if records:
        latest = records[0]["date"]
        buy_data = eastmoney_datacenter(
            "RPT_BILLBOARD_DAILYDETAILSBUY",
            filter_str=f'(TRADE_DATE=\'{latest}\')(SECURITY_CODE="{code}")',
            page_size=10, sort_columns="BUY", sort_types="-1")
        sell_data = eastmoney_datacenter(
            "RPT_BILLBOARD_DAILYDETAILSSELL",
            filter_str=f'(TRADE_DATE=\'{latest}\')(SECURITY_CODE="{code}")',
            page_size=10, sort_columns="SELL", sort_types="-1")
        for r in buy_data[:5]:
            seats["buy"].append({"name": r.get("OPERATEDEPT_NAME", ""),
                                 "buy_amt": round((r.get("BUY") or 0) / 10000, 1),
                                 "sell_amt": round((r.get("SELL") or 0) / 10000, 1),
                                 "net": round((r.get("NET") or 0) / 10000, 1)})
        for r in sell_data[:5]:
            seats["sell"].append({"name": r.get("OPERATEDEPT_NAME", ""),
                                  "buy_amt": round((r.get("BUY") or 0) / 10000, 1),
                                  "sell_amt": round((r.get("SELL") or 0) / 10000, 1),
                                  "net": round((r.get("NET") or 0) / 10000, 1)})
        for detail, side in ((buy_data, "buy"), (sell_data, "sell")):
            for r in detail:
                if str(r.get("OPERATEDEPT_CODE", "")) == "0":  # 机构专用席位
                    amt = (r.get("BUY") or 0) if side == "buy" else (r.get("SELL") or 0)
                    institution[f"{side}_amt"] += amt
        institution["buy_amt"] = round(institution["buy_amt"] / 10000, 1)
        institution["sell_amt"] = round(institution["sell_amt"] / 10000, 1)
        institution["net_amt"] = round(institution["buy_amt"] - institution["sell_amt"], 1)
    return {"records": records, "seats": seats, "institution": institution}


def lockup_expiry(code: str, trade_date: str | None = None, forward_days: int = 90) -> dict:
    """限售解禁日历：历史解禁记录 + 未来 N 天待解禁事件。

    字段随东财 2026 改列名同步（a-stock-data §3.6）：旧 LIMITED_STOCK_TYPE/FREE_SHARES_NUM
    已废、致 type/shares 恒空 → 改 FREE_SHARES_TYPE/FREE_SHARES，并补 able_shares（实际可流通股数）。
    """
    trade_date = trade_date or datetime.now().strftime("%Y-%m-%d")
    history = [{
        "date": str(r.get("FREE_DATE", ""))[:10], "type": r.get("FREE_SHARES_TYPE", ""),
        "shares": r.get("FREE_SHARES", 0), "able_shares": r.get("ABLE_FREE_SHARES", 0),
        "ratio": r.get("FREE_RATIO", 0),
    } for r in eastmoney_datacenter(
        "RPT_LIFT_STAGE", filter_str=f'(SECURITY_CODE="{code}")',
        page_size=15, sort_columns="FREE_DATE", sort_types="-1")]

    end = (datetime.strptime(trade_date, "%Y-%m-%d") + timedelta(days=forward_days)).strftime("%Y-%m-%d")
    upcoming = [{
        "date": str(r.get("FREE_DATE", ""))[:10], "type": r.get("FREE_SHARES_TYPE", ""),
        "shares": r.get("FREE_SHARES", 0), "able_shares": r.get("ABLE_FREE_SHARES", 0),
        "ratio": r.get("FREE_RATIO", 0),
    } for r in eastmoney_datacenter(
        "RPT_LIFT_STAGE",
        filter_str=f'(SECURITY_CODE="{code}")(FREE_DATE>=\'{trade_date}\')(FREE_DATE<=\'{end}\')',
        page_size=20, sort_columns="FREE_DATE", sort_types="1")]
    return {"history": history, "upcoming": upcoming}


def concept_blocks(code: str) -> dict:
    """个股所属板块/概念归属（东财 slist，行业/概念/地域混合，板块名自解释）。"""
    market_code = 1 if code.startswith("6") else 0
    params = {"fltt": "2", "invt": "2", "secid": f"{market_code}.{code}",
              "spt": "3", "pi": "0", "pz": "200", "po": "1", "fields": "f12,f14,f3,f128"}
    headers = {"User-Agent": UA, "Referer": "https://quote.eastmoney.com/"}
    try:
        d = em_get("https://push2.eastmoney.com/api/qt/slist/get", params=params, headers=headers, timeout=15).json()
    except Exception:
        return {"total": 0, "boards": [], "concept_tags": []}
    diff = (d.get("data") or {}).get("diff") or {}
    items = diff.values() if isinstance(diff, dict) else diff
    boards = [{"name": it.get("f14", ""), "code": it.get("f12", ""),
               "change_pct": it.get("f3", ""), "lead_stock": it.get("f128", "")} for it in items]
    return {"total": len(boards), "boards": boards, "concept_tags": [b["name"] for b in boards]}


def hot_concepts(code: str) -> list[dict]:
    """个股当下被市场归到哪些概念在炒（东财热门概念命中，按热度降序）。"""
    import requests

    try:
        prefix = "SH" if code.startswith("6") else "SZ"
        r = requests.post(
            "https://emappdata.eastmoney.com/stockrank/getHotStockRankList",
            json={"appId": "appId01", "globalId": "786e4c21-70dc-435a-93bb-38", "srcSecurityCode": prefix + code},
            headers={"User-Agent": UA}, timeout=10)
        data = r.json().get("data") or []
    except Exception:
        return []
    return [{"concept": x.get("conceptName"), "bk": x.get("conceptId"), "hit": x.get("hitCount")} for x in data]


def investor_qa(code: str, page_size: int = 30) -> list[dict]:
    """互动易问答（巨潮）：投资者提问 + 公司回复（answer=None 表示未回复）。"""
    import requests

    try:
        r1 = requests.post("https://irm.cninfo.com.cn/newircs/index/queryKeyboardInfo",
                           data={"keyWord": code}, headers={"User-Agent": UA}, timeout=10)
        d1 = r1.json().get("data") or []
        if not d1:
            return []
        org_id = d1[0].get("secid")
        params = {"_t": 1, "stockcode": code, "orgId": org_id, "pageSize": page_size,
                  "pageNum": 1, "keyWord": "", "startDay": "", "endDay": ""}
        rows = requests.post("https://irm.cninfo.com.cn/newircs/company/question",
                             params=params, headers={"User-Agent": UA}, timeout=10).json().get("rows") or []
    except Exception:
        return []
    out = []
    for it in rows:
        ts = it.get("pubDate")
        out.append({
            "company": it.get("companyShortName"),
            "question": it.get("mainContent"), "answer": it.get("attachedContent"),
            "answerer": it.get("attachedAuthor"),
            "ask_time": datetime.fromtimestamp(ts / 1000).strftime("%Y-%m-%d %H:%M") if ts else "",
        })
    return out


def industry_comparison(top_n: int = 20) -> dict:
    """全行业涨跌幅排名（东财行业板块，~100 个行业）：板块级涨跌 / 涨跌家数 / 领涨。"""
    params = {"pn": "1", "pz": "100", "po": "1", "np": "1", "fltt": "2", "invt": "2",
              "fid": "f3",  # fid=f3 + po=1：按涨跌幅降序，否则 top/bottom 切片非涨幅序（a-stock-data §3.7）
              "fs": "m:90+t:2", "fields": "f2,f3,f4,f12,f13,f14,f104,f105,f128,f136,f140,f141,f207"}
    try:
        d = em_get("https://push2.eastmoney.com/api/qt/clist/get",
                   params=params, headers={"User-Agent": UA}, timeout=15).json()
    except Exception:
        return {"top": [], "bottom": [], "total": 0}
    items = d.get("data", {}).get("diff", [])
    if isinstance(items, dict):
        items = list(items.values())
    if not items:
        return {"top": [], "bottom": [], "total": 0}
    rows = [{
        "rank": i + 1, "name": it.get("f14", ""), "change_pct": it.get("f3", 0),
        "code": it.get("f12", ""), "up_count": it.get("f104", 0), "down_count": it.get("f105", 0),
    } for i, it in enumerate(items)]
    return {"top": rows[:top_n], "bottom": rows[-top_n:], "total": len(rows)}
