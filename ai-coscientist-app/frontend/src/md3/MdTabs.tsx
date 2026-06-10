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
    <md-tabs ref={ref as React.Ref<MdTabsElement>}>
      {tabs.map((t, i) => (
        <md-secondary-tab key={t.label} active={i === activeIndex || undefined}>
          {t.icon && <md-icon slot="icon">{t.icon}</md-icon>}
          {t.label}
        </md-secondary-tab>
      ))}
    </md-tabs>
  );
}
