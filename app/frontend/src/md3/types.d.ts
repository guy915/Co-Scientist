import type {MdChipSet} from '@material/web/chips/chip-set.js';
import type {MdFilterChip} from '@material/web/chips/filter-chip.js';
import type {MdDivider} from '@material/web/divider/divider.js';
import type {MdIcon} from '@material/web/icon/icon.js';
import type {MdCircularProgress} from '@material/web/progress/circular-progress.js';
import type {MdLinearProgress} from '@material/web/progress/linear-progress.js';
import type {MdOutlinedSelect} from '@material/web/select/outlined-select.js';
import type {MdSelectOption} from '@material/web/select/select-option.js';
import type {MdSwitch} from '@material/web/switch/switch.js';
import type {MdOutlinedTextField} from '@material/web/textfield/outlined-text-field.js';
import type React from 'react';

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

type CustomEl<T> = Omit<
  React.HTMLAttributes<HTMLElement>,
  keyof T | 'children' | 'style'
> &
  Omit<Partial<T>, 'children' | 'style'> &
  LowercaseHandlers & {
    ref?: React.Ref<T>;
    children?: React.ReactNode;
    style?: React.CSSProperties;
    key?: React.Key | null;
  };

declare module 'react' {
  namespace JSX {
    interface IntrinsicElements {
      'md-icon': CustomEl<MdIcon>;
      'md-outlined-text-field': CustomEl<MdOutlinedTextField>;
      'md-outlined-select': CustomEl<MdOutlinedSelect>;
      'md-select-option': CustomEl<MdSelectOption>;
      'md-filter-chip': CustomEl<MdFilterChip>;
      'md-chip-set': CustomEl<MdChipSet>;
      'md-circular-progress': CustomEl<MdCircularProgress>;
      'md-linear-progress': CustomEl<MdLinearProgress>;
      'md-divider': CustomEl<MdDivider>;
      'md-switch': CustomEl<MdSwitch>;
    }
  }
}
