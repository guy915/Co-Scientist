import { Route, Routes } from "react-router-dom";
import { ErrorBoundary } from "@/components/ErrorBoundary";
import { useGlobalShortcuts } from "./hooks/useGlobalShortcuts";
import { Layout } from "./Layout";
import { Dashboard } from "./pages/Dashboard";
import { NewRun } from "./pages/NewRun";
import { RunDetail } from "./pages/RunDetail";
import { ThemeProvider } from "./ThemeContext";

function ShortcutsBridge() {
  useGlobalShortcuts();
  return null;
}

export function WorkbenchApp() {
  return (
    <ErrorBoundary>
      <ThemeProvider>
        <Layout>
          <ShortcutsBridge />
          <Routes>
            <Route path="/" element={<Dashboard />} />
            <Route path="/runs/new" element={<NewRun />} />
            <Route path="/runs/:id" element={<RunDetail />} />
            <Route path="/runs/:id/:tab" element={<RunDetail />} />
          </Routes>
        </Layout>
      </ThemeProvider>
    </ErrorBoundary>
  );
}
