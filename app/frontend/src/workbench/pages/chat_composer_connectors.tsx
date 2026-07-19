import {
  type ChangeEvent,
  type RefObject,
  useEffect,
  useRef,
  useState,
} from 'react';
import {type Connector} from '@/api/system';
import {Icon, type IconName} from '@/components/icon';
import {useAudience} from '../audience_context';
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
// empty. Only PubMed belongs here: it is the always-present literature base,
// whereas web search exists only when the MCP server has a provider key.
// Listing web search optimistically would flash a connector that a deployment
// without a key does not actually have.
const DEFAULT_CONNECTORS: Connector[] = [{id: 'pubmed', display: 'PubMed'}];

// The connector id whose row drives the standalone web-search toggle; every
// other id shares the literature toggle (see ConnectorsMenu).
const WEB_SEARCH_CONNECTOR_ID = 'web_search';

// The connector id for the SBI/UCD paper corpus ("Lab papers"). Its row drives
// its own standalone toggle and is only shown to the sbi_ucd audience (see
// ConnectorsMenu).
const PAPER_CORPUS_CONNECTOR_ID = 'paper_corpus';

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
 * connectors menu with its connector toggle rows.
 */
export function SourceControls({
  connectorsOpen,
  onToggleConnectors,
  sourceControlsRef,
  fileInputRef,
  onFilesChanged,
  pubmedEnabled,
  onPubmedEnabledChange,
  webSearchEnabled,
  onWebSearchEnabledChange,
  paperCorpusEnabled,
  onPaperCorpusEnabledChange,
}: {
  connectorsOpen: boolean;
  onToggleConnectors: () => void;
  sourceControlsRef: RefObject<HTMLDivElement | null>;
  fileInputRef: RefObject<HTMLInputElement | null>;
  onFilesChanged: (e: ChangeEvent<HTMLInputElement>) => void;
  pubmedEnabled: boolean;
  onPubmedEnabledChange?: (value: boolean) => void;
  webSearchEnabled: boolean;
  onWebSearchEnabledChange?: (value: boolean) => void;
  paperCorpusEnabled: boolean;
  onPaperCorpusEnabledChange?: (value: boolean) => void;
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
          webSearchEnabled={webSearchEnabled}
          onWebSearchEnabledChange={onWebSearchEnabledChange}
          paperCorpusEnabled={paperCorpusEnabled}
          onPaperCorpusEnabledChange={onPaperCorpusEnabledChange}
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
// derived from literature and web-search availability plus the configured tools
// YAML, so newly configured connectors appear here automatically. Each row keys
// its checked state and handler off `connector.id`: the web-search and Lab
// papers rows each drive their own independent toggle, while every literature
// source (PubMed, INDRA, ...) shares the single literature-retrieval toggle,
// since the engine enables that stack as one unit. The Lab papers corpus is
// SBI/UCD-specific, so its row is dropped for every other audience even when
// the backend advertises it. Closed by the outside-mousedown effect in the
// parent composer.
function ConnectorsMenu({
  pubmedEnabled,
  onPubmedEnabledChange,
  webSearchEnabled,
  onWebSearchEnabledChange,
  paperCorpusEnabled,
  onPaperCorpusEnabledChange,
}: {
  pubmedEnabled: boolean;
  onPubmedEnabledChange?: (value: boolean) => void;
  webSearchEnabled: boolean;
  onWebSearchEnabledChange?: (value: boolean) => void;
  paperCorpusEnabled: boolean;
  onPaperCorpusEnabledChange?: (value: boolean) => void;
}) {
  const {status} = useSystemStatus();
  const {audience} = useAudience();
  const advertised = status?.connectors?.length
    ? status.connectors
    : DEFAULT_CONNECTORS;
  // Backend already orders the connectors (web, pubmed, corpus); only drop the
  // Lab papers row for non-SBI audiences, preserving that order otherwise.
  const connectors = advertised.filter(
    connector =>
      connector.id !== PAPER_CORPUS_CONNECTOR_ID || audience === 'sbi_ucd',
  );
  return (
    <div
      className={CONNECTORS_MENU_CLASSES}
      role="menu"
      aria-label="Connectors"
    >
      <div className={CONNECTORS_MENU_HEADER_CLASSES}>
        <span>Connectors</span>
      </div>
      {connectors.map(connector => {
        const isWebSearch = connector.id === WEB_SEARCH_CONNECTOR_ID;
        const isPaperCorpus = connector.id === PAPER_CORPUS_CONNECTOR_ID;
        const checked = isWebSearch
          ? webSearchEnabled
          : isPaperCorpus
            ? paperCorpusEnabled
            : pubmedEnabled;
        const toggle = () =>
          isWebSearch
            ? onWebSearchEnabledChange?.(!webSearchEnabled)
            : isPaperCorpus
              ? onPaperCorpusEnabledChange?.(!paperCorpusEnabled)
              : onPubmedEnabledChange?.(!pubmedEnabled);
        const iconName: IconName = isWebSearch
          ? 'search'
          : isPaperCorpus
            ? 'science'
            : 'article';
        return (
          <button
            type="button"
            role="menuitemcheckbox"
            aria-checked={checked}
            className={CONNECTORS_MENU_ROW_CLASSES}
            key={connector.id}
            onClick={toggle}
          >
            <Icon
              className={CONNECTOR_ICON_CLASSES}
              aria-hidden="true"
              name={iconName}
            />
            <span>{connector.display}</span>
            <span
              className={joinClasses(
                CONNECTOR_TOGGLE_BASE_CLASSES,
                checked
                  ? CONNECTOR_TOGGLE_ON_CLASSES
                  : CONNECTOR_TOGGLE_OFF_CLASSES,
              )}
              aria-hidden="true"
            />
          </button>
        );
      })}
    </div>
  );
}
