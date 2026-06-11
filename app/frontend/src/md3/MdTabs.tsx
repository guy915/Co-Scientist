import "@material/web/tabs/tabs.js";
import "@material/web/tabs/secondary-tab.js";
import "@material/web/icon/icon.js";
import type { MdTabs as MdTabsElement } from "@material/web/tabs/tabs.js";
import { useEffect, useRef } from "react";

interface Tab {
  label: string;
  icon?: string;
}

interface MdSecondaryTabsProps {
  tabs: Tab[];
  activeIndex: number;
  onChange: (index: number) => void;
}

export function MdSecondaryTabs({ tabs, activeIndex, onChange }: MdSecondaryTabsProps) {
  const ref = useRef<MdTabsElement>(null);

  useEffect(() => {
    const el = ref.current;
    if (!el) return;
    const handler = () => onChange(el.activeTabIndex);
    el.addEventListener("change", handler);
    return () => el.removeEventListener("change", handler);
  }, [onChange]);

  return (
    <>
      <nav
        className="sm:hidden -mx-4 overflow-x-auto border-b px-4"
        style={{ borderColor: "var(--md-sys-color-outline-variant)" }}
        aria-label="Run sections"
      >
        <div className="flex min-w-max gap-1 pb-2">
          {tabs.map((t, i) => {
            const active = i === activeIndex;
            return (
              <button
                key={t.label}
                type="button"
                onClick={() => onChange(i)}
                aria-current={active ? "page" : undefined}
                className="inline-flex min-h-11 items-center gap-1.5 rounded-full px-4 text-sm font-medium transition-colors"
                style={{
                  backgroundColor: active
                    ? "var(--md-sys-color-secondary-container)"
                    : "transparent",
                  color: active
                    ? "var(--md-sys-color-on-secondary-container)"
                    : "var(--md-sys-color-on-surface-variant)",
                }}
              >
                {t.icon && <md-icon style={{ fontSize: "18px" }}>{t.icon}</md-icon>}
                {t.label}
              </button>
            );
          })}
        </div>
      </nav>
      <div className="hidden sm:block">
        <md-tabs ref={ref as React.Ref<MdTabsElement>}>
          {tabs.map((t, i) => (
            <md-secondary-tab key={t.label} active={i === activeIndex || undefined}>
              {t.icon && <md-icon slot="icon">{t.icon}</md-icon>}
              {t.label}
            </md-secondary-tab>
          ))}
        </md-tabs>
      </div>
    </>
  );
}
