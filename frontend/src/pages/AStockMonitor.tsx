import { useEffect, useMemo, useRef, useState } from "react";
import "./astock-monitor.css";

/* ============================================================
   a股监控板 · 每日市场监控
   UI 逐像素对齐上游 HTML v1.1（preview (2).html）：
   类名体系 / 字体 / 颜色 / 布局 / 手绘 SVG 图 + 图例 + 双滑块
   数据合同：report_data.json（Canonical → report_data）
   ============================================================ */

interface MarketRow {
  date: string; advance: number | null; decline: number | null; flat: number | null;
  limit_up: number | null; limit_down: number | null; effective_stocks: number | null;
  total_amount_100m: number | null; hot_count: number | null; market_breadth: number | null;
}
interface IndexRow { date: string; name: string; close: number | null; return: number | null; amount_100m: number | null }
interface SwRow { 日期: string; 行业层级: string; 一级行业: string; 指数代码: string; 指数名称: string; 收盘价: number | null; 成交额: number | null; 日收益率: number | null; "20日年化波动率": number | null }
interface HotRow { rank: number | null; stock_code: string; stock_name: string; close: number | null; return: number | null; amount_100m: number | null; sw_level1: string; sw_level2: string }
interface ReportData {
  meta: { report_date: string; status: string; latest_market_date: string };
  market_history: MarketRow[];
  indices_history: IndexRow[];
  sw_industry_latest: SwRow[];
  hot_stock_matrix: { dates: string[]; rows: { industry: string; counts: number[]; history_total: number }[] };
  hot_stocks_latest: HotRow[];
  sw_crowding_history: { date: string; targets: Record<string, { amount_100m: number | null; amount_share_of_a: number | null; turnover: number | null }> }[];
  innovation_history: { date: string; amount_100m: number | null; amount_share_of_a: number | null; turnover: number | null; return: number | null; volume: number | null }[];
  quality: { status: string; unresolved?: { module: string; level: string; detail: unknown }[]; module_latest_dates?: Record<string, string>; canonical_validation?: { status?: string } };
}

const CROWD_TARGETS = ["通信设备", "计算机设备", "元件", "半导体"] as const;
const INDEX_NAMES = ["上证50", "Choice微盘", "中证全指"] as const;
const UP = "#f2503f", DOWN = "#2fbf71";
const signedPct = (v: number | null | undefined) => (v == null ? "—" : `${v > 0 ? "+" : ""}${(v * 100).toFixed(2)}%`);
const num2 = (v: number | null | undefined) => (v == null ? "—" : v.toLocaleString("zh-CN", { minimumFractionDigits: 2, maximumFractionDigits: 2 }));
const num0 = (v: number | null | undefined) => (v == null ? "—" : v.toLocaleString("zh-CN", { maximumFractionDigits: 0 }));
const upDownCls = (v: number | null | undefined) => (v == null ? "neutral" : v > 0 ? "up" : v < 0 ? "down" : "neutral");

function useReportData() {
  const [data, setData] = useState<ReportData | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  useEffect(() => {
    fetch("/api/market-monitor")
      .then((r) => { if (!r.ok) throw new Error(`HTTP ${r.status}`); return r.json(); })
      .then((b) => setData(b.data))
      .catch((e) => setError(e instanceof Error ? e.message : "加载失败"))
      .finally(() => setLoading(false));
  }, []);
  return { data, error, loading };
}

/* ---------- 手绘 SVG 时间图（复刻上游 drawSvg + mountTimeChart） ---------- */
interface Series {
  name: string; values: (number | null)[]; type: "bar" | "line" | "area";
  axis?: "left" | "right"; color: string; sign?: 1 | -1; unit?: string; percent?: boolean; opacity?: number;
}
interface ChartConfig {
  title: string; dates: string[]; series: Series[]; yLabel: string; rightLabel?: string; chartType?: "market" | "series";
}

function TimeChart({ cfg }: { cfg: ChartConfig }) {
  const svgRef = useRef<SVGSVGElement>(null);
  const tipRef = useRef<HTMLDivElement>(null);
  const [range, setRange] = useState<[number, number]>([0, Math.max(0, cfg.dates.length - 1)]);
  const [hidden, setHidden] = useState<Set<number>>(new Set());
  const W = 1200, H = 360, ml = 72, mr = cfg.rightLabel ? 94 : 40, mt = 22, mb = 48;
  const x0 = ml, x1 = W - mr, y0 = mt, y1 = H - mb;

  useEffect(() => {
    const svg = svgRef.current, tip = tipRef.current;
    if (!svg || !tip) return;
    const [startIndex, endIndex] = range;
    const visibleSeries = cfg.series.map((s, i) => ({ s, i })).filter((x) => !hidden.has(x.i));

    const domain = (axis: "left" | "right") => {
      const v: number[] = [];
      visibleSeries.filter((x) => (x.s.axis || "left") === axis).forEach((x) =>
        (x.s.values || []).slice(startIndex, endIndex + 1).forEach((z) => {
          if (z != null && z !== "") { const n = Number(z) * (x.s.sign || 1); if (Number.isFinite(n)) v.push(n); }
        }));
      if (!v.length) return [-1, 1];
      let lo = Math.min(...v), hi = Math.max(...v);
      if (cfg.chartType === "market" || lo < 0) { lo = Math.min(0, lo); hi = Math.max(0, hi); }
      if (lo === hi) { lo -= 1; hi += 1; }
      const p = (hi - lo) * 0.08;
      return [lo - p, hi + p];
    };
    const dl = domain("left"), dr = domain("right");
    const span = Math.max(1, endIndex - startIndex);
    const X = (i: number) => x0 + (x1 - x0) * (i - startIndex) / span;
    const Y = (v: number, d: number[]) => y1 - (v - d[0]) / (d[1] - d[0]) * (y1 - y0);

    let out = "";
    const rightSeries = visibleSeries.find((x) => (x.s.axis || "left") === "right");
    const rightColor = rightSeries?.s.color || "#6a7585";
    const rightPct = Boolean(rightSeries?.s.percent);
    for (let k = 0; k < 5; k++) {
      const yy = y0 + (y1 - y0) * k / 4;
      const lv = dl[1] - (dl[1] - dl[0]) * k / 4;
      out += `<line x1="${x0}" y1="${yy}" x2="${x1}" y2="${yy}" stroke="hsl(var(--chart-grid))"/>`;
      out += `<text x="${x0 - 8}" y="${yy + 4}" text-anchor="end" class="axis-label">${cfg.yLabel.includes("%") ? (lv * 100).toFixed(1) + "%" : lv.toFixed(0)}</text>`;
      if (cfg.rightLabel) {
        const rv = dr[1] - (dr[1] - dr[0]) * k / 4;
        out += `<text x="${x1 + 10}" y="${yy + 4}" class="axis-label" fill="${rightColor}" font-weight="650">${rightPct ? (rv * 100).toFixed(1) + "%" : rv.toFixed(0)}</text>`;
      }
    }
    const ticks: number[] = [];
    for (let k = 0; k < 8; k++) ticks.push(Math.round(startIndex + (endIndex - startIndex) * k / 7));
    [...new Set(ticks)].forEach((i) => {
      out += `<text x="${X(i)}" y="${H - 15}" text-anchor="${i === startIndex ? "start" : i === endIndex ? "end" : "middle"}" class="axis-label">${(cfg.dates[i] || "").slice(5)}</text>`;
    });
    visibleSeries.forEach(({ s }) => {
      const d = (s.axis || "left") === "right" ? dr : dl;
      const pts: [number, number, number, number][] = [];
      for (let i = startIndex; i <= endIndex; i++) {
        const raw = s.values[i];
        if (raw == null || raw === "") continue;
        const v = Number(raw) * (s.sign || 1);
        const x = X(i), y = Y(v, d);
        pts.push([x, y, i, Number(raw)]);
        if (s.type === "bar") {
          const z = Y(0, d);
          const bw = Math.max(2, Math.min(10, (x1 - x0) / (span + 1) * 0.55));
          out += `<rect x="${x - bw / 2}" y="${Math.min(y, z)}" width="${bw}" height="${Math.max(1, Math.abs(z - y))}" fill="${s.color}" opacity=".25"/>`;
        }
      }
      if ((s.type === "line" || s.type === "area") && pts.length) {
        const path = pts.map((p, j) => (j ? "L" : "M") + p[0] + "," + p[1]).join(" ");
        if (s.type === "area") {
          const base = Y((0 >= d[0] && 0 <= d[1]) ? 0 : d[0], d);
          out += `<path d="${path} L${pts[pts.length - 1][0]},${base} L${pts[0][0]},${base} Z" fill="${s.color}" opacity="${s.opacity || 0.16}"/>`;
        }
        out += `<path d="${path}" fill="none" stroke="${s.color}" stroke-width="2.2"/>`;
      }
    });
    svg.innerHTML = out;

    const move = (e: MouseEvent) => {
      const r = svg.getBoundingClientRect();
      const px = (e.clientX - r.left) / r.width * W;
      let idx = Math.round(startIndex + (px - x0) / (x1 - x0) * (endIndex - startIndex));
      idx = Math.max(startIndex, Math.min(endIndex, idx));
      const valueText = (v: number | null | undefined, s: Series) => {
        if (v == null || v === "") return "—";
        const n = Number(v);
        if (!Number.isFinite(n)) return "—";
        return s.percent ? (n * 100).toFixed(2) + "%" : n.toLocaleString("zh-CN", { maximumFractionDigits: 4 }) + (s.unit ? " " + s.unit : "");
      };
      tip.innerHTML = `<b>${cfg.dates[idx]}</b><br>` +
        visibleSeries.map(({ s }) => `<span style="color:${s.color}">●</span> ${s.name}：${valueText(s.values[idx], s)}`).join("<br>");
      tip.style.display = "block";
      tip.style.left = Math.max(6, Math.min(r.width - 220, e.clientX - r.left + 12)) + "px";
      tip.style.top = "10px";
    };
    svg.onmousemove = move;
    svg.onmouseleave = () => { tip.style.display = "none"; };
    return () => { svg.onmousemove = null; svg.onmouseleave = null; };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [cfg, range, hidden]);

  const toggleHidden = (i: number) => setHidden((prev) => {
    const next = new Set(prev);
    next.has(i) ? next.delete(i) : next.add(i);
    return next;
  });

  return (
    <div className="time-chart">
      <div className="chart-head"><h3>{cfg.title}</h3></div>
      <div className="chart-subtitle">
        <div className="sub-left">
          <div className="chart-legend">
            {cfg.series.map((s, i) => (
              <button key={s.name} type="button" className={`legend-btn${hidden.has(i) ? " off" : ""}`} onClick={() => toggleHidden(i)}>
                <span style={{ background: s.color }} />{s.name}
              </button>
            ))}
          </div>
          <span className="hint">{cfg.yLabel}</span>
        </div>
        {cfg.rightLabel ? <div className={`sub-right ${cfg.rightLabel.includes("换手率") ? "right-orange" : "right-down"}`}>右轴：{cfg.rightLabel}</div> : null}
      </div>
      <div className="chart-stage">
        <svg ref={svgRef} className="chart-svg" viewBox={`0 0 ${W} ${H}`} />
        <div ref={tipRef} className="chart-tooltip" />
      </div>
      <div className="time-range">
        <div className="time-range-track">
          <input
            type="range"
            min={0}
            max={Math.max(0, cfg.dates.length - 1)}
            value={range[0]}
            onChange={(e) => setRange(([a, b]) => [Math.min(Number(e.target.value), b), b])}
          />
          <input
            type="range"
            className="time-range-end"
            min={0}
            max={Math.max(0, cfg.dates.length - 1)}
            value={range[1]}
            onChange={(e) => setRange(([a, b]) => [a, Math.max(Number(e.target.value), a)])}
          />
          <button
            type="button"
            className="time-range-all"
            onClick={() => setRange([0, Math.max(0, cfg.dates.length - 1)])}
            title="全部"
            aria-label="全部"
          >
            ≡
          </button>
        </div>
      </div>
    </div>
  );
}

/* ---------- 页面 ---------- */
export function AStockMonitor() {
  const { data, error, loading } = useReportData();
  const [swQuery, setSwQuery] = useState("");
  const [swLevel, setSwLevel] = useState(""); // 全部层级 / 一级行业 / 二级行业
  const [swSort, setSwSort] = useState<{ key: "成交额" | "日收益率" | "20日年化波动率" | null; state: "original" | "desc" | "asc" }>({ key: null, state: "original" });

  const charts = useMemo(() => {
    if (!data) return [] as ChartConfig[];
    const mh = data.market_history;
    return [
      {
        title: "市场涨跌结构", chartType: "market" as const,
        dates: mh.map((r) => r.date), yLabel: "上涨/下跌家数（家）", rightLabel: "涨停/跌停家数（家）",
        series: [
          { name: "上涨家数", values: mh.map((r) => r.advance), type: "bar" as const, axis: "left" as const, color: UP, unit: "家" },
          { name: "下跌家数", values: mh.map((r) => r.decline), type: "bar" as const, axis: "left" as const, color: DOWN, sign: -1 as const, unit: "家" },
          { name: "涨停家数", values: mh.map((r) => r.limit_up), type: "line" as const, axis: "right" as const, color: UP, unit: "家" },
          { name: "跌停家数", values: mh.map((r) => r.limit_down), type: "line" as const, axis: "right" as const, color: DOWN, sign: -1 as const, unit: "家" },
        ],
      },
      {
        title: "市场宽度", chartType: "series" as const,
        dates: mh.map((r) => r.date), yLabel: "市场宽度（%）",
        series: [{ name: "市场宽度", values: mh.map((r) => r.market_breadth), type: "line" as const, color: "#123d68", percent: true }],
      },
    ];
  }, [data]);

  const crowdChart = useMemo(() => {
    if (!data) return null as ChartConfig | null;
    const dates = data.sw_crowding_history.map((r) => r.date);
    const colors = ["#2563eb", "#f97316", "#7c3aed", "#0891b2"];
    return {
      title: "四行业 | 成交额占全A 与 换手率", chartType: "series" as const, dates,
      yLabel: "成交额占全A（%）", rightLabel: "换手率（%）",
      series: [
        ...CROWD_TARGETS.map((name, i) => ({ name: `${name}·成交占比`, type: "area" as const, axis: "left" as const, color: colors[i], percent: true, opacity: 0.4, values: data.sw_crowding_history.map((r) => r.targets[name]?.amount_share_of_a ?? null) })),
        ...CROWD_TARGETS.map((name, i) => ({ name: `${name}·换手率`, type: "line" as const, axis: "right" as const, color: colors[i], percent: true, values: data.sw_crowding_history.map((r) => r.targets[name]?.turnover ?? null) })),
      ],
    };
  }, [data]);

  // 05 节顶部：单行业（通信设备）面积+折线双轴图
  const commChart = useMemo(() => {
    if (!data) return null as ChartConfig | null;
    const dates = data.sw_crowding_history.map((r) => r.date);
    return {
      title: "通信设备 | 成交额占全A 与 换手率", chartType: "series" as const, dates,
      yLabel: "成交额占全A（%）", rightLabel: "换手率（%）",
      series: [
        { name: "通信设备成交额占全A", type: "area" as const, axis: "left" as const, color: "#2563eb", percent: true, opacity: 0.5, values: data.sw_crowding_history.map((r) => r.targets["通信设备"]?.amount_share_of_a ?? null) },
        { name: "通信设备换手率", type: "line" as const, axis: "right" as const, color: "#ef4444", percent: true, values: data.sw_crowding_history.map((r) => r.targets["通信设备"]?.turnover ?? null) },
      ],
    };
  }, [data]);

  // 四行业合计：成交额（柱，左轴亿元）与 成交额占全A（折线，右轴%）
  const fourChart = useMemo(() => {
    if (!data) return null as ChartConfig | null;
    const dates = data.sw_crowding_history.map((r) => r.date);
    return {
      title: "四行业 | 成交额与成交额占比", chartType: "series" as const, dates,
      yLabel: "成交额（亿元）", rightLabel: "成交额占全A（%）",
      series: [
        { name: "四行业合计成交额", type: "bar" as const, axis: "left" as const, color: "#4f81bd", values: data.sw_crowding_history.map((r) => r.combined?.amount_100m ?? null) },
        { name: "四行业成交额占全A", type: "line" as const, axis: "right" as const, color: "#f59e0b", percent: true, values: data.sw_crowding_history.map((r) => r.combined?.amount_share_of_a ?? null) },
      ],
    };
  }, [data]);

  const innovChart = useMemo(() => {
    if (!data) return null as ChartConfig | null;
    const dates = data.innovation_history.map((r) => r.date);
    return {
      title: "创新药 | 成交额占全A 与 换手率", chartType: "series" as const, dates,
      yLabel: "成交额占全A（%）", rightLabel: "换手率（%）",
      series: [
        { name: "创新药成交额占全A", type: "area" as const, axis: "left" as const, color: "#2563eb", percent: true, opacity: 0.4, values: data.innovation_history.map((r) => r.amount_share_of_a ?? null) },
        { name: "创新药换手率", type: "line" as const, axis: "right" as const, color: "#f97316", percent: true, values: data.innovation_history.map((r) => r.turnover ?? null) },
      ],
    };
  }, [data]);

  const latest = data?.market_history[data.market_history.length - 1];
  const latestIndices = useMemo(() => {
    if (!data) return {} as Record<string, IndexRow | undefined>;
    const out: Record<string, IndexRow | undefined> = {};
    for (const name of INDEX_NAMES) {
      const rows = data.indices_history.filter((r) => r.name === name);
      out[name] = rows[rows.length - 1];
    }
    return out;
  }, [data]);

  const indexRecent = useMemo(() => {
    if (!data) return [];
    const dates = [...new Set(data.indices_history.map((r) => r.date))].sort().slice(-5);
    return dates.map((d) => ({
      date: d,
      rows: Object.fromEntries(INDEX_NAMES.map((n) => [n, data.indices_history.find((r) => r.date === d && r.name === n) ?? null])),
      marketAmount: data.market_history.find((r) => r.date === d)?.total_amount_100m ?? null,
    }));
  }, [data]);

  const swRows = useMemo(() => {
    if (!data) return [];
    let rows = [...data.sw_industry_latest];
    if (swQuery.trim()) {
      const q = swQuery.trim().toLowerCase();
      rows = rows.filter((r) => String(r.指数名称 || "").toLowerCase().includes(q) || String(r.指数代码 || "").includes(q));
    }
    if (swLevel) rows = rows.filter((r) => r.行业层级 === swLevel);
    if (swSort.key) rows = [...rows].sort((a, b) => (swSort.state === "desc" ? -1 : 1) * ((a[swSort.key!] ?? -Infinity) - (b[swSort.key!] ?? -Infinity)));
    return rows;
  }, [data, swQuery, swLevel, swSort]);

  const cycleSort = (key: "成交额" | "日收益率" | "20日年化波动率") => {
    setSwSort((s) => {
      if (s.key !== key) return { key, state: "desc" as const };
      if (s.state === "desc") return { key, state: "asc" as const };
      return { key: null, state: "original" as const };
    });
  };
  const sortInd = (key: "成交额" | "日收益率" | "20日年化波动率") =>
    swSort.key === key ? (swSort.state === "desc" ? "↓" : "↑") : "↕";

  const crowdLatest = data?.sw_crowding_history[data.sw_crowding_history.length - 1];
  const innovLatest = data?.innovation_history[data.innovation_history.length - 1];
  const quality = data?.quality;
  const moduleLatest = quality?.module_latest_dates ?? {};
  const canonicalStatus = quality?.canonical_validation?.status ?? quality?.status ?? data?.meta.status ?? "";

  if (loading) return <div className="asm-root"><div className="page"><div className="empty">正在加载市场监控数据…</div></div></div>;
  if (error || !data) return <div className="asm-root"><div className="page"><div className="empty" style={{ color: "#dc2626" }}>加载失败：{error ?? "无数据"}</div></div></div>;

  return (
    <div className="asm-root">
      <div className="page">
        {/* Hero */}
        <header className="hero">
          <div className="hero-top">
            <div>
              <h1>A股每日市场监控</h1>
              <div className="meta">报告日期 {data.meta.report_date} ｜ 申万行业最新有效日 {moduleLatest.sw_industry ?? "—"} ｜ 单文件离线报告</div>
            </div>
            <div className={`status ${data.meta.status === "PASS" ? "pass" : "warn"}`}>数据状态 {data.meta.status}</div>
          </div>
        </header>

        {/* 6 KPI */}
        <div className="kpis">
          {INDEX_NAMES.map((n) => {
            const ret = latestIndices[n]?.return;
            return (
              <div className="kpi" key={n}>
                <div className="kpi-label">{n}</div>
                <div className={`kpi-value ${upDownCls(ret)}`}>{signedPct(ret)}</div>
              </div>
            );
          })}
          <div className="kpi">
            <div className="kpi-label">全A成交额</div>
            <div className="kpi-value neutral">{latest ? `${num0(latest.total_amount_100m)} 亿` : "—"}</div>
          </div>
          <div className="kpi">
            <div className="kpi-label">百亿成交股</div>
            <div className="kpi-value neutral">{data.hot_stocks_latest.length} 只</div>
          </div>
          <div className="kpi">
            <div className="kpi-label">市场宽度</div>
            <div className={`kpi-value ${upDownCls(latest?.market_breadth)}`}>{latest?.market_breadth == null ? "—" : `${(latest.market_breadth * 100).toFixed(1)}%`}</div>
          </div>
        </div>

        {/* 00 涨跌结构 */}
        <section className="section">
          <div className="section-title">00｜市场总览 · 市场涨跌结构</div>
          <div className="card">
            <div className="subnote">默认全历史；双滚轴可筛选时间。上涨/下跌左轴，涨停/跌停右轴。</div>
            <TimeChart cfg={charts[0]} />
          </div>
        </section>

        {/* 00 市场宽度 */}
        <section className="section">
          <div className="section-title">00｜市场总览 · 市场宽度</div>
          <div className="card">
            <TimeChart cfg={charts[1]} />
          </div>
        </section>

        {/* 00 指数与成交 */}
        <section className="section">
          <div className="section-title">00｜市场总览 · 最近交易日指数与成交</div>
          <div className="card">
            <div className="table-wrap">
              <table>
                <thead>
                  <tr>
                    <th>日期</th>
                    {INDEX_NAMES.map((n) => (<th key={n}>{n}</th>))}
                    {INDEX_NAMES.map((n) => (<th key={n + "-amt"}>成交额</th>))}
                    <th>全A成交额</th>
                  </tr>
                </thead>
                <tbody>
                  {indexRecent.map((row) => (
                    <tr key={row.date}>
                      <td>{row.date}</td>
                      {INDEX_NAMES.map((n) => {
                        const ret = row.rows[n]?.return;
                        return <td key={n}><span className={upDownCls(ret)}>{signedPct(ret)}</span></td>;
                      })}
                      {INDEX_NAMES.map((n) => {
                        const amt = row.rows[n]?.amount_100m;
                        return <td key={n + "-amt"}>{amt != null ? num2(amt) : "—"}</td>;
                      })}
                      <td>{row.marketAmount != null ? num2(row.marketAmount) : "—"}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>
        </section>

        {/* 01 申万行业 */}
        <section className="section">
          <div className="section-title">01｜申万行业</div>
          <div className="card">
            <div className="toolbar">
              <input id="swSearch" type="search" placeholder="搜索行业/指数代码…" value={swQuery} onChange={(e) => setSwQuery(e.target.value)} />
              <select id="swLevel" value={swLevel} onChange={(e) => setSwLevel(e.target.value)}>
                <option value="">全部层级</option>
                <option value="一级行业">一级行业</option>
                <option value="二级行业">二级行业</option>
              </select>
              <span className="hint">成交额 / 日收益率 / 20日年化波动率：原始→降序→升序→原始</span>
            </div>
            <div className="table-wrap sw-table">
              <table>
                <thead>
                  <tr>
                    <th>层级</th>
                    <th>一级行业</th>
                    <th>指数代码</th>
                    <th>指数名称</th>
                    <th>收盘</th>
                    <th className="sortable" onClick={() => cycleSort("成交额")}>成交额<span className="sort-ind">{sortInd("成交额")}</span></th>
                    <th className="sortable" onClick={() => cycleSort("日收益率")}>日收益率<span className="sort-ind">{sortInd("日收益率")}</span></th>
                    <th className="sortable" onClick={() => cycleSort("20日年化波动率")}>20日年化波动率<span className="sort-ind">{sortInd("20日年化波动率")}</span></th>
                  </tr>
                </thead>
                <tbody>
                  {swRows.map((r) => (
                    <tr key={r.指数代码}>
                      <td>{r.行业层级}</td>
                      <td>{r.一级行业}</td>
                      <td className="code">{r.指数代码}</td>
                      <td>{r.指数名称}</td>
                      <td>{r.收盘价 == null ? "—" : r.收盘价.toLocaleString("zh-CN", { minimumFractionDigits: 2, maximumFractionDigits: 2 })}</td>
                      <td>{r.成交额 == null ? "—" : r.成交额.toFixed(2)}</td>
                      <td><span className={upDownCls(r.日收益率)}>{signedPct(r.日收益率)}</span></td>
                      <td>{r["20日年化波动率"] == null ? "—" : pct2(r["20日年化波动率"])}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>
        </section>

        {/* 04 百亿成交 */}
        <section className="section">
          <div className="section-title">04｜百亿成交</div>
          <div className="card">
            <h3>最近{data.hot_stock_matrix.dates.length}个有记录交易日｜最新日期在左</h3>
            <div className="table-wrap">
              <table>
                <thead>
                  <tr>
                    <th>行业</th>
                    {data.hot_stock_matrix.dates.map((d) => <th key={d}>{d.slice(5)}</th>)}
                    <th>历史累计</th>
                  </tr>
                </thead>
                <tbody>
                  {data.hot_stock_matrix.rows.map((row) => (
                    <tr key={row.industry}>
                      <td>{row.industry}</td>
                      {row.counts.map((c, i) => (
                        <td key={i}>{c || ""}</td>
                      ))}
                      <td>{row.history_total}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            <h3>{data.meta.report_date} 成交额超过100亿元个股｜完整明细 {data.hot_stocks_latest.length} 只</h3>
            <div className="table-wrap">
              <table>
                <thead>
                  <tr>
                    <th>排名</th><th>代码</th><th>名称</th><th>收盘价</th><th>涨跌幅</th><th>成交额(亿元)</th><th>申万一级</th><th>申万二级</th>
                  </tr>
                </thead>
                <tbody>
                  {data.hot_stocks_latest.map((s) => (
                    <tr key={s.stock_code}>
                      <td>{s.rank ?? "—"}</td>
                      <td><span className="code">{s.stock_code}</span></td>
                      <td>{s.stock_name}</td>
                      <td>{s.close == null ? "—" : s.close.toFixed(2)}</td>
                      <td><span className={upDownCls(s.return)}>{signedPct(s.return)}</span></td>
                      <td>{s.amount_100m == null ? "—" : s.amount_100m.toFixed(2)}</td>
                      <td>{s.sw_level1}</td>
                      <td>{s.sw_level2}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>
        </section>

        {/* 05 四行业拥挤度 */}
        <section className="section">
          <div className="section-title">05｜申万四行业资金拥挤度</div>
          <div className="card">
            <div className="subnote">{crowdLatest ? `最新官方有效日：${crowdLatest.date}` : "暂无拥挤度数据"}</div>
            {commChart && <TimeChart cfg={commChart} />}
            {fourChart && <TimeChart cfg={fourChart} />}
          </div>
        </section>

        {/* 06 创新药 */}
        <section className="section">
          <div className="section-title">06｜创新药交易拥挤度</div>
          <div className="card">
            <div className="subnote">成交额占全A使用面积图；换手率仅使用供应商直接板块换手率。</div>
            <div className="table-wrap">
              <table>
                <thead>
                  <tr><th>最新日</th><th>成交额(亿元)</th><th>占全A</th><th>换手率</th><th>日收益率</th><th>成交量</th></tr>
                </thead>
                <tbody>
                  {innovLatest && (
                    <tr>
                      <td>{innovLatest.date}</td>
                      <td>{innovLatest.amount_100m != null ? num2(innovLatest.amount_100m) : "—"}</td>
                      <td>{pct2(innovLatest.amount_share_of_a)}</td>
                      <td>{pct2(innovLatest.turnover)}</td>
                      <td><span className={upDownCls(innovLatest.return)}>{signedPct(innovLatest.return)}</span></td>
                      <td>{innovLatest.volume != null ? innovLatest.volume.toLocaleString("zh-CN") : "—"}</td>
                    </tr>
                  )}
                </tbody>
              </table>
            </div>
            {innovChart && <TimeChart cfg={innovChart} />}
          </div>
        </section>

        {/* 99 数据质量 */}
        <section className="section">
          <div className="section-title">99｜数据质量</div>
          <div className="card">
            <div className="table-wrap">
              <table>
                <thead><tr><th>模块</th><th>最新有效日</th></tr></thead>
                <tbody>
                  <tr><td>市场核心</td><td>{moduleLatest.market ?? "—"}</td></tr>
                  <tr><td>三项指数</td><td>{moduleLatest.indices ?? "—"}</td></tr>
                  <tr><td>申万行业</td><td>{moduleLatest.sw_industry ?? "—"}</td></tr>
                  <tr><td>四行业拥挤度</td><td>{moduleLatest.sw_crowding ?? "—"}</td></tr>
                  <tr><td>创新药</td><td>{moduleLatest.innovation ?? "—"}</td></tr>
                </tbody>
              </table>
            </div>
            <div className="quality-meta">Canonical：<b>{canonicalStatus}</b></div>
            {quality?.unresolved?.length ? (
              <div className="quality-warn">
                <b>未解决事项</b>
                <ul>
                  {quality.unresolved.map((u, i) => (
                    <li key={i}><b>{u.module}</b>：{typeof u.detail === "string" ? u.detail : JSON.stringify(u.detail)}</li>
                  ))}
                </ul>
              </div>
            ) : (
              <div className="quality-pass"><b>无未解决事项</b></div>
            )}
          </div>
        </section>
      </div>
    </div>
  );
}

function pct2(v: number | null | undefined) {
  return v == null ? "—" : `${(v * 100).toFixed(2)}%`;
}
