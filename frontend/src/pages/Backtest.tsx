/**
 * 策略回测 —— 本地回测引擎（新浪前复权日线，A股/美股/港股）
 * 数据流：闸口校验 → 取数 → 引擎撮合 → 指标。闸口拒绝/失败均显式呈现，不静默出数。
 */
import { useState } from "react";
import { PlayCircle, Loader2, AlertCircle, BarChart3, ShieldCheck, Database } from "lucide-react";
import { PageHeader } from "@/components/ui/PageHeader";
import { GlassCard } from "@/components/ui/GlassCard";
import { cn } from "@/lib/utils";
import { ApiError, api, type BacktestResult } from "@/lib/api";

const STRATEGIES = [
  { key: "ma_cross", label: "均线交叉", hint: "快线上穿慢线买入 / 下穿卖出（默认 20/60 日）" },
  { key: "buy_and_hold", label: "买入持有", hint: "期初一次性买入，期末卖出（对照基准）" },
  { key: "rsi_reversion", label: "RSI 反转", hint: "超卖买入 / 超买卖出" },
] as const;

const STYLES = [
  { key: "swing", label: "短线波段", hint: "持仓数日至数周，默认" },
  { key: "long", label: "长线", hint: "月/季级持仓" },
] as const;

const fmtDate = (d: Date) => {
  const y = d.getFullYear();
  const m = String(d.getMonth() + 1).padStart(2, "0");
  const day = String(d.getDate()).padStart(2, "0");
  return `${y}-${m}-${day}`;
};

const num = (v: number | null | undefined, nd = 2) =>
  v == null || Number.isNaN(v) ? "—" : v.toFixed(nd);
const pct = (v: number | null | undefined) =>
  v == null || Number.isNaN(v) ? "—" : `${v > 0 ? "+" : ""}${(v * 100).toFixed(2)}%`;
// A股红涨绿跌：收益/回撤正负着色
const signColor = (v: number | null | undefined) =>
  v == null || v === 0 ? "text-foreground" : v > 0 ? "text-danger" : "text-success";

export function Backtest() {
  const today = new Date();
  const twoYearsAgo = new Date(today.getFullYear() - 2, today.getMonth(), today.getDate());

  const [codes, setCodes] = useState("600519.SH");
  const [strategy, setStrategy] = useState<string>("ma_cross");
  const [style, setStyle] = useState<string>("swing");
  const [start, setStart] = useState(fmtDate(twoYearsAgo));
  const [end, setEnd] = useState(fmtDate(today));
  const [initialCash, setInitialCash] = useState("1000000");

  const [result, setResult] = useState<BacktestResult | null>(null);
  const [loading, setLoading] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  const run = async () => {
    const codeList = codes.split(/[,，\s]+/).map((s) => s.trim()).filter(Boolean);
    if (!codeList.length) { setErr("请至少输入一个股票代码"); return; }
    const cash = Number(initialCash);
    if (!cash || cash <= 0) { setErr("初始资金需为正数"); return; }
    setLoading(true); setErr(null); setResult(null);
    try {
      const r = await api.backtest({
        codes: codeList, start, end, style, strategy,
        initial_cash: cash,
      });
      setResult(r);
    } catch (e) {
      setErr(e instanceof ApiError ? e.message : "回测失败");
    } finally {
      setLoading(false);
    }
  };

  const m = result?.metrics;
  const metricCards = m ? [
    { k: "总收益", v: pct(m.total_return), c: signColor(m.total_return) },
    { k: "年化收益", v: pct(m.annual_return), c: signColor(m.annual_return) },
    { k: "最大回撤", v: pct(m.max_drawdown), c: signColor(m.max_drawdown) },
    { k: "夏普比率", v: num(m.sharpe), c: "text-foreground" },
    { k: "卡玛比率", v: num(m.calmar), c: "text-foreground" },
    { k: "索提诺", v: num(m.sortino), c: "text-foreground" },
    { k: "交易笔数", v: m.trade_count == null ? "—" : String(m.trade_count), c: "text-foreground" },
    { k: "胜率", v: pct(m.win_rate), c: signColor(m.win_rate) },
    { k: "盈亏比", v: num(m.profit_loss_ratio), c: "text-foreground" },
  ] : [];

  return (
    <div>
      <PageHeader
        title="策略回测"
        subtitle="本地回测引擎 · 新浪前复权日线 · A股/美股/港股（代码示例：600519.SH / AAPL / 00700.HK，多只逗号分隔）"
      />

      {/* 参数表单 */}
      <GlassCard className="mb-4">
        <h3 className="mb-3 flex items-center gap-1.5 text-sm font-semibold">
          <BarChart3 className="h-4 w-4 text-primary" /> 回测参数
        </h3>

        <div className="grid gap-4 lg:grid-cols-2">
          {/* 股票代码 */}
          <div className="lg:col-span-2">
            <label className="mb-1 block text-xs text-muted-foreground">股票代码（多只逗号分隔）</label>
            <input
              className="input w-full"
              value={codes}
              onChange={(e) => setCodes(e.target.value)}
              placeholder="600519.SH, AAPL, 00700.HK"
            />
          </div>

          {/* 策略 */}
          <div>
            <label className="mb-1.5 block text-xs text-muted-foreground">策略</label>
            <div className="flex flex-wrap gap-1.5">
              {STRATEGIES.map((s) => (
                <button
                  key={s.key}
                  onClick={() => setStrategy(s.key)}
                  title={s.hint}
                  className={cn(
                    "rounded-lg px-3 py-1.5 text-[13px] transition-colors",
                    strategy === s.key
                      ? "bg-primary/15 font-medium text-primary"
                      : "text-muted-foreground hover:bg-muted/60 hover:text-foreground",
                  )}
                >
                  {s.label}
                </button>
              ))}
            </div>
            <p className="mt-1 text-[11px] text-muted-foreground/60">
              {STRATEGIES.find((s) => s.key === strategy)?.hint}
            </p>
          </div>

          {/* 风格 */}
          <div>
            <label className="mb-1.5 block text-xs text-muted-foreground">持仓风格</label>
            <div className="flex flex-wrap gap-1.5">
              {STYLES.map((s) => (
                <button
                  key={s.key}
                  onClick={() => setStyle(s.key)}
                  title={s.hint}
                  className={cn(
                    "rounded-lg px-3 py-1.5 text-[13px] transition-colors",
                    style === s.key
                      ? "bg-primary/15 font-medium text-primary"
                      : "text-muted-foreground hover:bg-muted/60 hover:text-foreground",
                  )}
                >
                  {s.label}
                </button>
              ))}
            </div>
            <p className="mt-1 text-[11px] text-muted-foreground/60">
              {STYLES.find((s) => s.key === style)?.hint}
            </p>
          </div>

          {/* 起止日期 */}
          <div>
            <label className="mb-1 block text-xs text-muted-foreground">开始日期</label>
            <input type="date" className="input w-full" value={start} onChange={(e) => setStart(e.target.value)} />
          </div>
          <div>
            <label className="mb-1 block text-xs text-muted-foreground">结束日期</label>
            <input type="date" className="input w-full" value={end} onChange={(e) => setEnd(e.target.value)} />
          </div>

          {/* 初始资金 */}
          <div>
            <label className="mb-1 block text-xs text-muted-foreground">初始资金（元）</label>
            <input
              className="input w-full"
              value={initialCash}
              onChange={(e) => setInitialCash(e.target.value.replace(/[^\d]/g, ""))}
              inputMode="numeric"
            />
          </div>

          {/* 运行按钮 */}
          <div className="flex items-end">
            <button onClick={run} disabled={loading} className="btn-primary w-full justify-center">
              {loading ? <Loader2 className="h-4 w-4 animate-spin" /> : <PlayCircle className="h-4 w-4" />}
              {loading ? "回测中…" : "运行回测"}
            </button>
          </div>
        </div>
      </GlassCard>

      {err && (
        <div className="mb-4 flex items-center gap-2 rounded-lg border border-destructive/30 bg-destructive/5 p-3 text-sm text-destructive">
          <AlertCircle className="h-4 w-4 shrink-0" /> {err}
        </div>
      )}

      {/* 闸口拒绝 */}
      {result && !result.ok && (
        <GlassCard className="mb-4">
          <div className="flex items-start gap-2.5">
            <ShieldCheck className="mt-0.5 h-5 w-5 shrink-0 text-warning" />
            <div className="space-y-2">
              <h3 className="text-sm font-semibold text-foreground">这次回测被闸口拦下，未出结果</h3>
              {result.reason && <p className="text-sm text-muted-foreground">{result.reason}</p>}
              {result.remedy && (
                <p className="text-sm">
                  <span className="font-medium text-foreground">怎么改：</span>
                  <span className="text-muted-foreground">{result.remedy}</span>
                </p>
              )}
            </div>
          </div>
        </GlassCard>
      )}

      {/* 回测结果 */}
      {result?.ok && m && (
        <>
          {/* 指标卡片 */}
          <div className="mb-4 grid grid-cols-3 gap-2 lg:grid-cols-9">
            {metricCards.map((c) => (
              <div key={c.k} className="glass rounded-xl p-3 text-center">
                <p className="text-[10px] text-muted-foreground">{c.k}</p>
                <p className={cn("mt-1 font-mono text-base font-bold", c.c)}>{c.v}</p>
              </div>
            ))}
          </div>

          {/* 摘要 + 数据来源 */}
          <div className="grid gap-4 lg:grid-cols-2">
            <GlassCard className="p-4">
              <h3 className="mb-2 flex items-center gap-1.5 text-sm font-semibold">
                <BarChart3 className="h-4 w-4 text-primary" /> 回测摘要
              </h3>
              {result.summary && (
                <pre className="whitespace-pre-wrap font-sans text-[13px] leading-relaxed text-muted-foreground">
                  {result.summary}
                </pre>
              )}
            </GlassCard>

            <GlassCard className="p-4">
              <h3 className="mb-2 flex items-center gap-1.5 text-sm font-semibold">
                <Database className="h-4 w-4 text-primary" /> 数据来源
              </h3>
              {result.provenance && Object.entries(result.provenance).length > 0 ? (
                <ul className="space-y-2 text-[13px] text-muted-foreground">
                  {Object.entries(result.provenance).map(([code, p]) => (
                    <li key={code} className="rounded-lg bg-muted/30 p-2.5">
                      <p className="font-mono font-semibold text-foreground">{code}</p>
                      <p className="mt-1 text-xs">
                        {p.endpoint} · {p.rows} 根日线 · {p.first_bar} → {p.last_bar}
                        {p.halted_bars ? ` · 停牌 ${p.halted_bars} 根` : ""}
                      </p>
                      {p.note && <p className="mt-1 text-xs text-warning">{p.note}</p>}
                    </li>
                  ))}
                </ul>
              ) : (
                <p className="text-xs text-muted-foreground/60">暂无数据来源信息</p>
              )}
            </GlassCard>
          </div>
        </>
      )}

      {!result && !loading && !err && (
        <p className="mt-2 text-sm text-muted-foreground">
          填好参数点「运行回测」。数据来自新浪前复权日线；A股按 T+1 / 涨跌停 / 整手 / 费率规则撮合，美股港股为普通日线规则。
        </p>
      )}
    </div>
  );
}
