import type { MdChipSet } from "@material/web/chips/chip-set.js";
import type { MdFilterChip } from "@material/web/chips/filter-chip.js";
import type { MdDialog } from "@material/web/dialog/dialog.js";
import type { MdDivider } from "@material/web/divider/divider.js";
import type { MdIcon } from "@material/web/icon/icon.js";
import type { MdFilledIconButton } from "@material/web/iconbutton/filled-icon-button.js";
import type { MdIconButton } from "@material/web/iconbutton/icon-button.js";
import type { MdCircularProgress } from "@material/web/progress/circular-progress.js";
import type { MdLinearProgress } from "@material/web/progress/linear-progress.js";
import type { MdOutlinedSelect } from "@material/web/select/outlined-select.js";
import type { MdSelectOption } from "@material/web/select/select-option.js";
import type { MdSwitch } from "@material/web/switch/switch.js";
import type { MdPrimaryTab } from "@material/web/tabs/primary-tab.js";
import type { MdSecondaryTab } from "@material/web/tabs/secondary-tab.js";
import type { MdTabs } from "@material/web/tabs/tabs.js";
import type { MdOutlinedTextField } from "@material/web/textfield/outlined-text-field.js";
import type { MdElevatedButton } from "@material/web/button/elevated-button.js";
import type { MdFilledButton } from "@material/web/button/filled-button.js";
import type { MdFilledTonalButton } from "@material/web/button/filled-tonal-button.js";
import type { MdOutlinedButton } from "@material/web/button/outlined-button.js";
import type { MdTextButton } from "@material/web/button/text-button.js";
import type React from "react";

interface LowercaseHandlers {
  onclick?: EventListener;
  onchange?: EventListener;
  oninput?: EventListener;
  onfocus?: EventListener;
  onblur?: EventListener;
  onkeydown?: EventListener;
  onkeyup?: EventListener;
  onmouseenter?: EventListener;
  onmouseleave?: EventListener;
}

type CustomEl<T> = Omit<React.HTMLAttributes<HTMLElement>, keyof T | "children" | "style"> &
  Omit<Partial<T>, "children" | "style"> &
  LowercaseHandlers & {
    ref?: React.Ref<T>;
    children?: React.ReactNode;
    style?: React.CSSProperties;
    key?: React.Key | null;
  };

declare module "react" {
  namespace JSX {
    interface IntrinsicElements {
      "md-elevated-button": CustomEl<MdElevatedButton>;
      "md-filled-button": CustomEl<MdFilledButton>;
      "md-filled-tonal-button": CustomEl<MdFilledTonalButton>;
      "md-outlined-button": CustomEl<MdOutlinedButton>;
      "md-text-button": CustomEl<MdTextButton>;
      "md-icon": CustomEl<MdIcon>;
      "md-icon-button": CustomEl<MdIconButton>;
      "md-filled-icon-button": CustomEl<MdFilledIconButton>;
      "md-outlined-text-field": CustomEl<MdOutlinedTextField>;
      "md-outlined-select": CustomEl<MdOutlinedSelect>;
      "md-select-option": CustomEl<MdSelectOption>;
      "md-filter-chip": CustomEl<MdFilterChip>;
      "md-chip-set": CustomEl<MdChipSet>;
      "md-circular-progress": CustomEl<MdCircularProgress>;
      "md-linear-progress": CustomEl<MdLinearProgress>;
      "md-divider": CustomEl<MdDivider>;
      "md-switch": CustomEl<MdSwitch>;
      "md-dialog": CustomEl<MdDialog>;
      "md-tabs": CustomEl<MdTabs>;
      "md-primary-tab": CustomEl<MdPrimaryTab>;
      "md-secondary-tab": CustomEl<MdSecondaryTab>;
    }
  }
}
