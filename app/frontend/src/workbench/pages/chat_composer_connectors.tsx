import {
  type ChangeEvent,
  type RefObject,
  useEffect,
  useRef,
  useState,
} from 'react';
import {type Connector} from '@/api/system';
import {Icon, type IconName} from '@/components/icon';
import {joinClasses} from '../classes';
import {useSystemStatus} from '../hooks/use_system_status';
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

// Shown until /status responds (and if it reports none), so the menu is never
// empty.
const DEFAULT_CONNECTORS: Connector[] = [{id: 'pubmed', display: 'PubMed'}];

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
  connectorsOpen,
  onToggleConnectors,
  sourceControlsRef,
  fileInputRef,
  onFilesChanged,
  pubmedEnabled,
  onPubmedEnabledChange,
}: {
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
        onClick={() => fileInputRef.current?.click()}
      />
      <SourceToolbarButton
        label="Connectors"
        icon="database"
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
  expanded,
  onClick,
}: {
  label: string;
  icon: IconName;
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

// Connectors menu: the available data sources come from the backend (/status),
// derived from literature availability plus the configured tools YAML, so newly
// configured connectors appear here automatically. They share the single
// literature-retrieval toggle, since the engine enables its data sources as one
// stack. Closed by the outside-mousedown effect in the parent composer.
function ConnectorsMenu({
  pubmedEnabled,
  onPubmedEnabledChange,
}: {
  pubmedEnabled: boolean;
  onPubmedEnabledChange?: (value: boolean) => void;
}) {
  const {status} = useSystemStatus();
  const connectors = status?.connectors?.length
    ? status.connectors
    : DEFAULT_CONNECTORS;
  return (
    <div
      className={CONNECTORS_MENU_CLASSES}
      role="menu"
      aria-label="Connectors"
    >
      <div className={CONNECTORS_MENU_HEADER_CLASSES}>
        <span>Connectors</span>
      </div>
      {connectors.map(connector => (
        <button
          type="button"
          role="menuitemcheckbox"
          aria-checked={pubmedEnabled}
          className={CONNECTORS_MENU_ROW_CLASSES}
          key={connector.id}
          onClick={() => onPubmedEnabledChange?.(!pubmedEnabled)}
        >
          <Icon
            className={CONNECTOR_ICON_CLASSES}
            aria-hidden="true"
            name="article"
          />
          <span>{connector.display}</span>
          <span
            className={joinClasses(
              CONNECTOR_TOGGLE_BASE_CLASSES,
              pubmedEnabled
                ? CONNECTOR_TOGGLE_ON_CLASSES
                : CONNECTOR_TOGGLE_OFF_CLASSES,
            )}
            aria-hidden="true"
          />
        </button>
      ))}
    </div>
  );
}
