import { useEffect, useState } from "react";
import { Link, Outlet, useLocation } from "react-router-dom";
import {
  Activity, Radar, LayoutGrid, Wallet, Settings, Search, NotebookPen,
  Moon, Sun, LineChart, Cog, Cpu, Database, Cable, Rocket,
  FlaskConical, FileText, Swords, Gauge, ListChecks, Newspaper, LayoutDashboard,
  ChevronsLeft, ChevronsRight, ChevronDown, ChevronRight,
} from "lucide-react";
import { cn } from "@/lib/utils";
import { useDarkMode } from "@/hooks/useDarkMode";
import { storageGet, storageSet } from "@/lib/storage";

// 导航分组：研究 / 我的 / 系统（a股监控板 + 统一交易晨报已并入「市场总览」）
const NAV_GROUPS: { label: string; items: { to: string; icon: typeof Gauge; label: string }[] }[] = [
  {
    label: "研究",
    items: [
      { to: "/market-overview", icon: LayoutDashboard, label: "市场总览" },
      { to: "/intel", icon: Radar, label: "资讯雷达" },
      { to: "/sectors", icon: LayoutGrid, label: "板块中心" },
    ],
  },
  {
    label: "我的",
    items: [
      { to: "/stock-pool", icon: ListChecks, label: "自选股" },
      { to: "/stock-data", icon: Search, label: "个股分析" },
      { to: "/portfolio", icon: Wallet, label: "我的持仓" },
      { to: "/my-reports", icon: FileText, label: "我的研报" },
      { to: "/notes", icon: NotebookPen, label: "研究记录" },
    ],
  },
  {
    label: "系统",
    items: [{ to: "/settings", icon: Settings, label: "接入 AI" }],
  },
];

// 常看的板块，作为「板块中心」下的快捷入口（缩进显示）。
const SECTOR_LINKS = [
  { to: "/sectors/humanoid", icon: Cog, label: "人形机器人" },
  { to: "/sectors/ai-computing", icon: Cpu, label: "AI 算力" },
  { to: "/sectors/hbm", icon: Database, label: "HBM" },
  { to: "/sectors/cpo", icon: Cable, label: "光互联" },
  { to: "/sectors/business-space", icon: Rocket, label: "商业航天" },
  { to: "/sectors/ai-pharma", icon: FlaskConical, label: "生物医药" },
];

export function Layout() {
  const { pathname } = useLocation();
  const { dark, toggle } = useDarkMode();
  const [collapsed, setCollapsed] = useState(() => storageGet("vr-sidebar") === "collapsed");
  // 板块中心下的快捷入口是否展开（持久化）
  const [sectorOpen, setSectorOpen] = useState(() => storageGet("vr-sector-open") !== "0");

  useEffect(() => {
    storageSet("vr-sidebar", collapsed ? "collapsed" : "expanded");
  }, [collapsed]);
  useEffect(() => {
    storageSet("vr-sector-open", sectorOpen ? "1" : "0");
  }, [sectorOpen]);

  return (
    <div className="flex h-screen">
      {/* Sidebar */}
      <aside className={cn(
        "glass z-10 m-2 flex shrink-0 flex-col rounded-2xl transition-all duration-200",
        collapsed ? "w-14" : "w-60",
      )}>
        {/* Brand */}
        <div className={cn("border-b border-border/50", collapsed ? "flex justify-center p-3" : "px-4 pb-3 pt-4")}>
          <Link to="/market-overview" className={cn("flex items-center", collapsed ? "justify-center" : "gap-2.5")}>
            <span className="flex h-8 w-8 shrink-0 items-center justify-center rounded-xl bg-gradient-to-br from-primary to-accent shadow-glow">
              <LineChart className="h-[18px] w-[18px] text-white" strokeWidth={2.4} />
            </span>
            {!collapsed && (
              <span className="font-serif text-[17px] font-bold tracking-wide">
                Vibe-<span className="bg-gradient-to-r from-accent to-primary bg-clip-text text-transparent">Research</span>
              </span>
            )}
          </Link>
        </div>

        {/* Nav */}
        <nav className={cn("flex-1 overflow-auto", collapsed ? "space-y-1 p-1.5" : "space-y-3 px-2.5 py-2")}>
          {NAV_GROUPS.map((group) => (
            <div key={group.label}>
              {!collapsed && (
                <p className="mb-1 px-2.5 text-[10px] font-semibold uppercase tracking-[0.14em] text-muted-foreground/50">
                  {group.label}
                </p>
              )}
              <div className="space-y-0.5">
                {group.items.map(({ to, icon: Icon, label }) => {
                  const active = pathname === to;
                  return (
                    <div key={to}>
                      {to === "/sectors" ? (
                        <div className="flex items-center">
                          <Link
                            to={to}
                            title={collapsed ? label : undefined}
                            className={cn(
                              "relative flex flex-1 items-center rounded-lg text-[13.5px] transition-all duration-150",
                              collapsed ? "justify-center p-2.5" : "gap-2.5 px-2.5 py-2",
                              active
                                ? "bg-primary/12 font-semibold text-primary"
                                : "text-muted-foreground hover:bg-muted/60 hover:text-foreground",
                            )}
                          >
                            {active && !collapsed && (
                              <span className="absolute left-0 top-1/2 h-4 w-[3px] -translate-y-1/2 rounded-full bg-gradient-to-b from-primary to-accent" />
                            )}
                            <Icon className={cn("shrink-0", collapsed ? "h-4 w-4" : "h-[15px] w-[15px]", active && "drop-shadow-[0_0_6px_hsl(var(--primary)/0.5)]")} />
                            {!collapsed && label}
                          </Link>
                          {!collapsed && (
                            <button
                              onClick={() => setSectorOpen((o) => !o)}
                              className="mr-1 rounded p-1 text-muted-foreground/60 hover:bg-muted/60 hover:text-foreground"
                              title={sectorOpen ? "收起板块快捷入口" : "展开板块快捷入口"}
                            >
                              {sectorOpen ? <ChevronDown className="h-3.5 w-3.5" /> : <ChevronRight className="h-3.5 w-3.5" />}
                            </button>
                          )}
                        </div>
                      ) : (
                        <Link
                          to={to}
                          title={collapsed ? label : undefined}
                          className={cn(
                            "relative flex items-center rounded-lg text-[13.5px] transition-all duration-150",
                            collapsed ? "justify-center p-2.5" : "gap-2.5 px-2.5 py-2",
                            active
                              ? "bg-primary/12 font-semibold text-primary"
                              : "text-muted-foreground hover:bg-muted/60 hover:text-foreground",
                          )}
                        >
                          {active && !collapsed && (
                            <span className="absolute left-0 top-1/2 h-4 w-[3px] -translate-y-1/2 rounded-full bg-gradient-to-b from-primary to-accent" />
                          )}
                          <Icon className={cn("shrink-0", collapsed ? "h-4 w-4" : "h-[15px] w-[15px]", active && "drop-shadow-[0_0_6px_hsl(var(--primary)/0.5)]")} />
                          {!collapsed && label}
                        </Link>
                      )}

                      {/* 板块中心下方：常看板块的快捷入口（缩进，可折叠） */}
                      {to === "/sectors" && sectorOpen && (
                        <div className={cn("mt-0.5 space-y-0.5", !collapsed && "ml-[15px] border-l border-border/50 pl-2")}>
                          {SECTOR_LINKS.map(({ to: st, icon: SIcon, label: slabel }) => {
                            const sactive = pathname === st;
                            return (
                              <Link
                                key={st}
                                to={st}
                                title={collapsed ? slabel : undefined}
                                className={cn(
                                  "flex items-center rounded-lg transition-colors",
                                  collapsed ? "justify-center p-2" : "gap-2 px-2 py-1.5 text-[12.5px]",
                                  sactive
                                    ? "bg-primary/10 font-semibold text-primary"
                                    : "text-muted-foreground/75 hover:bg-muted/50 hover:text-foreground",
                                )}
                              >
                                <SIcon className="h-3.5 w-3.5 shrink-0" />
                                {!collapsed && slabel}
                              </Link>
                            );
                          })}
                        </div>
                      )}
                    </div>
                  );
                })}
              </div>
            </div>
          ))}
        </nav>

        {/* Footer —— 主题切换 + 侧栏折叠 */}
        <div className={cn("flex items-center border-t border-border/50", collapsed ? "flex-col gap-1 p-2" : "justify-between p-2.5")}>
          <button
            onClick={toggle}
            className={cn(
              "rounded-lg text-muted-foreground transition-colors hover:bg-muted/60 hover:text-foreground",
              collapsed ? "p-2" : "flex items-center gap-2 px-2.5 py-1.5 text-xs",
            )}
            title={dark ? "亮色" : "暗色"}
          >
            {dark ? <Sun className="h-4 w-4" /> : <Moon className="h-4 w-4" />}
            {!collapsed && (dark ? "切换到亮色" : "切换到暗色")}
          </button>
          <button
            onClick={() => setCollapsed(!collapsed)}
            className="rounded-lg p-2 text-muted-foreground transition-colors hover:bg-muted/60 hover:text-foreground"
            title={collapsed ? "展开侧栏" : "折叠侧栏"}
          >
            {collapsed ? <ChevronsRight className="h-4 w-4" /> : <ChevronsLeft className="h-4 w-4" />}
          </button>
        </div>
      </aside>

      {/* Main */}
      <main className="flex-1 overflow-auto">
        <div className="mx-auto w-full max-w-[1700px] px-4 py-5">
          <Outlet />
        </div>
      </main>
    </div>
  );
}
