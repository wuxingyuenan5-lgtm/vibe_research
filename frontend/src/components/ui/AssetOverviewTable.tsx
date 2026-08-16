/**
 * 海内外大类资产总览（合并 view · 实时 + 晨报）
 * - 国内/香港指数：实时数据（api.indices / api.globalIndices，5 分钟缓存）
 * - 海外/商品/汇率/国债：晨报 asset_overview（每日生成）
 * - 点击行 → 弹模态框看 K 线（有 code 的指数）；无 code 友好提示
 */
import { useState } from "react";
import { X, AlertCircle } from "lucide-react";
import { GlassCard } from "@/components/ui/GlassCard";
import { KlineChart } from "@/components/ui/KlineChart";
import { cn } from "@/lib/utils";

export interface AssetRow {
  market: string;    // 国内 / 海外 / 香港 / 商品
  asset: string;
  value: string;
  change: string;
  cls: string;       // up / down / flat
  source: "实时" | "晨报";
  meaning?: string;
  code?: string;     // K 线代码（带前缀 sh000001 / hkHSI 等）
  kMarket?: "A" | "HK" | "US";
}

// 晨报资产 → K 线代码（实时行由 MarketOverview 直接带 code）
// - A/H 股票指数：腾讯源（裸 code，如 sh000001）
// - 海外/商品/汇率/国债：Yahoo v8 chart（code 加 "y:" 前缀；后端识别后走 yahoo）
// - 中证商品期货指数 / 中国10Y国债活跃券 / 锂：yahoo 无数据，保持 null
export const BRIEF_CODE_MAP: Record<string, { code: string; market: "A" | "HK" | "US" } | null> = {
  "上证综指": { code: "sh000001", market: "A" },
  "沪深300": { code: "sh000300", market: "A" },
  "创业板指": { code: "sz399006", market: "A" },
  "中证1000": { code: "sh000852", market: "A" },
  "上证50": { code: "sh000016", market: "A" },
  "科创50": { code: "sh000688", market: "A" },
  "恒生指数": { code: "hkHSI", market: "HK" },
  "恒生科技": { code: "hkHSTECH", market: "HK" },
  // Yahoo v8 覆盖的 11 个：美股指数 3 + 外汇 + DXY 期货 + 商品期货 5 + 美国10Y国债收益率
  "标普500": { code: "y:^GSPC", market: "US" },
  "纳斯达克综指": { code: "y:^IXIC", market: "US" },
  "道琼斯": { code: "y:^DJI", market: "US" },
  "美国10Y国债": { code: "y:^TNX", market: "US" },            // 收益率指数，单位 %
  "DXY（美元指数）": { code: "y:DX-Y.NYB", market: "US" },     // 美元指数期货
  "USD/CNY": { code: "y:CNY=X", market: "US" },               // 在岸人民币（用户决定保留 CNY 口径）
  "现货黄金": { code: "y:GC=F", market: "US" },
  "白银": { code: "s:AG0", market: "A" },                     // 沪银主力连续（新浪期货，用户点名沪银）
  "铜": { code: "s:CU0", market: "A" },                       // 沪铜主力连续（新浪期货）
  "Brent原油": { code: "y:BZ=F", market: "US" },
  "WTI原油": { code: "y:CL=F", market: "US" },
  // 新浪期货主力连续（国内品种）
  "锂": { code: "s:LC0", market: "A" },                       // 碳酸锂主力连续（新浪期货）
  "中国10Y国债活跃券": { code: "s:T0", market: "A" },         // 国债期货 T 主力（现货收益率无公开 K 线源，用期货替代）
  // 无公开 K 线源
  "中证商品期货价格指数": null,
};

const MARKET_BADGE: Record<string, string> = {
  国内: "bg-danger/10 text-danger",
  香港: "bg-warning/10 text-warning",
  海外: "bg-primary/10 text-primary",
  商品: "bg-muted/40 text-muted-foreground",
};

const MARKET_ORDER: Record<string, number> = { 国内: 0, 海外: 1, 香港: 1, 商品: 2 };

// 数据源 market 字段错位（如黄金/Brent/WTI 被标"海外"），按资产名重映射到正确类别
const MARKET_FIX: Record<string, string> = {
  "现货黄金": "商品", "Brent原油": "商品", "WTI原油": "商品", "中证商品期货价格指数": "商品",
  "美国10Y国债": "海外", "DXY（美元指数）": "海外",  // 货币指标并入海外大类，跟美债一档
  "上证综指": "国内",  // 与 realtime"上证指数"归一
};

// 资产按重要性排序（每类内独立 rank，避免不同类的 rank 冲突）
const ASSET_ORDER: Record<string, Record<string, number>> = {
  国内: { "上证指数": 0, "深证成指": 1, "上证50": 2, "沪深300": 3, "创业板指": 4, "科创50": 5, "中证1000": 6, "中国10Y国债活跃券": 7, "USD/CNY": 8 },
  海外: { "标普500": 0, "纳斯达克": 1, "道琼斯": 2, "美国10Y国债": 3, "DXY（美元指数）": 4 },
  香港: { "恒生指数": 0, "恒生科技": 1 },
  商品: { "中证商品期货价格指数": 0, "现货黄金": 1, "白银": 2, "铜": 3, "锂": 4, "Brent原油": 5, "WTI原油": 6 },
};

export function AssetOverviewTable({ rows }: { rows: AssetRow[] }) {
  const [selected, setSelected] = useState<AssetRow | null>(null);
  // 按 MARKET_FIX 重映射 market；brief 里的"中国"统一归"国内"（避免掉到排序末尾）
  const mapped = rows.map((r) => {
    const m = MARKET_FIX[r.asset] || r.market;
    return { ...r, market: m === "中国" ? "国内" : m };
  });
  const sorted = [...mapped].sort((a, b) => {
    const ma = MARKET_ORDER[a.market] ?? 9, mb = MARKET_ORDER[b.market] ?? 9;
    if (ma !== mb) return ma - mb;
    const ra = ASSET_ORDER[a.market]?.[a.asset] ?? 99, rb = ASSET_ORDER[b.market]?.[b.asset] ?? 99;
    if (ra !== rb) return ra - rb;
    return a.asset.localeCompare(b.asset);
  });

  if (sorted.length === 0) {
    return (
      <GlassCard className="p-4">
        <h3 className="mb-2 flex items-center gap-1.5 text-sm font-semibold">🌐 海内外大类资产总览</h3>
        <p className="text-xs text-muted-foreground/60">暂无资产数据</p>
      </GlassCard>
    );
  }

  return (
    <>
      <GlassCard className="mb-4 p-4">
        <div className="mb-2 flex items-center gap-2">
          <h3 className="flex items-center gap-1.5 text-sm font-semibold">🌐 海内外大类资产总览</h3>
        </div>
        <div className="overflow-x-auto">
          <table className="w-full text-xs">
            <thead>
              <tr className="border-b border-border/60 text-[11px] text-muted-foreground">
                <th className="px-2 py-2 text-left font-medium">市场</th>
                <th className="px-2 py-2 text-left font-medium">资产</th>
                <th className="px-2 py-2 text-right font-medium">最新值</th>
                <th className="px-2 py-2 text-right font-medium">变化</th>
                <th className="px-2 py-2 text-left font-medium">市场含义</th>
                <th className="px-2 py-2 text-center font-medium">K 线</th>
              </tr>
            </thead>
            <tbody>
              {sorted.map((r, i) => (
                <tr
                  key={i}
                  onClick={() => setSelected(r)}
                  className="cursor-pointer border-b border-border/30 transition-colors hover:bg-primary/5"
                >
                  <td className="px-2 py-1.5">
                    <span className={cn("inline-block rounded px-1.5 py-0.5 text-[10px] font-medium", MARKET_BADGE[r.market] || "bg-muted/40 text-muted-foreground")}>
                      {r.market}
                    </span>
                  </td>
                  <td className="px-2 py-1.5 font-medium">{r.asset}</td>
                  <td className="num px-2 py-1.5 text-right font-mono">{r.value}</td>
                  <td className={cn("px-2 py-1.5 text-right font-mono", r.cls === "up" ? "text-danger" : r.cls === "down" ? "text-success" : "text-muted-foreground")}>
                    {r.change}
                  </td>
                  <td className="px-2 py-1.5 text-foreground/90">
                    {r.meaning && <span>{r.meaning}</span>}
                    <span className={cn("ml-1.5 rounded px-1 py-0.5 align-middle text-[9px]", r.source === "实时" ? "bg-success/10 text-success" : "bg-muted/30 text-muted-foreground")}>
                      {r.source}
                    </span>
                  </td>
                  <td className="px-2 py-1.5 text-center text-[11px]">
                    {r.code ? <span className="text-primary">▸ 可看</span> : <span className="text-muted-foreground/40">—</span>}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </GlassCard>

      {selected && <AssetModal row={selected} onClose={() => setSelected(null)} />}
    </>
  );
}

function AssetModal({ row, onClose }: { row: AssetRow; onClose: () => void }) {
  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 p-4 backdrop-blur-sm"
      onClick={onClose}
    >
      <GlassCard className="w-full max-w-5xl p-5" >
        <div onClick={(e) => e.stopPropagation()} className="space-y-3">
          <div className="flex items-baseline gap-2">
            <span className={cn("rounded px-1.5 py-0.5 text-[10px] font-medium", MARKET_BADGE[row.market] || "bg-muted/40 text-muted-foreground")}>
              {row.market}
            </span>
            <h3 className="text-lg font-bold">{row.asset}</h3>
            <span className="font-mono text-lg font-bold">{row.value}</span>
            <span className={cn("font-mono", row.cls === "up" ? "text-danger" : row.cls === "down" ? "text-success" : "text-muted-foreground")}>
              {row.change}
            </span>
            <span className={cn("rounded px-1 py-0.5 text-[10px]", row.source === "实时" ? "bg-success/10 text-success" : "bg-muted/30 text-muted-foreground")}>
              {row.source}
            </span>
            <button onClick={onClose} className="ml-auto rounded-md p-1 text-muted-foreground hover:bg-muted/30 hover:text-foreground" aria-label="关闭">
              <X className="h-4 w-4" />
            </button>
          </div>
          {row.meaning && (
            <p className="rounded-lg bg-primary/5 px-3 py-2 text-xs text-foreground/90">{row.meaning}</p>
          )}
          {row.code ? (
            <KlineChart code={row.code} market={row.kMarket} height={460} />
          ) : (
            <div className="flex items-center gap-2 rounded-lg border border-warning/30 bg-warning/5 p-4 text-sm text-muted-foreground">
              <AlertCircle className="h-4 w-4 shrink-0 text-warning" />
              <span>该资产（{row.asset}）暂无走势图，目前 K 线仅支持股票/股指（腾讯数据源）。商品/外汇/国债等可关注 <a href="https://cn.investing.com" target="_blank" rel="noreferrer" className="text-primary hover:underline">英为财情</a> 等专业行情站。</span>
            </div>
          )}
        </div>
      </GlassCard>
    </div>
  );
}