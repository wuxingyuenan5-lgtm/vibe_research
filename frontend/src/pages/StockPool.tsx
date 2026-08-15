import { useEffect, useMemo, useRef, useState } from "react";
import "./stock-pool.css";

/* ============================================================
   自选股明细 · 核心股票池 Dashboard V0.1
   高保真复刻《A股看板_V0.1_UI统一版.html》（母版 payload + JS 逻辑）
   数据：/api/stock-pool（Astock_study feat/dashboard-v0.1 数据 → payload）
   ============================================================ */

interface Stock {
  instrument_id: string; code: string | null; exchange: string | null; name: string;
  industry: string; price: number | null; change: number | null; change_5d: number | null;
  change_20d: number | null; ytd: number | null; amount_yi: number | null; mcap_yi: number | null;
  turnover: number | null; pe_ttm: number | null; pb: number | null; data_status: string;
}
interface IndexRow {
  code: string; name: string; price: number | null; change: number | null; change_5d: number | null;
  change_20d: number | null; ytd: number | null; amount_yi: number | null; mcap_yi: number | null;
}
interface Payload {
  meta: { report_date: string };
  summary: {
    tracked_count: number;
    breadth: { count: number; up: number; down: number; flat: number; median: number | null };
    avg_change: number | null; total_amount_yi: number;
  };
  stocks: Stock[];
  indices: IndexRow[];
  heatmap: { instrument_id: string; name: string; industry: string; change: number | null; weight: number }[];
  leaders: { up: Stock[]; down: Stock[] };
  default_index_selfselect: string[];
}

const UP = "#ef4444", DOWN = "#10b981";
const SELF_KEY = "astock.dashboard.v01.indexSelfSelect";
const fmt = (v: number | null | undefined, d = 2) => (v == null || Number.isNaN(Number(v)) ? "--" : Number(v).toFixed(d));
const pct = (v: number | null | undefined) => (v == null ? "--" : `${Number(v) >= 0 ? "+" : ""}${(Number(v) * 100).toFixed(2)}%`);
const cls = (v: number | null | undefined) => (v == null ? "neutral" : v > 0 ? "up" : v < 0 ? "down" : "neutral");

function heatColor(v: number | null): string {
  if (v == null) return "#94a3b8";
  const x = Math.min(Math.abs(v) / 0.08, 1);
  if (v >= 0) {
    const r = 239, g = Math.round(180 - 112 * x), b = Math.round(180 - 112 * x);
    return `rgb(${r},${g},${b})`;
  }
  const r = Math.round(110 - 94 * x), g = Math.round(190 + 5 * x), b = Math.round(150 - 21 * x);
  return `rgb(${r},${g},${b})`;
}

function sortValue(v: unknown): number | string | null {
  if (v == null || v === "") return null;
  if (typeof v === "number") return v;
  const n = Number(v);
  return Number.isFinite(n) && String(v).trim() !== "" ? n : String(v).toLocaleLowerCase();
}
function sortRows<T extends Record<string, unknown>>(rows: T[], key: string | null, dir: "asc" | "desc" | null): T[] {
  if (!key || !dir) return [...rows];
  return rows
    .map((r, i) => ({ r, i }))
    .sort((a, b) => {
      const av = sortValue(a.r[key]), bv = sortValue(b.r[key]);
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
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  useEffect(() => {
    fetch("/api/stock-pool")
      .then((r) => { if (!r.ok) throw new Error(`HTTP ${r.status}`); return r.json(); })
      .then((b) => setData(b.data))
      .catch((e) => setError(e instanceof Error ? e.message : "加载失败"))
      .finally(() => setLoading(false));
  }, []);
  return { data, error, loading };
}

function loadSelf(data: Payload): { code: string; name: string | null }[] {
  try {
    const x = JSON.parse(localStorage.getItem(SELF_KEY) || "null");
    if (Array.isArray(x)) return x;
  } catch { /* ignore */ }
  return (data.default_index_selfselect || []).map((code) => ({ code, name: null }));
}

export function StockPool() {
  const { data, error, loading } = useStockPool();
  const [period, setPeriod] = useState<"change" | "change_5d" | "change_20d" | "ytd">("change");
  const [selfSel, setSelfSel] = useState<{ code: string; name: string | null }[]>([]);
  const [selfSort, setSelfSort] = useState<{ key: string | null; dir: "asc" | "desc" | null }>({ key: null, dir: null });
  const [stockSort, setStockSort] = useState<{ key: string | null; dir: "asc" | "desc" | null }>({ key: null, dir: null });
  const [search, setSearch] = useState("");
  const [typeFilter, setTypeFilter] = useState("");
  const [industry, setIndustry] = useState("");
  const [modalOpen, setModalOpen] = useState(false);
  const [selfCode, setSelfCode] = useState("");
  const [selfName, setSelfName] = useState("");
  const [drawerStock, setDrawerStock] = useState<Stock | null>(null);
  const [drawerTab, setDrawerTab] = useState("overview");

  useEffect(() => {
    if (data) setSelfSel(loadSelf(data));
  }, [data]);

  useEffect(() => {
    try { localStorage.setItem(SELF_KEY, JSON.stringify(selfSel)); } catch { /* ignore */ }
  }, [selfSel]);

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

  const heatTiles = useMemo(() => {
    if (!data) return [];
    const rows = [...data.heatmap].sort((a, b) => (b.weight || 0) - (a.weight || 0)).slice(0, 120);
    const weights = rows.map((x) => x.weight || 1).sort((a, b) => a - b);
    const q = (p: number) => weights[Math.floor((weights.length - 1) * p)] || 1;
    const q60 = q(0.6), q82 = q(0.82), q94 = q(0.94);
    return rows.map((x) => ({
      ...x,
      size: x.weight >= q94 ? "s4" : x.weight >= q82 ? "s3" : x.weight >= q60 ? "s2" : "s1",
    }));
  }, [data]);

  const ranking = useMemo(() => {
    if (!data) return [];
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

  const stockType = (x: Stock) => "个股";

  const filteredStocks = useMemo(() => {
    if (!data) return [];
    const q = search.trim().toLowerCase();
    return data.stocks.filter(
      (x) =>
        (!q || (x.name || "").toLowerCase().includes(q) || (x.industry || "").toLowerCase().includes(q) || (x.code || "").toLowerCase().includes(q)) &&
        (!industry || x.industry === industry) &&
        (!typeFilter || stockType(x) === typeFilter),
    );
  }, [data, search, industry, typeFilter]);

  const stockRows = useMemo(() => sortRows(filteredStocks, stockSort.key, stockSort.dir), [filteredStocks, stockSort]);
  const selfRows = useMemo(() => {
    if (!data) return [];
    const rows = selfSel.map((item, original_index) => {
      const d = data.indices.find((x) => String(x.code) === String(item.code)) || {};
      return {
        code: item.code, name: (d as IndexRow).name || item.name || "未命名",
        price: (d as IndexRow).price ?? null, change: (d as IndexRow).change ?? null,
        change_5d: (d as IndexRow).change_5d ?? null, change_20d: (d as IndexRow).change_20d ?? null,
        ytd: (d as IndexRow).ytd ?? null, original_index,
      };
    });
    return sortRows(rows, selfSort.key, selfSort.dir);
  }, [data, selfSel, selfSort]);

  const cycleSort = (which: "self" | "stocks", key: string) => {
    const setter = which === "self" ? setSelfSort : setStockSort;
    setter((s) => {
      if (s.key !== key) return { key, dir: "desc" as const };
      if (s.dir === "desc") return { key, dir: "asc" as const };
      return { key: null, dir: null };
    });
  };

  const addSelf = () => {
    const code = selfCode.trim(), name = selfName.trim();
    if (!code) return;
    const d = data?.indices.find((x) => String(x.code) === code);
    const finalName = d?.name || name;
    if (!finalName) return;
    setSelfSel((prev) => (prev.some((x) => String(x.code) === code) ? prev : [...prev, { code, name: finalName }]));
    setModalOpen(false);
    setSelfCode(""); setSelfName("");
  };
  const resetSelf = () => {
    if (!data) return;
    setSelfSel((data.default_index_selfselect || []).map((code) => ({ code, name: data.indices.find((x) => String(x.code) === code)?.name || null })));
  };
  const removeSelf = (code: string) => setSelfSel((prev) => prev.filter((x) => String(x.code) !== String(code)));

  if (loading) return <div className="sp-root"><div className="page"><div className="empty">正在加载股票池数据…</div></div></div>;
  if (error || !data) return <div className="sp-root"><div className="page"><div className="empty" style={{ color: "#dc2626" }}>加载失败：{error ?? "无数据"}</div></div></div>;

  const b = data.summary.breadth;
  const binTotal = breadth.reduce((a, x) => a + x, 0) || 1;
  const sortInd = (key: string, s: { key: string | null; dir: "asc" | "desc" | null }) =>
    s.key === key ? (s.dir === "desc" ? "↓" : "↑") : "↕";
  const th = (key: string, label: string, which: "self" | "stocks", s: { key: string | null; dir: "asc" | "desc" | null }, left = false) => (
    <th className={`sortable${left ? " left" : ""}`} data-sort-key={key} onClick={() => cycleSort(which, key)}>
      {label}<span className="sort-ind">{sortInd(key, s)}</span>
    </th>
  );

  return (
    <div className="sp-root">
      <div className="page">
        {/* Hero */}
        <header className="hero">
          <h1>A股看板｜核心股票池</h1>
          <div className="meta">报告日期 {data.meta.report_date}</div>
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

        {/* 热力图 + 行业/指数强弱 */}
        <div className="chart-grid-two section">
          <section>
            <div className="section-title">核心股票池热力图</div>
            <div className="section-card">
              <div className="heatmap">
                {heatTiles.map((x) => (
                  <div key={x.instrument_id} className={`tile ${x.size}`} style={{ background: heatColor(x.change) }} title={`${x.name} · ${pct(x.change)}`}>
                    <div className="tile-name">{x.name}</div>
                    <div className="tile-val">{pct(x.change)}</div>
                    <div className="tile-ind">{x.industry || ""}</div>
                  </div>
                ))}
                {heatTiles.length === 0 && <div className="empty">暂无数据</div>}
              </div>
            </div>
          </section>
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
        </div>

        {/* 强弱矩阵 + 最强 + 最弱 */}
        <div className="chart-grid-three section">
          <section>
            <div className="section-title">强弱矩阵</div>
            <div className="section-card">
              <div className="matrix-wrap">
                {matrix.length === 0 ? (
                  <div className="empty">暂无数据</div>
                ) : (
                  <MatrixSvg rows={matrix} />
                )}
              </div>
            </div>
          </section>
          <section>
            <div className="section-title">今日最强</div>
            <div className="section-card">
              <div className="leader-col">
                {data.leaders.up.map((x) => (
                  <div className="leader-r" key={x.instrument_id}>
                    <span>{x.name}</span>
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
                {data.leaders.down.map((x) => (
                  <div className="leader-r" key={x.instrument_id}>
                    <span>{x.name}</span>
                    <b className={cls(x.change)}>{pct(x.change)}</b>
                  </div>
                ))}
              </div>
            </div>
          </section>
        </div>

        {/* 自选行业 / 指数 */}
        <section className="section">
          <div className="section-title">
            <span>自选行业 / 指数</span>
            <div className="toolbar">
              <button className="btn primary" onClick={() => setModalOpen(true)}>＋ 新增</button>
              <button className="btn" onClick={resetSelf}>恢复默认</button>
            </div>
          </div>
          <div className="section-card">
            <div className="table-wrap">
              <table id="self-table">
                <thead>
                  <tr>
                    {th("code", "代码", "self", selfSort, true)}
                    {th("name", "名称", "self", selfSort, true)}
                    {th("price", "最新", "self", selfSort)}
                    {th("change", "今日", "self", selfSort)}
                    {th("change_5d", "5日", "self", selfSort)}
                    {th("change_20d", "20日", "self", selfSort)}
                    {th("ytd", "YTD", "self", selfSort)}
                    <th></th>
                  </tr>
                </thead>
                <tbody id="selfselect-body">
                  {selfRows.map((d) => (
                    <tr key={d.code}>
                      <td className="left"><b>{d.code || "--"}</b></td>
                      <td className="left">{d.name}</td>
                      <td>{fmt(d.price, 2)}</td>
                      <td className={cls(d.change)}>{pct(d.change)}</td>
                      <td className={cls(d.change_5d)}>{pct(d.change_5d)}</td>
                      <td className={cls(d.change_20d)}>{pct(d.change_20d)}</td>
                      <td className={cls(d.ytd)}>{pct(d.ytd)}</td>
                      <td><button className="remove" onClick={() => removeSelf(d.code)}>×</button></td>
                    </tr>
                  ))}
                  {selfRows.length === 0 && <tr><td colSpan={8} className="empty">暂无自选</td></tr>}
                </tbody>
              </table>
            </div>
          </div>
        </section>

        {/* 核心股票池明细 */}
        <section className="section">
          <div className="section-title">
            <span>核心股票池明细</span>
            <div className="toolbar">
              <input placeholder="搜索名称 / 行业" value={search} onChange={(e) => setSearch(e.target.value)} />
              <select value={typeFilter} onChange={(e) => setTypeFilter(e.target.value)}>
                <option value="">全部类型</option>
                <option value="个股">个股</option>
                <option value="行业">行业</option>
                <option value="指数">指数</option>
                <option value="ETF">ETF</option>
              </select>
              <select value={industry} onChange={(e) => setIndustry(e.target.value)}>
                <option value="">全部行业</option>
                {industries.map((x) => <option key={x}>{x}</option>)}
              </select>
            </div>
          </div>
          <div className="section-card">
            <div className="table-wrap">
              <table id="stock-table">
                <thead>
                  <tr>
                    {th("name", "名称", "stocks", stockSort, true)}
                    {th("asset_type", "类型", "stocks", stockSort, true)}
                    {th("industry", "行业", "stocks", stockSort, true)}
                    {th("price", "现价", "stocks", stockSort)}
                    {th("change", "今日", "stocks", stockSort)}
                    {th("change_5d", "5日", "stocks", stockSort)}
                    {th("change_20d", "20日", "stocks", stockSort)}
                    {th("ytd", "YTD", "stocks", stockSort)}
                    {th("amount_yi", "成交额(亿)", "stocks", stockSort)}
                    {th("turnover", "换手率", "stocks", stockSort)}
                    {th("mcap_yi", "市值(亿)", "stocks", stockSort)}
                    {th("pe_ttm", "PE TTM", "stocks", stockSort)}
                    {th("pb", "PB", "stocks", stockSort)}
                  </tr>
                </thead>
                <tbody id="stock-body">
                  {stockRows.map((x) => (
                    <tr key={x.instrument_id}>
                      <td className="left">
                        <button className="stock-link" onClick={() => { setDrawerStock(x); setDrawerTab("overview"); }}>{x.name}</button>
                        {x.code ? <><br /><span className="muted" style={{ fontSize: 11 }}>{x.code}{x.exchange ? "." + x.exchange : ""}</span></> : null}
                      </td>
                      <td className="left"><span className="type-pill">{stockType(x)}</span></td>
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
                    </tr>
                  ))}
                  {stockRows.length === 0 && <tr><td colSpan={13} className="empty">暂无数据</td></tr>}
                </tbody>
              </table>
            </div>
          </div>
        </section>

        {/* 新增自选 modal */}
        {modalOpen && (
          <div className="modal-mask show" onClick={() => setModalOpen(false)}>
            <div className="modal" onClick={(e) => e.stopPropagation()}>
              <h3>新增自选行业 / 指数</h3>
              <div className="form-row">
                <label>代码</label>
                <input className="input" value={selfCode} onChange={(e) => setSelfCode(e.target.value)} />
              </div>
              <div className="form-row">
                <label>名称</label>
                <input className="input" value={selfName} onChange={(e) => setSelfName(e.target.value)} />
              </div>
              <div className="toolbar" style={{ justifyContent: "flex-end", marginTop: 16 }}>
                <button className="btn" onClick={() => setModalOpen(false)}>取消</button>
                <button className="btn primary" onClick={addSelf}>保存</button>
              </div>
            </div>
          </div>
        )}

        {/* 个股详情 Drawer */}
        {drawerStock && (
          <div className="drawer-mask show" onClick={() => setDrawerStock(null)}>
            <aside className="drawer" onClick={(e) => e.stopPropagation()}>
              <div className="drawer-head">
                <div className="drawer-head-row">
                  <div>
                    <div className="drawer-title">{drawerStock.name}</div>
                    <div className="drawer-code">
                      {drawerStock.code ? `${drawerStock.code}${drawerStock.exchange ? "." + drawerStock.exchange : ""}` : stockType(drawerStock)}
                    </div>
                  </div>
                  <button className="drawer-close" onClick={() => setDrawerStock(null)}>×</button>
                </div>
              </div>
              <div className="drawer-tabs">
                {["overview", "financials", "announcements", "news", "sentiment"].map((t) => (
                  <button key={t} className={`drawer-tab${drawerTab === t ? " active" : ""}`} data-tab={t} onClick={() => setDrawerTab(t)}>
                    {{ overview: "概览", financials: "财报", announcements: "公告", news: "新闻", sentiment: "舆情" }[t]}
                  </button>
                ))}
              </div>
              <div className="drawer-body">
                {drawerTab === "overview" ? (
                  <div id="tab-overview" className="tab-panel active">
                    <div className="detail-grid">
                      {[
                        ["现价", fmt(drawerStock.price, 2), null],
                        ["今日", pct(drawerStock.change), cls(drawerStock.change)],
                        ["5日", pct(drawerStock.change_5d), cls(drawerStock.change_5d)],
                        ["20日", pct(drawerStock.change_20d), cls(drawerStock.change_20d)],
                        ["YTD", pct(drawerStock.ytd), cls(drawerStock.ytd)],
                        ["成交额", `${fmt(drawerStock.amount_yi, 1)} 亿`, null],
                        ["换手率", pct(drawerStock.turnover), null],
                        ["总市值", `${fmt(drawerStock.mcap_yi, 1)} 亿`, null],
                        ["PE TTM", fmt(drawerStock.pe_ttm, 1), null],
                        ["PB", fmt(drawerStock.pb, 2), null],
                        ["类型", stockType(drawerStock), null],
                        ["行业", drawerStock.industry || "--", null],
                      ].map(([label, value, color], i) => (
                        <div className="detail-card" key={i}>
                          <div className="detail-label">{label}</div>
                          <div className={`detail-value ${color || ""}`}>{value}</div>
                        </div>
                      ))}
                    </div>
                  </div>
                ) : (
                  <div className="tab-panel active"><div className="empty">暂无数据</div></div>
                )}
              </div>
            </aside>
          </div>
        )}
      </div>
    </div>
  );
}

/* 强弱矩阵（SVG 散点，复刻母版 renderMatrix） */
function MatrixSvg({ rows }: { rows: Stock[] }) {
  const W = 700, H = 320, pad = 30;
  const xs = rows.map((x) => x.change_20d ?? 0), ys = rows.map((x) => x.change ?? 0);
  const mx = Math.max(0.01, ...xs.map(Math.abs));
  const my = Math.max(0.01, ...ys.map(Math.abs));
  const X = (v: number) => pad + (v + mx) / (2 * mx) * (W - 2 * pad);
  const Y = (v: number) => H - pad - (v + my) / (2 * my) * (H - 2 * pad);
  return (
    <svg viewBox={`0 0 ${W} ${H}`} preserveAspectRatio="none">
      <line x1={X(0)} y1={pad} x2={X(0)} y2={H - pad} stroke="#cbd5e1" />
      <line x1={pad} y1={Y(0)} x2={W - pad} y2={Y(0)} stroke="#cbd5e1" />
      <text className="axis-label" x={W - 100} y={H - 8}>20日涨幅 →</text>
      <text className="axis-label" x={6} y={18}>今日涨幅 ↑</text>
      {rows.map((x) => (
        <circle key={x.instrument_id} className="matrix-point" cx={X(x.change_20d ?? 0)} cy={Y(x.change ?? 0)}
          r={Math.min(7, 2 + Math.log10((x.amount_yi || 1) + 1))} fill={(x.change ?? 0) >= 0 ? UP : DOWN}>
          <title>{x.name} 今日 {pct(x.change)} / 20日 {pct(x.change_20d)}</title>
        </circle>
      ))}
    </svg>
  );
}
