import { useCallback, useEffect, useMemo, useState } from "react";
import { RefreshCw, CloudUpload, Plus } from "lucide-react";
import { AskAiButton } from "@/components/ui/AskAiButton";
import { addCodes } from "@/lib/watchlist";
import "./stock-pool.css";

/* ============================================================
   自选股 · 核心股票池 Dashboard V0.1（合并原「自选股」页功能）
   研究视图（复刻母版）+ 池子可编辑（增删 → 后端 JSON → GitHub 真源）
   + AI 读自选 / 批量添加（合并自「自选股」页功能，日度数据）
   ============================================================ */

interface Stock {
  instrument_id: string; code: string | null; exchange: string | null; name: string;
  industry: string; price: number | null; change: number | null; change_5d: number | null;
  change_20d: number | null; ytd: number | null; amount_yi: number | null; mcap_yi: number | null;
  turnover: number | null; pe_ttm: number | null; pb: number | null; data_status: string;
  research_baskets?: string[];
}
interface ResearchBasket {
  key: string; name: string; codes: string[]; count: number;
}
interface IndexRow {
  code: string; name: string; price: number | null; change: number | null; change_5d: number | null;
  change_20d: number | null; ytd: number | null; amount_yi: number | null; mcap_yi: number | null;
}
interface Payload {
  meta: { report_date: string };
  definitions?: { focus_codes: string[]; research_baskets: ResearchBasket[] };
  summary: {
    tracked_count: number;
    breadth: { count: number; up: number; down: number; flat: number; median: number | null };
    avg_change: number | null; total_amount_yi: number;
  };
  stocks: Stock[];
  indices: IndexRow[];
  heatmap: { instrument_id: string; name: string; industry: string; change: number | null; change_5d: number | null; change_20d: number | null; ytd: number | null; weight: number }[];
  leaders: {
    up: Stock[]; down: Stock[];               // 今日（兼容旧字段）
    today: { up: Stock[]; down: Stock[] };
    "5d": { up: Stock[]; down: Stock[] };
    "20d": { up: Stock[]; down: Stock[] };
  };
  default_index_selfselect: string[];
}
interface StockPoolPublication {
  data_date: string;
  published_at?: string;
  source?: string;
  using_fallback?: boolean;
}

const UP = "#f2503f", DOWN = "#2fbf71";
const fmt = (v: number | null | undefined, d = 2) => (v == null || Number.isNaN(Number(v)) ? "--" : Number(v).toFixed(d));
const pct = (v: number | null | undefined) => (v == null ? "--" : `${Number(v) >= 0 ? "+" : ""}${(Number(v) * 100).toFixed(2)}%`);
const cls = (v: number | null | undefined) => (v == null ? "neutral" : v > 0 ? "up" : v < 0 ? "down" : "neutral");

// 热力图周期：与「行业强弱」的下拉保持一致
type PeriodKey = "change" | "change_5d" | "change_20d" | "ytd";
const HEAT_PERIOD_LABEL: Record<PeriodKey, string> = {
  change: "今日", change_5d: "5日", change_20d: "20日", ytd: "YTD",
};
const HEAT_PERIODS: { key: PeriodKey; label: string }[] = [
  { key: "change", label: "今日" },
  { key: "change_5d", label: "5日" },
  { key: "change_20d", label: "20日" },
  { key: "ytd", label: "YTD" },
];

// 色阶随所选周期动态缩放：maxAbs 为该周期 P90 涨幅绝对值（避免个别极端值撑爆色阶）
function heatColor(v: number | null, maxAbs = 0.08): string {
  // 深夜底 + 白字：用深饱和色阶，保证对比度
  if (v == null) return "#4a5a70";
  const x = Math.min(Math.abs(v) / maxAbs, 1);
  if (v >= 0) {
    const r = Math.round(138 + 84 * x), g = Math.round(56 - 18 * x), b = Math.round(56 - 16 * x);
    return `rgb(${r},${g},${b})`;
  }
  const r = Math.round(28), g = Math.round(108 + 62 * x), b = Math.round(70 + 8 * x);
  return `rgb(${r},${g},${b})`;
}

function sortValue(v: unknown): number | string | null {
  if (v == null || v === "") return null;
  if (typeof v === "number") return v;
  const n = Number(v);
  return Number.isFinite(n) && String(v).trim() !== "" ? n : String(v).toLocaleLowerCase();
}
function sortRows<T>(rows: T[], key: string | null, dir: "asc" | "desc" | null): T[] {
  if (!key || !dir) return [...rows];
  return rows
    .map((r, i) => ({ r, i }))
    .sort((a, b) => {
      const left = a.r as Record<string, unknown>;
      const right = b.r as Record<string, unknown>;
      const av = sortValue(left[key]), bv = sortValue(right[key]);
      if (av == null && bv == null) return a.i - b.i;
      if (av == null) return 1;
      if (bv == null) return -1;
      let c = typeof av === "number" && typeof bv === "number" ? av - bv : String(av).localeCompare(String(bv), "zh-CN", { numeric: true });
      if (c === 0) c = a.i - b.i;
      return dir === "asc" ? c : -c;
    })
    .map((x) => x.r);
}

function useStockPool() {
  const [data, setData] = useState<Payload | null>(null);
  const [publication, setPublication] = useState<StockPoolPublication | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const load = useCallback(() => {
    fetch(`/api/stock-pool?_ts=${Date.now()}`, { cache: "no-store" })
      .then((r) => { if (!r.ok) throw new Error(`HTTP ${r.status}`); return r.json(); })
      .then((b) => {
        setData(b.data as Payload);
        setPublication((b.publication as StockPoolPublication) || null);
        setError(null);
      })
      .catch((e) => setError(e instanceof Error ? e.message : "加载失败"))
      .finally(() => setLoading(false));
  }, []);
  useEffect(() => { load(); }, [load]);
  return { data, publication, error, loading, refresh: load };
}

export function StockPool() {
  const { data, publication, error, loading, refresh: refreshAll } = useStockPool();
  const [period, setPeriod] = useState<"change" | "change_5d" | "change_20d" | "ytd">("change");
  // 热力图独立周期（不与「行业强弱」联动，各自可看不同维度）
  const [heatPeriod, setHeatPeriod] = useState<PeriodKey>("change");
  const [stockSort, setStockSort] = useState<{ key: string | null; dir: "asc" | "desc" | null }>({ key: null, dir: null });
  const [search, setSearch] = useState("");
  const [stockFilter, setStockFilter] = useState("");
  const [stockDataCode, setStockDataCode] = useState<string | null>(null);

  // —— AI 读自选（合并自「自选股」页功能）：把池子日度行情喂给 AI ——
  const poolAiContext = useMemo(() => {
    if (!data?.stocks?.length) return "还没有股票池数据。";
    const lines = data.stocks.slice(0, 80).map((s) =>
      `${s.name}(${s.code || "无码"}) 现价${fmt(s.price, 2)} 今日${pct(s.change)} 5日${pct(s.change_5d)} 20日${pct(s.change_20d)} PE${fmt(s.pe_ttm, 1)} PB${fmt(s.pb, 2)} 换手${pct(s.turnover)}`
    );
    return `核心股票池（共 ${data.stocks.length} 只，展示前 80 只）：\n${lines.join("\n")}`;
  }, [data]);
  const [batchInput, setBatchInput] = useState("");

  // —— 近期关注（定义层并入 pool.json，同步 GitHub；在筛选器里作为第一层）——
  const [watchCodes, setWatchCodes] = useState<string[]>([]);
  const [focusInput, setFocusInput] = useState("");
  useEffect(() => {
    setWatchCodes(data?.definitions?.focus_codes || []);
  }, [data]);
  const persistFocus = (codes: string[]) => {
    fetch("/api/stock-pool/focus", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ codes }) }).catch((e) => console.warn("[stock-pool] focus 保存失败:", e));
  };
  const addFocus = () => {
    const { next, added } = addCodes(watchCodes, focusInput);
    if (!added) { setFocusInput(""); return; }
    setWatchCodes(next); persistFocus(next); setFocusInput("");
  };
  const removeFocus = (c: string) => {
    const next = watchCodes.filter((x) => x !== c);
    setWatchCodes(next); persistFocus(next);
  };
  // —— 池子编辑（批量添加 / 同步 GitHub，收纳在「编辑池子」弹窗）——
  const [editOpen, setEditOpen] = useState(false);
  const [poolMsg, setPoolMsg] = useState<string | null>(null);
  const [syncing, setSyncing] = useState(false);
  const apiPost = (url: string, body: unknown) => fetch(url, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) }).then((r) => r.json());
  const addBatch = async () => {
    const codes = (batchInput.match(/\d{5,6}/g) || []).slice(0, 50);
    if (!codes.length) { setPoolMsg("没识别到证券代码"); return; }
    const r = await apiPost("/api/stock-pool/add-batch", { codes });
    if (r.data?.ok) {
      const f = r.data.failed?.length ? `；失败 ${r.data.failed.length}（${r.data.failed.join("、")}）` : "";
      setPoolMsg(`已添加 ${r.data.added.length} 只，池子 ${r.data.count} 只（已同步 GitHub）${f}`);
    } else setPoolMsg(r.error || "批量添加失败");
    setBatchInput("");
    refreshAll();
  };
  const removePool = async (id: string, name: string) => {
    // 从核心股票池移除 = 会同步 GitHub，属较重操作 → 二次确认，防止与「取消关注」混淆
    if (!window.confirm(`确定将「${name}」从核心股票池移除？\n此操作会同步到 GitHub（vibe_research/data/stock-pool/pool.json），且近期关注里也会随之消失。`)) return;
    const r = await fetch(`/api/stock-pool/remove?instrument_id=${encodeURIComponent(id)}`, { method: "DELETE" }).then((x) => x.json());
    setPoolMsg(r.data?.ok ? `已移除，池子 ${r.data.count} 只（已同步 GitHub）` : (r.error || "移除失败"));
    refreshAll();
  };
  // 明细表行删除：近期关注模式下只改 pool.json 里的 focus；其他模式下才动核心股票池定义
  const handleRemoveRow = (x: Stock) => {
    if (stockFilter === "__focus__") {
      if (x.code) removeFocus(x.code); // 仅取消关注，绝不涉及池子 / GitHub
    } else {
      removePool(x.instrument_id, x.name);
    }
  };
  const syncNow = async () => {
    setSyncing(true);
    const r = await apiPost("/api/stock-pool/sync", {});
    setPoolMsg(r.data?.ok ? `已同步 GitHub（commit ${r.data.commit}）` : (r.error || "同步失败"));
    setSyncing(false);
  };

  const breadth = useMemo(() => {
    const bins = [0, 0, 0, 0, 0];
    if (!data) return bins;
    data.stocks.forEach((s) => {
      const v = s.change;
      if (v == null) return;
      if (v <= -0.05) bins[0]++;
      else if (v < -0.01) bins[1]++;
      else if (v <= 0.01) bins[2]++;
      else if (v < 0.05) bins[3]++;
      else bins[4]++;
    });
    return bins;
  }, [data]);

  // 热力图 tiles：市值取前 120 → 按行业聚类（同行业相邻，行业内按所选周期涨跌降序）
  const heatTiles = useMemo(() => {
    if (!data) return { tiles: [], maxAbs: 0.08 };
    const rows = [...data.heatmap]
      .sort((a, b) => (b.weight || 0) - (a.weight || 0))
      .slice(0, 120)
      .sort((a, b) => {
        const ia = (a.industry || "~").localeCompare(b.industry || "~", "zh-CN");
        if (ia !== 0) return ia;
        return (b[heatPeriod] ?? 0) - (a[heatPeriod] ?? 0);
      });
    const weights = rows.map((x) => x.weight || 1).sort((a, b) => a - b);
    const q = (p: number) => weights[Math.floor((weights.length - 1) * p)] || 1;
    const q60 = q(0.6), q82 = q(0.82), q94 = q(0.94);
    const tiles = rows.map((x) => ({
      ...x,
      size: x.weight >= q94 ? "s4" : x.weight >= q82 ? "s3" : x.weight >= q60 ? "s2" : "s1",
    }));
    // 色阶刻度：取所选周期涨幅绝对值的 P90，避免个别极值（如 +70% YTD）把其余 tile 全冲成浅色
    const absVals = rows
      .map((x) => Math.abs(x[heatPeriod] ?? 0))
      .filter((v) => Number.isFinite(v) && v > 0)
      .sort((a, b) => a - b);
    const maxAbs = absVals.length
      ? Math.max(absVals[Math.min(Math.floor(absVals.length * 0.9), absVals.length - 1)], 0.005)
      : 0.08;
    return { tiles, maxAbs };
  }, [data, heatPeriod]);

  const ranking = useMemo(() => {
    if (!data) return { view: [] as IndexRow[], max: 0.0001 };
    const rows = [...data.indices].filter((x) => typeof x[period] === "number").sort((a, b) => (b[period] ?? 0) - (a[period] ?? 0));
    const view = [...rows.slice(0, 8), ...rows.slice(-8)];
    const max = Math.max(...view.map((x) => Math.abs(x[period] ?? 0)), 0.0001);
    return { view, max };
  }, [data, period]);

  const matrix = useMemo(() => {
    if (!data) return [];
    return data.stocks.filter((x) => typeof x.change === "number" && typeof x.change_20d === "number");
  }, [data]);

  const industries = useMemo(
    () => (data ? [...new Set(data.stocks.map((x) => x.industry).filter(Boolean))].sort((a, b) => a.localeCompare(b, "zh-CN")) : []),
    [data],
  );
  const researchBaskets = useMemo(() => data?.definitions?.research_baskets || [], [data]);
  const basketCodesByFilter = useMemo(() => {
    const out: Record<string, string[]> = {};
    researchBaskets.forEach((basket) => {
      out[`basket:${basket.key}`] = basket.codes || [];
    });
    return out;
  }, [researchBaskets]);

  const filteredStocks = useMemo(() => {
    if (!data) return [];
    const q = search.trim().toLowerCase();
    const focusMode = stockFilter === "__focus__";
    const basketCodes = basketCodesByFilter[stockFilter] || [];
    const selectedIndustry = stockFilter.startsWith("industry:") ? stockFilter.slice("industry:".length) : "";
    if (focusMode) {
      // 近期关注也统一按日更缓存口径展示，不再混入实时 quote。
      const all: Stock[] = [];
      watchCodes.forEach((c) => {
        const s = data.stocks.find((x) => x.code === c);
        all.push({
          instrument_id: s?.instrument_id || `watch:${c}`,
          code: c,
          exchange: s?.exchange || "",
          name: s?.name || c,
          industry: s?.industry || "",
          price: s?.price ?? null,
          change: s?.change ?? null,
          change_5d: s?.change_5d ?? null,
          change_20d: s?.change_20d ?? null,
          ytd: s?.ytd ?? null,
          amount_yi: s?.amount_yi ?? null,
          mcap_yi: s?.mcap_yi ?? null,
          turnover: s?.turnover ?? null,
          pe_ttm: s?.pe_ttm ?? null,
          pb: s?.pb ?? null,
          data_status: s?.data_status || "no_snapshot",
        });
      });
      if (q) return all.filter((x) => (x.name || "").toLowerCase().includes(q) || (x.industry || "").toLowerCase().includes(q) || (x.code || "").toLowerCase().includes(q));
      return all;
    }
    return data.stocks.filter(
      (x) =>
        (!q || (x.name || "").toLowerCase().includes(q) || (x.industry || "").toLowerCase().includes(q) || (x.code || "").toLowerCase().includes(q)) &&
        (!selectedIndustry || x.industry === selectedIndustry) &&
        (!basketCodes.length || basketCodes.includes(x.code || "")),
    );
  }, [data, search, stockFilter, watchCodes, basketCodesByFilter]);

  const stockRows = useMemo(() => sortRows(filteredStocks, stockSort.key, stockSort.dir), [filteredStocks, stockSort]);

  const cycleSort = (key: string) => {
    setStockSort((s) => {
      if (s.key !== key) return { key, dir: "desc" as const };
      if (s.dir === "desc") return { key, dir: "asc" as const };
      return { key: null, dir: null };
    });
  };

  if (loading) return <div className="sp-root"><div className="page"><div className="empty">正在加载股票池数据…</div></div></div>;
  if (error || !data) return <div className="sp-root"><div className="page"><div className="empty" style={{ color: "#dc2626" }}>加载失败：{error ?? "无数据"}</div></div></div>;

  const b = data.summary.breadth;
  const binTotal = breadth.reduce((a, x) => a + x, 0) || 1;
  const sortInd = (key: string, s: { key: string | null; dir: "asc" | "desc" | null }) =>
    s.key === key ? (s.dir === "desc" ? "↓" : "↑") : "↕";
  const th = (key: string, label: string, s: { key: string | null; dir: "asc" | "desc" | null }, left = false) => (
    <th className={`sortable${left ? " left" : ""}`} data-sort-key={key} onClick={() => cycleSort(key)}>
      {label}<span className="sort-ind">{sortInd(key, s)}</span>
    </th>
  );

  return (
    <div className="sp-root">
      <div className="page">
        {/* Hero */}
        <header className="hero">
          <h1>A股看板｜核心股票池</h1>
          <div className="meta">
            报告日期 {data.meta.report_date}
            {publication?.published_at ? ` ｜ 缓存发布时间 ${publication.published_at.slice(0, 16).replace("T", " ")}` : ""}
            {publication?.using_fallback ? " ｜ 当前为最后有效缓存" : " ｜ 本页仅展示日更缓存"}
          </div>
        </header>

        {/* KPI */}
        <div className="kpis">
          {[
            ["股票池", String(data.summary.tracked_count), "只", "neutral"],
            ["上涨", String(b.up || 0), "只", "up"],
            ["下跌", String(b.down || 0), "只", "down"],
            ["中位涨幅", pct(b.median), "", cls(b.median)],
            ["平均涨幅", pct(data.summary.avg_change), "", cls(data.summary.avg_change)],
            ["成交额", fmt(data.summary.total_amount_yi, 1), "亿", "neutral"],
          ].map(([label, value, unit, color], i) => (
            <div className="kpi" key={i}>
              <div className="kpi-label">{label}</div>
              <div className={`kpi-value ${color}`}>
                {value}
                {unit ? <span style={{ fontSize: 12, fontWeight: 500, color: "#64748b" }}> {unit}</span> : null}
              </div>
            </div>
          ))}
        </div>

        {/* 股票池涨跌宽度 */}
        <section className="section">
          <div className="section-title">股票池涨跌宽度</div>
          <div className="section-card">
            <div className="breadth">
              {breadth.map((n, i) => (
                <span key={i} className={["d2", "d1", "flat", "u1", "u2"][i]} style={{ width: `${(n / binTotal) * 100}%` }} title={`${n}只`} />
              ))}
            </div>
            <div className="dist-labels">
              <span>≤ -5%</span><span>-5% ~ -1%</span><span>-1% ~ +1%</span><span>+1% ~ +5%</span><span>≥ +5%</span>
            </div>
          </div>
        </section>

        {/* 强弱矩阵（独立一行，放大显示，每个点标注名称） */}
        <section className="section">
          <div className="section-title">强弱矩阵</div>
          <div className="section-card">
            <div className="matrix-wrap matrix-wide">
              {matrix.length === 0 ? (
                <div className="empty">暂无数据</div>
              ) : (
                <MatrixSvg rows={matrix} />
              )}
            </div>
            <div className="matrix-legend">
              <span><i className="dot d-leading" />绿色 = 一致持多（LEADING）</span>
              <span><i className="dot d-lagging" />红色 = 一致持空（LAGGING）</span>
              <span><i className="dot d-mix" />灰色 = 不一致（IMPROVING / WEAKENING）</span>
              <span><i className="dot d-rim" />金边 = 正在右上方移动</span>
            </div>
          </div>
        </section>

        {/* 行：行业 / 指数强弱 + 今日最强 + 今日最弱（一行 3 列） */}
        <div className="chart-grid-quad section">
          <section>
            <div className="section-title">
              <span>行业 / 指数强弱</span>
              <select className="input" value={period} onChange={(e) => setPeriod(e.target.value as typeof period)}>
                <option value="change">今日</option>
                <option value="change_5d">5日</option>
                <option value="change_20d">20日</option>
                <option value="ytd">YTD</option>
              </select>
            </div>
            <div className="section-card">
              <div className="rank-list">
                {ranking.view.map((x) => (
                  <div className="rank-row" key={x.code}>
                    <div className="rank-name">{x.name}</div>
                    <div className="bar-bg">
                      <div className="bar" style={{ width: `${Math.abs(x[period] ?? 0) / ranking.max * 100}%`, background: (x[period] ?? 0) >= 0 ? UP : DOWN }} />
                    </div>
                    <div className={`rank-val ${cls(x[period])}`}>{pct(x[period])}</div>
                  </div>
                ))}
                {ranking.view.length === 0 && <div className="empty">暂无数据</div>}
              </div>
            </div>
          </section>
          <section>
            <div className="section-title">今日最强</div>
            <div className="section-card">
              <div className="leader-col">
                {data.leaders.today.up.map((x) => (
                  <div className="leader-r" key={x.instrument_id}>
                    <button className="stock-link leader-name" title={x.name} onClick={() => setStockDataCode(x.code ?? null)}>{x.name}</button>
                    <span className={`leader-ind${x.industry ? "" : " is-empty"}`} title={x.industry || "暂无行业"}>{x.industry || "—"}</span>
                    <b className={cls(x.change)}>{pct(x.change)}</b>
                  </div>
                ))}
              </div>
            </div>
          </section>
          <section>
            <div className="section-title">今日最弱</div>
            <div className="section-card">
              <div className="leader-col">
                {data.leaders.today.down.map((x) => (
                  <div className="leader-r" key={x.instrument_id}>
                    <button className="stock-link leader-name" title={x.name} onClick={() => setStockDataCode(x.code ?? null)}>{x.name}</button>
                    <span className={`leader-ind${x.industry ? "" : " is-empty"}`} title={x.industry || "暂无行业"}>{x.industry || "—"}</span>
                    <b className={cls(x.change)}>{pct(x.change)}</b>
                  </div>
                ))}
              </div>
            </div>
          </section>
        </div>

        {/* 行 2：5 日 / 20 日最强 + 最弱（紧凑 4 列） */}
        <div className="chart-grid-quad-mini section">
          {([
            { label: "5日最强", list: data.leaders["5d"].up, field: "change_5d" as const },
            { label: "5日最弱", list: data.leaders["5d"].down, field: "change_5d" as const },
            { label: "20日最强", list: data.leaders["20d"].up, field: "change_20d" as const },
            { label: "20日最弱", list: data.leaders["20d"].down, field: "change_20d" as const },
          ] as const).map((g) => (
            <section key={g.label}>
              <div className="section-title">{g.label}</div>
              <div className="section-card">
                <div className="leader-col">
                  {g.list.map((x) => (
                    <div className="leader-r" key={x.instrument_id}>
                      <button className="stock-link leader-name" title={x.name} onClick={() => setStockDataCode(x.code ?? null)}>{x.name}</button>
                      <span className={`leader-ind${x.industry ? "" : " is-empty"}`} title={x.industry || "暂无行业"}>{x.industry || "—"}</span>
                      <b className={cls(x[g.field])}>{pct(x[g.field])}</b>
                    </div>
                  ))}
                </div>
              </div>
            </section>
          ))}
        </div>

        {/* 股票池明细（focus 模式下只保留与"关注股增减"相关的控件；其他按钮挪到表外） */}
        <section className="section">
          <div className="section-title">
            <span>股票池明细</span>
            <div className="toolbar">
              <input placeholder="搜索名称 / 行业" value={search} onChange={(e) => setSearch(e.target.value)} />
              <select value={stockFilter} onChange={(e) => setStockFilter(e.target.value)} title="按近期关注 / 研究篮子 / 行业分类筛选">
                <option value="">全部股票</option>
                <optgroup label="重点列表">
                  <option value="__focus__">★ 近期关注（{watchCodes.length}）</option>
                </optgroup>
                <optgroup label="研究篮子">
                  {researchBaskets.map((basket) => (
                    <option key={basket.key} value={`basket:${basket.key}`}>{basket.name}（{basket.count}）</option>
                  ))}
                </optgroup>
                <optgroup label="行业分类">
                  {industries.map((x) => <option key={x} value={`industry:${x}`}>{x}</option>)}
                </optgroup>
              </select>
              {stockFilter === "__focus__" ? (
                <>
                  <input
                    className="input"
                    style={{ width: 280 }}
                    value={focusInput}
                    onChange={(e) => setFocusInput(e.target.value.replace(/[^\d,\s]/g, "").slice(0, 80))}
                    onKeyDown={(e) => e.key === "Enter" && addFocus()}
                    placeholder="加自选：可批量，如 600519 000858"
                  />
                  <button className="btn-primary" onClick={addFocus}><Plus className="h-4 w-4" /> 增加</button>
                </>
              ) : (
                <>
                  <button className="btn" onClick={() => setEditOpen(true)}>＋ 编辑池子</button>
                  <AskAiButton context={poolAiContext} label="AI 读自选" suggestions={["哪些估值偏高", "按赛道分组看看", "各自最大的风险点"]} />
                  <button className="btn" onClick={refreshAll}><RefreshCw size={13} /> 刷新</button>
                </>
              )}
            </div>
          </div>
          {poolMsg && <div className="hint" style={{ margin: "4px 2px 8px" }}>{poolMsg}</div>}
          <div className="section-card">
            <div className="table-wrap">
              <table id="stock-table">
                <thead>
                  <tr>
                    {th("name", "名称", stockSort, true)}
                    {th("industry", "行业", stockSort, true)}
                    {th("price", "现价", stockSort)}
                    {th("change", "今日", stockSort)}
                    {th("change_5d", "5日", stockSort)}
                    {th("change_20d", "20日", stockSort)}
                    {th("ytd", "YTD", stockSort)}
                    {th("amount_yi", "成交额(亿)", stockSort)}
                    {th("turnover", "换手率", stockSort)}
                    {th("mcap_yi", "市值(亿)", stockSort)}
                    {th("pe_ttm", "PE TTM", stockSort)}
                    {th("pb", "PB", stockSort)}
                    <th></th>
                  </tr>
                </thead>
                <tbody id="stock-body">
                  {stockRows.map((x) => (
                    <tr key={x.instrument_id}>
                      <td className="left">
                        <button className="stock-link" onClick={() => setStockDataCode(x.code ?? null)}>{x.name}</button>
                        {x.code ? <><br /><span className="muted" style={{ fontSize: 11 }}>{x.code}{x.exchange ? "." + x.exchange : ""}</span></> : null}
                      </td>
                      <td className="left">{x.industry || "--"}</td>
                      <td>{fmt(x.price, 2)}</td>
                      <td className={cls(x.change)}>{pct(x.change)}</td>
                      <td className={cls(x.change_5d)}>{pct(x.change_5d)}</td>
                      <td className={cls(x.change_20d)}>{pct(x.change_20d)}</td>
                      <td className={cls(x.ytd)}>{pct(x.ytd)}</td>
                      <td>{fmt(x.amount_yi, 1)}</td>
                      <td>{pct(x.turnover)}</td>
                      <td>{fmt(x.mcap_yi, 1)}</td>
                      <td>{fmt(x.pe_ttm, 1)}</td>
                      <td>{fmt(x.pb, 2)}</td>
                      <td><button
                        className="remove"
                        title={stockFilter === "__focus__" ? "从近期关注移除（会同步 pool.json）" : "从股票池移除（会同步 GitHub）"}
                        onClick={() => handleRemoveRow(x)}
                      >×</button></td>
                    </tr>
                  ))}
                  {stockRows.length === 0 && (
                  <tr><td colSpan={13} className="empty">
                    {stockFilter === "__focus__"
                      ? "还没有关注股票——在上方「加自选」框粘贴代码批量加入，或先去「全部行业」把想关注的加进核心股票池。"
                      : "暂无数据"}
                  </td></tr>
                )}
                </tbody>
              </table>
            </div>
          </div>
        </section>

        {/* 股票池热力图（页底） */}
        <section className="section">
          <div className="section-title">
            <span>股票池热力图</span>
            <select className="input" value={heatPeriod} onChange={(e) => setHeatPeriod(e.target.value as PeriodKey)} title="切换热力图着色周期">
              {HEAT_PERIODS.map((p) => (
                <option key={p.key} value={p.key}>{p.label}</option>
              ))}
            </select>
          </div>
          <div className="section-card">
            <div className="heatmap">
              {heatTiles.tiles.map((x, i) => {
                // 行业组起点：与上一个 tile 行业不同 → 加 grp-start，视觉上画出分组边界
                const prev = heatTiles.tiles[i - 1];
                const grpStart = !prev || prev.industry !== x.industry;
                return (
                  <div
                    key={x.instrument_id}
                    className={`tile ${x.size}${grpStart ? " grp-start" : ""}`}
                    style={{ background: heatColor(x[heatPeriod] ?? null, heatTiles.maxAbs) }}
                    title={`${x.name} · ${x.industry} · ${HEAT_PERIOD_LABEL[heatPeriod]} ${pct(x[heatPeriod] ?? null)}`}
                  >
                    <div className="tile-name">{x.name}</div>
                    <div className="tile-val">{pct(x[heatPeriod] ?? null)}</div>
                    <div className="tile-ind">{x.industry || ""}</div>
                  </div>
                );
              })}
              {heatTiles.tiles.length === 0 && <div className="empty">暂无数据</div>}
            </div>
            {/* 色阶图例：绿跌 → 红涨（A股惯例），刻度随所选周期自动缩放 */}
            <div className="heat-legend">
              <div className="heat-legend-gradient" />
              <div className="heat-legend-scale">
                <span>-{pct(heatTiles.maxAbs)}</span>
                <span>0%</span>
                <span>+{pct(heatTiles.maxAbs)}</span>
              </div>
            </div>
          </div>
        </section>

        {/* 编辑池子弹窗（批量添加 / 同步 GitHub） */}
        {editOpen && (
          <div className="modal-mask show" onClick={() => setEditOpen(false)}>
            <div className="modal" onClick={(e) => e.stopPropagation()}>
              <h3>编辑池子</h3>
              <div className="form-row">
                <label>粘贴证券代码</label>
                <input className="input" value={batchInput} onChange={(e) => setBatchInput(e.target.value)} placeholder="600519, 000858, 00700 …" />
              </div>
              <div className="toolbar" style={{ justifyContent: "flex-end", marginTop: 16 }}>
                <button className="btn" onClick={syncNow} disabled={syncing}><CloudUpload size={13} /> {syncing ? "同步中…" : "同步 GitHub"}</button>
                <button className="btn primary" onClick={addBatch}>批量添加</button>
                <button className="btn" onClick={() => setEditOpen(false)}>关闭</button>
              </div>
            </div>
          </div>
        )}

        {/* 个股分析弹窗（内嵌 /stock-data 子页，自动搜索该股票） */}
        {stockDataCode && (
          <div className="drawer-mask show" onClick={() => setStockDataCode(null)}>
            <aside className="drawer sd-drawer" onClick={(e) => e.stopPropagation()}>
              <div className="drawer-head">
                <div className="drawer-head-row">
                  <div className="drawer-title">个股分析 · {stockDataCode}</div>
                  <button className="drawer-close" onClick={() => setStockDataCode(null)}>×</button>
                </div>
              </div>
              <iframe
                src={`/stock-data-embed?code=${stockDataCode}`}
                title={`个股分析 ${stockDataCode}`}
                style={{ width: "100%", flex: 1, border: 0, display: "block", background: "var(--bg)" }}
              />
            </aside>
          </div>
        )}
      </div>
    </div>
  );
}

/* 强弱矩阵：4 象限（IMPROVING/LEADING/LAGGING/WEAKENING）散点
   X = 20日涨幅，Y = 今日涨幅
   颜色规则（按截图色板）：
     LEADING     (今日>0 且 20日>0) → 绿色 (一致持多)
     LAGGING     (今日<0 且 20日<0) → 红色 (一致持空)
     IMPROVING   (今日>0 且 20日<0) → 灰色 (不一致)
     WEAKENING   (今日<0 且 20日>0) → 灰色 (不一致)
   金边 = 正在右上方移动 (change > change_5d > change_20d)             */
const MATRIX_GREEN = "#22c55e";
const MATRIX_RED = "#ef4444";
const MATRIX_GRAY = "#94a3b8";
const MATRIX_RIM = "#facc15";

function MatrixSvg({ rows }: { rows: Stock[] }) {
  // viewBox 宽高比与卡片容器一致（≈1500:600 = 2.5:1），meet 时完全填满不留白
  const W = 1500, H = 600, pad = 70;
  const xs = rows.map((x) => x.change_20d ?? 0), ys = rows.map((x) => x.change ?? 0);
  const mx = Math.max(0.01, ...xs.map(Math.abs));
  const my = Math.max(0.01, ...ys.map(Math.abs));
  const X = (v: number) => pad + (v + mx) / (2 * mx) * (W - 2 * pad);
  const Y = (v: number) => H - pad - (v + my) / (2 * my) * (H - 2 * pad);
  const x0 = X(0), y0 = Y(0);
  // 信号强度阈值（小数单位）：hypot(今日涨幅, 20日涨幅) ≥ 0.10（即 10%）的股票才常显名称；其余只显示点、hover 才出名称
  const LABEL_STRENGTH = 0.10;
  const [hoverId, setHoverId] = useState<string | null>(null);

  const quad = (x: Stock) => {
    const td = x.change ?? 0, tw = x.change_20d ?? 0;
    if (td >= 0 && tw >= 0) return "L";
    if (td < 0 && tw < 0) return "G";   // LAGGING
    return "M";                          // MIXED (IMPROVING / WEAKENING)
  };
  const rising = (x: Stock) => {
    const td = x.change, c5 = x.change_5d, c20 = x.change_20d;
    return [td, c5, c20].every((v) => typeof v === "number") &&
      (td as number) > (c5 as number) && (c5 as number) > (c20 as number);
  };
  const colorOf = (q: string) => (q === "L" ? MATRIX_GREEN : q === "G" ? MATRIX_RED : MATRIX_GRAY);

  // 预计算点位：半径 = 市值打底 + 强度加成；透明度随强度（弱信号淡、强信号实）
  const pts = rows.map((x) => {
    const td = x.change ?? 0, tw = x.change_20d ?? 0;
    const strength = Math.hypot(td, tw);
    const px = X(tw), py = Y(td);
    const baseR = Math.min(6, 1.8 + Math.log10((x.amount_yi || 1) + 1));
    const r = Math.min(7.5, baseR * (0.9 + Math.min(0.45, strength * 4)));
    const q = quad(x);
    return { x, px, py, r, strength, q, isUp: rising(x), color: colorOf(q) };
  });

  // 4 象限底色：铺满整个 viewBox（不留 pad），由 0 轴分割。pad 仅供文字/坐标轴标签留位置
  const rects = [
    { cls: "q-tl", x: 0, y: 0, w: x0, h: y0 },                  // IMPROVING（今日>0 且 20日<0）
    { cls: "q-tr", x: x0, y: 0, w: W - x0, h: y0 },            // LEADING  （今日>0 且 20日>0）
    { cls: "q-bl", x: 0, y: y0, w: x0, h: H - y0 },            // LAGGING  （今日<0 且 20日<0）
    { cls: "q-br", x: x0, y: y0, w: W - x0, h: H - y0 },      // WEAKENING（今日<0 且 20日>0）
  ];
  const labelPad = 18;

  return (
    <svg
      viewBox={`0 0 ${W} ${H}`}
      preserveAspectRatio="xMidYMid meet"
      className="matrix-svg"
      onMouseLeave={() => setHoverId(null)}
    >
      {/* 4 象限底色铺满 */}
      {rects.map((r, i) => (
        <rect key={i} x={r.x} y={r.y} width={r.w} height={r.h} className={`matrix-quad ${r.cls}`} />
      ))}
      {/* 0 轴虚线（贯通全高/全宽） */}
      <line x1={x0} y1={0} x2={x0} y2={H} stroke="hsl(var(--chart-axis))" strokeDasharray="3 3" />
      <line x1={0} y1={y0} x2={W} y2={y0} stroke="hsl(var(--chart-axis))" strokeDasharray="3 3" />
      {/* 象限名（4 角紧贴边缘）+ 轴标（顶/底中央避免与象限名重叠） */}
      <text className="quad-label" x={labelPad} y={labelPad + 14}>IMPROVING</text>
      <text className="quad-label" x={W - labelPad} y={labelPad + 14} textAnchor="end">LEADING</text>
      <text className="quad-label" x={labelPad} y={H - labelPad + 4}>LAGGING</text>
      <text className="quad-label" x={W - labelPad} y={H - labelPad + 4} textAnchor="end">WEAKENING</text>
      <text className="axis-label" x={W / 2} y={labelPad - 4} textAnchor="middle">今日涨幅 ↑</text>
      <text className="axis-label" x={W / 2} y={H - labelPad + 12} textAnchor="middle">20日涨幅 →</text>
      {/* 散点：全部只画点；强信号常显名称；任何点 hover 显示名称浮层 + 点击进个股分析 */}
      {pts.map((p) => {
        const nearRight = p.px > W - pad - 64;   // 贴右缘 → 名称放左侧
        const nearTop = p.py < pad + 16;          // 贴顶缘 → 名称放下方，避免顶到边
        const showLabel = p.strength >= LABEL_STRENGTH;
        const isHover = hoverId === p.x.instrument_id;
        const opacity = isHover ? 1 : Math.max(0.18, Math.min(1, 0.2 + p.strength * 8));
        // hover 浮层（跟随点原位，防溢出）：宽 182 / 高 32，两行（名称 + 涨跌）
        const panelW = 182, panelH = 32;
        const panelX = Math.min(W - pad - panelW - 4, Math.max(pad + 4, p.px - panelW / 2));
        const panelY = nearTop ? p.py + p.r + 8 : p.py - p.r - panelH - 8;
        return (
          <g
            key={p.x.instrument_id}
            style={{ cursor: "pointer" }}
            onMouseEnter={() => setHoverId(p.x.instrument_id)}
            onMouseLeave={() => setHoverId((h) => (h === p.x.instrument_id ? null : h))}
            onClick={() => {
              const c = (p.x.code || p.x.instrument_id || "").toUpperCase();
              window.open(`/stock-data?code=${encodeURIComponent(c)}`, "_blank");
            }}
          >
            {p.isUp && (
              <circle
                cx={p.px} cy={p.py}
                r={p.r + 2} fill="none" stroke={MATRIX_RIM} strokeWidth={1.6} opacity={0.95}
              />
            )}
            <circle
              className="matrix-point"
              cx={p.px} cy={p.py}
              r={p.r} fill={p.color} opacity={opacity}
            />
            {/* 常显名称：仅信号强度达标（外围/强信号） */}
            {showLabel && !isHover && (
              <text
                className="matrix-label"
                x={nearRight ? p.px - 6 : p.px + 6}
                y={nearTop ? p.py + p.r + 11 : p.py - p.r - 5}
                textAnchor={nearRight ? "end" : "start"}
              >{p.x.name}</text>
            )}
            {/* hover 浮层：任何点悬停都显示名称 + 涨跌明细 */}
            {isHover && (
              <g>
                <rect
                  x={panelX} y={panelY} width={panelW} height={panelH} rx={5}
                  fill="var(--card)" stroke="var(--line)" strokeWidth={1}
                  style={{ filter: "drop-shadow(0 2px 6px rgba(0,0,0,0.18))" }}
                />
                <text x={panelX + 9} y={panelY + 14} fontSize={12} fontWeight={600} fill="var(--text)">{p.x.name}</text>
                <text x={panelX + 9} y={panelY + 26} fontSize={10} fill="var(--muted)">
                  今 {pct(p.x.change)} · 5日 {pct(p.x.change_5d)} · 20日 {pct(p.x.change_20d)}{p.isUp ? " · 动量↑" : ""}
                </text>
              </g>
            )}
          </g>
        );
      })}
    </svg>
  );
}
