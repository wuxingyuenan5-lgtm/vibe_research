import { useState, useEffect, useCallback, useMemo } from "react";
import { Link } from "react-router-dom";
import { TrendingUp, FileText, Newspaper, Rss, RefreshCw, Loader2, ExternalLink, AlertCircle, Sparkles, Lightbulb, Star, X, BarChart3 } from "lucide-react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { PageHeader } from "@/components/ui/PageHeader";
import { GlassCard } from "@/components/ui/GlassCard";
import { SaveNoteButton } from "@/components/ui/SaveNoteButton";
import { api, ApiError, type RadarData, type Industry, type Announcement, type NewsItem, type HalfYearReport } from "@/lib/api";
import { hasLlm, chatStream } from "@/lib/llm";
import { cn } from "@/lib/utils";

const TABS = [
  { key: "events", label: "事件概率", icon: TrendingUp, integrated: false, desc: "全球宏观预期概率（公开数据、免登录只读），后续接入" },
  { key: "filings", label: "A股公告", icon: FileText, integrated: false, desc: "汇总关注列表里各个股的近期公告（东财公开披露）" },
  { key: "news", label: "公开新闻", icon: Newspaper, integrated: false, desc: "汇总关注列表里各个股的近期新闻（公开源）" },
  { key: "investment-news", label: "Investment News", icon: Rss, integrated: true, desc: "12 赛道全球公开 RSS 资讯（集成自 investment-news 仓库）" },
];

interface Digest { loading?: boolean; text?: string; err?: string; needKey?: boolean }

function InvestmentNewsPanel() {
  const [data, setData] = useState<RadarData | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [active, setActive] = useState("ai");
  const [refreshing, setRefreshing] = useState(false);
  const [digests, setDigests] = useState<Record<string, Digest>>({});
  const [bulk, setBulk] = useState<{ running: boolean; done: number; total: number }>({ running: false, done: 0, total: 0 });

  useEffect(() => {
    api.radar().then(setData).catch((e) => setErr(e instanceof ApiError ? e.message : "加载失败"));
  }, []);

  const refresh = async () => {
    setRefreshing(true); setErr(null);
    try { setData(await api.radarRefresh()); }
    catch (e) { setErr(e instanceof ApiError ? e.message : "刷新失败"); }
    finally { setRefreshing(false); }
  };

  const industries: Industry[] = data?.industries || [];
  const cur = industries.find((i) => i.key === active) || industries[0];
  const hasData = !!data?.generated_at;

  const genDigest = async (ind: Industry) => {
    if (!hasLlm()) { setDigests((d) => ({ ...d, [ind.key]: { needKey: true } })); return; }
    setDigests((d) => ({ ...d, [ind.key]: { loading: true } }));
    const ctx = ind.items.slice(0, 25).map((it) => `[${it.time}] ${it.source}｜${it.zh || it.title}`).join("\n");
    const prompt =
      `以下是「${ind.name}」赛道近期资讯。请提炼「今日要点」3-5 条：每条一句话（≤40 字），` +
      `只客观陈述重要事件 / 趋势。直接用「- 」列点，不要多余前后缀。\n\n${ctx}`;
    try {
      let acc = "";
      await chatStream([{ role: "user", content: prompt }], `${ind.name}赛道资讯`, {
        onDelta: (t) => { acc += t; setDigests((d) => ({ ...d, [ind.key]: { text: acc } })); },
      });
    } catch (e) {
      setDigests((d) => ({ ...d, [ind.key]: { err: e instanceof ApiError ? e.message : "生成失败" } }));
    }
  };

  // 一键提炼全部赛道要点（串行，带进度；单赛道按需的按钮仍保留）
  const genAll = async () => {
    if (!hasLlm()) { if (cur) setDigests((d) => ({ ...d, [cur.key]: { needKey: true } })); return; }
    const targets = industries.filter((i) => i.items.length > 0);
    setBulk({ running: true, done: 0, total: targets.length });
    for (const ind of targets) {
      await genDigest(ind);
      setBulk((b) => ({ ...b, done: b.done + 1 }));
    }
    setBulk((b) => ({ ...b, running: false }));
  };

  const dg = cur ? digests[cur.key] : undefined;

  return (
    <div>
      <div className="mb-3 flex flex-wrap items-center justify-between gap-2">
        <span className="text-xs text-muted-foreground">
          {hasData ? `${data!.stats.total_sources} 个公开源 · 近 ${data!.recent_days} 天 · 更新于 ${data!.generated_at}` : "12 赛道 · 108 个公开源"}
        </span>
        <div className="flex items-center gap-2">
          {hasData && (
            <button onClick={genAll} disabled={bulk.running || refreshing}
              className="inline-flex items-center gap-1.5 rounded-lg bg-primary/15 px-3 py-1.5 text-sm font-medium text-primary shadow-glow hover:bg-primary/25 disabled:opacity-50">
              {bulk.running ? <Loader2 className="h-4 w-4 animate-spin" /> : <Sparkles className="h-4 w-4" />}
              {bulk.running ? `提炼中 ${bulk.done}/${bulk.total}` : "一键提炼全部要点"}
            </button>
          )}
          <button onClick={refresh} disabled={refreshing || bulk.running}
            className="inline-flex items-center gap-1.5 rounded-lg border border-border px-3 py-1.5 text-sm text-muted-foreground hover:text-foreground disabled:opacity-50">
            {refreshing ? <Loader2 className="h-4 w-4 animate-spin" /> : <RefreshCw className="h-4 w-4" />}
            {refreshing ? "抓取中…" : "刷新"}
          </button>
        </div>
      </div>

      {err && (
        <div className="mb-3 flex items-center gap-2 rounded-lg border border-destructive/30 bg-destructive/5 p-3 text-sm text-destructive">
          <AlertCircle className="h-4 w-4 shrink-0" /> {err}
        </div>
      )}

      {!hasData && !err ? (
        <div className="rounded-lg border border-dashed border-border/70 p-8 text-center text-sm text-muted-foreground/70">
          还没有抓取资讯，点上方<b className="text-foreground">「刷新」</b>拉取（约 20-40 秒）。
        </div>
      ) : (
        <>
          {/* 赛道筛选 —— 暖橙边框 pill */}
          <div className="mb-4 flex flex-wrap gap-2">
            {industries.map((ind) => (
              <button key={ind.key} onClick={() => setActive(ind.key)}
                className={cn(
                  "inline-flex items-center gap-1.5 rounded-full border px-3 py-1 text-xs transition-colors",
                  active === ind.key
                    ? "border-primary bg-primary/15 font-medium text-primary shadow-glow"
                    : "border-primary/25 text-muted-foreground hover:border-primary/60 hover:text-foreground",
                )}>
                <span className="h-2 w-2 rounded-full" style={{ background: ind.accent }} />
                {ind.name}<span className="text-muted-foreground/50">{ind.items.length}</span>
              </button>
            ))}
          </div>

          {cur && (
            <>
              {/* 今日要点总结框（暖橙框） */}
              <div className="mb-4 rounded-xl border border-primary/30 bg-primary/5 p-4">
                <div className="mb-2 flex items-center justify-between">
                  <span className="flex items-center gap-1.5 text-sm font-semibold text-primary">
                    <Lightbulb className="h-4 w-4" /> 今日要点 · {cur.name}
                  </span>
                  {(dg?.text || dg?.err || dg?.needKey) && (
                    <button onClick={() => genDigest(cur)} className="text-xs text-muted-foreground hover:text-primary">重新提炼</button>
                  )}
                </div>
                {dg?.loading ? (
                  <p className="flex items-center gap-2 text-sm text-muted-foreground"><Loader2 className="h-3.5 w-3.5 animate-spin" /> AI 正在读这个赛道的资讯…</p>
                ) : dg?.text ? (
                  <>
                    <div className="prose prose-sm dark:prose-invert max-w-none text-foreground"><ReactMarkdown remarkPlugins={[remarkGfm]}>{dg.text}</ReactMarkdown></div>
                    <div className="mt-2"><SaveNoteButton kind="今日要点" title={`${cur.name} 今日要点`} content={dg.text} /></div>
                  </>
                ) : dg?.needKey ? (
                  <p className="text-sm text-muted-foreground">还没接入 AI。<Link to="/settings" className="text-primary">先接入你的 AI</Link>，即可一键提炼本赛道今日要点。</p>
                ) : dg?.err ? (
                  <p className="text-sm text-destructive">{dg.err}</p>
                ) : (
                  <button onClick={() => genDigest(cur)}
                    className="inline-flex items-center gap-1.5 rounded-lg bg-primary/15 px-3 py-1.5 text-sm font-medium text-primary hover:bg-primary/25">
                    <Sparkles className="h-4 w-4" /> 让 AI 提炼今日要点
                  </button>
                )}
              </div>

              {/* 资讯列表 */}
              <div className="space-y-2">
                {cur.items.length === 0 ? (
                  <p className="py-6 text-center text-sm text-muted-foreground/60">近 {data!.recent_days} 天该赛道暂无更新</p>
                ) : (
                  cur.items.map((it, i) => (
                    <a key={i} href={it.url} target="_blank" rel="noreferrer"
                      className="group flex items-baseline gap-3 border-b border-border/30 pb-2 text-sm last:border-0">
                      <span className="w-24 shrink-0 font-mono text-xs text-muted-foreground/70">{it.time}</span>
                      <span className="w-20 shrink-0 truncate text-xs text-muted-foreground">{it.source}</span>
                      <span className="flex-1 group-hover:text-primary">{it.zh || it.title}</span>
                      <ExternalLink className="mt-0.5 h-3 w-3 shrink-0 text-muted-foreground/0 group-hover:text-primary/60" />
                    </a>
                  ))
                )}
              </div>
            </>
          )}
        </>
      )}
    </div>
  );
}

// 关注股公告 / 新闻聚合：从本地关注列表取代码，复用个股接口批量拉取、按时间倒序合并。
// 只做公开信息聚合，标的均为用户自己关注列表里的。
interface FeedRow { code: string; name: string; when: string; title: string; meta?: string; url?: string }
const MAX_ROWS = 60;

// 业绩报告判定：白名单命中且不在黑名单 → 保留
// 白名单 = 定期报告（年报/中报/季报全文与摘要）+ 业绩预告/快报 + 主要经营数据公告
// 黑名单 = 业绩说明会/发布会、募集资金、审计报告、调研活动、再融资 等事务性公告
const EARNINGS_TYPE_KW = ["年报", "中报", "季报", "业绩预告", "业绩快报", "经营数据", "报告"];
const EARNINGS_TITLE_KW = ["年度报告", "半年度报告", "季度报告", "主要经营数据", "业绩预告", "业绩快报"];
const EARNINGS_BLACK_TYPE = ["募集资金", "审计报告", "调研活动", "再融资"];
const EARNINGS_BLACK_TITLE = ["业绩说明会", "业绩发布会", "业绩说明", "业绩发布", "募集资金", "审计报告", "再融资"];
function isEarningsAnnouncement(type: string, title: string): boolean {
  // 黑名单优先：明确事务性公告直接排除（业绩说明会、募集资金、审计报告等）
  if (EARNINGS_BLACK_TYPE.some((k) => type.includes(k))) return false;
  if (EARNINGS_BLACK_TITLE.some((k) => title.includes(k))) return false;
  // 白名单：定期报告 / 业绩预告·快报 / 经营数据
  return EARNINGS_TYPE_KW.some((k) => type.includes(k)) || EARNINGS_TITLE_KW.some((k) => title.includes(k));
}

function WatchlistFeed({ kind }: { kind: "filings" | "news" }) {
  const [poolStocks, setPoolStocks] = useState<{ code: string; name: string; industry: string }[]>([]);
  const [industry, setIndustry] = useState("");
  const [stockCode, setStockCode] = useState("");
  const [days, setDays] = useState(7);  // 日期范围：0 = 全部
  const [earningsOnly, setEarningsOnly] = useState(true);  // 业绩报告筛选（默认打开，仅 A 股公告）
  const [rows, setRows] = useState<FeedRow[]>([]);
  const [loading, setLoading] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const [depNote, setDepNote] = useState<string | null>(null);

  // 半年报追踪抽屉状态
  const [hyOpen, setHyOpen] = useState(false);
  const [hyLoading, setHyLoading] = useState(false);
  const [hyErr, setHyErr] = useState<string | null>(null);
  const [hyData, setHyData] = useState<HalfYearReport | null>(null);
  const [hyDays, setHyDays] = useState(1);

  // 标的池 = 核心股票池（/api/stock-pool）；公告/新闻接口仅支持 A 股 6 位代码
  const loadPoolStocks = useCallback(async () => {
    try {
      const r = await fetch("/api/stock-pool").then((x) => x.json());
      const stocks = ((r?.data?.stocks || []) as Array<{ code: string; name: string; industry: string }>)
        .map((s) => ({ code: s.code || "", name: s.name || "", industry: s.industry || "" }))
        .filter((s) => s.code && /^\d{6}$/.test(s.code));
      setPoolStocks(stocks);
      return stocks;
    } catch {
      return [];
    }
  }, []);

  const industries = useMemo(
    () => Array.from(new Set(poolStocks.map((s) => s.industry).filter(Boolean))).sort(),
    [poolStocks],
  );
  const filtered = useMemo(
    () => poolStocks.filter((s) => (!industry || s.industry === industry) && (!stockCode || s.code === stockCode)),
    [poolStocks, industry, stockCode],
  );

  const load = useCallback(async (cs: string[]) => {
    if (!cs.length) { setRows([]); return; }
    setLoading(true); setErr(null); setDepNote(null);
    try {
      // 股名（一次批量），失败则退回显示代码
      const nameOf: Record<string, string> = {};
      try {
        const quotes = await api.quote(cs.join(","));
        for (const c of cs) if (quotes[c]?.name) nameOf[c] = quotes[c].name;
      } catch { /* 忽略：无股名不影响公告/新闻 */ }

      const out: FeedRow[] = [];
      if (kind === "filings") {
        // 分批（每批 10 只）拉公告，避免 140+ 并发打爆上游
        const res: { c: string; a: Announcement[] }[] = [];
        for (let i = 0; i < cs.length; i += 10) {
          const batch = await Promise.all(
            cs.slice(i, i + 10).map((c) => api.announcements(c).then((a) => ({ c, a })).catch((e) => { console.warn("[intel] 公告失败:", c, e); return { c, a: [] as Announcement[] }; })),
          );
          res.push(...batch);
        }
        for (const { c, a } of res)
          for (const x of a)
            out.push({ code: c, name: nameOf[c] || c, when: x.date, title: x.title.replace(/^[^:：]*[:：]/, ""), meta: x.type, url: x.url });
      } else {
        let dep: string | null = null;
        const res: { c: string; n: NewsItem[] }[] = [];
        for (let i = 0; i < cs.length; i += 10) {
          const batch = await Promise.all(
            cs.slice(i, i + 10).map((c) =>
              api.news(c).then((n) => ({ c, n })).catch((e) => {
                if (e instanceof ApiError && e.status === 501) dep = e.message;
                return { c, n: [] as NewsItem[] };
              }),
            ),
          );
          res.push(...batch);
        }
        for (const { c, n } of res)
          for (const x of n)
            out.push({ code: c, name: nameOf[c] || c, when: x.发布时间 || "", title: x.新闻标题 || "", url: x.新闻链接 });
        if (dep && out.length === 0) setDepNote(dep);
      }
      // 按真实时间倒序：多新闻源的时间字符串格式不统一（有无秒/斜杠日期），字典序会排乱
      const ts = (s: string) => {
        const raw = (s || "").trim();
        let t = Date.parse(raw);
        if (Number.isNaN(t)) t = Date.parse(raw.replace(" ", "T"));
        return Number.isNaN(t) ? 0 : t;
      };
      // 日期范围过滤（近 N 天；0 = 全部）
      const cutoff = days > 0 ? Date.now() - days * 86400000 : 0;
      const inRange = cutoff > 0 ? out.filter((r) => ts(r.when) >= cutoff) : out;
      inRange.sort((p, q) => ts(q.when) - ts(p.when));
      // 兜底：拉到股票池但一条公告都没拿到 → 提示上游可能异常，避免静默 0 条
      if (cs.length > 0 && inRange.length === 0 && kind === "filings") {
        setDepNote("已请求 " + cs.length + " 只个股公告，但接口均返回空（可能上游被掐或非交易时段）。可点「刷新」重试或切换「近 30 天」。");
      }
      // 存全量（未截断），展示层再按「业绩报告」筛选 + 截断
      setRows(inRange);
    } catch (e) {
      setErr(e instanceof ApiError ? e.message : "加载失败");
    } finally {
      setLoading(false);
    }
  }, [kind, days]);

  useEffect(() => { loadPoolStocks(); }, [loadPoolStocks]);
  useEffect(() => { load(filtered.map((s) => s.code)); }, [load, filtered]);

  const refresh = () => { load(filtered.map((s) => s.code)); };

  // 半年报追踪：拉取窗口期内发布半年报的自选股聚合报告
  const fetchHalfYear = useCallback(async (d: number) => {
    if (!poolStocks.length) return;
    setHyLoading(true); setHyErr(null);
    try {
      const names: Record<string, string> = {};
      const codes = poolStocks.map((s) => { names[s.code] = s.name; return s.code; });
      const data = await api.halfYearReport(codes, d, names);
      setHyData(data);
    } catch (e) {
      setHyErr(e instanceof ApiError ? e.message : "半年报聚合失败");
      setHyData(null);
    } finally {
      setHyLoading(false);
    }
  }, [poolStocks]);

  const openHalfYear = () => {
    setHyOpen(true);
    setHyDays(1);
    if (!hyData) fetchHalfYear(1);
  };

  // 展示行：业绩报告筛选（默认开启）→ 再截断；切换筛选无需重新请求
  const visibleRows = useMemo(() => {
    const base = kind === "filings" && earningsOnly
      ? rows.filter((r) => isEarningsAnnouncement(r.meta || "", r.title))
      : rows;
    return base.slice(0, MAX_ROWS);
  }, [rows, kind, earningsOnly]);

  if (!poolStocks.length) {
    return (
      <div className="rounded-lg border border-dashed border-border/70 p-8 text-center text-sm text-muted-foreground/70">
        核心股票池暂无 A 股标的，这里会汇总它们的{kind === "filings" ? "公告" : "新闻"}。
      </div>
    );
  }

  const selStyle = "rounded-lg border border-border/60 bg-background/60 px-2.5 py-1.5 text-xs outline-none focus:border-primary/60";

  return (
    <div>
      <div className="mb-3 flex flex-wrap items-center gap-2">
        <select value={industry} onChange={(e) => { setIndustry(e.target.value); setStockCode(""); }} className={selStyle}>
          <option value="">全部行业</option>
          {industries.map((x) => <option key={x}>{x}</option>)}
        </select>
        <select value={stockCode} onChange={(e) => setStockCode(e.target.value)} className={selStyle}>
          <option value="">全部个股</option>
          {poolStocks.filter((s) => !industry || s.industry === industry).map((s) => (
            <option key={s.code} value={s.code}>{s.name}（{s.code}）</option>
          ))}
        </select>
        <select value={days} onChange={(e) => setDays(Number(e.target.value))} className={selStyle}>
          <option value={1}>近 1 天</option>
          <option value={3}>近 3 天</option>
          <option value={7}>近 7 天</option>
          <option value={30}>近 30 天</option>
          <option value={0}>全部日期</option>
        </select>
        <span className="flex items-center gap-1.5 text-xs text-muted-foreground">
          <Star className="h-3.5 w-3.5 text-primary/70" /> 筛选 {filtered.length} 只 · 共 {visibleRows.length} 条{kind === "filings" ? "公告" : "新闻"}
        </span>
        {kind === "filings" && (
          <button onClick={() => setEarningsOnly((v) => !v)}
            title="只显示年报 / 中报 / 季报 / 业绩预告等业绩类公告，过滤事务性公告"
            className={cn("inline-flex items-center gap-1.5 rounded-lg border px-3 py-1.5 text-sm transition-colors",
              earningsOnly ? "border-primary/50 bg-primary/15 font-medium text-primary" : "border-border text-muted-foreground hover:text-foreground")}>
            业绩报告
          </button>
        )}
        {kind === "filings" && (
          <button onClick={openHalfYear}
            title="汇总自选股池中近 24 小时内发布半年报的公司：实际H1净利 + 同花顺一致预期 + 完成度（网页公开数据）"
            className="inline-flex items-center gap-1.5 rounded-lg border border-border px-3 py-1.5 text-sm text-muted-foreground hover:text-foreground">
            <BarChart3 className="h-4 w-4" />半年报追踪
          </button>
        )}
        <button onClick={refresh} disabled={loading}
          className="inline-flex items-center gap-1.5 rounded-lg border border-border px-3 py-1.5 text-sm text-muted-foreground hover:text-foreground disabled:opacity-50">
          {loading ? <Loader2 className="h-4 w-4 animate-spin" /> : <RefreshCw className="h-4 w-4" />}
          {loading ? "拉取中…" : "刷新"}
        </button>
      </div>

      {err && (
        <div className="mb-3 flex items-center gap-2 rounded-lg border border-destructive/30 bg-destructive/5 p-3 text-sm text-destructive">
          <AlertCircle className="h-4 w-4 shrink-0" /> {err}
        </div>
      )}

      {depNote ? (
        <p className="py-6 text-center text-xs text-warning">{depNote}（安装后新闻即可用）</p>
      ) : loading && rows.length === 0 ? (
        <p className="flex items-center justify-center gap-2 py-8 text-sm text-muted-foreground"><Loader2 className="h-4 w-4 animate-spin" /> 正在汇总关注股的{kind === "filings" ? "公告" : "新闻"}…</p>
      ) : visibleRows.length === 0 ? (
        <p className="py-8 text-center text-sm text-muted-foreground/60">
          {kind === "filings" && earningsOnly
            ? "关注列表里的个股近期暂无业绩报告，可关闭「业绩报告」筛选查看全部公告。"
            : `关注列表里的个股近期暂无${kind === "filings" ? "公告" : "新闻"}。`}
        </p>
      ) : (
        <div className="space-y-2">
          {visibleRows.map((r, i) => (
            <a key={i} href={r.url || undefined} target={r.url ? "_blank" : undefined} rel="noreferrer"
              className={cn("group flex items-baseline gap-3 border-b border-border/30 pb-2 text-sm last:border-0", r.url && "cursor-pointer")}>
              <span className="w-20 shrink-0 font-mono text-xs text-muted-foreground/70">{(r.when || "").slice(kind === "filings" ? 0 : 5, kind === "filings" ? 10 : 16)}</span>
              <span className="w-16 shrink-0 truncate text-xs text-primary/90" title={r.code}>{r.name}</span>
              {kind === "filings" && r.meta && <span className="hidden w-20 shrink-0 truncate text-xs text-muted-foreground sm:block">{r.meta}</span>}
              <span className="flex-1 group-hover:text-primary">{r.title}</span>
              {r.url && <ExternalLink className="mt-0.5 h-3 w-3 shrink-0 text-muted-foreground/0 group-hover:text-primary/60" />}
            </a>
          ))}
        </div>
      )}

      {/* 半年报追踪抽屉 */}
      {hyOpen && (
        <div className="fixed inset-0 z-40 bg-black/40" onClick={() => setHyOpen(false)} />
      )}
      {hyOpen && (
        <aside className="fixed inset-y-0 right-0 z-50 flex w-[480px] max-w-full flex-col border-l border-border bg-background shadow-2xl">
          {/* Header */}
          <div className="flex items-center justify-between border-b border-border px-4 py-3">
            <div className="flex items-center gap-2">
              <BarChart3 className="h-4 w-4 text-primary" />
              <h2 className="text-sm font-medium">自选股半年报追踪</h2>
            </div>
            <button onClick={() => setHyOpen(false)} className="rounded p-1 text-muted-foreground hover:bg-muted hover:text-foreground" title="关闭">
              <X className="h-4 w-4" />
            </button>
          </div>

          {/* 工具栏：时间窗切换 + 摘要 */}
          <div className="flex items-center gap-2 border-b border-border/60 px-4 py-2 text-xs">
            <span className="text-muted-foreground">时间窗</span>
            {([1, 7, 30] as const).map((d) => (
              <button key={d} onClick={() => { setHyDays(d); fetchHalfYear(d); }}
                className={cn("rounded border px-2 py-0.5 text-xs",
                  hyDays === d ? "border-primary/50 bg-primary/15 text-primary" : "border-border text-muted-foreground hover:text-foreground")}>
                近 {d} 天
              </button>
            ))}
            {hyData && (
              <span className="ml-auto text-muted-foreground/80">
                扫描 {hyData.scanned} · 命中 {hyData.published} · 财务覆盖 {hyData.covered}
              </span>
            )}
          </div>

          {/* 内容区 */}
          <div className="flex-1 overflow-y-auto px-4 py-3 text-sm">
            {hyErr && (
              <div className="flex items-center gap-2 rounded-lg border border-destructive/30 bg-destructive/5 p-3 text-sm text-destructive">
                <AlertCircle className="h-4 w-4 shrink-0" />{hyErr}
              </div>
            )}
            {hyLoading && !hyData && (
              <p className="flex items-center justify-center gap-2 py-12 text-sm text-muted-foreground">
                <Loader2 className="h-4 w-4 animate-spin" />正在批量扫描公告并汇总命中公司的财务数据…
              </p>
            )}
            {hyData && (
              <>
                {hyData.fetched_at && (
                  <p className="mb-3 text-xs text-muted-foreground/70">
                    数据时间：{hyData.fetched_at}　|　公告扫描{hyData.scan_complete ? "完整" : "不完整"}，
                    {hyData.announcement_requests} 次批量请求覆盖 {hyData.requested_codes} 只股票　|　
                    一致预期来自同花顺盈利预测，完成度 = 实际H1净利 / 当年全年预期
                  </p>
                )}
                {hyData.published === 0 && (
                  <p className="py-12 text-center text-muted-foreground/60">
                    近 {hyData.window_days} 天自选股池中无新增半年报披露。
                  </p>
                )}
                {([
                  ["big_beat", "大幅超预期（完成度 ≥ 70%）", TrendingUp, "text-emerald-600 dark:text-emerald-400"],
                  ["meet", "符合预期", Sparkles, "text-primary"],
                  ["pending", "预期待验证", Lightbulb, "text-muted-foreground"],
                ] as const).map(([key, title, Icon, color]) => {
                  const items = hyData.groups[key];
                  if (!items.length) return null;
                  return (
                    <section key={key} className="mb-5">
                      <h3 className={cn("mb-2 flex items-center gap-1.5 text-sm font-medium", color)}>
                        <Icon className="h-4 w-4" />{title}　<span className="text-xs text-muted-foreground/70">{items.length} 家</span>
                      </h3>
                      <ul className="space-y-1.5">
                        {items.map((row) => {
                          const yoy = row.yoy_pct;
                          const yoyColor = yoy == null ? "text-muted-foreground/70" :
                            yoy >= 100 ? "text-emerald-600 dark:text-emerald-400" :
                            yoy <= -30 ? "text-rose-600 dark:text-rose-400" :
                            "text-muted-foreground";
                          return (
                            <li key={row.code} className="rounded-md border border-border/60 px-2.5 py-1.5">
                              <div className="flex items-baseline gap-2 text-sm">
                                {row.ann_url ? (
                                  <a href={row.ann_url} target="_blank" rel="noreferrer"
                                    className="font-mono text-xs text-primary/90 hover:underline">{row.code}</a>
                                ) : (
                                  <span className="font-mono text-xs text-primary/90">{row.code}</span>
                                )}
                                <span className="flex-1 truncate text-sm">{row.name || row.code}</span>
                                {row.completion_pct != null ? (
                                  <span className="shrink-0 text-xs font-medium tabular-nums text-primary">
                                    完成度 {row.completion_pct.toFixed(1)}%
                                  </span>
                                ) : (
                                  <span className={cn("shrink-0 text-xs font-medium tabular-nums", yoyColor)}>
                                    {yoy == null ? "—" : `同比 ${yoy >= 0 ? "+" : ""}${yoy.toFixed(1)}%`}
                                  </span>
                                )}
                              </div>
                              <div className="mt-0.5 flex flex-wrap items-center gap-x-3 gap-y-0.5 text-xs text-muted-foreground/80">
                                {row.net_profit_yi != null && (
                                  <span>实际 H1 净利 <span className="text-foreground tabular-nums">{row.net_profit_yi >= 0 ? "" : "-"}{Math.abs(row.net_profit_yi).toFixed(2)} 亿</span></span>
                                )}
                                {row.consensus_mean != null && (
                                  <span>一致预期 <span className="tabular-nums">{row.consensus_mean.toFixed(1)} 亿</span>
                                    {row.consensus_n ? <span className="text-muted-foreground/60">（{row.consensus_n} 机构）</span> : null}
                                  </span>
                                )}
                                {row.yoy_pct != null && row.completion_pct != null && (
                                  <span className={yoyColor}>同比 {row.yoy_pct >= 0 ? "+" : ""}{row.yoy_pct.toFixed(1)}%</span>
                                )}
                                {row.period && <span>报告期 {row.period}</span>}
                                {row._note && <span className="text-warning/80">{row._note}</span>}
                              </div>
                            </li>
                          );
                        })}
                      </ul>
                    </section>
                  );
                })}
              </>
            )}
          </div>
        </aside>
      )}
    </div>
  );
}

export function Intel() {
  const [tab, setTab] = useState("investment-news");
  const cur = TABS.find((t) => t.key === tab)!;

  return (
    <div>
      <PageHeader title="资讯雷达" subtitle="多来源资讯中心：AI 帮你跨源捞资讯、提炼要点" />

      <div className="mb-4 flex flex-wrap gap-2">
        {TABS.map(({ key, label, icon: Icon, integrated }) => (
          <button key={key} onClick={() => setTab(key)}
            className={cn("inline-flex items-center gap-1.5 rounded-lg px-3 py-1.5 text-sm transition-colors",
              tab === key ? "bg-primary/15 font-medium text-primary shadow-glow" : "text-muted-foreground hover:bg-muted/50")}>
            <Icon className="h-4 w-4" /> {label}
            {integrated && <span className="rounded-full bg-primary/20 px-1.5 py-0.5 text-[9px] font-medium text-primary">集成</span>}
          </button>
        ))}
      </div>

      <GlassCard glow>
        <div className="mb-3 flex items-center gap-2">
          <cur.icon className="h-5 w-5 text-primary" />
          <h3 className="font-semibold">{cur.label}</h3>
          {cur.integrated && <span className="rounded-full bg-primary/15 px-2 py-0.5 text-[10px] text-primary">investment-news</span>}
        </div>
        {cur.key === "investment-news" ? (
          <InvestmentNewsPanel />
        ) : cur.key === "filings" ? (
          <WatchlistFeed kind="filings" />
        ) : cur.key === "news" ? (
          <WatchlistFeed kind="news" />
        ) : (
          <>
            <p className="text-sm text-muted-foreground">{cur.desc}</p>
            <div className="mt-4 rounded-lg border border-dashed border-border/70 p-8 text-center text-sm text-muted-foreground/70">该数据源规划中——可先用右侧「Investment News」看 12 赛道公开资讯，或用「A 股公告 / 公开新闻」看关注股动态。</div>
          </>
        )}
      </GlassCard>
    </div>
  );
}
