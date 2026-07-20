import { DataImportPage } from "./pages/DataImportPage";
import { NotFoundPage } from "./pages/NotFoundPage";
import { SystemStatusPage } from "./pages/SystemStatusPage";

export default function App() {
  if (window.location.pathname === "/") return <SystemStatusPage />;
  if (window.location.pathname === "/data/import") return <DataImportPage />;
  return <NotFoundPage />;
}
