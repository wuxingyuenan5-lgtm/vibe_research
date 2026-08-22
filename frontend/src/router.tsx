import { createBrowserRouter, Navigate } from "react-router-dom";
import { Layout } from "@/components/layout/Layout";
import { MarketOverview } from "@/pages/MarketOverview";
import { AStockMonitor } from "@/pages/AStockMonitor";
import { StockPool } from "@/pages/StockPool";
import { MorningBrief } from "@/pages/MorningBrief";
import { Intel } from "@/pages/Intel";
import { Sectors } from "@/pages/Sectors";
import { SectorDetail } from "@/pages/SectorDetail";
import { Debate } from "@/pages/Debate";
import { Portfolio } from "@/pages/Portfolio";
import { StockData } from "@/pages/StockData";
import { MyReports } from "@/pages/MyReports";
import { Notes } from "@/pages/Notes";
import { Settings } from "@/pages/Settings";

export const router = createBrowserRouter([
  {
    element: <Layout />,
    children: [
      { path: "/", element: <Navigate to="/market-overview" replace /> },
      { path: "/market-overview", element: <MarketOverview /> },
      { path: "/a-stock-monitor", element: <AStockMonitor /> },
      { path: "/stock-pool", element: <StockPool /> },
      { path: "/watchlist", element: <Navigate to="/stock-pool" replace /> },
      { path: "/morning-brief", element: <MorningBrief /> },
      { path: "/intel", element: <Intel /> },
      { path: "/sectors", element: <Sectors /> },
      { path: "/sectors/:key", element: <SectorDetail /> },
      { path: "/portfolio", element: <Portfolio /> },
      { path: "/stock-data", element: <StockData /> },
      { path: "/debate", element: <Debate /> },
      { path: "/my-reports", element: <MyReports /> },
      { path: "/notes", element: <Notes /> },
      { path: "/settings", element: <Settings /> },
    ],
  },
  // 嵌入模式（自选股弹窗 iframe 用）：无侧边栏/顶栏，仅个股数据内容
  { path: "/stock-data-embed", element: <StockData embed /> },
]);
