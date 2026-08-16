/**
 * 市场概览 —— 三页合并的过渡产物（方案 B 第一步）
 * 数据源：实时层 market.py（指数/情绪/板块资金/成交额榜）+ 快照层 report_data（申万行业）+ 晨报 payload
 * 原三页（a股监控板 / 统一交易晨报 / 每日复盘）保留，本页做好后由用户确认再删。
 */
import { useEffect, useMemo, useRef, useState } from "react";
import { RefreshCw, Loader2, Gauge, Flame, TrendingUp, TrendingDown, ArrowDownUp, Wallet, Newspaper, AlertCircle, Sparkles, X } from "lucide-react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { PageHeader } from "@/components/ui/PageHeader";
import { GlassCard } from "@/components/ui/GlassCard";
import { AStockMonitor, TrendCharts, type ReportData } from "@/pages/AStockMonitor";
import { AssetOverviewTable, BRIEF_CODE_MAP, type AssetRow } from "@/components/ui/AssetOverviewTable";
import { SectorTrendTable, FundRotation, TurnoverTopTable, LianbanTable, HotStockMatrixTable } from "@/components/ui/marketPanels";
import { hasLlm, chatStream } from "@/lib/llm";
import { cn } from "@/lib/utils";
import "./astock-monitor.css";  // 加载 .asm-root 样式给 TrendCharts 用
import {
  api, ApiError,
  type IndexQuote, type GlobalIndex, type MarketOverview, type MarketSentiment, type ShortTermEmotion,
  type TurnoverTop, type SectorFlow,
} from "@/lib/api";

const fmt = (v: number | null | undefined, suffix = "") => (v == null || Number.isNaN(v) ? "—" : `${v}${suffix}`);
const pct = (v: number | null | undefined) => (v == null || !Number.isFinite(Number(v)) ? "—" : `${Number(v) > 0 ? "+" : ""}${Number(v).toFixed(2)}%`);
const pctColor = (v: number | null | undefined) => (v != null && v > 0 ? "text-danger" : v != null && v < 0 ? "text-success" : "text-muted-foreground");
const yi = (v: number | null | undefined) => (v == null ? "—" : `${(v / 1e8).toFixed(2)} 亿`);

// 申万一级行业（report_data.sw_industry_latest 中文键）
interface SwRow { 日期: string; 一级行业: string; 收盘价: number | null; 成交额: number | null; 日收益率: number | null }
interface BriefPayload {
  report_meta?: { date?: string; title?: string };
  summary?: {
    kicker?: string;
    overnight_changes?: { title?: string; text?: string }[];
    china_changes?: { title?: string; text?: string }[];
  };
  china_market?: { title?: string; kicker?: string; warning?: string; switch?: string; breadth?: string; industry?: string };
  mainlines?: { kicker?: string; items?: { tags?: string[]; title?: string; paras?: string[] }[] };
}

export function MarketOverview() {
  const [indices, setIndices] = useState<IndexQuote[]>([]);
  const [globalIdx, setGlobalIdx] = useState<GlobalIndex[]>([]);
  const [overview, setOverview] = useState<MarketOverview | null>(null);
  const [emotion, setEmotion] = useState<ShortTermEmotion | null>(null);
  const [turnover, setTurnover] = useState<TurnoverTop | null>(null);
  const [brief, setBrief] = useState<BriefPayload | null>(null);
  const [reportData, setReportData] = useState<ReportData | null>(null);
  const [loading, setLoading] = useState(true);
  const [err, setErr] = useState<string | null>(null);
  const [updated, setUpdated] = useState("");
  const runIdRef = useRef(0);

  const load = async () => {
    const rid = ++runIdRef.current;
    setLoading(true); setErr(null);
    const ok = <T,>(set: (v: T) => void) => (v: T) => { if (rid === runIdRef.current) set(v); };
    const safe = (p: Promise<unknown>, fallback: unknown = null) => p.catch(() => fallback);

    const [ind, gIdx, ov, emo, tt, br, mon] = await Promise.all([
      safe(api.indices(), []),
      safe(api.globalIndices(), []),
      safe(api.marketOverview(), null),
      safe(api.emotion(), null),
      safe(api.turnoverTop(), null),
      fetch("/api/morning-brief").then((r) => (r.ok ? r.json() : {})).catch(() => ({})),
      fetch("/api/market-monitor").then((r) => (r.ok ? r.json() : {})).catch(() => ({})),
    ]);
    if (rid !== runIdRef.current) return;

    ok(setIndices)((ind as IndexQuote[]) || []);
    ok(setGlobalIdx)((gIdx as GlobalIndex[]) || []);
    ok(setOverview)(ov as MarketOverview | null);
    ok(setEmotion)(emo as ShortTermEmotion | null);
    ok(setTurnover)(tt as TurnoverTop | null);
    ok(setReportData)((mon as { data?: ReportData } | undefined)?.data || null);
    // 晨报 payload
    const brData = (br as { data?: BriefPayload })?.data;
    ok(setBrief)(brData || null);

    const upTime = (ov as MarketOverview | null)?.updated;
    ok(setUpdated)(upTime || "");
    ok(setLoading)(false);
  };

  useEffect(() => { load(); /* eslint-disable-next-line react-hooks/exhaustive-deps */ }, []);

  // 自动更新：仅 A 股开盘时段（工作日 9:15-15:05）每 1h 一次；
  // 收盘/夜盘/周末大部分标的不动，不自动拉（需要实时时手动点「刷新」全量更新）
  useEffect(() => {
    const timer = setInterval(() => {
      const now = new Date();
      const day = now.getDay();
      if (day === 0 || day === 6) return;                       // 周末跳过
      const t = now.getHours() * 60 + now.getMinutes();
      if (t >= 9 * 60 + 15 && t <= 15 * 60 + 5) load();          // 仅开盘时段
    }, 3600_000);
    return () => clearInterval(timer);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // AI 当日复盘（LLM 流式；接入失败/未配置给提示，不阻塞页面）
  const [review, setReview] = useState("");
  const [reviewLoading, setReviewLoading] = useState(false);
  const [reviewErr, setReviewErr] = useState<string | null>(null);
  const [reviewCollapsed, setReviewCollapsed] = useState(false);
  const [needConfig, setNeedConfig] = useState(false);
  const [topN, setTopN] = useState<10 | 20>(10);
  const [ladderOpen, setLadderOpen] = useState(false);   // 连板股弹窗
  const [sectorsOpen, setSectorsOpen] = useState(false); // 板块资金全表弹窗
  const [helpOpen, setHelpOpen] = useState(false);       // 情绪等级说明弹窗
  const [hotMatrixOpen, setHotMatrixOpen] = useState(false); // 百亿成交·行业分布弹窗
  const runReview = async () => {
    setReviewErr(null); setNeedConfig(false);
    if (!hasLlm()) { setNeedConfig(true); return; }
    setReviewLoading(true); setReview("");
    const dataSummary = indices.length
      ? indices.map((i) => `${i.name} ${i.price}（${i.change_pct > 0 ? "+" : ""}${i.change_pct}%）`).join("；")
      : "（指数数据未取到）";
    const prompt =
      `以下是今天 A 股大盘的客观数据：\n${dataSummary}\n\n` +
      "请用中文做一段当天大盘复盘：整体涨跌、主要指数表现、盘面值得注意的点。";
    try {
      await chatStream([{ role: "user", content: prompt }], `今日大盘数据：${dataSummary}`, {
        onDelta: (t) => setReview((r) => r + t),
      });
    } catch (e) {
      setReviewErr(e instanceof ApiError ? e.message : "复盘失败");
    } finally {
      setReviewLoading(false);
    }
  };

  const sentiment = overview?.sentiment;
  const sectors = overview?.sectors || [];
  const emoCells = emotion ? [
    { k: "涨停", v: fmt(emotion.zt_count), c: "text-danger" },
    { k: "跌停", v: fmt(emotion.dt_count), c: "text-success" },
    { k: "炸板", v: fmt(emotion.zb_count), c: "text-muted-foreground" },
    { k: "最高连板", v: fmt(emotion.max_boards, " 板"), c: "text-danger" },
    { k: "连板家数", v: fmt(emotion.lianban_count), c: "text-danger" },
    { k: "封板率", v: emotion.seal_rate == null ? "—" : `${(emotion.seal_rate * 100).toFixed(0)}%`, c: "text-muted-foreground" },
    { k: "炸板率", v: emotion.break_rate == null ? "—" : `${(emotion.break_rate * 100).toFixed(0)}%`, c: "text-muted-foreground" },
    { k: "晋级率", v: emotion.promotion_rate == null ? "—" : `${(emotion.promotion_rate * 100).toFixed(0)}%`, c: "text-muted-foreground" },
  ] : [];
  const sentCells = sentiment ? [
    { k: "上涨", v: fmt(sentiment.up), c: "text-danger" },
    { k: "下跌", v: fmt(sentiment.down), c: "text-success" },
    { k: "平盘", v: fmt(sentiment.flat), c: "text-muted-foreground" },
    { k: "涨停", v: fmt(sentiment.zt), c: "text-danger" },
    { k: "真实涨停", v: fmt(sentiment.zt_real), c: "text-danger" },
    { k: "跌停", v: fmt(sentiment.dt), c: "text-success" },
    { k: "真实跌停", v: fmt(sentiment.dt_real), c: "text-success" },
    { k: "活跃度", v: sentiment.active || "—", c: "text-muted-foreground" },
  ] : [];

  const briefSummary = brief?.summary;
  const briefMainlines = brief?.mainlines?.items || [];

  // 资产总览合并：实时（国内 6 指数 + 港股）+ 晨报（海外/商品/汇率/国债），按 code 去重
  const assetRows = useMemo<AssetRow[]>(() => {
    const INDICES_CODE: Record<string, string> = {
      "上证指数": "sh000001", "深证成指": "sz399001", "创业板指": "sz399006",
      "沪深300": "sh000300", "上证50": "sh000016", "科创50": "sh000688",
    };
    const HK_CODE: Record<string, string> = { "恒生指数": "hkHSI", "恒生科技": "hkHSTECH" };
    const clsOf = (v: number | null | undefined): "up" | "down" | "flat" =>
      v != null && v > 0 ? "up" : v != null && v < 0 ? "down" : "flat";
    const realtime: AssetRow[] = [
      ...indices.map((i) => ({
        market: "国内", asset: i.name, value: String(i.price), change: pct(i.change_pct),
        cls: clsOf(i.change_pct), source: "实时" as const, code: INDICES_CODE[i.name], kMarket: "A" as const,
      })),
      ...globalIdx.map((g) => ({
        market: g.region === "美股" ? "海外" : "香港",
        asset: g.name, value: g.price == null ? "—" : String(g.price),
        change: g.change_pct == null ? "—" : pct(g.change_pct), cls: clsOf(g.change_pct),
        source: "实时" as const, code: HK_CODE[g.name] || BRIEF_CODE_MAP[g.name]?.code,
        kMarket: g.region === "美股" ? ("US" as const) : ("HK" as const),
      })),
    ];
    const realtimeNames = new Set(realtime.map((r) => r.asset));
    const briefRows: AssetRow[] = (
      (brief?.asset_overview as { rows?: Array<{ market: string; asset: string; value: string; change: string; cls: string; meaning?: string }> } | undefined)?.rows || []
    )
      .map((r) => {
        const cm = BRIEF_CODE_MAP[r.asset];
        return {
          market: r.market, asset: r.asset, value: r.value, change: r.change, cls: r.cls,
          source: "晨报" as const, meaning: r.meaning, code: cm?.code, kMarket: cm?.market,
        } as AssetRow;
      })
      // 过滤已被实时覆盖的（brief 里"纳斯达克综指" → realtime"纳斯达克"做归一）
      .filter((r) =>
        !realtimeNames.has(r.asset) &&
        !(r.asset === "纳斯达克综指" && realtimeNames.has("纳斯达克")) &&
        !(r.asset === "上证综指" && realtimeNames.has("上证指数"))
      );

    // 商品占位：白银/铜/锂（待接入实时源，目前显示"待接入"）
    const placeholder: AssetRow[] = [
      { market: "商品", asset: "白银", value: "—", change: "—", cls: "flat", source: "待接入", meaning: "待接入实时源（新浪/英为财情）", code: undefined, kMarket: undefined },
      { market: "商品", asset: "铜", value: "—", change: "—", cls: "flat", source: "待接入", meaning: "待接入实时源（新浪/英为财情）", code: undefined, kMarket: undefined },
      { market: "商品", asset: "锂", value: "—", change: "—", cls: "flat", source: "待接入", meaning: "待接入实时源（新浪/英为财情）", code: undefined, kMarket: undefined },
    ];
    return [...realtime, ...briefRows, ...placeholder];
    return [...realtime, ...briefRows];
  }, [indices, globalIdx, brief]);

  return (
    <div>
      <PageHeader
        title="市场总览"
        actions={
          <button onClick={load} disabled={loading}
            className="inline-flex items-center gap-1.5 rounded-lg bg-primary/15 px-3 py-2 text-sm font-medium text-primary hover:bg-primary/25 disabled:opacity-50">
            {loading ? <Loader2 className="h-4 w-4 animate-spin" /> : <RefreshCw className="h-4 w-4" />}
            刷新
          </button>
        }
      />

      {/* AI 当日复盘（最顶部，重要！含收起分析） */}
      <GlassCard glow className="mb-4">
        <div className="flex items-center justify-between">
          <h3 className="flex items-center gap-1.5 font-semibold"><Sparkles className="h-4 w-4 text-primary" /> AI 当日复盘</h3>
          <div className="flex items-center gap-2">
            <button onClick={runReview} disabled={reviewLoading} className="btn-primary">
              {reviewLoading ? <Loader2 className="h-4 w-4 animate-spin" /> : <Sparkles className="h-4 w-4" />}
              {review ? "重新复盘" : "让 AI 复盘今天"}
            </button>
            {review && (
              <button onClick={() => setReviewCollapsed((c) => !c)} className="btn-primary">
                {reviewCollapsed ? "展开分析" : "收起分析"} ▾
              </button>
            )}
          </div>
        </div>
        {needConfig && (
          <div className="mt-3 flex items-center gap-2 rounded-lg border border-warning/30 bg-warning/5 p-3 text-sm text-muted-foreground">
            <AlertCircle className="h-4 w-4 shrink-0 text-warning" />
            还没接入 AI。<a href="/settings" className="text-primary hover:underline">先去接入你的 AI</a>，之后一键出复盘。
          </div>
        )}
        {reviewErr && (
          <div className="mt-3 flex items-center gap-2 rounded-lg border border-destructive/30 bg-destructive/5 p-3 text-sm text-destructive">
            <AlertCircle className="h-4 w-4 shrink-0" /> {reviewErr}
          </div>
        )}
        {review && !reviewCollapsed && (
          <div className="prose prose-sm dark:prose-invert mt-4 max-w-none text-foreground">
            <ReactMarkdown remarkPlugins={[remarkGfm]}>{review}</ReactMarkdown>
          </div>
        )}
        {review && reviewCollapsed && (
          <p className="mt-3 text-[11px] text-muted-foreground/60">已收起分析（{review.length} 字）</p>
        )}
        {!review && !needConfig && !reviewErr && !reviewLoading && (
          <p className="mt-3 text-sm text-muted-foreground">点上方按钮，系统把当天客观数据打包给你的 AI，由它生成复盘。<b className="text-foreground">分析是它给的，我们只负责喂数据。</b></p>
        )}
      </GlassCard>

      {err && (
        <div className="mb-4 flex items-center gap-2 rounded-lg border border-destructive/30 bg-destructive/5 p-3 text-sm text-destructive">
          <AlertCircle className="h-4 w-4 shrink-0" /> {err}
        </div>
      )}

      {/* 统一交易晨报摘要（放 AI 当日复盘下，后续两者合并） */}
      <GlassCard className="mt-4 p-4">
        <div className="mb-3 flex items-center gap-1.5 text-sm font-semibold">
          <Newspaper className="h-4 w-4 text-primary" /> 统一交易晨报摘要
          <span className="text-[11px] font-normal text-muted-foreground/50">· {brief?.report_meta?.date || "最新"}</span>
          <a href="/morning-brief" className="ml-auto text-[11px] text-primary hover:underline">查看完整晨报 →</a>
        </div>
        {!briefSummary ? (
          <p className="text-xs text-muted-foreground/60">暂无晨报数据（后端 data/market-monitor/morning-brief/ 无 payload）</p>
        ) : (
          <div className="space-y-4">
            {briefSummary.kicker && (
              <p className="rounded-lg bg-primary/5 px-3 py-2 text-sm font-medium text-primary">{briefSummary.kicker}</p>
            )}
            {briefSummary.overnight_changes && briefSummary.overnight_changes.length > 0 && (
              <div>
                <p className="mb-1.5 text-[11px] font-medium text-muted-foreground">{briefSummary.overnight_title || "隔夜变化"}</p>
                <div className="space-y-1.5">
                  {briefSummary.overnight_changes.slice(0, 2).map((c, i) => (
                    <p key={i} className="text-xs leading-relaxed text-foreground/90"><b className="text-foreground">{c.title}</b>{c.text}</p>
                  ))}
                </div>
              </div>
            )}
            {briefMainlines.slice(0, 2).map((m, i) => (
              <div key={i}>
                <p className="mb-1.5 text-[11px] font-medium text-muted-foreground">主线 {i + 1}</p>
                <p className="text-xs leading-relaxed text-foreground/90"><b className="text-foreground">{m.title}</b>{" "}{m.paras?.[0]}</p>
              </div>
            ))}
          </div>
        )}
      </GlassCard>

      {/* ② 合并资产总览（实时指数 + 晨报海外/商品；点击行看 K 线） */}
      <AssetOverviewTable rows={assetRows} />

      {/* ③ 市场情绪 + 短线情绪 */}
      <div className="grid gap-4 lg:grid-cols-2">
        <GlassCard className="p-4">
          <h3 className="mb-3 flex items-center gap-1.5 text-sm font-semibold"><Gauge className="h-4 w-4 text-primary" /> 市场情绪
            {sentiment?.breadth && (
              <button
                onClick={() => setHelpOpen(true)}
                title="点击查看等级定义"
                className={cn("ml-auto cursor-pointer rounded px-1.5 py-0.5 text-[11px] transition-colors", sentiment.breadth === "普涨" || sentiment.breadth === "偏强" ? "bg-danger/10 text-danger hover:bg-danger/20" : sentiment.breadth === "冰点" ? "bg-success/10 text-success hover:bg-success/20" : "bg-muted/40 text-muted-foreground hover:bg-muted/60")}
              >
                {sentiment.breadth} · {sentiment.speculation}
              </button>
            )}
          </h3>
          <div className="grid grid-cols-4 gap-2">
            {sentCells.map((m) => (
              <div key={m.k} className="rounded-lg bg-muted/30 p-2.5 text-center">
                <p className="text-[10px] text-muted-foreground">{m.k}</p>
                <p className={cn("mt-0.5 font-mono text-sm font-bold", m.c)}>{m.v}</p>
              </div>
            ))}
          </div>
          {reportData && (
            <div className="mt-3 grid grid-cols-3 gap-2 border-t border-border/40 pt-3">
              {(() => {
                const latest = reportData.market_history[reportData.market_history.length - 1];
                const aAmt = latest?.total_amount_100m;
                const hotN = reportData.hot_stocks_latest.length;
                const bw = latest?.market_breadth;
                const cells = [
                  { k: "全A成交额", v: aAmt == null ? "—" : `${aAmt.toLocaleString()} 亿`, c: "text-foreground", click: null as null | (() => void) },
                  { k: "百亿成交股", v: `${hotN} 只`, c: "text-foreground", click: () => setHotMatrixOpen(true) },
                  { k: "市场宽度", v: bw == null ? "—" : `${(bw * 100).toFixed(1)}%`, c: bw > 0 ? "text-danger" : bw < 0 ? "text-success" : "text-foreground", click: null },
                ];
                return cells.map((m) => (
                  <div key={m.k} className="rounded-lg bg-muted/30 p-2 text-center">
                    <p className="text-[10px] text-muted-foreground">{m.k}</p>
                    {m.click ? (
                      <button onClick={m.click} className={cn("mt-0.5 w-full font-mono text-base font-bold hover:text-primary cursor-pointer", m.c)}>{m.v}</button>
                    ) : (
                      <p className={cn("mt-0.5 font-mono text-base font-bold", m.c)}>{m.v}</p>
                    )}
                  </div>
                ));
              })()}
            </div>
          )}
        </GlassCard>

        <GlassCard className="p-4">
          <h3 className="mb-3 flex items-center gap-1.5 text-sm font-semibold"><Flame className="h-4 w-4 text-primary" /> 短线情绪
            {emotion?.date && <span className="text-[11px] font-normal text-muted-foreground/50">· {emotion.date}</span>}
          </h3>
          <div className="grid grid-cols-4 gap-2">
            {emoCells.map((m) => (
              <div key={m.k} className="rounded-lg bg-muted/30 p-2.5 text-center">
                <p className="text-[10px] text-muted-foreground">{m.k}</p>
                <p className={cn("mt-0.5 font-mono text-sm font-bold", m.c)}>{m.v}</p>
              </div>
            ))}
          </div>
          {emotion && emotion.ladder.length > 0 && (
            <div className="mt-3 flex flex-wrap items-center gap-1.5">
              <span className="text-[11px] text-muted-foreground">连板梯队：</span>
              {emotion.ladder.map((t) => (
                <button
                  key={t.boards}
                  onClick={() => setLadderOpen(true)}
                  title="点击查看连板股清单"
                  className={cn("cursor-pointer rounded px-1.5 py-0.5 font-mono text-[11px] transition-colors", t.plus ? "bg-danger/10 text-danger hover:bg-danger/20" : "bg-primary/10 text-primary hover:bg-primary/20")}
                >
                  {t.boards}{t.plus ? "+" : ""} 板 ×{t.count}
                </button>
              ))}
            </div>
          )}
        </GlassCard>
      </div>

      {/* ④ 市场涨跌结构 + 市场宽度（历史走势，盘后快照） */}
      {reportData && (
        <div className="mt-4">
          <TrendCharts data={reportData} initialRange="recent" />
        </div>
      )}

      {/* ⑤ 板块资金趋势榜（行业 · 按今日净流入排序，点击查看完整） */}
      <div className="mt-4 mb-3 flex items-center gap-2">
        <h3 className="section-title"><TrendingUp className="h-4 w-4 text-primary" /> 板块资金趋势榜</h3>
        <span className="text-[11px] text-muted-foreground/50">行业 · 按今日净流入排序</span>
        <button onClick={() => setSectorsOpen(true)} title="查看完整" className="ml-auto text-[11px] text-primary hover:underline">查看完整 →</button>
      </div>
      <GlassCard className="mb-4 p-4">
        {loading && sectors.length === 0 ? (
          <p className="text-xs text-muted-foreground/60">加载中…</p>
        ) : (
          <SectorTrendTable sectors={sectors} max={7} />
        )}
      </GlassCard>

      {/* ⑥ 资金轮动（板块级净流入 / 流出） */}
      <div className="mb-3 flex items-center gap-2">
        <h3 className="section-title"><ArrowDownUp className="h-4 w-4 text-primary" /> 资金轮动</h3>
        <span className="text-[11px] text-muted-foreground/50">板块级净流入 / 流出</span>
      </div>
      <GlassCard className="mb-4 p-4">
        {loading && sectors.length === 0 ? (
          <p className="text-xs text-muted-foreground/60">加载中…</p>
        ) : (
          <FundRotation sectors={sectors} />
        )}
      </GlassCard>

      {/* ④ 全市场成交额榜（T10/T20 切换） */}
      <GlassCard className="mt-4 p-4">
        <div className="mb-3 flex items-center gap-1.5 text-sm font-semibold">
          <TrendingDown className="h-4 w-4 text-primary" /> 全市场成交额榜
          <span className="ml-auto flex items-center gap-1 rounded-lg border border-border/60 p-0.5 text-[11px]">
            {([10, 20] as const).map((n) => (
              <button
                key={n}
                onClick={() => setTopN(n)}
                className={cn("rounded px-2 py-0.5 transition-colors", topN === n ? "bg-primary/15 text-primary" : "text-muted-foreground hover:text-foreground")}
              >
                T{n}
              </button>
            ))}
          </span>
        </div>
        {!turnover || turnover.stocks.length === 0 ? (
          <p className="text-xs text-muted-foreground/60">{loading ? "加载中…" : "暂无成交额榜数据"}</p>
        ) : (
          <TurnoverTopTable stocks={turnover.stocks} topN={topN} onTopN={setTopN} />
        )}
      </GlassCard>

      {/* ⑥ 监控板完整内容（embed 模式：无重复标题，直接融入市场总览） */}
      <div className="mt-6">
        <AStockMonitor embed />
      </div>

      {/* 连板股弹窗（内容 = 每日复盘同款表格） */}
      {ladderOpen && <LadderModal emotion={emotion} onClose={() => setLadderOpen(false)} />}

      {/* 板块资金趋势榜全表弹窗（内容 = 每日复盘同款表格） */}
      {sectorsOpen && <SectorsModal sectors={sectors} onClose={() => setSectorsOpen(false)} />}

      {/* 百亿成交·行业分布弹窗（点击情绪卡的"百亿成交股"打开） */}
      {hotMatrixOpen && (
        <HotMatrixModal matrix={reportData?.hot_stock_matrix || null} onClose={() => setHotMatrixOpen(false)} />
      )}

      {/* 情绪等级定义弹窗 */}
      {helpOpen && (
        <HelpModal sentiment={sentiment} onClose={() => setHelpOpen(false)} />
      )}
    </div>
  );
}

/* ---------- 连板股弹窗（内容 = 每日复盘同款表格，点击连板梯队打开） ---------- */
function LadderModal({ emotion, onClose }: { emotion: ShortTermEmotion | null; onClose: () => void }) {
  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 p-4 backdrop-blur-sm" onClick={onClose}>
      <GlassCard className="w-full max-w-4xl p-5">
        <div onClick={(e) => e.stopPropagation()} className="space-y-3">
          <div className="flex items-center gap-2">
            <h3 className="text-lg font-bold">连板股清单</h3>
            <span className="text-[11px] text-muted-foreground/60">2 板以上连涨停 · 客观公开榜单，非推荐/非预测</span>
            <button onClick={onClose} className="ml-auto rounded-md p-1 text-muted-foreground hover:bg-muted/30 hover:text-foreground" aria-label="关闭">
              <X className="h-4 w-4" />
            </button>
          </div>
          <LianbanTable emotion={emotion} />
        </div>
      </GlassCard>
    </div>
  );
}

/* ---------- 情绪等级定义弹窗（与后端 market.py _sentiment 口径一致） ---------- */
const BREADTH_DEF = [
  { level: "普涨", desc: "上涨/下跌 ≥ 2.5：市场普涨，情绪极强" },
  { level: "偏强", desc: "上涨/下跌 1.2~2.5：上涨家数明显占优" },
  { level: "中性", desc: "上涨/下跌 0.7~1.2：涨跌家数接近，多空均衡" },
  { level: "偏弱", desc: "上涨/下跌 < 0.7：下跌家数占优" },
  { level: "冰点", desc: "上涨家数 < 600 或极度低迷" },
];
const SPEC_DEF = [
  { level: "亢奋", desc: "真实涨停 ≥ 100 家：题材投机过热" },
  { level: "活跃", desc: "真实涨停 60~100 家：题材活跃" },
  { level: "普通", desc: "真实涨停 30~60 家：题材正常" },
  { level: "冰点", desc: "真实涨停 < 30 家：题材极弱" },
];
const breadthOf = (s: MarketSentiment | null) => s?.breadth ?? null;
const specOf = (s: MarketSentiment | null) => s?.speculation ?? null;

function HelpModal({ sentiment, onClose }: { sentiment: MarketSentiment | null; onClose: () => void }) {
  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 p-4 backdrop-blur-sm" onClick={onClose}>
      <GlassCard className="w-full max-w-md p-5">
        <div onClick={(e) => e.stopPropagation()} className="space-y-4">
          <div className="flex items-center gap-2">
            <h3 className="text-lg font-bold">情绪等级说明</h3>
            <button onClick={onClose} className="ml-auto rounded-md p-1 text-muted-foreground hover:bg-muted/30 hover:text-foreground" aria-label="关闭">
              <X className="h-4 w-4" />
            </button>
          </div>
          <div>
            <p className="mb-1.5 text-sm font-semibold">市场宽度{breadthOf(sentiment) ? `（当前：${breadthOf(sentiment)}）` : ""}</p>
            <ul className="space-y-1 text-xs text-muted-foreground">
              {BREADTH_DEF.map((d) => (
                <li key={d.level} className="flex gap-2"><span className="w-8 shrink-0 font-medium text-foreground">{d.level}</span>{d.desc}</li>
              ))}
            </ul>
          </div>
          <div>
            <p className="mb-1.5 text-sm font-semibold">题材投机{specOf(sentiment) ? `（当前：${specOf(sentiment)}）` : ""}</p>
            <ul className="space-y-1 text-xs text-muted-foreground">
              {SPEC_DEF.map((d) => (
                <li key={d.level} className="flex gap-2"><span className="w-8 shrink-0 font-medium text-foreground">{d.level}</span>{d.desc}</li>
              ))}
            </ul>
          </div>
        </div>
      </GlassCard>
    </div>
  );
}

/* ---------- 板块资金趋势榜全表弹窗（内容 = 每日复盘同款表格） ---------- */
function SectorsModal({ sectors, onClose }: { sectors: SectorFlow[]; onClose: () => void }) {
  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 p-4 backdrop-blur-sm" onClick={onClose}>
      <GlassCard className="w-full max-w-5xl p-5">
        <div onClick={(e) => e.stopPropagation()} className="space-y-3">
          <div className="flex items-baseline gap-2">
            <h3 className="text-lg font-bold">板块资金趋势榜</h3>
            <span className="text-[11px] text-muted-foreground/60">行业 · 按今日净流入排序</span>
            <button onClick={onClose} className="ml-auto rounded-md p-1 text-muted-foreground hover:bg-muted/30 hover:text-foreground" aria-label="关闭">
              <X className="h-4 w-4" />
            </button>
          </div>
          <div className="max-h-[60vh] overflow-y-auto pr-1">
            <SectorTrendTable sectors={sectors} max={90} />
          </div>
        </div>
      </GlassCard>
    </div>
  );
}

/* ---------- 百亿成交·行业分布弹窗（点击市场情绪卡的"百亿成交股"打开） ---------- */
function HotMatrixModal({ matrix, onClose }: {
  matrix: { dates: string[]; rows: { industry: string; counts: number[]; history_total: number }[] } | null;
  onClose: () => void;
}) {
  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 p-4 backdrop-blur-sm" onClick={onClose}>
      <GlassCard className="w-full max-w-5xl p-5">
        <div onClick={(e) => e.stopPropagation()} className="space-y-3">
          <div className="flex items-baseline gap-2">
            <h3 className="text-lg font-bold">百亿成交 · 行业分布</h3>
            <span className="text-[11px] text-muted-foreground/60">最近 10 个有记录交易日｜最新日期在左</span>
            <button onClick={onClose} className="ml-auto rounded-md p-1 text-muted-foreground hover:bg-muted/30 hover:text-foreground" aria-label="关闭">
              <X className="h-4 w-4" />
            </button>
          </div>
          <div className="max-h-[60vh] overflow-x-auto overflow-y-auto pr-1">
            <HotStockMatrixTable matrix={matrix} />
          </div>
        </div>
      </GlassCard>
    </div>
  );
}
