import type { LucideIcon } from "lucide-react";
import { Anchor, Briefcase, Moon, Sun, Waves } from "lucide-react";
import { Button } from "@/components/ui/button";
import { useTheme } from "@/context/ThemeContext";
import { themes } from "@/themes/themes";

const themeIcons: Record<string, LucideIcon> = {
  light: Sun,
  dark: Moon,
  navy: Anchor,
  business: Briefcase,
  ocean: Waves,
};

export function ThemeSwitcher() {
  const { currentTheme, cycleTheme, availableThemes } = useTheme();

  if (availableThemes.length <= 1) {
    return null;
  }

  const theme = themes[currentTheme];
  const themeName = theme?.name || currentTheme;
  const Icon = themeIcons[currentTheme] || Sun;

  return (
    <Button
      variant="ghost"
      size="icon"
      onClick={cycleTheme}
      className="h-9 w-9"
      title={`Theme: ${themeName}. Click to change.`}
    >
      <Icon className="w-5 h-5" />
    </Button>
  );
}
