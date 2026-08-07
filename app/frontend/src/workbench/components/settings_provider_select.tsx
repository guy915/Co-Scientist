import {useEffect, useRef, useState, type KeyboardEvent} from 'react';
import {Icon} from '@/components/icon';
import {BYOK_PROVIDERS, type ByokProvider} from '@/lib/api_key';

/** Display names for the BYOK provider choices. */
export const PROVIDER_LABELS: Record<ByokProvider, string> = {
  anthropic: 'Anthropic',
  deepseek: 'DeepSeek',
  gemini: 'Gemini',
  openai: 'OpenAI',
};

const TRIGGER_ID = 'cosci-settings-provider';
const LABEL_ID = 'cosci-settings-provider-label';

// Closes the menu on a pointerdown outside `container`. Registered only
// while open, matching the shell's own popover dismissal
// (layout_hooks.useDismissPanelOnOutsideClick).
function useCloseOnOutsidePointer(
  open: boolean,
  container: React.RefObject<HTMLDivElement | null>,
  onClose: () => void,
) {
  useEffect(() => {
    if (!open) return;
    function onPointerDown(event: PointerEvent) {
      if (!container.current?.contains(event.target as Node)) onClose();
    }
    document.addEventListener('pointerdown', onPointerDown);
    return () => {
      document.removeEventListener('pointerdown', onPointerDown);
    };
  }, [open, container, onClose]);
}

// One row of the open menu: a real button (so Tab and Enter work without an
// activedescendant dance), carrying a check on the current choice so the
// selection reads without relying on the highlight alone.
function ProviderOption({
  option,
  selected,
  onSelect,
}: {
  option: ByokProvider;
  selected: boolean;
  onSelect: (option: ByokProvider) => void;
}) {
  return (
    <button
      type="button"
      role="menuitemradio"
      aria-checked={selected}
      className="ucs-provider-option"
      onClick={() => onSelect(option)}
    >
      <span>{PROVIDER_LABELS[option]}</span>
      {selected && (
        <Icon
          aria-hidden="true"
          className="ucs-provider-option-check"
          name="check"
        />
      )}
    </button>
  );
}

/**
 * Provider chooser for the Settings dialog's Model section.
 *
 * A button plus an own-markup menu rather than a native `<select>`: the
 * native control stretched to the panel width and parked its arrow against
 * the far edge, a long reach from the value it belongs to, and its list is
 * drawn by the browser in its own style rather than by the workspace.
 *
 * @param provider The currently chosen provider.
 * @param onChange Called with the newly chosen provider (never with the one
 *   already selected -- picking the current value just closes the menu).
 */
export function ProviderSelect({
  provider,
  onChange,
}: {
  provider: ByokProvider;
  onChange: (provider: ByokProvider) => void;
}) {
  const [open, setOpen] = useState(false);
  const container = useRef<HTMLDivElement>(null);
  useCloseOnOutsidePointer(open, container, () => setOpen(false));

  function onSelect(option: ByokProvider) {
    setOpen(false);
    if (option !== provider) onChange(option);
  }

  // Escape closes the menu and stops there: the Settings dialog listens for
  // Escape on the window to close itself, and dismissing both at once would
  // throw the reader out of Settings for cancelling a dropdown.
  function onKeyDown(event: KeyboardEvent<HTMLDivElement>) {
    if (event.key === 'Escape' && open) {
      event.stopPropagation();
      setOpen(false);
    }
  }

  return (
    <div className="ucs-provider-select" ref={container} onKeyDown={onKeyDown}>
      <button
        type="button"
        id={TRIGGER_ID}
        className="ucs-provider-trigger"
        aria-haspopup="menu"
        aria-expanded={open}
        aria-labelledby={`${LABEL_ID} ${TRIGGER_ID}`}
        onClick={() => setOpen(current => !current)}
      >
        <span>{PROVIDER_LABELS[provider]}</span>
        <Icon
          aria-hidden="true"
          className="ucs-provider-chevron"
          name="expand_more"
        />
      </button>
      {open && (
        <div className="ucs-provider-menu" role="menu" aria-label="Provider">
          {BYOK_PROVIDERS.map(option => (
            <ProviderOption
              key={option}
              option={option}
              selected={option === provider}
              onSelect={onSelect}
            />
          ))}
        </div>
      )}
    </div>
  );
}

/** The `<label>` that names the trigger; rendered by the Model section. */
export function ProviderSelectLabel() {
  return (
    <label
      id={LABEL_ID}
      className="ucs-settings-field-label"
      htmlFor={TRIGGER_ID}
    >
      Provider
    </label>
  );
}
