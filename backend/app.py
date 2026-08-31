from __future__ import annotations

import json
import os
import re

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from pydantic import BaseModel

import astock
import chat as chat_layer
import cli_runtime
import debate as debate_layer
import gstock
import macro_brief as macro_brief_mod
import market_monitor.report_builder as market_monitor_builder
import market_monitor.stock_pool as stock_pool_builder
import newsradar
import portfolio as pf
import market
from dataservice import TTL, get as _ds_get, invalidate as _ds_invalidate
import myreports as mr
import reflection as reflect_layer
import market_monitor.morning_brief as morning_brief
from pathlib import Path

app = FastAPI(title="Vibe-Research API", version="0.2.2")

# 每半小时后台刷新持仓数据
pf.start_scheduler(1800)

# CORS：默认放开（本地自托管友好）；公网部署时用 VR_ALLOW_ORIGINS 收紧成白名单。
#   例：VR_ALLOW_ORIGINS="https://myhost"  （逗号分隔多个）
_ORIGINS = [o.strip() for o in os.environ.get("VR_ALLOW_ORIGINS", "*").split(",") if o.strip()] or ["*"]
app.add_middleware(
    CORSMiddleware,
    allow_origins=_ORIGINS,
    allow_methods=["GET", "POST", "DELETE", "OPTIONS"],
    allow_headers=["*"],
)

# 可选鉴权：设了 VR_API_KEY 就要求所有 /api/* 带 `Authorization: Bearer <key>`
#   （本地自托管不设=开放；公网部署务必设，否则别人能读你的持仓/调你的后端）。
_API_KEY = os.environ.get("VR_API_KEY", "").strip()


@app.middleware("http")
async def _require_api_key(request: Request, call_next):
    if (
        _API_KEY
        and request.method != "OPTIONS"
        and request.url.path.startswith("/api/")
        and request.url.path != "/api/health"
    ):
        if request.headers.get("authorization", "") != f"Bearer {_API_KEY}":
            return JSONResponse({"detail": "未授权：缺少或错误的 API Key（VR_API_KEY）"}, status_code=401)
    return await call_next(request)

_CODE_RE = r"^\d{6}$"


def _validate(code: str) -> str:
    code = (code or "").strip()
    if not code.isdigit() or len(code) != 6:
        raise HTTPException(400, "代码必须是 6 位数字")
    return code


@app.get("/api/health")
def health():
    return {"ok": True, "service": "vibe-research-api", "version": "0.2.2"}


@app.get("/api/health/providers")
def health_providers():
    """数据源健康状态（tencent / eastmoney / akshare 等，含 ok / 耗时 / 是否降级）。"""
    from dataservice import provider_health
    return {"data": provider_health()}


class LLMConfig(BaseModel):
    provider: str = ""       # cli-* = 订阅接入（调本机 CLI）；其余 = API 接入
    baseURL: str = ""        # 订阅接入时留空
    apiKey: str = ""         # 订阅接入时留空
    model: str


class ChatReq(BaseModel):
    messages: list[dict]
    context: str = ""
    llm: LLMConfig


@app.post("/api/chat")
def chat(req: ChatReq):
    """系统 AI 对话，**流式** NDJSON（每行一个事件 {type: tool|delta|done|error}）。

    - API 接入：OpenAI 兼容 function-calling，边流答案边推工具调用事件。
    - 订阅接入（provider=cli-*）：调本机已登录的 CLI，stdout 边出边流（数据靠 context）。
    配置错误（缺 key / 未装 CLI）走 HTTP 400；运行时错误走流内 error 事件。用户配置随请求传入，后端不持久化。
    """
    if not req.messages:
        raise HTTPException(400, "messages 不能为空")
    if not req.llm.model:
        raise HTTPException(400, "缺少模型配置，请先在「接入 AI」里选择")

    is_cli = req.llm.provider.startswith("cli-")
    if is_cli:
        kind = req.llm.provider[4:]
        if not cli_runtime.detect_cli(kind):
            raise HTTPException(400, f"未检测到「{kind}」对应的本机命令。请先安装并登录该 CLI，或改用「API 接入」。")
    elif not req.llm.apiKey or not req.llm.baseURL:
        raise HTTPException(400, "缺少 Base URL 或 API Key，请先在「接入 AI」里填写")

    cfg = req.llm.model_dump()

    def gen():
        try:
            events = (chat_layer.run_chat_cli_stream if is_cli else chat_layer.run_chat_stream)(cfg, req.messages, req.context)
            for ev in events:
                yield json.dumps(ev, ensure_ascii=False) + "\n"
        except Exception as e:  # noqa: BLE001 — 运行时错误以流内事件上报，不中断连接
            yield json.dumps({"type": "error", "message": f"对话失败：{e}"}, ensure_ascii=False) + "\n"

    return StreamingResponse(gen(), media_type="application/x-ndjson")


def _check_llm(llm: LLMConfig) -> dict:
    """校验模型配置并返回 cfg（chat / debate / reflect 三个流式端点共用）。

    配置问题走 HTTP 400（前端能弹提示引导去「接入 AI」页），运行时错误留给流内 error 事件。
    """
    if not llm.model:
        raise HTTPException(400, "缺少模型配置，请先在「接入 AI」里选择")
    if llm.provider.startswith("cli-"):
        kind = llm.provider[4:]
        if not cli_runtime.detect_cli(kind):
            raise HTTPException(400, f"未检测到「{kind}」对应的本机命令。请先安装并登录该 CLI，或改用「API 接入」。")
    elif not llm.apiKey or not llm.baseURL:
        raise HTTPException(400, "缺少 Base URL 或 API Key，请先在「接入 AI」里填写")
    return llm.model_dump()


def _ndjson(events):
    """把事件生成器包成 NDJSON 流；运行时异常转成流内 error 事件，不中断连接。"""
    def gen():
        try:
            for ev in events():
                yield json.dumps(ev, ensure_ascii=False) + "\n"
        except Exception as e:  # noqa: BLE001
            yield json.dumps({"type": "error", "message": str(e)}, ensure_ascii=False) + "\n"

    return StreamingResponse(gen(), media_type="application/x-ndjson")


class DebateReq(BaseModel):
    code: str
    rounds: int = 1
    llm: LLMConfig


@app.post("/api/debate")
def debate(req: DebateReq):
    """多空辩论：后端先拉客观事实底稿，再让多方 / 空方 / 中立主持依次发言，**流式** NDJSON。

    刻意不产出买卖结论——终点是「分歧点 + 验证清单」，判断留给用户自己。
    """
    code = _validate(req.code)
    cfg = _check_llm(req.llm)
    rounds = 2 if req.rounds >= 2 else 1
    return _ndjson(lambda: debate_layer.run_debate_stream(cfg, code, rounds))


class ReflectReq(BaseModel):
    source: str
    title: str = ""
    llm: LLMConfig


@app.post("/api/reflect")
def reflect(req: ReflectReq):
    """反思：对一段已写好的分析做推理审计（哪些有数据支撑、最脆弱一环、验证清单），流式 NDJSON。"""
    if not (req.source or "").strip():
        raise HTTPException(400, "source 不能为空")
    cfg = _check_llm(req.llm)
    return _ndjson(lambda: reflect_layer.run_reflection_stream(cfg, req.source, req.title))


class HoldingIn(BaseModel):
    code: str
    shares: float
    cost: float


@app.get("/api/portfolio")
def portfolio_get():
    """持仓 + 实时盈亏（浮动盈亏红涨绿跌）。"""
    try:
        return {"data": pf.get_portfolio()}
    except Exception as e:  # noqa: BLE001
        raise HTTPException(502, f"持仓读取异常：{e}") from e


@app.post("/api/portfolio/holding")
def portfolio_add(h: HoldingIn):
    """加一笔持仓（同代码按加权平均成本合并）。存本地，不上传。"""
    code = (h.code or "").strip()
    if not code.isdigit() or len(code) != 6:
        raise HTTPException(400, "代码必须是 6 位数字")
    if h.shares <= 0:
        raise HTTPException(400, "数量必须大于 0")
    # 成本价不限正负：融券 / 返息 / 摊薄后为负成本等情形按结果计算，用户想怎么输就怎么输。
    return {"data": pf.add_holding(code, h.shares, h.cost)}


@app.delete("/api/portfolio/holding")
def portfolio_remove(code: str = Query(...)):
    return {"data": pf.remove_holding(code.strip())}


# ---- 我的研报（用户上传自己的研报，存本地、不上传、不进开源仓库）----

class ReportIn(BaseModel):
    name: str
    content_b64: str


@app.get("/api/myreports")
def myreports_list():
    return {"data": mr.list_reports()}


@app.post("/api/myreports")
def myreports_upload(r: ReportIn):
    """上传一份研报（base64）→ 存本地 + 按文件名自动打行业标签。"""
    try:
        return {"data": mr.save_report(r.name, r.content_b64)}
    except mr.ReportError as e:
        raise HTTPException(400, str(e)) from e


@app.get("/api/myreports/file/{rid}")
def myreports_file(rid: str):
    """下载/预览某份研报原文件。"""
    hit = mr.report_path(rid)
    if not hit:
        raise HTTPException(404, "研报不存在")
    path, name = hit
    return FileResponse(str(path), filename=name)


@app.delete("/api/myreports/{rid}")
def myreports_delete(rid: str):
    return {"data": {"ok": mr.delete_report(rid)}}


class CloseIn(BaseModel):
    code: str
    date: str
    price: float
    shares: float
    cost: float


@app.post("/api/portfolio/close")
def portfolio_close(c: CloseIn):
    """记一笔已清仓（已实现盈亏）。存本地。"""
    code = (c.code or "").strip()
    if not code.isdigit() or len(code) != 6:
        raise HTTPException(400, "代码必须是 6 位数字")
    if c.price <= 0 or c.shares <= 0:
        raise HTTPException(400, "清仓价与股数必须大于 0")
    # 买入成本不限正负（同持仓录入）：按 (清仓价 - 成本) × 股数 的结果计算已实现盈亏。
    date = (c.date or "").strip()
    if not date:
        raise HTTPException(400, "请填清仓日期")
    from datetime import datetime
    try:
        datetime.strptime(date, "%Y-%m-%d")
    except ValueError:
        raise HTTPException(400, "清仓日期格式应为 YYYY-MM-DD") from None
    return {"data": pf.close_position(code, date, c.price, c.shares, c.cost)}


@app.delete("/api/portfolio/close")
def portfolio_close_remove(index: int = Query(...)):
    return {"data": pf.remove_closed(index)}


@app.post("/api/portfolio/refresh")
def portfolio_refresh():
    """手动刷新：立即重拉行情算盈亏。"""
    try:
        return {"data": pf.get_portfolio()}
    except Exception as e:  # noqa: BLE001
        raise HTTPException(502, f"刷新失败：{e}") from e


@app.get("/api/radar")
def radar():
    """资讯雷达：12 赛道公开 RSS 资讯（读缓存，无缓存返回赛道骨架）。"""
    try:
        return {"data": newsradar.get_radar(force=False)}
    except Exception as e:  # noqa: BLE001
        raise HTTPException(502, f"资讯雷达异常：{e}") from e


@app.post("/api/radar/refresh")
def radar_refresh():
    """强制重抓全部 RSS 源（耗时约 20-40s），更新缓存。"""
    try:
        return {"data": newsradar.fetch_radar()}
    except Exception as e:  # noqa: BLE001
        raise HTTPException(502, f"资讯雷达刷新失败：{e}") from e


@app.get("/api/market-monitor")
def market_monitor():
    """直接读取根目录唯一母表；不经过发布包、后端副本或内存回退。"""
    project_root = Path(__file__).resolve().parent.parent
    try:
        mother_root = project_root / "market-monitor"
        target_date = market_monitor_builder.latest_market_date(mother_root)
        if not target_date:
            raise RuntimeError("market_core.csv 没有有效日期")
        report = market_monitor_builder.build_report_data(target_date, mother_root)
        return {"data": report, "publication": {
            "data_date": target_date,
            "source": "canonical-mother-tables",
            "using_fallback": False,
        }}
    except Exception as exc:
        raise HTTPException(502, f"读取市场母表失败：{exc}") from exc


@app.get("/api/stock-pool")
def stock_pool():
    """核心股票池页面只读取本地最新日更 bundle，避免网络抖动拖慢或覆盖本地修复结果。"""
    try:
        local_bundle = stock_pool_builder.load_bundled_latest()
        bundle = local_bundle
        source = "local-bundle"
        if bundle is None:
            raise RuntimeError("没有可用的已验证股票池发布包")
        return {"data": bundle["payload"], "publication": {
            "data_date": bundle["data_date"],
            "published_at": bundle.get("published_at"),
            "source": source,
            "using_fallback": False,
        }}
    except Exception as e:  # noqa: BLE001
        raise HTTPException(502, f"股票池数据异常：{e}") from e


@app.post("/api/stock-pool/add")
async def stock_pool_add(request: Request):
    """新增标的到核心股票池（自动同步 GitHub 真源）。"""
    try:
        body = await request.json()
        result = stock_pool_builder.add_stock(body.get("name", ""), body.get("code"), body.get("industry", ""))
        if not result.get("ok"):
            raise HTTPException(400, result.get("error", "添加失败"))
        return {"data": result, "payload": stock_pool_builder.build_stock_pool_payload()}
    except HTTPException:
        raise
    except Exception as e:  # noqa: BLE001
        raise HTTPException(502, f"添加失败：{e}") from e


@app.post("/api/stock-pool/add-batch")
async def stock_pool_add_batch(request: Request):
    """批量添加标的（代码列表 → 自动补名称，同步 GitHub 真源）。"""
    try:
        body = await request.json()
        result = stock_pool_builder.add_stock_batch(body.get("codes") or [])
        if not result.get("ok"):
            raise HTTPException(400, result.get("error", "批量添加失败"))
        return {"data": result, "payload": stock_pool_builder.build_stock_pool_payload()}
    except HTTPException:
        raise
    except Exception as e:  # noqa: BLE001
        raise HTTPException(502, f"批量添加失败：{e}") from e


@app.delete("/api/stock-pool/remove")
def stock_pool_remove(instrument_id: str = ""):
    """从核心股票池移除标的（自动同步 GitHub 真源）。"""
    try:
        result = stock_pool_builder.remove_stock(instrument_id)
        if not result.get("ok"):
            raise HTTPException(400, result.get("error", "移除失败"))
        return {"data": result, "payload": stock_pool_builder.build_stock_pool_payload()}
    except HTTPException:
        raise
    except Exception as e:  # noqa: BLE001
        raise HTTPException(502, f"移除失败：{e}") from e


@app.post("/api/stock-pool/sync")
def stock_pool_sync():
    """手动触发同步到 GitHub 真源。"""
    try:
        result = stock_pool_builder.sync_to_github()
        if not result.get("ok"):
            raise HTTPException(502, result.get("error", "同步失败"))
        return {"data": result}
    except HTTPException:
        raise
    except Exception as e:  # noqa: BLE001
        raise HTTPException(502, f"同步失败：{e}") from e


@app.get("/api/stock-pool/focus")
def stock_pool_focus_get():
    """近期关注列表（定义层并入 pool.json，和核心股票池一起做 GitHub 备份）。"""
    try:
        try:
            codes = _ds_get(
                "stock-pool:focus:main",
                TTL["minute"],
                stock_pool_builder.fetch_remote_focus,
                valid=lambda value: isinstance(value, list),
                provider="github-stock-pool-focus",
            )
        except Exception:
            codes = stock_pool_builder.load_focus()
        return {"data": {"codes": codes}}
    except Exception as e:  # noqa: BLE001
        raise HTTPException(502, f"读取近期关注失败：{e}") from e


@app.post("/api/stock-pool/focus")
async def stock_pool_focus_save(request: Request):
    """保存近期关注列表（写回 pool.json 并同步 GitHub 真源）。"""
    try:
        body = await request.json()
        codes = body.get("codes", [])
        result = stock_pool_builder.save_focus(codes)
        if not result.get("ok"):
            raise HTTPException(502, result.get("error", "保存失败"))
        _ds_invalidate("stock-pool:focus:main")
        return {"data": {"ok": True, "count": len(codes), "commit": result.get("commit")}}
    except HTTPException:
        raise
    except Exception as e:  # noqa: BLE001
        raise HTTPException(502, f"保存近期关注失败：{e}") from e


@app.get("/api/morning-brief")
def morning_brief_payload(date: str | None = None):
    """统一交易晨报 payload（冻结研究成品；Dashboard 只消费展示）。默认取最近可用日期。"""
    dates = morning_brief.list_dates()
    date = date or (dates[-1] if dates else None)
    if not date:
        raise HTTPException(404, "暂无晨报 payload")
    payload = morning_brief.load_payload(date)
    if payload is None:
        raise HTTPException(404, f"未找到 {date} 的晨报 payload")
    return {"data": payload, "dates": dates}


@app.get("/api/morning-brief/download")
def morning_brief_download(date: str | None = None, kind: str = "html"):
    """下载晨报 HTML / PDF 产物（与 payload 同源）。默认取最近可用日期。"""
    dates = morning_brief.list_dates()
    date = date or (dates[-1] if dates else None)
    if not date:
        raise HTTPException(404, "暂无晨报产物")
    path = morning_brief.resolve_artifact(date, kind)
    if path is None:
        raise HTTPException(404, f"未找到 {date} 的 {kind} 产物")
    media = "application/pdf" if kind == "pdf" else "text/html; charset=utf-8"
    filename = f"统一交易晨报_{date}.{kind}"
    return FileResponse(path, media_type=media, filename=filename)


@app.get("/api/market/overview")
def market_overview():
    """市场情绪 + 板块资金流（板块/大盘级，全站共享缓存 5 分钟）。"""
    try:
        return {"data": market.get_overview()}
    except Exception as e:  # noqa: BLE001
        raise HTTPException(502, f"市场总览异常：{e}") from e


@app.get("/api/market/overview-v2")
def market_overview_v2():
    """市场总览聚合端点：并发取实时层全部数据，单源失败只置空并标记降级，不拖垮整页。

    返回字段（对旧 /api/market/overview 只增不改，兼容 sentiment/sectors/updated）：
      indices / global_indices / sentiment / sectors / emotion / turnover_top / updated / providers
    前端市场总览页由 5 个实时请求合并为这 1 个，快照层（晨报/市场监控）仍独立。
    """
    from concurrent.futures import ThreadPoolExecutor, TimeoutError
    from datetime import datetime

    from dataservice import provider_health

    def _safe(fn, fallback):
        try:
            return fn()
        except Exception as e:  # noqa: BLE001
            print(f"[overview-v2] 子数据源失败: {e}")
            return fallback

    tasks = {
        "indices": (market.get_a_indices, []),
        "global_indices": (market.get_global_indices, []),
        "sentiment": (market.get_sentiment, None),
        "sectors": (market.get_sectors, []),
        "emotion": (market.get_short_term_emotion, None),
        "turnover_top": (market.get_turnover_top, None),
    }

    result: dict = {}
    ex = ThreadPoolExecutor(max_workers=len(tasks))
    try:
        futures = {k: ex.submit(_safe, fn, fb) for k, (fn, fb) in tasks.items()}
        for k, fut in futures.items():
            fallback = tasks[k][1]
            try:
                result[k] = fut.result(timeout=8)
            except TimeoutError:
                print(f"[overview-v2] 子数据源超时: {k}")
                result[k] = fallback
    finally:
        ex.shutdown(wait=False, cancel_futures=True)

    result["updated"] = datetime.now(market.BEIJING).strftime("%Y-%m-%d %H:%M")
    result["providers"] = provider_health()
    return {"data": result}


@app.get("/api/market/emotion")
def market_emotion():
    """短线情绪：连板梯队 / 最高连板 / 炸板率 / 封板率 / 晋级率 / 涨跌停家数。

    含连板梯队个股清单（code/name/连板数等）——2026-07-05 起如实展示客观公开榜单（东财同款），
    只呈现事实，不附推荐/评分/预测/买卖时机。全站共享缓存 5 分钟。
    """
    try:
        return {"data": market.get_short_term_emotion()}
    except Exception as e:  # noqa: BLE001
        raise HTTPException(502, f"短线情绪异常：{e}") from e


@app.get("/api/market/turnover-top")
def market_turnover_top():
    """全市场成交额榜 Top20（客观公开榜单数据，非推荐/非预测/不评分）。全站共享缓存 5 分钟。"""
    try:
        return {"data": market.get_turnover_top()}
    except Exception as e:  # noqa: BLE001
        raise HTTPException(502, f"成交额榜异常：{e}") from e


@app.get("/api/global/indices")
def global_indices():
    """全球指数快照（道指 / 标普500 / 纳斯达克 / 恒生 / 恒生科技）—— A 股看隔夜外围脸色。缓存 5 分钟。"""
    try:
        return {"data": market.get_global_indices()}
    except Exception as e:  # noqa: BLE001
        raise HTTPException(502, f"全球指数异常：{e}") from e


@app.get("/api/global/stock")
def global_stock(symbol: str = Query(..., min_length=1, max_length=16)):
    """美股 / 港股个股聚合：行情 + 关键财务指标（东财域内源）。symbol 如 AAPL / BABA / 00700。"""
    try:
        data = gstock.us_hk_stock(symbol.strip())
        if not data:
            raise HTTPException(404, f"未找到美股/港股代码「{symbol}」")
        return {"data": data}
    except HTTPException:
        raise
    except Exception as e:  # noqa: BLE001
        raise HTTPException(502, f"美港股查询异常：{e}") from e


@app.get("/api/indices")
def indices():
    """A股大盘指数实时行情（上证/深证成指/创业板指/沪深300）。仅标准库，短 TTL 缓存。"""
    try:
        return {"data": market.get_a_indices()}
    except Exception as e:  # noqa: BLE001
        raise HTTPException(502, f"指数行情异常：{e}") from e


@app.get("/api/quote")
def quote(codes: str = Query(..., description="逗号分隔的 6 位代码")):
    """实时行情：现价/涨跌/PE/PB/市值/换手/涨跌停。仅标准库，永远可用。短 TTL 缓存 + 请求合并。"""
    # 排序去重：让 "600519,000858" 与 "000858,600519" 命中同一缓存，且多标签页/轮询共享
    lst = sorted({c.strip() for c in codes.split(",") if c.strip()})
    if not lst or any(not c.isdigit() or len(c) != 6 for c in lst):
        raise HTTPException(400, "codes 必须是逗号分隔的 6 位数字")
    try:
        data = _ds_get("quote:" + ",".join(lst), TTL["live"], lambda: astock.tencent_quote(lst), valid=bool, provider="tencent")
        return {"data": data}
    except Exception as e:  # noqa: BLE001 — 边界统一兜底
        raise HTTPException(502, f"行情源异常：{e}") from e


import time as _time
_PCT_CACHE: dict = {}


@app.get("/api/valuation/percentile")
def valuation_percentile(code: str = Query(...)):
    """PE-TTM / PB 历史分位（近5年）。全站缓存 30 分钟/代码（历史序列日频、变化慢）。"""
    code = _validate(code)
    hit = _PCT_CACHE.get(code)
    if hit and _time.time() - hit[0] < 1800:
        return {"data": hit[1]}
    try:
        data = astock.valuation_percentile(code)
        _PCT_CACHE[code] = (_time.time(), data)
        return {"data": data}
    except astock.DependencyMissing as e:
        raise HTTPException(501, str(e)) from e
    except Exception as e:  # noqa: BLE001
        raise HTTPException(502, f"估值分位异常：{e}") from e


_SPOT_CACHE: dict = {}


@app.get("/api/sina-spot")
def sina_spot(codes: str = Query(...)):
    """新浪实时行情（nf_ 国内期货主力连续 / hf_ 国际商品原油）：现价/昨收/涨跌。缓存 20 秒。"""
    lst = [c.strip() for c in codes.split(",") if c.strip()]
    if not lst:
        raise HTTPException(400, "codes 为空")
    key = ",".join(lst)
    hit = _SPOT_CACHE.get(key)
    if hit and _time.time() - hit[0] < 20:
        return {"data": hit[1]}
    try:
        data = astock.sina_spot(lst)
        _SPOT_CACHE[key] = (_time.time(), data)
        return {"data": data}
    except Exception as e:  # noqa: BLE001
        raise HTTPException(502, f"新浪实时行情异常：{e}") from e


_GOLD_CACHE: dict = {}


@app.get("/api/gold-spot")
def gold_spot():
    """伦敦金现货（XAU/USD）实时价：新浪 hf_XAU，代理给前端。缓存 30 秒。"""
    hit = _GOLD_CACHE.get("xau")
    if hit and _time.time() - hit[0] < 30:
        return {"data": hit[1]}
    try:
        data = astock.gold_spot()
        _GOLD_CACHE["xau"] = (_time.time(), data)
        return {"data": data}
    except Exception as e:  # noqa: BLE001
        raise HTTPException(502, f"黄金现货源异常：{e}") from e


_ANN_CACHE: dict = {}


@app.get("/api/announcements")
def announcements(code: str = Query(...)):
    """个股近期公告（东财，仅 requests）。缓存 15 分钟/代码。"""
    code = _validate(code)
    hit = _ANN_CACHE.get(code)
    if hit and _time.time() - hit[0] < 900:
        return {"data": hit[1]}
    try:
        data = astock.announcements(code)
        _ANN_CACHE[code] = (_time.time(), data)
        return {"data": data}
    except Exception as e:  # noqa: BLE001
        raise HTTPException(502, f"公告源异常：{e}") from e


class HalfYearReportReq(BaseModel):
    codes: list[str] = []
    days: int = 1
    names: dict[str, str] = {}


_EMPTY_HYR = {
    "window_days": 0, "scanned": 0, "published": 0, "covered": 0,
    "scan_complete": True, "requested_codes": 0, "scanned_batches": 0,
    "announcement_requests": 0, "announcement_rows": 0, "fetched_at": "",
    "groups": {"big_beat": [], "meet": [], "pending": []},
}

_HYR_CACHE: dict = {}


@app.post("/api/half-year-report")
def half_year_report(req: HalfYearReportReq):
    """自选股池中近 N 天内发布半年报的公司聚合报告。

    东财公告批量分页筛半年报 + 同花顺 F10 财务摘要取实际净利和同比，
    再读取同花顺盈利预测计算半年完成度。

    请求体：{ codes: ["600519", ...], days: 1, names?: {code: 中文名} }
    缓存：30 分钟（key = (frozenset(codes), days)，同一批股票复用结果）
    """
    codes = [c for c in (req.codes or []) if re.fullmatch(r"\d{6}", c)]
    days = max(1, min(int(req.days or 1), 30))
    if not codes:
        return {"data": {**_EMPTY_HYR, "window_days": days, "fetched_at": _time.strftime("%Y-%m-%dT%H:%M:%S")}}

    key = (frozenset(codes), days)
    hit = _HYR_CACHE.get(key)
    if hit and _time.time() - hit[0] < 1800:
        return {"data": hit[1]}

    try:
        rep = astock.half_year_report(codes, window_days=days)
        # 把 names 合并进结果（前端传过来的自选股名称）
        nmap = req.names or {}
        for g in rep["groups"].values():
            for row in g:
                row["name"] = nmap.get(row["code"], "")
        _HYR_CACHE[key] = (_time.time(), rep)
        return {"data": rep}
    except Exception as e:  # noqa: BLE001
        raise HTTPException(502, f"半年报聚合异常：{e}") from e


_FIN_CACHE: dict = {}


@app.get("/api/financials")
def financials(code: str = Query(...)):
    """财务关键指标（同花顺财务摘要，最新报告期）。缓存 30 分钟/代码。"""
    code = _validate(code)
    hit = _FIN_CACHE.get(code)
    if hit and _time.time() - hit[0] < 1800:
        return {"data": hit[1]}
    try:
        data = astock.financials(code)
        _FIN_CACHE[code] = (_time.time(), data)
        return {"data": data}
    except astock.DependencyMissing as e:
        raise HTTPException(501, str(e)) from e
    except Exception as e:  # noqa: BLE001
        raise HTTPException(502, f"财务摘要异常：{e}") from e


@app.get("/api/valuation")
def valuation(code: str = Query(...)):
    """完整估值：行情 + 一致预期 + 前向PE/PEG/消化年数。"""
    code = _validate(code)
    try:
        return {"data": astock.full_valuation(code)}
    except ValueError as e:
        raise HTTPException(404, str(e)) from e
    except Exception as e:  # noqa: BLE001
        raise HTTPException(502, f"估值计算异常：{e}") from e


@app.get("/api/reports")
def reports(code: str = Query(...), pages: int = Query(2, ge=1, le=5)):
    """个股研报列表（东财，含 PDF 链接）。仅需 requests。"""
    code = _validate(code)
    try:
        rows = astock.eastmoney_reports(code, max_pages=pages)
        for r in rows:
            r["pdfUrl"] = astock.pdf_url(r.get("infoCode", "")) if r.get("infoCode") else None
        return {"data": rows}
    except Exception as e:  # noqa: BLE001
        raise HTTPException(502, f"研报源异常：{e}") from e


@app.get("/api/news")
def news(code: str = Query(...), limit: int = Query(20, ge=1, le=50)):
    """个股新闻（东财，需 akshare）。"""
    code = _validate(code)
    try:
        return {"data": astock.stock_news(code, limit=limit)}
    except astock.DependencyMissing as e:
        raise HTTPException(501, str(e)) from e
    except Exception as e:  # noqa: BLE001
        raise HTTPException(502, f"新闻源异常：{e}") from e


@app.get("/api/macro-brief")
def macro_brief(force: bool = Query(False)):
    """宏观速览 + 重大要闻（自动采集：akshare 中国宏观 + 财联社/东财当天要闻）。

    AI 当日复盘数据源，替代静态快照。30 分钟缓存。
    """
    try:
        return {"data": macro_brief_mod.get_macro_brief(force=force)}
    except Exception as e:  # noqa: BLE001
        raise HTTPException(502, f"宏观速览采集异常：{e}") from e


@app.get("/api/info")
def info(code: str = Query(...)):
    """个股基本面：行业/股本/上市时间（需 akshare）。"""
    code = _validate(code)
    try:
        return {"data": astock.individual_info(code)}
    except astock.DependencyMissing as e:
        raise HTTPException(501, str(e)) from e
    except Exception as e:  # noqa: BLE001
        raise HTTPException(502, f"基本面源异常：{e}") from e


@app.get("/api/disclosure")
def disclosure(code: str = Query(...)):
    """巨潮公告列表（需 akshare）。"""
    code = _validate(code)
    try:
        return {"data": astock.disclosure(code)}
    except astock.DependencyMissing as e:
        raise HTTPException(501, str(e)) from e
    except Exception as e:  # noqa: BLE001
        raise HTTPException(502, f"公告源异常：{e}") from e


def _kline_sina(symbol: str, period: str, offset: int):
    """新浪期货主力连续日 K：AG0 沪银 / CU0 沪铜 / LC0 碳酸锂 / T0 国债期货。
    返回全部历史（3000+ 条），截取最近 offset 条；OHLCV 形状与腾讯/yahoo 一致。
    """
    import urllib.parse  # noqa: PLC0415
    if period != "day":
        raise HTTPException(400, "新浪期货源仅支持 day 日线")
    url = (
        "https://stock2.finance.sina.com.cn/futures/api/jsonp.php/var%20_/"
        f"InnerFuturesNewService.getDailyKLine?symbol={urllib.parse.quote(symbol)}"
    )
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 financial-data", "Referer": "https://finance.sina.com.cn/"})
        text = urllib.request.build_opener(urllib.request.ProxyHandler({})).open(req, timeout=10).read().decode("utf-8")
        # JSONP 响应：var _( [{d,o,h,l,c,v,p,s}, ...] );
        m = re.search(r"\((\[.*\])\)", text, re.S)
        if not m:
            raise HTTPException(502, "新浪期货 K 线返回格式异常")
        arr = json.loads(m.group(1))
        if not arr:
            raise HTTPException(404, f"新浪期货无 {symbol} 数据")
        out = []
        for r in arr[-offset:]:
            out.append({
                "date": r.get("d"),
                "open": float(r.get("o") or 0),
                "close": float(r.get("c") or 0),
                "high": float(r.get("h") or 0),
                "low": float(r.get("l") or 0),
                "volume": float(r.get("v") or 0),
            })
        return {"data": out, "symbol": symbol, "period": period, "count": len(out),
                "source": "sina", "currency": "CNY"}
    except HTTPException:
        raise
    except Exception as e:  # noqa: BLE001
        raise HTTPException(502, f"新浪期货 K 线获取失败：{e}") from e


@app.get("/api/kline")
def kline(code: str = Query(...), period: str = Query("day"), offset: int = Query(180, ge=1, le=800)):
    """K线：腾讯（A/H/美股股票）+ Yahoo v8（指数/期货/外汇/国债收益率，code 加 y: 前缀）
    + 新浪（国内期货主力连续 AG0/CU0/LC0/T0，code 加 s: 前缀）。
    period=day|week|month|60m。day/week/month 走前复权/复权口径；60m 仅腾讯支持。
    返回 [{date,open,close,high,low,volume}]。"""
    code = code.strip()
    # Yahoo 源：code 以 "y:" 开头 → symbol = "y:^GSPC"[2:]
    if code.lower().startswith("y:"):
        return _kline_yahoo(code[2:], period.lower(), offset)
    # 新浪期货源：code 以 "s:" 开头 → symbol = "s:AG0"[2:]
    if code.lower().startswith("s:"):
        return _kline_sina(code[2:], period.lower(), offset)
    code = code.upper()
    # 带前缀代码：指数（sh000001/sz399006）、港股指数（hkHSI/hkHSTECH）等直接透传
    if re.match(r"^(SH|SZ)\d{6}$", code):
        sym = code.lower()
    elif re.match(r"^HK[A-Z0-9]+$", code):
        sym = code.lower()
    elif re.match(r"^US[A-Z0-9.\^]+$", code):
        sym = "us" + code[2:]
    elif len(code) == 6 and code.isdigit():
        sym = ("sh" if code.startswith(("6", "9")) else "sz") + code
    elif len(code) == 5 and code.isdigit():
        sym = "hk" + code
    elif code.isalpha():
        sym = "us" + code
    else:
        raise HTTPException(400, "无法识别代码（A 股 6 位 / 港股 5 位 / 美股字母 / 指数 sh000001 等）")
    period = period.lower()
    if period not in ("day", "week", "month", "60m"):
        raise HTTPException(400, "period 仅支持 day|week|month|60m")
    try:
        import urllib.request  # noqa: PLC0415
        _no_proxy = urllib.request.build_opener(urllib.request.ProxyHandler({}))  # 国内财经站直连，绕系统代理
        if period == "60m":
            # 1 小时线走分钟 K 线接口（不复权），参数 m60
            url = f"https://ifzq.gtimg.cn/appstock/app/kline/mkline?param={sym},m60,,{offset}"
            key = "m60"
        else:
            url = f"https://web.ifzq.gtimg.cn/appstock/app/fqkline/get?param={sym},{period},,,{offset},qfq"
            key = f"qfq{period}"
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        d = json.loads(_no_proxy.open(req, timeout=10).read().decode("utf-8"))
        node = d.get("data", {}).get(sym, {}) or {}
        raw = node.get(key) or node.get(period) or []
        out = []
        for r in raw:
            if len(r) >= 6:
                out.append({"date": r[0], "open": float(r[1]), "close": float(r[2]),
                            "high": float(r[3]), "low": float(r[4]), "volume": float(r[5])})
        return {"data": out, "symbol": sym, "period": period, "count": len(out)}
    except Exception as e:  # noqa: BLE001
        raise HTTPException(502, f"K线获取失败：{e}") from e


def _kline_yahoo(symbol: str, period: str, offset: int):
    """Yahoo Finance v8 chart：美股指数 / 商品期货 / 外汇 / 国债收益率指数。
    仅支持日/周/月线（60m 走腾讯）。返回与腾讯源相同的 OHLCV 形状，前端无感。
    来源参考：~/Desktop/my_skill/skills/financial-data/providers/yahoo.md + adapters/yahoo_chart.py
    """
    import urllib.parse  # noqa: PLC0415
    from datetime import datetime, timezone  # noqa: PLC0415
    period_map = {"day": "1d", "week": "1wk", "month": "1mo"}
    if period not in period_map:
        raise HTTPException(400, "Yahoo 源仅支持 day/week/month（60m 请走腾讯源）")
    interval = period_map[period]
    # range 按 offset 选：1mo≈22d, 3mo≈66d, 6mo≈130d, 1y≈252d, 2y, 5y, 10y, ytd, max
    range_map = {96: "6mo", 180: "1y", 252: "1y", 500: "2y", 800: "5y"}
    rng = range_map.get(offset, "1y")
    url = (
        f"https://query2.finance.yahoo.com/v8/finance/chart/{urllib.parse.quote(symbol)}"
        f"?interval={interval}&range={rng}&events=div,splits"
    )
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 financial-data"})
        d = json.loads(urllib.request.build_opener(urllib.request.ProxyHandler({})).open(req, timeout=10).read().decode("utf-8"))
        result = (d.get("chart") or {}).get("result") or []
        if not result:
            err = (d.get("chart") or {}).get("error")
            raise HTTPException(404, f"Yahoo 无 {symbol} 数据" + (f"：{err}" if err else ""))
        r = result[0]
        meta = r.get("meta") or {}
        timestamps = r.get("timestamp") or []
        quotes = (r.get("indicators") or {}).get("quote") or [{}]
        q = quotes[0] if quotes else {}
        opens = q.get("open") or []
        highs = q.get("high") or []
        lows = q.get("low") or []
        closes = q.get("close") or []
        vols = q.get("volume") or []
        out = []
        for i, ts in enumerate(timestamps):
            try:
                o, c, h, l = opens[i], closes[i], highs[i], lows[i]
            except IndexError:
                continue
            if o is None or c is None:
                continue
            dt = datetime.fromtimestamp(int(ts), timezone.utc).strftime("%Y-%m-%d")
            out.append({
                "date": dt,
                "open": float(o),
                "close": float(c),
                "high": float(h),
                "low": float(l),
                "volume": float(vols[i] or 0) if i < len(vols) else 0.0,
            })
        # 单位提示：^TNX 等收益率指数单位是 %（不是价格）
        unit = "%" if symbol.startswith("^TNX") or symbol.startswith("^TYX") or symbol.startswith("^FVX") or symbol.startswith("^IRX") else None
        return {
            "data": out,
            "symbol": symbol,
            "period": period,
            "count": len(out),
            "source": "yahoo",
            "currency": meta.get("currency"),
            "unit": unit,
            # 兜底实时值：Yahoo 部分品种（如 DX-Y.NYB 美元指数）日 K 偶发只有 1 根 bar，
            # 用 meta 实时价/昨收补，前端在 bars<2 时优先用 latest 而非回退晨报快照
            "latest": meta.get("regularMarketPrice"),
            "prev_close": meta.get("chartPreviousClose"),
        }
    except HTTPException:
        raise
    except Exception as e:  # noqa: BLE001
        raise HTTPException(502, f"Yahoo K线获取失败：{e}") from e


@app.get("/api/finance")
def finance(code: str = Query(...)):
    """季报财务快照（需 mootdx）。"""
    code = _validate(code)
    try:
        return {"data": astock.finance(code)}
    except astock.DependencyMissing as e:
        raise HTTPException(501, str(e)) from e
    except Exception as e:  # noqa: BLE001
        raise HTTPException(502, f"财务源异常：{e}") from e


# ---------------------------------------------------------------------------
# 资金面 / 筹码 / 信号（东财数据中心，v3.3 并入）—— 均为「用户查的那只股」的公开数据。
# 东财有 1s 限流，这些多为日/季级静态数据，统一走 30 分钟缓存，进一步降低被封风险。
# ---------------------------------------------------------------------------

_DC_CACHE: dict = {}  # key=(endpoint, code) -> (ts, data)


def _cached(endpoint: str, code: str, ttl: int, fetch):
    key = (endpoint, code)
    hit = _DC_CACHE.get(key)
    if hit and _time.time() - hit[0] < ttl:
        return hit[1]
    data = fetch()
    _DC_CACHE[key] = (_time.time(), data)
    return data


@app.get("/api/margin")
def margin(code: str = Query(...)):
    """融资融券明细（东财，日级）。缓存 30 分钟。"""
    code = _validate(code)
    try:
        return {"data": _cached("margin", code, 1800, lambda: astock.margin_trading(code))}
    except Exception as e:  # noqa: BLE001
        raise HTTPException(502, f"融资融券异常：{e}") from e


@app.get("/api/block-trade")
def block_trade(code: str = Query(...)):
    """大宗交易（东财）。缓存 30 分钟。"""
    code = _validate(code)
    try:
        return {"data": _cached("block", code, 1800, lambda: astock.block_trade(code))}
    except Exception as e:  # noqa: BLE001
        raise HTTPException(502, f"大宗交易异常：{e}") from e


@app.get("/api/holders")
def holders(code: str = Query(...)):
    """股东户数变化（东财，季度级）。缓存 30 分钟。"""
    code = _validate(code)
    try:
        return {"data": _cached("holders", code, 1800, lambda: astock.holder_num_change(code))}
    except Exception as e:  # noqa: BLE001
        raise HTTPException(502, f"股东户数异常：{e}") from e


@app.get("/api/dividend")
def dividend(code: str = Query(...)):
    """分红送转历史（东财）。缓存 30 分钟。"""
    code = _validate(code)
    try:
        return {"data": _cached("dividend", code, 1800, lambda: astock.dividend_history(code))}
    except Exception as e:  # noqa: BLE001
        raise HTTPException(502, f"分红送转异常：{e}") from e


@app.get("/api/fund-flow")
def fund_flow(code: str = Query(...)):
    """个股资金流（东财 push2his，120 日主力净流入）。缓存 15 分钟。
    注：push2his 对部分大陆住宅 IP 有间歇风控，可能返回空（非代码问题）。"""
    code = _validate(code)
    try:
        return {"data": _cached("fundflow", code, 900, lambda: astock.stock_fund_flow_120d(code))}
    except Exception as e:  # noqa: BLE001
        raise HTTPException(502, f"资金流异常：{e}") from e


@app.get("/api/dragon-tiger")
def dragon_tiger(code: str = Query(...)):
    """龙虎榜：该股近期上榜记录 + 买卖席位 + 机构净买（东财）。缓存 30 分钟。"""
    code = _validate(code)
    try:
        return {"data": _cached("dt", code, 1800, lambda: astock.dragon_tiger_board(code))}
    except Exception as e:  # noqa: BLE001
        raise HTTPException(502, f"龙虎榜异常：{e}") from e


@app.get("/api/lockup")
def lockup(code: str = Query(...)):
    """限售解禁日历：历史解禁 + 未来 90 天待解禁（东财）。缓存 30 分钟。"""
    code = _validate(code)
    try:
        return {"data": _cached("lockup", code, 1800, lambda: astock.lockup_expiry(code))}
    except Exception as e:  # noqa: BLE001
        raise HTTPException(502, f"解禁日历异常：{e}") from e


@app.get("/api/blocks")
def blocks(code: str = Query(...)):
    """个股所属板块/概念归属（东财 slist）。缓存 30 分钟。"""
    code = _validate(code)
    try:
        return {"data": _cached("blocks", code, 1800, lambda: astock.concept_blocks(code))}
    except Exception as e:  # noqa: BLE001
        raise HTTPException(502, f"板块归属异常：{e}") from e


@app.get("/api/hot-concepts")
def hot_concepts(code: str = Query(...)):
    """个股当下被市场归到哪些概念在炒（东财热门概念命中）。缓存 15 分钟。"""
    code = _validate(code)
    try:
        return {"data": _cached("hotcon", code, 900, lambda: astock.hot_concepts(code))}
    except Exception as e:  # noqa: BLE001
        raise HTTPException(502, f"热门概念异常：{e}") from e


@app.get("/api/investor-qa")
def investor_qa(code: str = Query(...)):
    """互动易问答（巨潮）：投资者提问 + 公司回复。缓存 15 分钟。"""
    code = _validate(code)
    try:
        return {"data": _cached("irm", code, 900, lambda: astock.investor_qa(code))}
    except Exception as e:  # noqa: BLE001
        raise HTTPException(502, f"互动易异常：{e}") from e


@app.get("/api/industry")
def industry(top: int = Query(20, ge=5, le=50)):
    """全行业涨跌幅排名（东财行业板块，板块级、零个股名单）。缓存 5 分钟。"""
    key = ("industry", str(top))
    hit = _DC_CACHE.get(key)
    if hit and _time.time() - hit[0] < 300:
        return {"data": hit[1]}
    try:
        data = astock.industry_comparison(top_n=top)
        _DC_CACHE[key] = (_time.time(), data)
        return {"data": data}
    except Exception as e:  # noqa: BLE001
        raise HTTPException(502, f"行业排名异常：{e}") from e
