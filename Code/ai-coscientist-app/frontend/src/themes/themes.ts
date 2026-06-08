export interface Theme {
  id: string;
  name: string;
  description: string;
  isDark: boolean;
  colors: {
    bg: string;
    fg: string;
    card: string;
    cardFg: string;
    popover: string;
    popoverFg: string;
    primary: string;
    primaryFg: string;
    secondary: string;
    secondaryFg: string;
    muted: string;
    mutedFg: string;
    accent: string;
    accentFg: string;
    destructive: string;
    destructiveFg: string;
    border: string;
    input: string;
    ring: string;
    success: string;
    successFg: string;
    warning: string;
    warningFg: string;
    info: string;
    infoFg: string;
    link: string;
    linkHover: string;
    phase0: string;
    phase1: string;
    phase2: string;
    phase3: string;
    phase4: string;
  };
}

export const themes: Record<string, Theme> = {
  // clean neutral theme - matches original pre-theming colors
  light: {
    id: "light",
    name: "Light",
    description: "clean, neutral light theme",
    isDark: false,
    colors: {
      bg: "hsl(0 0% 100%)",
      fg: "hsl(0 0% 3.9%)",
      card: "hsl(0 0% 100%)",
      cardFg: "hsl(0 0% 3.9%)",
      popover: "hsl(0 0% 100%)",
      popoverFg: "hsl(0 0% 3.9%)",
      primary: "hsl(0 0% 9%)",
      primaryFg: "hsl(0 0% 98%)",
      secondary: "hsl(0 0% 96.1%)",
      secondaryFg: "hsl(0 0% 9%)",
      muted: "hsl(0 0% 96.1%)",
      mutedFg: "hsl(0 0% 45.1%)",
      accent: "hsl(0 0% 96.1%)",
      accentFg: "hsl(0 0% 9%)",
      destructive: "hsl(0 84.2% 60.2%)",
      destructiveFg: "hsl(0 0% 98%)",
      border: "hsl(0 0% 89.8%)",
      input: "hsl(0 0% 89.8%)",
      ring: "hsl(0 0% 3.9%)",
      success: "hsl(142 71% 45%)",
      successFg: "hsl(0 0% 100%)",
      warning: "hsl(38 92% 50%)",
      warningFg: "hsl(0 0% 100%)",
      info: "hsl(199 89% 48%)",
      infoFg: "hsl(0 0% 100%)",
      link: "hsl(221 83% 53%)",
      linkHover: "hsl(221 83% 43%)",
      phase0: "hsl(142 71% 45%)",
      phase1: "hsl(271 69% 55%)",
      phase2: "hsl(32 95% 50%)",
      phase3: "hsl(0 72% 51%)",
      phase4: "hsl(248 53% 58%)",
    },
  },
  // dark mode - high contrast, easy on eyes
  dark: {
    id: "dark",
    name: "Dark",
    description: "dark mode theme",
    isDark: true,
    colors: {
      bg: "hsl(224 71% 4%)",
      fg: "hsl(213 31% 91%)",
      card: "hsl(224 40% 8%)",
      cardFg: "hsl(213 31% 91%)",
      popover: "hsl(224 40% 8%)",
      popoverFg: "hsl(213 31% 91%)",
      primary: "hsl(210 100% 66%)",
      primaryFg: "hsl(220 9% 10%)",
      secondary: "hsl(223 47% 16%)",
      secondaryFg: "hsl(213 31% 91%)",
      muted: "hsl(223 47% 14%)",
      mutedFg: "hsl(215 20% 55%)",
      accent: "hsl(223 47% 20%)",
      accentFg: "hsl(213 31% 91%)",
      destructive: "hsl(0 63% 55%)",
      destructiveFg: "hsl(0 0% 100%)",
      border: "hsl(223 35% 20%)",
      input: "hsl(223 35% 20%)",
      ring: "hsl(210 100% 66%)",
      success: "hsl(142 71% 50%)",
      successFg: "hsl(0 0% 100%)",
      warning: "hsl(38 92% 55%)",
      warningFg: "hsl(0 0% 10%)",
      info: "hsl(199 89% 55%)",
      infoFg: "hsl(0 0% 10%)",
      link: "hsl(210 100% 66%)",
      linkHover: "hsl(210 100% 76%)",
      phase0: "hsl(142 50% 35%)",
      phase1: "hsl(271 45% 45%)",
      phase2: "hsl(32 70% 40%)",
      phase3: "hsl(0 55% 42%)",
      phase4: "hsl(248 40% 48%)",
    },
  },
  // navy - military operations, deep blue with gold accents
  navy: {
    id: "navy",
    name: "Navy",
    description: "us navy operational theme",
    isDark: false,
    colors: {
      bg: "hsl(220 30% 96%)",
      fg: "hsl(220 40% 13%)",
      card: "hsl(0 0% 100%)",
      cardFg: "hsl(220 40% 13%)",
      popover: "hsl(0 0% 100%)",
      popoverFg: "hsl(220 40% 13%)",
      primary: "hsl(220 70% 25%)",
      primaryFg: "hsl(0 0% 100%)",
      secondary: "hsl(220 25% 90%)",
      secondaryFg: "hsl(220 40% 20%)",
      muted: "hsl(220 20% 94%)",
      mutedFg: "hsl(220 15% 45%)",
      accent: "hsl(45 93% 47%)",
      accentFg: "hsl(220 40% 13%)",
      destructive: "hsl(0 72% 51%)",
      destructiveFg: "hsl(0 0% 100%)",
      border: "hsl(220 20% 85%)",
      input: "hsl(220 20% 85%)",
      ring: "hsl(220 70% 25%)",
      success: "hsl(160 60% 40%)",
      successFg: "hsl(0 0% 100%)",
      warning: "hsl(45 93% 47%)",
      warningFg: "hsl(220 40% 13%)",
      info: "hsl(220 70% 45%)",
      infoFg: "hsl(0 0% 100%)",
      link: "hsl(220 70% 35%)",
      linkHover: "hsl(220 70% 25%)",
      phase0: "hsl(160 60% 40%)",
      phase1: "hsl(220 70% 35%)",
      phase2: "hsl(45 80% 45%)",
      phase3: "hsl(0 60% 45%)",
      phase4: "hsl(248 50% 50%)",
    },
  },
  // business - modern corporate, high contrast, professional blues and greens
  business: {
    id: "business",
    name: "Business",
    description: "modern corporate business theme",
    isDark: false,
    colors: {
      bg: "hsl(210 20% 98%)",
      fg: "hsl(210 40% 12%)",
      card: "hsl(0 0% 100%)",
      cardFg: "hsl(210 40% 12%)",
      popover: "hsl(0 0% 100%)",
      popoverFg: "hsl(210 40% 12%)",
      primary: "hsl(210 100% 40%)",
      primaryFg: "hsl(0 0% 100%)",
      secondary: "hsl(210 20% 93%)",
      secondaryFg: "hsl(210 40% 20%)",
      muted: "hsl(210 15% 95%)",
      mutedFg: "hsl(210 15% 45%)",
      accent: "hsl(160 84% 39%)",
      accentFg: "hsl(0 0% 100%)",
      destructive: "hsl(0 72% 51%)",
      destructiveFg: "hsl(0 0% 100%)",
      border: "hsl(210 18% 87%)",
      input: "hsl(210 18% 87%)",
      ring: "hsl(210 100% 40%)",
      success: "hsl(160 84% 39%)",
      successFg: "hsl(0 0% 100%)",
      warning: "hsl(38 92% 50%)",
      warningFg: "hsl(0 0% 100%)",
      info: "hsl(210 100% 50%)",
      infoFg: "hsl(0 0% 100%)",
      link: "hsl(210 100% 40%)",
      linkHover: "hsl(210 100% 30%)",
      phase0: "hsl(160 70% 42%)",
      phase1: "hsl(210 90% 45%)",
      phase2: "hsl(38 85% 50%)",
      phase3: "hsl(0 65% 50%)",
      phase4: "hsl(248 55% 55%)",
    },
  },
  // ocean - calm teal and slate, subtle and professional
  ocean: {
    id: "ocean",
    name: "Ocean",
    description: "calm ocean teal theme",
    isDark: false,
    colors: {
      bg: "hsl(195 20% 97%)",
      fg: "hsl(200 30% 15%)",
      card: "hsl(0 0% 100%)",
      cardFg: "hsl(200 30% 15%)",
      popover: "hsl(0 0% 100%)",
      popoverFg: "hsl(200 30% 15%)",
      primary: "hsl(185 70% 38%)",
      primaryFg: "hsl(0 0% 100%)",
      secondary: "hsl(195 20% 92%)",
      secondaryFg: "hsl(200 30% 20%)",
      muted: "hsl(195 18% 94%)",
      mutedFg: "hsl(200 15% 45%)",
      accent: "hsl(175 60% 45%)",
      accentFg: "hsl(0 0% 100%)",
      destructive: "hsl(0 72% 51%)",
      destructiveFg: "hsl(0 0% 100%)",
      border: "hsl(195 15% 87%)",
      input: "hsl(195 15% 87%)",
      ring: "hsl(185 70% 38%)",
      success: "hsl(160 60% 42%)",
      successFg: "hsl(0 0% 100%)",
      warning: "hsl(38 92% 50%)",
      warningFg: "hsl(0 0% 100%)",
      info: "hsl(195 70% 48%)",
      infoFg: "hsl(0 0% 100%)",
      link: "hsl(185 70% 38%)",
      linkHover: "hsl(185 70% 28%)",
      phase0: "hsl(160 55% 42%)",
      phase1: "hsl(195 60% 45%)",
      phase2: "hsl(38 75% 48%)",
      phase3: "hsl(0 55% 48%)",
      phase4: "hsl(248 45% 52%)",
    },
  },
};

export const themeIds = Object.keys(themes) as Array<keyof typeof themes>;

export function getTheme(themeId: string): Theme {
  return themes[themeId] || themes.light;
}

export function applyTheme(theme: Theme): void {
  const root = document.documentElement;

  // Map from theme color keys to CSS variable names
  const keyToVar: Record<string, string> = {
    bg: "--color-th-bg",
    fg: "--color-th-fg",
    card: "--color-th-card",
    cardFg: "--color-th-card-fg",
    popover: "--color-th-popover",
    popoverFg: "--color-th-popover-fg",
    primary: "--color-th-primary",
    primaryFg: "--color-th-primary-fg",
    secondary: "--color-th-secondary",
    secondaryFg: "--color-th-secondary-fg",
    muted: "--color-th-muted",
    mutedFg: "--color-th-muted-fg",
    accent: "--color-th-accent",
    accentFg: "--color-th-accent-fg",
    destructive: "--color-th-destructive",
    destructiveFg: "--color-th-destructive-fg",
    border: "--color-th-border",
    input: "--color-th-input",
    ring: "--color-th-ring",
    success: "--color-th-success",
    successFg: "--color-th-success-fg",
    warning: "--color-th-warning",
    warningFg: "--color-th-warning-fg",
    info: "--color-th-info",
    infoFg: "--color-th-info-fg",
    link: "--color-th-link",
    linkHover: "--color-th-link-hover",
    phase0: "--color-th-phase0",
    phase1: "--color-th-phase1",
    phase2: "--color-th-phase2",
    phase3: "--color-th-phase3",
    phase4: "--color-th-phase4",
  };

  Object.entries(theme.colors).forEach(([key, value]) => {
    const cssVarName = keyToVar[key];
    if (cssVarName) {
      root.style.setProperty(cssVarName, value);
    }
  });
}
