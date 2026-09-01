/**
 * K 线图（数据源：后端 /api/kline，腾讯前复权日线）
 * - 完全本地渲染，不再依赖任何外部 widget 服务
 * - 红涨绿跌（A 股惯例；美/港/韩一致）
 * - 支持浅色 / 深色主题
 */
import { useEffect, useMemo, useRef, useState } from "react";
import * as echarts from "echarts";
import { cn } from "@/lib/utils";

type Market = "A" | "HK" | "US" | "KR" | string;

function marketOf(code: string, hint?: string): Market {
  if (hint) return hint;
  if (/^\d{6}$/.test(code)) return "A";
  if (/^\d{5}$/.test(code)) return "HK";
  if (/^\d{6}\.KS$/.test(code.toUpperCase())) return "KR";
  return "US";
}

function darkTheme(dark?: boolean) {
  return dark
    ? {
        bg: "transparent",
        text: "#cbd5e1",
        axis: "#1e293b",
        up: "#ef4444",     // 红涨
        down: "#10b981",   // 绿跌
        ma: ["#fbbf24", "#60a5fa", "#a78bfa"],
        grid: "rgba(148,163,184,0.12)",
        tooltipBg: "rgba(15,23,42,0.92)",
      }
    : {
        bg: "transparent",
        text: "#475569",
        axis: "#e2e8f0",
        up: "#ef4444",
        down: "#10b981",
        ma: ["#d97706", "#2563eb", "#7c3aed"],
        grid: "rgba(148,163,184,0.25)",
        tooltipBg: "rgba(255,255,255,0.96)",
      };
}

function calcMA(day: number, closes: number[]) {
  const out: (number | null)[] = [];
  for (let i = 0; i < closes.length; i++) {
    if (i < day - 1) { out.push(null); continue; }
    let s = 0;
    for (let j = i - day + 1; j <= i; j++) s += closes[j];
    out.push(+(s / day).toFixed(3));
  }
  return out;
}

// 布林带 BOLL(20, 2)：中轨=MA20，上下轨=中轨±2σ
function calcBOLL(period: number, k: number, closes: number[]) {
  const mid: (number | null)[] = [];
  const up: (number | null)[] = [];
  const low: (number | null)[] = [];
  for (let i = 0; i < closes.length; i++) {
    if (i < period - 1) { mid.push(null); up.push(null); low.push(null); continue; }
    let s = 0;
    for (let j = i - period + 1; j <= i; j++) s += closes[j];
    const m = s / period;
    let v = 0;
    for (let j = i - period + 1; j <= i; j++) v += (closes[j] - m) ** 2;
    const sd = Math.sqrt(v / period);
    mid.push(+m.toFixed(3));
    up.push(+(m + k * sd).toFixed(3));
    low.push(+(m - k * sd).toFixed(3));
  }
  return { mid, up, low };
}

export function KlineChart({
  code,
  market,
  dark,
  height = 440,
}: {
  code: string;
  market?: Market;
  dark?: boolean;
  height?: number;
}) {
  const elRef = useRef<HTMLDivElement | null>(null);
  const chartRef = useRef<echarts.ECharts | null>(null);
  const [loading, setLoading] = useState(true);
  const [err, setErr] = useState<string | null>(null);
  const [count, setCount] = useState(0);
  // 周期（1h/日/周/月）+ 均线开关 + 布林带（默认关）
  const [period, setPeriod] = useState<"day" | "week" | "month" | "60m">("day");
  const [ma, setMa] = useState({ ma5: true, ma10: true, ma20: true });
  const [boll, setBoll] = useState(false);
  const periodLabel = period === "60m" ? "1h" : period === "day" ? "日K" : period === "week" ? "周K" : "月K";
  const t = useMemo(() => darkTheme(dark), [dark]);
  const mkt = useMemo(() => marketOf(code, market), [code, market]);

  // 初始化 echarts 实例（仅一次）
  useEffect(() => {
    if (!elRef.current) return;
    const c = echarts.init(elRef.current, undefined, { renderer: "canvas" });
    chartRef.current = c;
    const ro = new ResizeObserver(() => c.resize());
    ro.observe(elRef.current);
    return () => { ro.disconnect(); c.dispose(); chartRef.current = null; };
  }, []);

  // 拉数据 + 渲染
  useEffect(() => {
    let cancelled = false;
    setLoading(true); setErr(null);
    const url = `/api/kline?code=${encodeURIComponent(code.trim().toUpperCase())}&period=${period}&offset=${period === "60m" ? 200 : period === "month" ? 96 : 180}`;
    fetch(url)
      .then((r) => { if (!r.ok) throw new Error(`HTTP ${r.status}`); return r.json(); })
      .then((j) => {
        if (cancelled) return;
        const raw: Array<{ date: string; open: number; close: number; high: number; low: number; volume: number }> =
          j?.data || [];
        if (raw.length === 0) {
          setCount(0);
          setErr("暂无 K 线数据");
          setLoading(false);
          chartRef.current?.clear();
          return;
        }
        // 60m 时间戳 "202608141400" → "08-14 14:00"；日/周/月 "2026-08-14" 原样
        const dates = raw.map((r) =>
          period === "60m" && r.date.length >= 12
            ? `${r.date.slice(4, 6)}-${r.date.slice(6, 8)} ${r.date.slice(8, 10)}:${r.date.slice(10, 12)}`
            : r.date
        );
        // echarts 蜡烛图要求 [open, close, low, high]
        const kvals = raw.map((r) => [r.open, r.close, r.low, r.high]);
        const closes = raw.map((r) => r.close);
        const vols = raw.map((r) => ({
          value: r.volume,
          itemStyle: { color: r.close >= r.open ? t.up : t.down },
        }));
        const ma5 = calcMA(5, closes);
        const ma10 = calcMA(10, closes);
        const ma20 = calcMA(20, closes);
        const bollData = calcBOLL(20, 2, closes);
        const legendData = ["K线"];
        if (ma.ma5) legendData.push("MA5");
        if (ma.ma10) legendData.push("MA10");
        if (ma.ma20) legendData.push("MA20");

        chartRef.current?.setOption(
          {
            backgroundColor: t.bg,
            animation: false,
            textStyle: { color: t.text, fontFamily: "inherit" },
            legend: {
              data: legendData,
              textStyle: { color: t.text, fontSize: 11 },
              top: 4,
              itemGap: 12,
            },
            tooltip: {
              trigger: "axis",
              axisPointer: { type: "cross" },
              backgroundColor: t.tooltipBg,
              borderColor: "transparent",
              textStyle: { color: t.text, fontSize: 12 },
              formatter: (params: unknown) => {
                const arr = params as Array<{ axisValue: string; data: number | number[]; seriesName: string }>;
                if (!arr.length) return "";
                const date = arr[0].axisValue;
                const kline = arr.find((p) => p.seriesName === "K线");
                const v = kline?.data as number[] | undefined;
                const vol = arr.find((p) => p.seriesName === "Volume")?.data as number | undefined;
                const maVal = (n: string) => arr.find((p) => p.seriesName === n)?.data as number | null | undefined;
                const lines: string[] = [`<b>${date}</b>`];
                if (v) {
                  const [o, c, l, h] = v;
                  lines.push(`开 ${o}  收 <b style="color:${c >= o ? t.up : t.down}">${c}</b>  低 ${l}  高 ${h}`);
                }
                if (ma.ma5) { const m5 = maVal("MA5"); if (m5 != null && m5 !== undefined) lines.push(`MA5  ${m5}`); }
                if (ma.ma10) { const m10 = maVal("MA10"); if (m10 != null && m10 !== undefined) lines.push(`MA10 ${m10}`); }
                if (ma.ma20) { const m20 = maVal("MA20"); if (m20 != null && m20 !== undefined) lines.push(`MA20 ${m20}`); }
                if (boll) {
                  const bu = arr.find((p) => p.seriesName === "BOLL上")?.data as number | null | undefined;
                  const bm = arr.find((p) => p.seriesName === "BOLL中")?.data as number | null | undefined;
                  const bl = arr.find((p) => p.seriesName === "BOLL下")?.data as number | null | undefined;
                  if (bm != null && bm !== undefined) lines.push(`BOLL 中 ${bm} / 上 ${bu ?? "—"} / 下 ${bl ?? "—"}`);
                }
                if (vol != null) lines.push(`量 ${Math.round(vol).toLocaleString()}`);
                return lines.join("<br/>");
              },
            },
            axisPointer: {
              link: [{ xAxisIndex: "all" }],
              label: { backgroundColor: t.axis },
            },
            grid: [
              { left: 50, right: 16, top: 36, height: "62%" },
              { left: 50, right: 16, top: "76%", height: "16%" },
            ],
            xAxis: [
              {
                type: "category", data: dates,
                boundaryGap: false,
                axisLine: { lineStyle: { color: t.axis } },
                axisLabel: { color: t.text, fontSize: 10 },
                splitLine: { show: false },
                axisPointer: { z: 100 },
              },
              {
                type: "category", gridIndex: 1, data: dates,
                boundaryGap: false,
                axisLine: { lineStyle: { color: t.axis } },
                axisLabel: { show: false },
                axisTick: { show: false },
                splitLine: { show: false },
              },
            ],
            yAxis: [
              {
                scale: true,
                splitArea: { show: false },
                axisLine: { lineStyle: { color: t.axis } },
                axisLabel: { color: t.text, fontSize: 10 },
                splitLine: { lineStyle: { color: t.grid } },
              },
              {
                gridIndex: 1, scale: true,
                axisNumber: "1e4",
                axisLine: { lineStyle: { color: t.axis } },
                axisLabel: { color: t.text, fontSize: 10, formatter: (v: number) => (v >= 1e4 ? `${(v / 1e4).toFixed(0)}万` : `${v}`) },
                splitLine: { show: false },
              },
            ],
            dataZoom: [
              { type: "inside", xAxisIndex: [0, 1], start: 60, end: 100 },
              { type: "slider", xAxisIndex: [0, 1], top: "94%", height: 18, start: 60, end: 100, borderColor: t.axis, textStyle: { color: t.text, fontSize: 10 } },
            ],
            series: [
              {
                name: "K线", type: "candlestick", data: kvals,
                itemStyle: {
                  color: t.up, color0: t.down,
                  borderColor: t.up, borderColor0: t.down,
                },
              },
              ...(ma.ma5 ? [{ name: "MA5", type: "line", data: ma5, smooth: true, showSymbol: false, lineStyle: { width: 1, color: t.ma[0] } }] : []),
              ...(ma.ma10 ? [{ name: "MA10", type: "line", data: ma10, smooth: true, showSymbol: false, lineStyle: { width: 1, color: t.ma[1] } }] : []),
              ...(ma.ma20 ? [{ name: "MA20", type: "line", data: ma20, smooth: true, showSymbol: false, lineStyle: { width: 1, color: t.ma[2] } }] : []),
              ...(boll ? [
                { name: "BOLL上", type: "line", data: bollData.up, smooth: true, showSymbol: false, lineStyle: { width: 1, color: "#f472b6" } },
                { name: "BOLL中", type: "line", data: bollData.mid, smooth: true, showSymbol: false, lineStyle: { width: 1, color: "#94a3b8", type: "dashed" as const } },
                { name: "BOLL下", type: "line", data: bollData.low, smooth: true, showSymbol: false, lineStyle: { width: 1, color: "#34d399" } },
              ] : []),
              { name: "Volume", type: "bar", xAxisIndex: 1, yAxisIndex: 1, data: vols },
            ],
          },
          true,
        );
        setCount(raw.length);
        setLoading(false);
      })
      .catch((e: Error) => {
        if (cancelled) return;
        setErr(e.message || "加载失败");
        setLoading(false);
        chartRef.current?.clear();
      });

    return () => { cancelled = true; };
  }, [code, t, period, ma, boll]);

  return (
    <div>
      {/* 工具栏：周期切换 + 均线开关 */}
      <div className="mb-1.5 flex flex-wrap items-center gap-1.5">
        {(["60m", "day", "week", "month"] as const).map((p) => (
          <button
            key={p}
            onClick={() => setPeriod(p)}
            className={cn(
              "rounded border px-2 py-0.5 text-[11px] transition-colors",
              period === p
                ? "border-primary/60 bg-primary/15 text-primary"
                : "border-border/60 text-muted-foreground hover:border-primary/40 hover:text-foreground"
            )}
          >
            {p === "60m" ? "1h" : p === "day" ? "日K" : p === "week" ? "周K" : "月K"}
          </button>
        ))}
        <span className="mx-1 h-3 w-px bg-border" />
        {([["ma5", "MA5"], ["ma10", "MA10"], ["ma20", "MA20"]] as const).map(([k, label]) => (
          <button
            key={k}
            onClick={() => setMa((s) => ({ ...s, [k]: !s[k] } as typeof s))}
            className={cn(
              "rounded border px-2 py-0.5 text-[11px] transition-colors",
              ma[k]
                ? "border-primary/60 bg-primary/15 text-primary"
                : "border-border/60 text-muted-foreground/50 hover:border-primary/40 hover:text-foreground"
            )}
          >
            {label}
          </button>
        ))}
        <button
          onClick={() => setBoll((b) => !b)}
          className={cn(
            "rounded border px-2 py-0.5 text-[11px] transition-colors",
            boll
              ? "border-primary/60 bg-primary/15 text-primary"
              : "border-border/60 text-muted-foreground/50 hover:border-primary/40 hover:text-foreground"
          )}
        >
          BOLL
        </button>
      </div>
      <div className="relative" style={{ height }}>
        <div ref={elRef} style={{ width: "100%", height: "100%" }} />
        {loading && (
          <div className="pointer-events-none absolute inset-0 flex items-center justify-center text-xs text-muted-foreground">
            加载 K 线…
          </div>
        )}
        {err && !loading && (
          <div className="pointer-events-none absolute inset-0 flex items-center justify-center text-xs text-destructive">
            {err}
          </div>
        )}
        {!loading && !err && count > 0 && (
          <div className="pointer-events-none absolute right-3 top-2 rounded bg-black/20 px-1.5 py-0.5 text-[10px] text-muted-foreground">
            {mkt} · {code} · {periodLabel} 近 {count} 根
          </div>
        )}
      </div>
    </div>
  );
}
