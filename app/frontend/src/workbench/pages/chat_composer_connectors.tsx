import {
  type ChangeEvent,
  type RefObject,
  useEffect,
  useRef,
  useState,
} from 'react';
import {Icon, type IconName} from '@/components/icon';
import {tooltipClassNames} from '../tooltip';
import {
  COMPOSER_FILE_INPUT_CLASSES,
  COMPOSER_SOURCE_BUTTON_CLASSES,
  COMPOSER_SOURCE_CONTROLS_CLASSES,
  COMPOSER_SOURCE_ICON_CLASSES,
  CONNECTOR_ICON_CLASSES,
  CONNECTOR_TOGGLE_BASE_CLASSES,
  CONNECTOR_TOGGLE_OFF_CLASSES,
  CONNECTOR_TOGGLE_ON_CLASSES,
  CONNECTORS_MENU_CLASSES,
  CONNECTORS_MENU_HEADER_CLASSES,
  CONNECTORS_MENU_ROW_CLASSES,
} from './chat_home_classes';

const COMPOSER_CONNECTORS = ['PubMed'];

/**
 * Owns the connectors-menu open flag and the outside-mousedown listener that
 * closes it; only subscribes to the document listener when the menu is
 * actually open.
 */
export function useConnectorsMenu() {
  const sourceControlsRef = useRef<HTMLDivElement>(null);
  const [connectorsOpen, setConnectorsOpen] = useState(false);

  useEffect(() => {
    if (!connectorsOpen) return;

    function closeConnectors(e: globalThis.MouseEvent) {
      if (
        e.target instanceof Node &&
        sourceControlsRef.current?.contains(e.target)
      ) {
        return;
      }
      setConnectorsOpen(false);
    }

    document.addEventListener('mousedown', closeConnectors);
    return () => document.removeEventListener('mousedown', closeConnectors);
  }, [connectorsOpen]);

  return {connectorsOpen, setConnectorsOpen, sourceControlsRef};
}

/**
 * Renders the composer's file/connector toolbar row: the hidden file input
 * and its trigger button, the Connectors button, and (while open) the
 * connectors menu with its PubMed toggle row.
 */
export function SourceControls({
  disabled,
  connectorsOpen,
  onToggleConnectors,
  sourceControlsRef,
  fileInputRef,
  onFilesChanged,
  pubmedEnabled,
  onPubmedEnabledChange,
}: {
  disabled: boolean;
  connectorsOpen: boolean;
  onToggleConnectors: () => void;
  sourceControlsRef: RefObject<HTMLDivElement | null>;
  fileInputRef: RefObject<HTMLInputElement | null>;
  onFilesChanged: (e: ChangeEvent<HTMLInputElement>) => void;
  pubmedEnabled: boolean;
  onPubmedEnabledChange?: (value: boolean) => void;
}) {
  return (
    <div className={COMPOSER_SOURCE_CONTROLS_CLASSES} ref={sourceControlsRef}>
      <input
        ref={fileInputRef}
        className={COMPOSER_FILE_INPUT_CLASSES}
        type="file"
        multiple
        aria-label="Upload files"
        onChange={onFilesChanged}
        tabIndex={-1}
      />
      <SourceToolbarButton
        label="Files"
        icon="add"
        disabled={disabled}
        onClick={() => fileInputRef.current?.click()}
      />
      <SourceToolbarButton
        label="Connectors"
        icon="database"
        disabled={disabled}
        expanded={connectorsOpen}
        onClick={onToggleConnectors}
      />
      {connectorsOpen ? (
        <ConnectorsMenu
          pubmedEnabled={pubmedEnabled}
          onPubmedEnabledChange={onPubmedEnabledChange}
        />
      ) : null}
    </div>
  );
}

// One toolbar trigger button in the source-controls row (Files, Connectors):
// an icon button with a shared tooltip/label. `expanded` is only set by the
// Connectors button; leaving it undefined for Files omits aria-expanded
// entirely, matching a plain non-expandable button.
function SourceToolbarButton({
  label,
  icon,
  disabled,
  expanded,
  onClick,
}: {
  label: string;
  icon: IconName;
  disabled: boolean;
  expanded?: boolean;
  onClick: () => void;
}) {
  return (
    <button
      type="button"
      className={tooltipClassNames({
        className: COMPOSER_SOURCE_BUTTON_CLASSES,
        placement: 'top',
      })}
      aria-label={label}
      aria-expanded={expanded}
      data-tooltip={label}
      disabled={disabled}
      onClick={onClick}
    >
      <Icon
        aria-hidden="true"
        className={COMPOSER_SOURCE_ICON_CLASSES}
        name={icon}
      />
    </button>
  );
}

// Connectors menu: currently a single PubMed toggle row, closed by the
// outside-mousedown effect in the parent composer.
function ConnectorsMenu({
  pubmedEnabled,
  onPubmedEnabledChange,
}: {
  pubmedEnabled: boolean;
  onPubmedEnabledChange?: (value: boolean) => void;
}) {
  return (
    <div
      className={CONNECTORS_MENU_CLASSES}
      role="menu"
      aria-label="Connectors"
    >
      <div className={CONNECTORS_MENU_HEADER_CLASSES}>
        <span>Connectors</span>
      </div>
      {COMPOSER_CONNECTORS.map(name => (
        <button
          type="button"
          role="menuitemcheckbox"
          aria-checked={pubmedEnabled}
          className={CONNECTORS_MENU_ROW_CLASSES}
          key={name}
          onClick={() => onPubmedEnabledChange?.(!pubmedEnabled)}
        >
          <Icon
            className={CONNECTOR_ICON_CLASSES}
            aria-hidden="true"
            name="article"
          />
          <span>{name}</span>
          <span
            className={[
              CONNECTOR_TOGGLE_BASE_CLASSES,
              pubmedEnabled
                ? CONNECTOR_TOGGLE_ON_CLASSES
                : CONNECTOR_TOGGLE_OFF_CLASSES,
            ].join(' ')}
            aria-hidden="true"
          />
        </button>
      ))}
    </div>
  );
}
