import { DataImportPage } from "./pages/DataImportPage";
import { NotFoundPage } from "./pages/NotFoundPage";
import { SystemStatusPage } from "./pages/SystemStatusPage";
import { DatasetsPage } from "./pages/DatasetsPage";
import { MarketDataPage } from "./pages/MarketDataPage";
import { BacktestsPage } from "./pages/BacktestsPage";
import { ResearchPage } from "./pages/ResearchPage";

export default function App() {
  if (window.location.pathname === "/") return <SystemStatusPage />;
  if (window.location.pathname === "/data/import") return <DataImportPage />;
  if (window.location.pathname === "/datasets") return <DatasetsPage />;
  if (window.location.pathname === "/market-data") return <MarketDataPage />;
  if (window.location.pathname === "/backtests") return <BacktestsPage />;
  if (window.location.pathname === "/research") return <ResearchPage />;
  return <NotFoundPage />;
}
