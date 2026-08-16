/**
 * 市场面板组件（从每日复盘 DailyReview 抽取，市场总览复用，保证格式 100% 一致）
 * 含：板块资金趋势榜 / 资金轮动 / 全市场成交额榜 / 连板股清单
 */
import { TrendingUp, TrendingDown } from "lucide-react";
import { GlassCard } from "@/components/ui/GlassCard";
import { cn } from "@/lib/utils";
import type { SectorFlow, ShortTermEmotion, TurnoverStock } from "@/lib/api";

const yi = (v: number | null | undefined) => (v == null ? "—" : `${(v / 1e8).toFixed(2)} 亿`);
const pctColor = (v: number | null | undefined) => (v != null && v > 0 ? "text-danger" : v != null && v < 0 ? "text-success" : "text-muted-foreground");
const fmt = (v: number | null | undefined) => (v == null ? "—" : v.toLocaleString("zh-CN", { minimumFractionDigits: 2, maximumFractionDigits: 2 }));

/* ---------- 板块资金趋势榜（行业 · 按今日净流入排序，6 列） ---------- */
export function SectorTrendTable({ sectors, max = 15 }: { sectors: SectorFlow[]; max?: number }) {
  if (sectors.length === 0) return <p className="text-xs text-muted-foreground/60">暂无板块资金数据</p>;
  return (
    <div className="overflow-x-auto">
      <table className="data-table">
        <thead>
          <tr className="border-b border-border/50 text-left text-xs text-muted-foreground">
            {["行业", "涨跌%", "今日净流入", "流入", "流出", "家数"].map((h) => (
              <th key={h} className="whitespace-nowrap px-2 py-2 font-medium">{h}</th>
            ))}
          </tr>
        </thead>
        <tbody>
          {sectors.slice(0, max).map((s) => (
            <tr key={s.name} className="border-b border-border/30">
              <td className="px-2 py-2 font-medium">{s.name}</td>
              <td className={cn("px-2 py-2 font-mono", pctColor(s.pct))}>{s.pct > 0 ? "+" : ""}{s.pct}%</td>
              <td className={cn("px-2 py-2 font-mono", pctColor(s.net))}>{s.net > 0 ? "+" : ""}{s.net} 亿</td>
              <td className="px-2 py-2 font-mono text-muted-foreground">{s.inflow} 亿</td>
              <td className="px-2 py-2 font-mono text-muted-foreground">{s.outflow} 亿</td>
              <td className="px-2 py-2 font-mono text-muted-foreground">{s.firms}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

/* ---------- 资金轮动（流入 Top + 流出 Top 双列，与每日复盘逐字一致） ---------- */
export function FundRotation({ sectors }: { sectors: SectorFlow[] }) {
  if (sectors.length === 0) return <p className="text-xs text-muted-foreground/60">暂无板块资金数据</p>;
  return (
    <div className="grid gap-4 md:grid-cols-2">
      {[
        { title: "流入 Top", icon: TrendingUp, color: "text-danger", rows: sectors.slice(0, 6) },
        { title: "流出 Top", icon: TrendingDown, color: "text-success", rows: [...sectors].slice(-6).reverse() },
      ].map((col) => (
        <GlassCard key={col.title}>
          <h4 className={cn("mb-3 flex items-center gap-1.5 text-sm font-semibold", col.color)}><col.icon className="h-4 w-4" /> {col.title}</h4>
          {col.rows.length === 0 ? (
            <p className="text-xs text-muted-foreground/60">加载中…</p>
          ) : (
            <div className="space-y-1.5">
              {col.rows.map((s, i) => (
                <div key={s.name} className="flex items-center gap-3 border-b border-border/30 pb-1.5 text-sm last:border-0">
                  <span className="w-5 text-xs text-muted-foreground/50">{i + 1}</span>
                  <span className="flex-1 truncate">{s.name}</span>
                  <span className={cn("font-mono text-xs", pctColor(s.pct))}>{s.pct > 0 ? "+" : ""}{s.pct}%</span>
                  <span className={cn("w-20 text-right font-mono text-xs", pctColor(s.net))}>{s.net > 0 ? "+" : ""}{fmt(s.net)} 亿</span>
                </div>
              ))}
            </div>
          )}
        </GlassCard>
      ))}
    </div>
  );
}

/* ---------- 全市场成交额榜（# / 名称 / 现价 / 涨跌% / 成交额 / 总市值 / 行业） ---------- */
export function TurnoverTopTable({ stocks, topN, onTopN }: { stocks: TurnoverStock[]; topN: 10 | 20; onTopN: (n: 10 | 20) => void }) {
  if (stocks.length === 0) return <p className="text-xs text-muted-foreground/60">暂无成交额榜数据</p>;
  return (
    <div className="overflow-x-auto">
      <table className="data-table">
        <thead>
          <tr className="border-b border-border/50 text-left text-xs text-muted-foreground">
            {["#", "名称", "现价", "涨跌%", "成交额", "总市值", "行业"].map((h) => (
              <th key={h} className="whitespace-nowrap px-2 py-2 font-medium">{h}</th>
            ))}
          </tr>
        </thead>
        <tbody>
          {stocks.slice(0, topN).map((s, i) => (
            <tr key={s.code} className="border-b border-border/30">
              <td className="px-2 py-2 font-mono text-xs text-muted-foreground/50">{i + 1}</td>
              <td className="px-2 py-2"><span className="font-medium">{s.name}</span> <span className="text-xs text-muted-foreground/50">{s.code}</span></td>
              <td className="px-2 py-2 font-mono">{s.price ?? "—"}</td>
              <td className={cn("px-2 py-2 font-mono", s.pct == null ? "text-muted-foreground" : pctColor(s.pct))}>
                {s.pct == null ? "—" : `${s.pct > 0 ? "+" : ""}${s.pct}%`}
              </td>
              <td className="whitespace-nowrap px-2 py-2 font-mono">{yi(s.amount)}</td>
              <td className="whitespace-nowrap px-2 py-2 font-mono text-muted-foreground">{yi(s.mcap)}</td>
              <td className="whitespace-nowrap px-2 py-2 text-xs text-muted-foreground">{s.industry}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

/* ---------- 连板股清单（2 板以上 · 客观公开榜单） ---------- */
export function LianbanTable({ emotion }: { emotion: ShortTermEmotion | null }) {
  const stocks = emotion?.lianban_stocks || [];
  if (stocks.length === 0) return <p className="text-xs text-muted-foreground/50">今日无 2 板以上个股</p>;
  return (
    <div className="overflow-x-auto">
      <table className="data-table">
        <thead>
          <tr className="border-b border-border/50 text-left text-xs text-muted-foreground">
            {["名称", "连板", "现价", "涨停%", "成交额", "流通市值", "概念"].map((h) => (
              <th key={h} className="whitespace-nowrap px-2 py-2 font-medium">{h}</th>
            ))}
          </tr>
        </thead>
        <tbody>
          {stocks.map((s) => (
            <tr key={s.code} className="border-b border-border/30">
              <td className="px-2 py-2"><span className="font-medium">{s.name}</span> <span className="text-xs text-muted-foreground/50">{s.code}</span></td>
              <td className="whitespace-nowrap px-2 py-2 font-mono font-bold text-primary">{s.boards} 板</td>
              <td className="px-2 py-2 font-mono">{s.price}</td>
              <td className="px-2 py-2 font-mono text-danger">+{s.pct}%</td>
              <td className="whitespace-nowrap px-2 py-2 font-mono text-muted-foreground">{yi(s.amount)}</td>
              <td className="whitespace-nowrap px-2 py-2 font-mono text-muted-foreground">{yi(s.float_cap)}</td>
              <td className="whitespace-nowrap px-2 py-2 text-xs text-muted-foreground">{s.industry}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

/* ---------- 短线情绪卡（关键计数 + 打板比率 + 连板股清单） ---------- */
export function ShortTermEmotionCard({ emotion }: { emotion: ShortTermEmotion | null }) {
  if (!emotion || emotion.zt_count === undefined) {
    return <p className="text-xs text-muted-foreground/60">加载中…</p>;
  }
  return (
    <div>
      {/* 关键计数 */}
      <div className="grid grid-cols-2 gap-2 sm:grid-cols-4">
        {[
          { k: "涨停", v: `${emotion.zt_count}`, cls: "text-danger" },
          { k: "跌停", v: `${emotion.dt_count}`, cls: "text-success" },
          { k: "最高连板", v: `${emotion.max_boards} 板`, cls: "text-primary" },
          { k: "连板（2板+）", v: `${emotion.lianban_count} 家`, cls: "text-primary" },
        ].map((c) => (
          <div key={c.k} className="rounded-lg bg-muted/25 p-3 text-center">
            <p className="text-[11px] text-muted-foreground">{c.k}</p>
            <p className={cn("mt-0.5 font-mono text-xl font-bold", c.cls)}>{c.v}</p>
          </div>
        ))}
      </div>
      {/* 打板情绪比率 */}
      <div className="mt-2 grid grid-cols-3 gap-2">
        {[
          { k: "封板率", v: emotion.seal_rate, hint: "封住 / 尝试涨停", strong: true },
          { k: "炸板率", v: emotion.break_rate, hint: "炸板 / 尝试涨停", strong: false },
          { k: "晋级率", v: emotion.promotion_rate, hint: "昨涨停今又停", strong: true },
        ].map((c) => (
          <div key={c.k} className="rounded-lg bg-muted/20 p-2.5 text-center">
            <p className="text-[11px] text-muted-foreground">{c.k}</p>
            <p className={cn("mt-0.5 font-mono text-sm font-bold", c.strong ? "text-danger" : "text-success")}>
              {c.v == null ? "—" : `${(c.v * 100).toFixed(1)}%`}
            </p>
            <p className="mt-0.5 text-[10px] text-muted-foreground/50">{c.hint}</p>
          </div>
        ))}
      </div>
      {/* 连板股清单 */}
      <div className="mt-3">
        <p className="mb-1.5 text-[11px] text-muted-foreground">连板股（2 板以上连续涨停）· 客观公开榜单，非推荐 / 非预测</p>
        <LianbanTable emotion={emotion} />
      </div>
    </div>
  );
}

export { GlassCard };

/* ---------- 百亿成交·行业分布（行业 × 日期计数 + 历史累计） ---------- */
export function HotStockMatrixTable({ matrix }: { matrix: { dates: string[]; rows: { industry: string; counts: number[]; history_total: number }[] } | null }) {
  if (!matrix || matrix.rows.length === 0) return <p className="text-xs text-muted-foreground/60">暂无百亿成交数据</p>;
  return (
    <div className="overflow-x-auto">
      <table className="data-table">
        <thead>
          <tr className="border-b border-border/50 text-left text-xs text-muted-foreground">
            <th className="whitespace-nowrap px-2 py-2 font-medium">行业</th>
            {matrix.dates.map((d) => (
              <th key={d} className="whitespace-nowrap px-2 py-2 text-center font-medium">{d.slice(5)}</th>
            ))}
            <th className="whitespace-nowrap px-2 py-2 text-right font-medium">历史累计</th>
          </tr>
        </thead>
        <tbody>
          {matrix.rows.map((row) => (
            <tr key={row.industry} className="border-b border-border/30">
              <td className="px-2 py-2 font-medium">{row.industry}</td>
              {row.counts.map((c, i) => (
                <td key={i} className="px-2 py-2 text-center font-mono text-xs">{c || ""}</td>
              ))}
              <td className="px-2 py-2 text-right font-mono">{row.history_total}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}