/**
 * 市场概览 —— 三页合并的过渡产物（方案 B 第一步）
 * 数据源：实时层 market.py（指数/情绪/板块资金/成交额榜）+ 快照层 report_data（申万行业）+ 宏观/要闻采集
 * 原三页（a股监控板 / 统一交易晨报 / 每日复盘）保留，本页做好后由用户确认再删。
 */
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { RefreshCw, Loader2, Gauge, Flame, TrendingUp, TrendingDown, ArrowDownUp, Wallet, AlertCircle, Sparkles, X } from "lucide-react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { PageHeader } from "@/components/ui/PageHeader";
import { GlassCard } from "@/components/ui/GlassCard";
import { AStockMonitor, TrendCharts, type MarketPublication, type ReportData } from "@/pages/AStockMonitor";
import { AssetOverviewTable, BRIEF_CODE_MAP, type AssetRow } from "@/components/ui/AssetOverviewTable";
import { SectorTrendTable, FundRotation, TurnoverTopTable, LianbanTable, HotStockMatrixTable } from "@/components/ui/marketPanels";
import { hasLlm, chatStream } from "@/lib/llm";
import { cn } from "@/lib/utils";
import { DailyReviewReport, type ReviewPayload } from "@/components/ui/DailyReviewReport";
import { macroBrief } from "@/data/macro_brief";
import "./astock-monitor.css";  // 加载 .asm-root 样式给 TrendCharts 用
import "./morning-brief.css";   // 晨报样式（AI 复盘用晨报同款版式渲染）
import {
  ApiError,
  type IndexQuote, type GlobalIndex, type MarketOverview, type MarketSentiment, type ShortTermEmotion,
  type TurnoverTop, type SectorFlow,
} from "@/lib/api";

const fmt = (v: number | null | undefined, suffix = "") => (v == null || Number.isNaN(v) ? "—" : `${v}${suffix}`);
const pct = (v: number | null | undefined) => (v == null || !Number.isFinite(Number(v)) ? "—" : `${Number(v) > 0 ? "+" : ""}${Number(v).toFixed(2)}%`);
const pctColor = (v: number | null | undefined) => (v != null && v > 0 ? "text-danger" : v != null && v < 0 ? "text-success" : "text-muted-foreground");
const yi = (v: number | null | undefined) => (v == null ? "—" : `${(v / 1e8).toFixed(2)} 亿`);
const yiInt = (v: number | null | undefined) => (v == null ? "—" : `${(v / 1e8).toFixed(0)}亿`);

// —— AI 当日复盘：客观数据聚合（实时 + 盘后快照兜底 + 宏观/要闻采集；缺哪路标「无数据」，不阻塞复盘） ——
function buildReviewData(d: {
  indices: IndexQuote[]; globalIdx: GlobalIndex[]; sentiment: MarketSentiment | null;
  emotion: ShortTermEmotion | null; turnover: TurnoverTop | null; sectors: SectorFlow[];
  reportData: ReportData | null; assets: string;
  usSectors: Record<string, { price: string; change: string; cls: string }>;
  macroChina: { indicator: string; period: string; release: string; value: string }[];
  headlines: { title: string; content: string; time: string; source: string }[];
}): string {
  const L: string[] = [];
  const { indices, globalIdx, sentiment, emotion, turnover, sectors, reportData, assets, usSectors, macroChina, headlines } = d;
  const moduleLatest = reportData?.quality?.module_latest_dates ?? {};

  // 盘后快照最新交易日（早上未开盘时实时接口可能为空，用它兜底 + 标注数据日期）
  const lastDay = reportData?.market_history?.[reportData.market_history.length - 1];
  if (lastDay) L.push(`【数据日期】最近完整交易日：${lastDay.date}（盘后快照）；实时数据若缺失以快照为准`);

  L.push(indices.length
    ? "【A股主要指数】" + indices.map((i) => `${i.name} ${i.price}（${pct(i.change_pct)}）`).join("；")
    : lastDay
      ? "【A股主要指数】（实时未取到，盘前/非交易时段；以下市场结构以盘后快照为准）"
      : "【A股主要指数】（无数据）");

  L.push(globalIdx.length
    ? "【全球指数】" + globalIdx.map((g) => `${g.name} ${g.price ?? "—"}（${pct(g.change_pct)}）`).join("；")
    : "【全球指数】（无数据）");

  if (sentiment) {
    L.push(`【市场情绪】上涨${sentiment.up} / 下跌${sentiment.down} / 平盘${sentiment.flat}；涨停${sentiment.zt}（真实${sentiment.zt_real}） / 跌停${sentiment.dt}（真实${sentiment.dt_real}）；活跃度${sentiment.active}；宽度等级「${sentiment.breadth}」；投机等级「${sentiment.speculation}」`);
  } else if (lastDay) {
    // 盘前/非交易时段：实时情绪缺失 → 用盘后快照兜底（advance/decline/limit_up/limit_down）
    L.push(`【市场情绪】上涨${lastDay.advance} / 下跌${lastDay.decline} / 平盘${lastDay.flat}；涨停${lastDay.limit_up} / 跌停${lastDay.limit_down}（${lastDay.date} 盘后快照）`);
  } else L.push("【市场情绪】（无数据）");

  if (emotion) {
    const ladderS = emotion.ladder.slice(0, 5).map((t) => `${t.boards}${t.plus ? "+" : ""}板×${t.count}`).join("、");
    L.push(`【短线情绪】涨停${emotion.zt_count} / 跌停${emotion.dt_count} / 炸板${emotion.zb_count}；最高${emotion.max_boards}板，连板${emotion.lianban_count}家；封板率${emotion.seal_rate == null ? "—" : `${(emotion.seal_rate * 100).toFixed(0)}%`}，炸板率${emotion.break_rate == null ? "—" : `${(emotion.break_rate * 100).toFixed(0)}%`}，晋级率${emotion.promotion_rate == null ? "—" : `${(emotion.promotion_rate * 100).toFixed(0)}%`}；连板梯队：${ladderS || "—"}`);
  } else if (lastDay) {
    L.push(`【短线情绪】涨停${lastDay.limit_up} / 跌停${lastDay.limit_down}（${lastDay.date} 盘后快照；连板梯队盘前无实时）`);
  } else L.push("【短线情绪】（无数据）");

  const topStocks = turnover?.stocks?.slice(0, 10) ?? [];
  L.push(topStocks.length
    ? "【成交额榜Top10】" + topStocks.map((s) => `${s.name} ${s.price ?? "—"}（${pct(s.pct)}，${yiInt(s.amount)}）`).join("；")
    : "【成交额榜】（无数据）");

  if (sectors.length) {
    const byNet = [...sectors].sort((a, b) => b.net - a.net);
    const top = byNet.slice(0, 5).map((s) => `${s.name} ${yiInt(s.net)}`).join("、");
    const bot = byNet.slice(-5).map((s) => `${s.name} ${yiInt(s.net)}`).join("、");
    L.push(`【板块资金】净流入Top5：${top}；净流出Top5：${bot}`);
  } else L.push("【板块资金】（无数据）");

  const latest = reportData?.market_history?.[reportData.market_history.length - 1];
  if (latest) {
    const bw = latest.market_breadth;
    L.push(`【市场概况】全A成交额 ${latest.total_amount_100m == null ? "—" : `${latest.total_amount_100m.toLocaleString()}亿`}；市场宽度 ${bw == null ? "—" : `${(bw * 100).toFixed(1)}%`}；百亿成交股 ${moduleLatest.hot_stocks === latest.date ? (reportData?.hot_stocks_latest?.length ?? 0) : "—"} 只`);
  }

  // 实时大类资产（来自资产总览表：黄金/原油/汇率/美债/国债/国内期货等），喂给 AI 复盘分析外围环境
  L.push(assets
    ? `【实时大类资产】${assets}`
    : "【实时大类资产】（数据加载中）");

  // 美股板块（GICS 板块 ETF 实时），供 AI 简要回顾美股走势与板块变化（不用 A 股那么详细）
  const us = Object.entries(usSectors);
  L.push(us.length
    ? "【美股板块】" + us.map(([sec, q]) => `${sec} ${q.price}（${q.change}）`).join("；")
    : "【美股板块】（数据加载中）");

  // 宏观速览：中国宏观自动采集（/api/macro-brief，带统计期+发布日），失败回退静态；美国宏观静态快照
  const fmtItem = (x: { indicator: string; period: string; release: string; value: string }) =>
    `${x.indicator}（${x.period}，${x.release}）：${x.value}`;
  const fmtEvent = (e: { time: string; event: string; markets: string; var: string }) =>
    `${e.time} ${e.event}（影响市场：${e.markets}；核心验证变量：${e.var}）`;
  L.push("【中美宏观速览（中国）】" + (macroChina.length ? macroChina.map(fmtItem).join("；") : "（采集失败，回退静态）" + macroBrief.china.map(fmtItem).join("；")));
  L.push("【中美宏观速览（美国）】" + macroBrief.us.map(fmtItem).join("；"));
  L.push("【未来关注事件】" + macroBrief.upcoming.map(fmtEvent).join("；"));

  // 重大要闻（财联社/东财当天实时，自动采集）——隔夜驱动/主线的信息源
  L.push(headlines.length
    ? "【重大要闻】" + headlines.map((h) => {
        // 原文去重（财联社 content 常以【title】开头）+ 放长给 AI 更多可整合信息
        const body = h.content && h.content !== h.title
          ? (h.content.startsWith(h.title) ? h.content.slice(h.title.length) : h.content)
          : "";
        return `${h.time} ${h.source}：${h.title}${body ? "｜" + body.slice(0, 180) : ""}`;
      }).join("\n")
    : "【重大要闻】（暂无/采集失败）");

  return L.join("\n\n");
}

// 资产总览行 → AI 复盘用的外围资产摘要（跳过已在【A股主要指数】/【全球指数】里的股票指数）
// 带上 meaning（市场含义/主流解释，晨报资产行自带），供 AI 写"大类资产走势与主流解释"
const REVIEW_ASSET_SKIP = new Set([
  "上证指数", "深证成指", "创业板指", "沪深300", "上证50", "科创50", "中证1000",
  "恒生指数", "恒生科技", "标普500", "纳斯达克", "道琼斯",
]);
function buildAssetsBrief(rows: AssetRow[]): string {
  return rows
    .filter((r) => !REVIEW_ASSET_SKIP.has(r.asset) && r.value !== "—")
    .map((r) => `${r.asset} ${r.value}（${r.change}${r.meaning ? `；${r.meaning}` : ""}）`)
    .join("；");
}

// —— AI 当日复盘：盘后化 JSON 输出（只喂数据、不编数字；数据全部来自实时行情源） ——
const REVIEW_PROMPT_TMPL = `你是盘后复盘研究员。基于下面的客观数据快照（含实时大类资产与全球指数），输出一份结构化复盘 JSON。

【硬性要求】
1. 只输出一个 JSON 对象：不要 markdown 代码围栏、不要任何解释或前后缀文字。
2. 只基于喂入数据，禁止编造数字；数据缺失的字段省略或填空串。
3. 不预测涨跌、不给买卖/仓位建议、不打分。
4. 不重复输出海内外大类资产总览表格（页面已有展示），分析中可引用资产数据佐证。

【写作原则（像晨报那样写；晨报只是版式与写作风格参考，不是内容来源）】
- 你是独立复盘研究员：所有内容基于喂入的数据（要闻/宏观/行情/板块）**自行搜集整合**，不引用、不依赖任何外部晨报或既有报告。
- 先结论后证据：每段开头一句主判断，再展开数据/事实；不要先讲半天数据再总结。
- 信息密度：每句话至少一个数据点；杜绝"今日市场表现平稳"这类空话；用具体家数/行业/金额/百分比。
- 因果表达谨慎：除非有正式来源明确归因，否则用「可能与…有关」「价格反应与…一致」「目前证据更支持…」「尚不能排除…」「仍需由…验证」；不写确定性因果。
- 分歧与反方：主结论后必须给反方证据/分歧（塞进 mainlines.evidence）。
- 区分重要与噪音：明确写出「可忽略噪音」（必含）。
- 输出前自查：结论先行、数据支撑、给出反方、说明噪音、不编数字。

【结构约束】
- china_market 是复盘的系统性数据底表（替代晨报「昨日中国市场：从大类资产到A股内部结构」），**必须完整填**：priority（一段最重要的日内结构总结）、breadth（用喂入的上涨/下跌家数与宽度等级）、industry（申万行业涨跌数 + 净流入/流出 Top3 行业名）、switch 数组**严格 2 项**（昨日 vs 今日两个最关键对比：宽度对比 + 全A成交对比；不要 3 项，3 项排不开）。这是市场总览数据的系统性总结，不可省略。
- **mainlines 由你自行提炼今日三条统一市场主线**（不依赖、不引用任何外部晨报——你是信息整合者，晨报只是输出版式参考）：基于【重大要闻】【中美宏观速览】【美股板块】【板块资金】【实时大类资产】等喂入数据，提炼当天真正驱动市场的 3 条主线。每条结构 { tags: 主线性质（「新主线/延续/强化/反转」之一）, title: 主线一句话, paras: 今日市场表达（1-2 段，含数据）, evidence: 证据与分歧（支持证据 + 反方）, validation: 明日继续看什么 }。
- mainlines.evidence = 证据与分歧；mainlines.validation = 明日继续看什么。
- funding_industry 改为**长点评版式**（不要 grid-3 简卡，区别于晨报）：3-5 段，每段包含一个数据点（建议：全A成交 / 百亿成交股 / 板块净流入 / 板块净流出 / 短线情绪 / 活跃度 中选 3-4 个），结构为 { label: 小标题, metric: 关键数字, note: 多段分析点评（用 \\n\\n 分段，每段 2-4 句话，先结论后证据，每句话至少一个数据点，不要只写一句简注） }。
- today_validation 2-3 条；events 从【未来关注事件】中提取正式日程（time 用具体日期/时点，event 用原始表述，markets/var 填相关市场与变量）。
- summary.overnight_changes = **今日最重要的 3 条事件**（从【重大要闻】中选，优先政策/央行/财政/地缘/大型公司财报；宏观数据放 china_changes 或并入事件，不写宏观数据罗列）。**每条按「事实 → 市场定价 → A股含义」三层写**：
  ① 事实：发生了什么（含具体数字/金额/幅度，如"10Y 重新站上 4.70%"）；
  ② 市场定价：市场如何反应（对美债收益率/美元/油价/美股板块/风险偏好的影响，用具体数字）；
  ③ A 股含义：传导到 A 股的哪条线（资源/成长/防御/外资敏感），今天盘面定价到什么程度。
  **事件间相关时串成传导链**（如：地缘→油价→美债→美元→A股资源/成长）。
  **必须给反方/边界**（如"仅凭 X 不足以……""若 Y 不发生则……"），避免单一叙事。
- summary.china_changes 覆盖「中国宏观与政策」1-2 条：用【中美宏观速览（中国）】写（物价/金融/政策定调），**保留数据期+发布日**。
- **宏观数据必须保留「数据期 + 发布日」**（如「7月CPI（8/9发布）同比+3.4%」）：写宏观时**不得省略日期**、不得只写月份不写发布日；数据期/发布日期未知的字段就写「日期不详」并照常输出数值。
- **重大要闻是核心信息源**：隔夜关键驱动 / summary 变化 / **主线提炼** / events 都应**主动从【重大要闻】中提取当天最重要的政策、央行、财政、地缘、监管类事件**（结合宏观与行情判断其对市场的影响），**引用时标注来源**（如「财联社 8/20」）并转述，不编造细节；个股公司新闻（业绩/公告类）除非是大型龙头财报且牵动板块（如沃尔玛/茅台式）否则不引用。
- events 优先取【未来关注事件】；【重大要闻】中带明确时间（如"8/20 LPR"）的正式日程也可列入。
- 宏观数据一律取自【中美宏观速览】两段，禁止外推编造数字；数据缺失的字段省略。
- assets_review 逐资产点评「大类资产走势与主流解释」：从【实时大类资产】中挑最重要的 5-8 个（黄金 / 美债 / 美元 / 原油 / 铜 / 比特币 / 人民币 / 商品指数等，跳过股票指数），每条结构为 { asset: 资产名, move: 走势数字（含 ±%）, meaning: 主流解释 }——meaning 优先引用数据中已给的市场含义，AI 补充解读一律用「可能与…有关」「价格反应与…一致」等谨慎因果，不得编造具体新闻或来源；不是表格，是紧凑点评列表。
- **美股走势与板块变化**：如【美股板块】有数据，在 assets_review 中补充 3-5 个美股主要板块（asset 写「美股·科技」「美股·金融」之类，move 用涨跌%，meaning 写板块轮动/风格观察）；美股部分**每条一句、整体保持简短**（简要回顾即可），不需要 A 股那种详细底表。

【输出 JSON 结构】
{
  "report_meta": { "report_name": "AI 当日复盘", "report_date": "最近交易日 YYYY-MM-DD", "report_cutoff": "收盘时点", "china_market_date": "X月X日收盘", "headline": "一句话总判断" },
  "summary": {
    "kicker": "总判断一句话",
    "overnight_title": "今日重要变化",
    "overnight_changes": [{ "title": "变化一：", "text": "细节" }, { "title": "变化二：", "text": "细节" }, { "title": "变化三：", "text": "细节" }],
    "china_title": "今日中国结构变化",
    "china_changes": [{ "title": "结构一：", "text": "细节" }, { "title": "结构二：", "text": "细节" }],
    "priority_card": { "label": "明天最高优先级", "title": "主题", "note": "为什么" },
    "priorities": [{ "head": "优先级一：", "text": "说明" }]
  },
  "china_market": {
    "title": "今日中国市场：一句话概括", "kicker": "A股核心行情简版（底表不全时）或省略",
    "priority": "最重要的日内结构段落", "warning": "数据局限（没有可省略）",
    "switch": [{ "label": "昨日 vs 今日", "metric": "关键数字", "cls": "up|down|flat", "note": "说明" }, { "label": "昨日 vs 今日", "metric": "关键数字", "cls": "up|down|flat", "note": "说明" }],
    "breadth": { "title": "市场宽度", "up": "上涨家数", "down": "下跌家数", "up_pct": 数值, "down_pct": 数值, "note": "说明" },
    "industry": { "title": "申万一级行业宽度", "up": "上涨行业数", "down": "下跌行业数", "up_pct": 数值, "down_pct": 数值, "note": "说明" }
  },
  "mainlines": {
    "kicker": "今日三条统一市场主线（自行提炼）",
    "items": [{ "tags": ["新主线"], "title": "主线标题", "paras": ["今日市场表达"], "evidence": "证据与分歧", "validation": "明日继续看什么" }]
  },
  "assets_review": {
    "kicker": "大类资产走势与主流解释",
    "items": [{ "asset": "黄金", "move": "+1.2%", "meaning": "市场含义/主流解释（谨慎因果）" }]
  },
  "today_validation": {
    "kicker": "把主线压缩成盘中可观察的问题",
    "rows": [{ "subject": "观察对象", "question": "今天留下的问题", "look": "明天看什么", "meaning": "判断含义" }]
  },
  "previous_review": { "kicker": "对先前判断的复盘", "rows": [{ "judgment": "原判断", "facts": "新增事实", "state": "兑现/部分兑现/未兑现/无法判断", "state_cls": "up|down|neutral", "adjust": "框架是否调整" }] },
  "funding_industry": { "kicker": "资金与产业数据", "items": [{ "label": "成交", "metric": "数字", "cls": "up|down|flat", "note": "说明" }] },
  "tracking": { "kicker": "3-6 个跟踪主题", "rows": [{ "topic": "主题", "judgment": "当前判断", "support": "支持证据", "counter": "反方证据", "next": "下一验证", "falsify": "证伪条件", "period": "周期" }] },
  "events": { "kicker": "未来7天事件（仅用数据中出现的正式日程）", "rows": [{ "time": "北京时间", "event": "事件", "markets": "影响市场", "var": "核心验证变量" }] }
}

【数据】
{{DATA}}`;

// 聚合端点 /api/market/overview-v2 的响应体（实时层 6 路数据一次返回）
interface MarketOverviewAggregate {
  indices: IndexQuote[];
  global_indices: GlobalIndex[];
  sentiment: MarketSentiment | null;
  sectors: SectorFlow[];
  emotion: ShortTermEmotion | null;
  turnover_top: TurnoverTop | null;
  updated: string;
  providers?: Record<string, { ok: boolean; degraded?: boolean }>;
}

export function MarketOverview() {
  const [indices, setIndices] = useState<IndexQuote[]>([]);
  const [globalIdx, setGlobalIdx] = useState<GlobalIndex[]>([]);
  const [overview, setOverview] = useState<MarketOverview | null>(null);
  const [emotion, setEmotion] = useState<ShortTermEmotion | null>(null);
  const [turnover, setTurnover] = useState<TurnoverTop | null>(null);
  const [reportData, setReportData] = useState<ReportData | null>(null);
  const [publication, setPublication] = useState<MarketPublication | null>(null);
  const [loading, setLoading] = useState(true);
  const [err, setErr] = useState<string | null>(null);
  const [updated, setUpdated] = useState("");
  // 白银/铜/锂占位行的实时快照（从后端 K 线最新两条算价格+涨跌；避开新浪实时字段不稳定的坑）
  const [placeholderQuotes, setPlaceholderQuotes] = useState<Record<string, { price: string; change: string; cls: "up" | "down" | "flat" }>>({});
  // 晨报每日快照的资产（海外/商品/汇率/国债）的实时补丁：用 Yahoo/Sina 最新 K 线覆盖
  // 解决「黄金现在 4397、表格 4350」的陈旧问题；K 线失败时静默回退晨报快照
  const [extraQuotes, setExtraQuotes] = useState<Record<string, { price: string; change: string; cls: "up" | "down" | "flat" }>>({});
  // 美股板块（GICS 11 板块 ETF，Yahoo K 线）——AI 复盘简要回顾美股走势与板块变化的数据源
  const [usSectors, setUsSectors] = useState<Record<string, { price: string; change: string; cls: "up" | "down" | "flat" }>>({});
  // 宏观速览 + 重大要闻（/api/macro-brief 自动采集；失败回退静态 macro_brief.ts）
  const [macroLive, setMacroLive] = useState<{
    china: { indicator: string; period: string; release: string; value: string }[];
    headlines: { title: string; content: string; time: string; source: string }[];
  }>({ china: [], headlines: [] });
  const runIdRef = useRef(0);

  // 实时资产拉取：mount / 点「刷新」 / 定时自动刷新都会调用
  // - 现货黄金：/api/gold-spot（新浪 hf_XAU，避免 COMEX 期货升水+延迟）
  // - 国内期货（白银/铜/锂）+ 中10Y国债 + 国际原油（Brent/WTI）：/api/sina-spot（新浪实时现价 vs 昨收，
  //   避免新浪日 K 停更（如周末后周一盘中 bar 缺失）导致涨跌算成上个交易日）
  // - USD/CNY / DXY / 美10Y：Yahoo K 线（已验证实时更新；单 bar 用 meta latest/prev_close 兜底）
  const loadLiveQuotes = useCallback(() => {
    const fmt = (price: number, chg: number) => ({
      price: price.toLocaleString(undefined, { maximumFractionDigits: 2 }),
      change: `${chg >= 0 ? "+" : ""}${(chg * 100).toFixed(2)}%`,
      cls: (chg > 0 ? "up" : chg < 0 ? "down" : "flat") as "up" | "down" | "flat",
    });
    const setX = (asset: string, q: ReturnType<typeof fmt>) => setExtraQuotes((s) => ({ ...s, [asset]: q }));
    const setP = (asset: string, q: ReturnType<typeof fmt>) => setPlaceholderQuotes((s) => ({ ...s, [asset]: q }));

    // ① 现货黄金（伦敦金现货）
    fetch("/api/gold-spot").then((x) => x.json()).then((g) => {
      const d = g?.data;
      if (d?.price != null) setX("现货黄金", fmt(d.price, d.change_pct ?? 0));
    }).catch(() => { /* 静默失败 */ });

    // ② 新浪实时：国内期货（白银/铜/锂）+ 中10Y国债 + 国际原油（现价 vs 昨收）
    const SPOT_MAP: Record<string, string> = {
      "白银": "nf_AG0", "铜": "nf_CU0", "锂": "nf_LC0", "中国10Y国债活跃券": "nf_T0",
      "Brent原油": "hf_OIL", "WTI原油": "hf_CL",
    };
    fetch(`/api/sina-spot?codes=${encodeURIComponent(Object.values(SPOT_MAP).join(","))}`)
      .then((x) => x.json())
      .then((g) => {
        const d = g?.data || {};
        Object.entries(SPOT_MAP).forEach(([asset, sym]) => {
          const q = d[sym];
          if (!q?.price) return;
          (asset === "白银" || asset === "铜" || asset === "锂" ? setP : setX)(asset, fmt(q.price, q.change_pct ?? 0));
        });
      })
      .catch(() => { /* 静默失败 */ });

    // ③ Yahoo K 线：USD/CNY / DXY / 美10Y（单 bar 用 meta latest/prev_close 兜底）
    const KLINE_EXTRA: [string, string][] = [
      ["USD/CNY", "y:CNY=X"], ["DXY（美元指数）", "y:DX-Y.NYB"], ["美国10Y国债", "y:^TNX"],
    ];
    KLINE_EXTRA.forEach(([asset, code]) => {
      fetch(`/api/kline?code=${encodeURIComponent(code)}&period=day&offset=5`)
        .then((x) => x.json())
        .then((r) => {
          const bars: Array<{ close: number }> = (r?.data || []).slice(-2);
          if (bars.length >= 2) {
            const last = bars[bars.length - 1].close;
            const prev = bars[bars.length - 2].close;
            setX(asset, fmt(last, prev ? (last - prev) / prev : 0));
          } else if (r?.latest != null && r?.prev_close != null) {
            setX(asset, fmt(r.latest, (r.latest - r.prev_close) / r.prev_close));
          }
        })
        .catch(() => { /* 静默失败 */ });
    });

    // ④ 美股板块（GICS 11 板块 ETF，Yahoo K 线）——复盘简要回顾美股板块变化的实时数据源
    const US_SECTORS: [string, string][] = [
      ["科技", "y:XLK"], ["金融", "y:XLF"], ["能源", "y:XLE"], ["公用事业", "y:XLU"],
      ["医疗保健", "y:XLV"], ["可选消费", "y:XLY"], ["必需消费", "y:XLP"], ["工业", "y:XLI"],
      ["材料", "y:XLB"], ["房地产", "y:XLRE"], ["通信服务", "y:XLC"],
    ];
    US_SECTORS.forEach(([sec, code]) => {
      fetch(`/api/kline?code=${encodeURIComponent(code)}&period=day&offset=5`)
        .then((x) => x.json())
        .then((r) => {
          const bars: Array<{ close: number }> = (r?.data || []).slice(-2);
          if (bars.length >= 2) {
            const last = bars[bars.length - 1].close;
            const prev = bars[bars.length - 2].close;
            setUsSectors((s) => ({ ...s, [sec]: fmt(last, prev ? (last - prev) / prev : 0) }));
          }
        })
        .catch(() => { /* 静默失败 */ });
    });
  }, []);

  const load = async () => {
    const rid = ++runIdRef.current;
    setLoading(true); setErr(null);
    const ok = <T,>(set: (v: T) => void) => (v: T) => { if (rid === runIdRef.current) set(v); };
    const safe = (p: Promise<unknown>, fallback: unknown = null) => p.catch((e) => { console.warn("[overview] 数据源失败:", e); return fallback; });

    // 实时层聚合为 1 个请求；快照层（market-monitor）独立（盘后固定，不随实时刷新反复拉）；宏观/要闻独立
    const [agg, mon, mb] = await Promise.all([
      safe(fetch("/api/market/overview-v2").then((r) => (r.ok ? r.json() : null)), null),
      fetch("/api/market-monitor").then((r) => (r.ok ? r.json() : {})).catch((e) => { console.warn("[overview] market-monitor 失败:", e); return {}; }),
      safe(fetch("/api/macro-brief").then((r) => (r.ok ? r.json() : null)), null),
    ]);
    if (rid !== runIdRef.current) return;

    const d = (agg as { data?: MarketOverviewAggregate } | null)?.data ?? null;
    const mbD = (mb as { data?: { china?: { indicator: string; period: string; release: string; value: string }[]; headlines?: { title: string; content: string; time: string; source: string }[] } } | null)?.data ?? null;
    ok(setMacroLive)({
      china: mbD?.china || [],
      headlines: mbD?.headlines || [],
    });
    ok(setIndices)(d?.indices || []);
    ok(setGlobalIdx)(d?.global_indices || []);
    ok(setOverview)(d ? { sentiment: d.sentiment ?? ({} as MarketSentiment), sectors: d.sectors ?? [], updated: d.updated ?? "" } : null);
    ok(setEmotion)(d?.emotion ?? null);
    ok(setTurnover)(d?.turnover_top ?? null);
    const monitor = mon as { data?: ReportData; publication?: MarketPublication } | undefined;
    ok(setReportData)(monitor?.data || null);
    ok(setPublication)(monitor?.publication || null);

    ok(setUpdated)(d?.updated ?? "");
    ok(setLoading)(false);
    loadLiveQuotes();  // 实时资产（黄金/商品/汇率/国债）随「刷新」一起更新
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

  // 15:20 是 GitHub 开始生产的时点，不是假定数据已经完成的时点。
  // 收盘后只轮询已发布快照；新包未发布或读取失败时保留当前已验证数据。
  useEffect(() => {
    const refreshPublication = async () => {
      const now = new Date();
      const day = now.getDay();
      const minute = now.getHours() * 60 + now.getMinutes();
      if (day === 0 || day === 6 || minute < 15 * 60 + 20 || minute > 16 * 60 + 20) return;
      try {
        const response = await fetch("/api/market-monitor", { cache: "no-store" });
        if (!response.ok) return;
        const payload = await response.json() as { data?: ReportData; publication?: MarketPublication };
        if (payload.data) setReportData(payload.data);
        if (payload.publication) setPublication(payload.publication);
      } catch (error) {
        console.warn("[overview] 已发布市场快照轮询失败，保留当前版本:", error);
      }
    };
    const timer = setInterval(refreshPublication, 300_000);
    return () => clearInterval(timer);
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
    const data = buildReviewData({
      indices, globalIdx, sentiment, emotion, turnover, sectors, reportData,
      assets: buildAssetsBrief(assetRows),
      usSectors,
      macroChina: macroLive.china,
      headlines: macroLive.headlines,
    });
    const prompt = REVIEW_PROMPT_TMPL.replace("{{DATA}}", data);
    try {
      await chatStream([{ role: "user", content: prompt }], data, {
        onDelta: (t) => setReview((r) => r + t),
      });
    } catch (e) {
      setReviewErr(e instanceof ApiError ? e.message : "复盘失败");
    } finally {
      setReviewLoading(false);
    }
  };

  // 流式全文 → 结构化 payload（AI 输出 JSON；剥代码围栏，失败回退 null → 原样 Markdown 展示）
  const reviewObj = useMemo<ReviewPayload | null>(() => {
    if (!review) return null;
    try {
      const t = review.trim();
      const f = t.match(/```(?:json)?\s*([\s\S]*?)\s*```/);
      const raw = f ? f[1] : t;
      const obj = JSON.parse(raw);
      return obj && typeof obj === "object" ? (obj as ReviewPayload) : null;
    } catch {
      return null;
    }
  }, [review]);

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

  // 资产总览：全部实时数据（A股 7 指数 + 港股/美股 + 海外/商品/汇率/国债），不再依赖晨报快照
  // 海外/商品/汇率/国债的值来自 extraQuotes（Yahoo/Sina K 线或 meta 兜底）与 placeholderQuotes（国内期货 K 线）
  const assetRows = useMemo<AssetRow[]>(() => {
    const INDICES_CODE: Record<string, string> = {
      "上证指数": "sh000001", "深证成指": "sz399001", "创业板指": "sz399006",
      "沪深300": "sh000300", "上证50": "sh000016", "科创50": "sh000688",
      "中证1000": "sh000852",
    };
    const HK_CODE: Record<string, string> = { "恒生指数": "hkHSI", "恒生科技": "hkHSTECH" };
    // 非实时指数类资产的市场分类（AssetOverviewTable 内 MARKET_FIX 还会二次校正）
    const MARKET_HINT: Record<string, string> = {
      "现货黄金": "商品", "Brent原油": "商品", "WTI原油": "商品", "白银": "商品", "铜": "商品", "锂": "商品",
      "中证商品期货价格指数": "商品", "中国10Y国债活跃券": "国内",
      "美国10Y国债": "海外", "DXY（美元指数）": "海外", "USD/CNY": "海外",
    };
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

    // 其余资产（海外/商品/汇率/国债）：从 BRIEF_CODE_MAP 全量构建，实时值缺失时显示"—"，绝不回退晨报快照
    const others: AssetRow[] = (Object.entries(BRIEF_CODE_MAP) as [string, { code: string; market: "A" | "HK" | "US" } | null][])
      .filter(([asset]) =>
        !realtimeNames.has(asset) &&
        !(asset === "纳斯达克综指" && realtimeNames.has("纳斯达克")) &&
        !(asset === "上证综指" && realtimeNames.has("上证指数"))
      )
      .map(([asset, cm]) => {
        const q = extraQuotes[asset] || placeholderQuotes[asset];
        return {
          market: MARKET_HINT[asset] ?? (cm?.market === "A" ? "国内" : "海外"),
          asset,
          value: q?.price ?? "—",
          change: q?.change ?? "—",
          cls: q?.cls ?? ("flat" as const),
          source: q ? ("实时" as const) : ("待接入" as const),
          meaning: q ? undefined : "暂无实时数据源",
          code: cm?.code,
          kMarket: cm?.market,
        } as AssetRow;
      });
    return [...realtime, ...others];
  }, [indices, globalIdx, extraQuotes, placeholderQuotes]);

  const publicationSubtitle = useMemo(() => {
    if (!publication) return reportData?.meta?.report_date ? `最后有效盘后数据：${reportData.meta.report_date}` : undefined;
    const published = publication.published_at
      ? new Date(publication.published_at).toLocaleString("zh-CN", { hour12: false })
      : "时间未知";
    const source = publication.using_fallback ? "GitHub 暂不可用，保留最后有效版本" : "GitHub 已验证发布";
    return `盘后数据：${publication.data_date} · 发布：${published} · ${source}`;
  }, [publication, reportData]);

  return (
    <div>
      <PageHeader
        title="市场总览"
        subtitle={publicationSubtitle}
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
          reviewObj ? (
            <div className="mt-4">
              <DailyReviewReport p={reviewObj} />
            </div>
          ) : (
            <div className="prose prose-sm dark:prose-invert mt-4 max-w-none text-foreground">
              <ReactMarkdown remarkPlugins={[remarkGfm]}>{review}</ReactMarkdown>
            </div>
          )
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
                const moduleLatest = reportData.quality?.module_latest_dates ?? {};
                const aAmt = latest?.total_amount_100m;
                const hotN = moduleLatest.hot_stocks === latest?.date ? reportData.hot_stocks_latest.length : null;
                const bw = latest?.market_breadth;
                const cells = [
                  { k: "全A成交额", v: aAmt == null ? "—" : `${aAmt.toLocaleString()} 亿`, c: "text-foreground", click: null as null | (() => void) },
                  { k: "百亿成交股", v: hotN == null ? "—" : `${hotN} 只`, c: "text-foreground", click: () => setHotMatrixOpen(true) },
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
