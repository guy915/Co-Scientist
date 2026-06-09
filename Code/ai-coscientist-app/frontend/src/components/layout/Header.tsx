import { ThemeSwitcher } from "@/components/theme/ThemeSwitcher";
import { IconRenderer } from "@/components/ui/IconRenderer";
import { useDomainText } from "@/hooks/useDomainText";

export function Header() {
  const { t, config } = useDomainText();
  const appName = config.appName || "Open Coscientist";
  const appIcon = config.appIcon || "Sparkles";

  return (
    <header className="border-b" style={{ borderColor: "var(--color-th-border)" }}>
      <div className="container mx-auto px-4 py-4">
        <div className="flex items-center justify-between gap-3 max-w-6xl m-auto">
          <div className="flex items-center gap-3">
            <IconRenderer
              icon={appIcon}
              className="w-8 h-8"
              style={{ color: "var(--color-th-primary)" }}
            />
            <div>
              <h1 className="text-2xl font-bold">{appName}</h1>
              <p className="text-sm" style={{ color: "var(--color-th-muted-fg)" }}>
                {t("app_subtitle")}
              </p>
            </div>
          </div>
          <ThemeSwitcher />
        </div>
      </div>
    </header>
  );
}
