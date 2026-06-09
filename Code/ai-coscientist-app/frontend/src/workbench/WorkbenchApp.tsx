import { Route, Routes } from "react-router-dom";
import { ErrorBoundary } from "@/components/ErrorBoundary";
import { ThemeProvider } from "./ThemeContext";
import { Dashboard } from "./pages/Dashboard";
import { NewRun } from "./pages/NewRun";
import { RunDetail } from "./pages/RunDetail";
import { Layout } from "./Layout";
import { useGlobalShortcuts } from "./hooks/useGlobalShortcuts";

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
