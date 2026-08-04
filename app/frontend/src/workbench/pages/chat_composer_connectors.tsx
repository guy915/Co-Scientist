import {
  type ChangeEvent,
  type RefObject,
  useEffect,
  useRef,
  useState,
} from 'react';
import {type Connector, type SystemStatus} from '@/api/system';
import {Icon, type IconName} from '@/components/icon';
import {type Audience, useAudience} from '../audience_context';
import {joinClasses} from '../classes';
import {useSystemStatus} from '../hooks/system_status_context';
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
  CONNECTORS_MENU_NOTE_CLASSES,
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
 * The PubMed/web-search/lab-papers connector toggle values plus their
 * change callbacks, bundled so SourceControls/ConnectorsMenu/ComposerFooter
 * can each take a single argument instead of six.
 */
export interface ConnectorToggleProps {
  pubmedEnabled: boolean;
  onPubmedEnabledChange?: (value: boolean) => void;
  webSearchEnabled: boolean;
  onWebSearchEnabledChange?: (value: boolean) => void;
  paperCorpusEnabled: boolean;
  onPaperCorpusEnabledChange?: (value: boolean) => void;
}

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

// Props for SourceControls, named at module level per the destructured
// prop signature otherwise pushing the component past the line cap.
interface SourceControlsProps {
  connectorsOpen: boolean;
  onToggleConnectors: () => void;
  sourceControlsRef: RefObject<HTMLDivElement | null>;
  fileInputRef: RefObject<HTMLInputElement | null>;
  onFilesChanged: (e: ChangeEvent<HTMLInputElement>) => void;
  connectors: ConnectorToggleProps;
}

/**
 * Renders the composer's file/connector toolbar row: the hidden file input
 * and its trigger button, the Connectors button, and (while open) the
 * connectors menu with its connector toggle rows.
 */
export function SourceControls(props: SourceControlsProps) {
  const {
    connectorsOpen,
    onToggleConnectors,
    sourceControlsRef,
    fileInputRef,
    onFilesChanged,
    connectors,
  } = props;
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
      {connectorsOpen ? <ConnectorsMenu connectors={connectors} /> : null}
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

// The available data sources come from the backend (/status), derived from
// literature and web-search availability plus the configured tools YAML, so
// newly configured connectors appear here automatically. Which are shown is
// filtered for the current audience: the backend already orders them (web,
// pubmed, corpus), so only the Lab papers row is ever dropped, for every
// non-SBI audience, preserving that order otherwise.
function visibleConnectors(
  status: SystemStatus | null,
  audience: Audience | null,
): Connector[] {
  // No answer yet is not the same as an empty answer: the caller renders its
  // own note for that, rather than this passing off the fallback as the
  // deployment's real source list.
  if (status === null) return [];
  const advertised = status.connectors?.length
    ? status.connectors
    : DEFAULT_CONNECTORS;
  return advertised.filter(
    connector =>
      connector.id !== PAPER_CORPUS_CONNECTOR_ID || audience === 'sbi_ucd',
  );
}

// Which toggle a connector row reads and writes, plus the icon it shows.
interface ConnectorBehavior {
  checked: boolean;
  setChecked?: (value: boolean) => void;
  icon: IconName;
}

// The connectors that own an independent toggle, keyed by id. Web search and
// Lab papers each stand alone here; every other connector falls through to
// the literature default below, since the engine enables that stack as one
// unit. This maps ids that are already on screen to their behavior — which
// connectors an audience sees is decided by visibleConnectors alone.
function standaloneBehaviors(
  toggles: ConnectorToggleProps,
): Record<string, ConnectorBehavior> {
  return {
    [WEB_SEARCH_CONNECTOR_ID]: {
      checked: toggles.webSearchEnabled,
      setChecked: toggles.onWebSearchEnabledChange,
      icon: 'search',
    },
    [PAPER_CORPUS_CONNECTOR_ID]: {
      checked: toggles.paperCorpusEnabled,
      setChecked: toggles.onPaperCorpusEnabledChange,
      icon: 'science',
    },
  };
}

// The shared pubmed/literature-retrieval behavior, for every connector with
// no entry of its own.
function literatureBehavior(toggles: ConnectorToggleProps): ConnectorBehavior {
  return {
    checked: toggles.pubmedEnabled,
    setChecked: toggles.onPubmedEnabledChange,
    icon: 'article',
  };
}

// One connector row's derived checked/toggle/icon state, from a single
// lookup in the table above.
function connectorRowState(
  connector: Connector,
  toggles: ConnectorToggleProps,
): {checked: boolean; toggle: () => void; iconName: IconName} {
  const behavior =
    standaloneBehaviors(toggles)[connector.id] ?? literatureBehavior(toggles);
  return {
    checked: behavior.checked,
    toggle: () => behavior.setChecked?.(!behavior.checked),
    iconName: behavior.icon,
  };
}

// One row in the connectors menu: an icon, the connector's display name, and
// its on/off toggle pill.
function ConnectorMenuRow({
  connector,
  toggles,
}: {
  connector: Connector;
  toggles: ConnectorToggleProps;
}) {
  const {checked, toggle, iconName} = connectorRowState(connector, toggles);
  return (
    <button
      type="button"
      role="menuitemcheckbox"
      aria-checked={checked}
      className={CONNECTORS_MENU_ROW_CLASSES}
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
          checked ? CONNECTOR_TOGGLE_ON_CLASSES : CONNECTOR_TOGGLE_OFF_CLASSES,
        )}
        aria-hidden="true"
      />
    </button>
  );
}

// A non-row line in the menu: the states that are not a connector list, and
// must not read as one.
function ConnectorsNote({text}: {text: string}) {
  return (
    <p className={CONNECTORS_MENU_NOTE_CLASSES} role="note">
      {text}
    </p>
  );
}

// The note shown in place of rows, or nothing when there are rows to show.
// A menu with no rows and no explanation is the one outcome to avoid: it
// looks like the list failed to load however it got there.
function ConnectorsMenuState({
  status,
  unreachable,
  visible,
}: {
  status: SystemStatus | null;
  unreachable: boolean;
  visible: number;
}) {
  if (visible > 0) return null;
  if (status !== null) {
    return <ConnectorsNote text="No sources are configured for this run." />;
  }
  if (unreachable) {
    return (
      <ConnectorsNote text="Sources unavailable — the API is unreachable." />
    );
  }
  return <ConnectorsNote text="Checking available sources…" />;
}

/**
 * The connectors menu: a header plus one ConnectorMenuRow per visible
 * connector. Closed by the outside-mousedown effect in the parent composer
 * (see useConnectorsMenu).
 *
 * The three states are kept apart on purpose. "Still checking" and "could not
 * check" both used to render the PubMed-only fallback, which is a claim about
 * the deployment -- a scientist reading it has no way to tell an unreachable
 * API from a backend that genuinely advertises one source.
 */
function ConnectorsMenu({
  connectors: toggles,
}: {
  connectors: ConnectorToggleProps;
}) {
  const {status, unreachable} = useSystemStatus();
  const {audience} = useAudience();
  const connectors = visibleConnectors(status, audience);
  return (
    <div
      className={CONNECTORS_MENU_CLASSES}
      role="menu"
      aria-label="Connectors"
    >
      <div className={CONNECTORS_MENU_HEADER_CLASSES}>
        <span>Connectors</span>
      </div>
      <ConnectorsMenuState
        status={status}
        unreachable={unreachable}
        visible={connectors.length}
      />
      {connectors.map(connector => (
        <ConnectorMenuRow
          key={connector.id}
          connector={connector}
          toggles={toggles}
        />
      ))}
    </div>
  );
}
