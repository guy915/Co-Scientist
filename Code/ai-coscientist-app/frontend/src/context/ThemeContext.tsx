import React, { createContext, useContext, useEffect, useState } from "react";
import { getTheme, applyTheme, themes } from "@/themes/themes";
import { useDomain } from "./DomainContext";

interface ThemeContextValue {
  currentTheme: string;
  isDark: boolean;
  availableThemes: string[];
  setTheme: (themeId: string) => void;
  cycleTheme: () => void;
}

const ThemeContext = createContext<ThemeContextValue | undefined>(undefined);

const THEME_STORAGE_KEY = "coscientist-theme";

export function ThemeProvider({ children }: { children: React.ReactNode }) {
  const { config } = useDomain();

  const availableThemes = config.availableThemes || ["light", "dark", "navy", "business", "ocean"];
  const defaultTheme = config.defaultTheme || availableThemes[0] || "light";

  const [currentTheme, setCurrentThemeState] = useState<string>(() => {
    const stored = localStorage.getItem(THEME_STORAGE_KEY);
    if (stored && availableThemes.includes(stored)) {
      return stored;
    }
    return defaultTheme;
  });

  const theme = getTheme(currentTheme);
  const isDark = theme.isDark;

  useEffect(() => {
    applyTheme(theme);
  }, [theme]);

  const setTheme = (themeId: string) => {
    if (availableThemes.includes(themeId)) {
      setCurrentThemeState(themeId);
      localStorage.setItem(THEME_STORAGE_KEY, themeId);
    }
  };

  const cycleTheme = () => {
    const currentIndex = availableThemes.indexOf(currentTheme);
    const nextIndex = (currentIndex + 1) % availableThemes.length;
    const nextTheme = availableThemes[nextIndex];
    setTheme(nextTheme);
  };

  return (
    <ThemeContext.Provider
      value={{
        currentTheme,
        isDark,
        availableThemes,
        setTheme,
        cycleTheme,
      }}
    >
      {children}
    </ThemeContext.Provider>
  );
}

export function useTheme() {
  const context = useContext(ThemeContext);
  if (!context) {
    throw new Error("useTheme must be used within ThemeProvider");
  }
  return context;
}
