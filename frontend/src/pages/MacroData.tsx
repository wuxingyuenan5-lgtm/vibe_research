/**
 * 宏观 / 商品数据 —— CFTC 持仓 + 宏观事件概率（Kalshi/Polymarket）+ 大宗期货/DRAM 现货
 * 数据源：CFTC COT（Socrata）、预测市场（零鉴权 API）、新浪连续合约（akshare）、社区 DRAM 存档
 * 护栏文字与数字同段呈现（预测市场是定价预期不是事实；期货价是市场价非采购价；DRAM 是社区转录）。
 */
import { useEffect, useState } from "react";
import { RefreshCw, Loader2, AlertCircle, Landmark, TrendingUp, Gem, Scale } from "lucide-react";
import { PageHeader } from "@/components/ui/PageHeader";
import { GlassCard } from "@/components/ui/GlassCard";
import { cn } from "@/lib/utils";
import { ApiError, api, type CftcRow, type CommodityData, type MacroProbability } from "@/lib/api";

const num = (v: number | null | undefined, nd = 2) =>
  v == null || Number.isNaN(v) ? "—" : v.toFixed(nd);
// A股红涨绿跌
const signColor = (v: number | null | undefined) =>
  v == null || v === 0 ? "text-foreground" : v > 0 ? "text-danger" : "text-success";
const signPct = (v: number | null | undefined) =>
  v == null || Number.isNaN(v) ? "—" : `${v > 0 ? "+" : ""}${v.toFixed(2)}%`;

const COT_MARKETS = ["GOLD", "SILVER", "COPPER"];

export function MacroData() {
  // CFTC 持仓
  const [cotMarket, setCotMarket] = useState("GOLD");
  const [cotRows, setCotRows] = useState<CftcRow[]>([]);
  const [cotLoading, setCotLoading] = useState(true);
  const [cotErr, setCotErr] = useState<string | null>(null);
  // 宏观概率
  const [macro, setMacro] = useState<MacroProbability | null>(null);
  const [macroLoading, setMacroLoading] = useState(true);
  const [macroErr, setMacroErr] = useState<string | null>(null);
  // 大宗期货 + DRAM
  const [commodity, setCommodity] = useState<CommodityData | null>(null);
  const [commLoading, setCommLoading] = useState(true);
  const [commErr, setCommErr] = useState<string | null>(null);

  const loadCot = async (market: string) => {
    setCotLoading(true); setCotErr(null);
    try {
      const r = await api.cftcCot(market, 20);
      setCotRows(r.rows || []);
    } catch (e) {
      setCotErr(e instanceof ApiError ? e.message : "CFTC 取数失败");
    } finally {
      setCotLoading(false);
    }
  };

  const loadMacro = async () => {
    setMacroLoading(true); setMacroErr(null);
    try {
      setMacro(await api.macroProbability(3));
    } catch (e) {
      setMacroErr(e instanceof ApiError ? e.message : "宏观概率取数失败");
    } finally {
      setMacroLoading(false);
    }
  };

  const loadCommodity = async () => {
    setCommLoading(true); setCommErr(null);
    try {
      setCommodity(await api.commodity());
    } catch (e) {
      setCommErr(e instanceof ApiError ? e.message : "大宗/DRAM 取数失败");
    } finally {
      setCommLoading(false);
    }
  };

  useEffect(() => {
    loadCot("GOLD");
    loadMacro();
    loadCommodity();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const futures = commodity?.futures?.futures || [];
  const dram = commodity?.dram?.dram || [];

  return (
    <div>
      <PageHeader
        title="宏观 / 商品数据"
        subtitle="CFTC 持仓报告 · 预测市场宏观概率 · 大宗期货与 DRAM 现货（海外源经本地代理抓取）"
      />

      {/* ① CFTC 持仓 */}
      <GlassCard className="mb-4 p-4">
        <div className="mb-3 flex flex-wrap items-center gap-2">
          <h3 className="flex items-center gap-1.5 text-sm font-semibold">
            <Landmark className="h-4 w-4 text-primary" /> CFTC 持仓报告
          </h3>
          <span className="text-[11px] text-muted-foreground/60">投机/对冲基金非商业头寸，按报告日倒序</span>
          <div className="ml-auto flex items-center gap-1.5">
            {COT_MARKETS.map((mkt) => (
              <button
                key={mkt}
                onClick={() => { setCotMarket(mkt); loadCot(mkt); }}
                className={cn(
                  "rounded-lg px-2.5 py-1 text-[12px] transition-colors",
                  cotMarket === mkt
                    ? "bg-primary/15 font-medium text-primary"
                    : "text-muted-foreground hover:bg-muted/60 hover:text-foreground",
                )}
              >
                {mkt}
              </button>
            ))}
            <button onClick={() => loadCot(cotMarket)} disabled={cotLoading}
              className="rounded-lg p-1.5 text-muted-foreground hover:bg-muted/60 hover:text-foreground disabled:opacity-50"
              title="刷新">
              {cotLoading ? <Loader2 className="h-4 w-4 animate-spin" /> : <RefreshCw className="h-4 w-4" />}
            </button>
          </div>
        </div>

        {cotErr && (
          <div className="mb-2 flex items-center gap-2 rounded-lg border border-destructive/30 bg-destructive/5 p-2.5 text-sm text-destructive">
            <AlertCircle className="h-4 w-4 shrink-0" /> {cotErr}
          </div>
        )}

        {cotLoading ? (
          <p className="text-xs text-muted-foreground/60">加载中…</p>
        ) : cotRows.length === 0 ? (
          <p className="text-xs text-muted-foreground/60">暂无数据</p>
        ) : (
          <div className="overflow-x-auto">
            <table className="data-table w-full text-[12.5px]">
              <thead>
                <tr className="text-left text-[11px] text-muted-foreground/70">
                  <th className="py-2 pr-3 font-medium">合约市场</th>
                  <th className="py-2 pr-3 font-medium">报告日期</th>
                  <th className="py-2 pr-3 text-right font-medium">未平仓总量</th>
                  <th className="py-2 pr-3 text-right font-medium">非商业多头</th>
                  <th className="py-2 pr-3 text-right font-medium">非商业空头</th>
                  <th className="py-2 text-right font-medium">非商业净头寸</th>
                </tr>
              </thead>
              <tbody>
                {cotRows.map((r, i) => {
                  const lo = Number(r.noncomm_positions_long_all);
                  const sh = Number(r.noncomm_positions_short_all);
                  const net = Number.isFinite(lo) && Number.isFinite(sh) ? lo - sh : NaN;
                  return (
                    <tr key={i} className="border-t border-border/40">
                      <td className="py-2 pr-3 font-medium text-foreground">{r.contract_market_name || "—"}</td>
                      <td className="py-2 pr-3 font-mono">{String(r.report_date || "").slice(0, 10)}</td>
                      <td className="py-2 pr-3 text-right font-mono">{Number(r.open_interest_all).toLocaleString() || "—"}</td>
                      <td className="py-2 pr-3 text-right font-mono">{Number.isFinite(lo) ? lo.toLocaleString() : "—"}</td>
                      <td className="py-2 pr-3 text-right font-mono">{Number.isFinite(sh) ? sh.toLocaleString() : "—"}</td>
                      <td className={cn("py-2 text-right font-mono font-semibold", signColor(Number.isFinite(net) ? net : NaN))}>
                        {Number.isFinite(net) ? (net > 0 ? "+" : "") + net.toLocaleString() : "—"}
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        )}
      </GlassCard>

      {/* ② 宏观事件概率 */}
      <GlassCard className="mb-4 p-4">
        <div className="mb-3 flex flex-wrap items-center gap-2">
          <h3 className="flex items-center gap-1.5 text-sm font-semibold">
            <Scale className="h-4 w-4 text-primary" /> 宏观事件概率
          </h3>
          <span className="text-[11px] text-muted-foreground/60">
            预测市场（Kalshi / Polymarket）· {macro ? `截至 ${macro.as_of}` : ""}
          </span>
          <button onClick={loadMacro} disabled={macroLoading}
            className="ml-auto rounded-lg p-1.5 text-muted-foreground hover:bg-muted/60 hover:text-foreground disabled:opacity-50"
            title="刷新">
            {macroLoading ? <Loader2 className="h-4 w-4 animate-spin" /> : <RefreshCw className="h-4 w-4" />}
          </button>
        </div>

        {macro?.guard && (
          <p className="mb-3 rounded-lg border border-warning/30 bg-warning/5 p-2.5 text-[12px] leading-relaxed text-muted-foreground">
            {macro.guard}
          </p>
        )}

        {macroErr && (
          <div className="mb-2 flex items-center gap-2 rounded-lg border border-destructive/30 bg-destructive/5 p-2.5 text-sm text-destructive">
            <AlertCircle className="h-4 w-4 shrink-0" /> {macroErr}
          </div>
        )}

        {macroLoading ? (
          <p className="text-xs text-muted-foreground/60">加载中…</p>
        ) : (
          <div className="grid gap-3 lg:grid-cols-3">
            {Object.entries(macro?.modules || {}).map(([mod, contracts]) => (
              <div key={mod} className="rounded-xl bg-muted/20 p-3">
                <p className="mb-2 text-[13px] font-semibold text-foreground">{mod}</p>
                {contracts.length === 0 ? (
                  <p className="text-xs text-muted-foreground/50">暂无流动性足够的合约</p>
                ) : (
                  <ul className="space-y-2">
                    {contracts.map((c, i) => (
                      <li key={i} className="rounded-lg bg-muted/30 p-2">
                        <p className="text-[12px] leading-snug text-foreground">{c.title}</p>
                        <div className="mt-1 flex items-center gap-1.5 text-[11px]">
                          <span className="font-mono text-[13px] font-bold text-primary">{(c.prob * 100).toFixed(c.prob < 0.01 ? 1 : 0)}%</span>
                          <span className={cn(
                            "rounded px-1 py-0.5 text-[10px]",
                            c.source === "kalshi" ? "bg-primary/10 text-primary" : "bg-accent/10 text-accent",
                          )}>
                            {c.source === "kalshi" ? "Kalshi" : "Poly"}
                          </span>
                          {c.close_date && <span className="text-muted-foreground/60">· {c.close_date}</span>}
                        </div>
                      </li>
                    ))}
                  </ul>
                )}
              </div>
            ))}
          </div>
        )}
      </GlassCard>

      {/* ③ 大宗期货 + DRAM */}
      <GlassCard className="p-4">
        <div className="mb-3 flex items-center gap-2">
          <h3 className="flex items-center gap-1.5 text-sm font-semibold">
            <Gem className="h-4 w-4 text-primary" /> 大宗期货与 DRAM 现货
          </h3>
          <button onClick={loadCommodity} disabled={commLoading}
            className="ml-auto rounded-lg p-1.5 text-muted-foreground hover:bg-muted/60 hover:text-foreground disabled:opacity-50"
            title="刷新">
            {commLoading ? <Loader2 className="h-4 w-4 animate-spin" /> : <RefreshCw className="h-4 w-4" />}
          </button>
        </div>

        {commErr && (
          <div className="mb-2 flex items-center gap-2 rounded-lg border border-destructive/30 bg-destructive/5 p-2.5 text-sm text-destructive">
            <AlertCircle className="h-4 w-4 shrink-0" /> {commErr}
          </div>
        )}

        {commodity?.futures?.guard && (
          <p className="mb-3 rounded-lg border border-warning/30 bg-warning/5 p-2.5 text-[12px] leading-relaxed text-muted-foreground">
            {commodity.futures.guard}
          </p>
        )}

        {commLoading ? (
          <p className="text-xs text-muted-foreground/60">加载中…</p>
        ) : (
          <div className="grid gap-4 lg:grid-cols-5">
            {/* 期货表（占 3 列） */}
            <div className="lg:col-span-3">
              <p className="mb-2 flex items-center gap-1.5 text-[13px] font-semibold text-foreground">
                <TrendingUp className="h-4 w-4 text-primary" /> 沪铜/锡/铝/镍/工业硅（连续合约）
              </p>
              <div className="overflow-x-auto">
                <table className="data-table w-full text-[12.5px]">
                  <thead>
                    <tr className="text-left text-[11px] text-muted-foreground/70">
                      <th className="py-2 pr-3 font-medium">品种</th>
                      <th className="py-2 pr-3 text-right font-medium">最新价</th>
                      <th className="py-2 pr-3 text-right font-medium">1日</th>
                      <th className="py-2 pr-3 text-right font-medium">1周</th>
                      <th className="py-2 pr-3 text-right font-medium">1月</th>
                      <th className="py-2 text-right font-medium">用途</th>
                    </tr>
                  </thead>
                  <tbody>
                    {futures.map((f) => (
                      <tr key={f.code} className="border-t border-border/40">
                        <td className="py-2 pr-3 font-medium text-foreground">{f.name}</td>
                        <td className="py-2 pr-3 text-right font-mono">{f.close.toLocaleString()}<span className="ml-0.5 text-[10px] text-muted-foreground/60">{f.unit}</span></td>
                        <td className={cn("py-2 pr-3 text-right font-mono", signColor(f.chg_1d))}>{signPct(f.chg_1d)}</td>
                        <td className={cn("py-2 pr-3 text-right font-mono", signColor(f.chg_1w))}>{signPct(f.chg_1w)}</td>
                        <td className={cn("py-2 pr-3 text-right font-mono", signColor(f.chg_1m))}>{signPct(f.chg_1m)}</td>
                        <td className="py-2 text-right text-[11px] text-muted-foreground">{f.use}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </div>

            {/* DRAM 表（占 2 列） */}
            <div className="lg:col-span-2">
              <p className="mb-2 flex items-center gap-1.5 text-[13px] font-semibold text-foreground">
                <Gem className="h-4 w-4 text-primary" /> DRAM / NAND 现货
              </p>
              <div className="overflow-x-auto">
                <table className="data-table w-full text-[12.5px]">
                  <thead>
                    <tr className="text-left text-[11px] text-muted-foreground/70">
                      <th className="py-2 pr-3 font-medium">品种</th>
                      <th className="py-2 pr-3 text-right font-medium">最新均价</th>
                      <th className="py-2 text-right font-medium">日期</th>
                    </tr>
                  </thead>
                  <tbody>
                    {dram.map((d) => (
                      <tr key={d.key} className="border-t border-border/40">
                        <td className="py-2 pr-3 font-medium text-foreground">{d.key}</td>
                        <td className="py-2 pr-3 text-right font-mono">{d.latest_avg == null ? "—" : num(d.latest_avg)}</td>
                        <td className="py-2 text-right font-mono text-[11px] text-muted-foreground">{d.date ? String(d.date).slice(0, 10) : "—"}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
              {commodity?.dram?.guard && (
                <p className="mt-2 rounded-lg border border-warning/30 bg-warning/5 p-2 text-[11px] leading-relaxed text-muted-foreground">
                  {commodity.dram.guard}
                </p>
              )}
            </div>
          </div>
        )}
      </GlassCard>
    </div>
  );
}
