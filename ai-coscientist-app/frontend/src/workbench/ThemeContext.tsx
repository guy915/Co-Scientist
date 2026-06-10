import { createContext, type ReactNode, useContext, useEffect, useState } from "react";
import { applyMd3Theme } from "../lib/theme";

type Mode = "light" | "dark";

interface ThemeContextValue {
  mode: Mode;
  setMode: (m: Mode) => void;
  toggle: () => void;
}

const ThemeContext = createContext<ThemeContextValue | null>(null);

const KEY = "coscientist:theme";

export function ThemeProvider({ children }: { children: ReactNode }) {
  const [mode, setModeState] = useState<Mode>(() => {
    if (typeof window === "undefined") return "light";
    const saved = window.localStorage.getItem(KEY) as Mode | null;
    const resolved =
      saved === "light" || saved === "dark"
        ? saved
        : window.matchMedia("(prefers-color-scheme: dark)").matches
          ? "dark"
          : "light";
    // Apply synchronously to prevent FOUC
    applyMd3Theme(resolved === "dark");
    document.documentElement.dataset.theme = resolved;
    document.documentElement.classList.toggle("dark", resolved === "dark");
    return resolved;
  });

  useEffect(() => {
    applyMd3Theme(mode === "dark");
    document.documentElement.dataset.theme = mode;
    document.documentElement.classList.toggle("dark", mode === "dark");
    window.localStorage.setItem(KEY, mode);
  }, [mode]);

  return (
    <ThemeContext.Provider
      value={{
        mode,
        setMode: setModeState,
        toggle: () => setModeState((m) => (m === "light" ? "dark" : "light")),
      }}
    >
      {children}
    </ThemeContext.Provider>
  );
}

export function useTheme(): ThemeContextValue {
  const ctx = useContext(ThemeContext);
  if (!ctx) throw new Error("useTheme used outside ThemeProvider");
  return ctx;
}
