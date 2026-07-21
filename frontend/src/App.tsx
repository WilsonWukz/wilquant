import { DataImportPage } from "./pages/DataImportPage";
import { NotFoundPage } from "./pages/NotFoundPage";
import { SystemStatusPage } from "./pages/SystemStatusPage";
import { DatasetsPage } from "./pages/DatasetsPage";

export default function App() {
  if (window.location.pathname === "/") return <SystemStatusPage />;
  if (window.location.pathname === "/data/import") return <DataImportPage />;
  if (window.location.pathname === "/datasets") return <DatasetsPage />;
  return <NotFoundPage />;
}
