import '@material/web/button/filled-button.js';
import '@material/web/button/outlined-button.js';
import '@material/web/button/text-button.js';
import '@material/web/chips/chip-set.js';
import '@material/web/chips/filter-chip.js';
import '@material/web/icon/icon.js';
import '@material/web/iconbutton/icon-button.js';

import {
  Fragment,
  type ChangeEvent,
  type FormEvent,
  type KeyboardEvent,
  type ReactNode,
  useCallback,
  useEffect,
  useLayoutEffect,
  useRef,
  useState,
} from 'react';
import {Link, useLocation, useNavigate} from 'react-router-dom';
import {
  createRun,
  getHypotheses,
  listDemoRuns,
  listRuns,
  type Hypothesis,
  type RunFocus,
  type RunTier,
  type Run,
  startRun,
} from '@/api/runs';
import {conciseTitle} from '@/lib/text';
import {
  FOCUS_OPTIONS,
  inferRunSpec,
  type InferredRunSpec,
  reviseRunSpec,
  TIER_OPTIONS,
} from '../run_spec';
import {GoogleLabsIcon} from '../components/google_labs_icon';
import {tooltipClassNames} from '../tooltip';
import {
  COMPOSER_ACTIONS_CLASSES,
  COMPOSER_BASE_CLASSES,
  COMPOSER_FILE_INPUT_CLASSES,
  COMPOSER_LABEL_CLASSES,
  COMPOSER_LABEL_ICON_CLASSES,
  COMPOSER_LABEL_TEXT_CLASSES,
  COMPOSER_LABEL_TEXT_HIDDEN_CLASSES,
  COMPOSER_SOURCE_BUTTON_CLASSES,
  COMPOSER_SOURCE_CONTROLS_CLASSES,
  COMPOSER_SOURCE_ICON_CLASSES,
  COMPOSER_SUBMIT_BUTTON_CLASSES,
  COMPOSER_TEXTAREA_CLASSES,
  CONNECTOR_ICON_CLASSES,
  CONNECTOR_TOGGLE_BASE_CLASSES,
  CONNECTOR_TOGGLE_OFF_CLASSES,
  CONNECTOR_TOGGLE_ON_CLASSES,
  CONNECTORS_MENU_CLASSES,
  CONNECTORS_MENU_HEADER_CLASSES,
  CONNECTORS_MENU_ROW_CLASSES,
  HOME_COMPOSER_CLASSES,
  HOME_COMPOSER_TEXTAREA_CLASSES,
  HOME_LOAD_MORE_BUTTON_CLASSES,
  HOME_LOAD_MORE_ITEM_CLASSES,
  HOME_MAIN_CLASSES,
  HOME_RECENTS_LIST_CLASSES,
  HOME_RECENTS_PANEL_CLASSES,
  HOME_RECENTS_HEADING_ROW_CLASSES,
  HOME_STAGE_CLASSES,
  HOME_STEP_BODY_CLASSES,
  HOME_STEP_HEADING_CLASSES,
  HOME_STEP_ITEM_CENTER_CLASSES,
  HOME_STEP_ITEM_CLASSES,
  HOME_STEP_ITEM_END_CLASSES,
  HOME_STEP_NUMBER_CLASSES,
  HOME_STEP_TIMELINE_CLASSES,
  HOME_SUGGESTION_BUTTON_CLASSES,
  HOME_SUGGESTION_BUTTON_PREVIEWED_CLASSES,
  HOME_SUGGESTION_PREVIEW_CENTER_CLASSES,
  HOME_SUGGESTION_PREVIEW_CLASSES,
  HOME_SUGGESTION_PREVIEW_END_CLASSES,
  HOME_SUGGESTION_PREVIEW_START_CLASSES,
  HOME_SUGGESTION_PREVIEW_VISIBLE_CLASSES,
  HOME_SUGGESTION_ROW_CLASSES,
  HOME_SUGGESTION_SLOT_CLASSES,
  HOME_SUGGESTION_TEXT_CLASSES,
  HOME_TITLE_CLASSES,
  HOME_TOAST_CLASSES,
  HOME_WORKSPACE_CLASSES,
  HOME_WORKSPACE_MAIN_CLASSES,
} from './chat_home_classes';
import {
  CHAT_BUBBLE_ROW_CLASSES,
  CHAT_BUBBLE_USER_ROW_CLASSES,
  CHAT_COLUMN_CLASSES,
  CHAT_COMPOSER_CLASSES,
  CHAT_TIMELINE_CLASSES,
  MESSAGE_ACTION_BUTTON_CLASSES,
  MESSAGE_ACTION_ICON_CLASSES,
  MESSAGE_ACTIONS_CLASSES,
  MESSAGE_ACTIONS_END_CLASSES,
  MODEL_BUBBLE_CLASSES,
  OPTION_CARD_BASE_CLASSES,
  OPTION_CARD_SELECTED_CLASSES,
  OPTION_DESCRIPTION_CLASSES,
  OPTION_GRID_CLASSES,
  OPTION_GROUP_CLASSES,
  OPTION_GROUP_LEGEND_CLASSES,
  OPTION_INPUT_CLASSES,
  OPTION_LABEL_CLASSES,
  OPTION_MARKER_CLASSES,
  OPTION_MARKER_SELECTED_CLASSES,
  PLAN_EDIT_BUTTON_CLASSES,
  PLAN_EDIT_ICON_CLASSES,
  PLAN_HEADING_CLASSES,
  PLAN_SUBHEADING_CLASSES,
  PLAN_TITLE_CLASSES,
  SETUP_ACTIONS_CLASSES,
  SETUP_DOCUMENT_CLASSES,
  SETUP_DOCUMENT_TITLE_CLASSES,
  SETUP_MESSAGE_CLASSES,
  SETUP_PARAGRAPH_CLASSES,
  SETUP_PRIMARY_BUTTON_CLASSES,
  SETUP_SECONDARY_BUTTON_CLASSES,
  SPEC_DETAIL_CLASSES,
  SPEC_GRID_CLASSES,
  SPEC_LIST_CLASSES,
  SPEC_ROW_CLASSES,
  SPEC_TERM_CLASSES,
  STARTED_COPY_CLASSES,
  STARTED_COPY_PARAGRAPH_CLASSES,
  STARTED_MESSAGE_CLASSES,
  STARTED_NEXT_BUTTON_CLASSES,
  STARTED_NEXT_CLASSES,
  STARTED_NEXT_COPY_CLASSES,
  STARTED_OPEN_CLASSES,
  STARTED_SESSION_CARD_CLASSES,
  STARTED_SESSION_META_CLASSES,
  STARTED_SESSION_TITLE_CLASSES,
  USER_BUBBLE_CLASSES,
  USER_BUBBLE_TEXT_CLASSES,
  USER_BUBBLE_TEXT_COLLAPSED_CLASSES,
  USER_COLLAPSE_BUTTON_CLASSES,
} from './chat_setup_classes';

interface ChatEntry {
  id: string;
  role: 'user' | 'assistant';
  content: string;
  created_at: number;
}

interface TimelineItem {
  id: string;
  at: number;
  order: number;
  node: ReactNode;
}

interface StartedSession {
  id: string;
  title: string;
  at: number;
}

const SUGGESTIONS = [
  {
    short: 'Find new therapeutic targets for M.tuberculosis by combining...',
    full: 'Find new therapeutic targets for M.tuberculosis by combining host-pathogen interaction datasets with recent literature.',
  },
  {
    short: 'Generate novel hypotheses for the link between...',
    full: 'Generate novel hypotheses for the link between synaptic pruning and treatment-resistant neuroinflammation.',
  },
  {
    short: 'Propose new mechanisms to explain why some patients...',
    full: 'Propose new mechanisms to explain why some patients fail to respond to checkpoint inhibitor therapy.',
  },
];

const COMPOSER_CONNECTORS = ['PubMed'];
const BASELINE_ELO_RATING = 1200;

const RECENTS_PANEL_CLASSES = `reference-recents min-[1181px]:!gap-[1.55rem] ${HOME_RECENTS_PANEL_CLASSES}`;

const RECENTS_HEADING_ICON_CLASSES =
  '[--md-icon-size:20px] min-[1181px]:[--md-icon-size:22px]';

const RECENTS_HEADING_CLASSES =
  'm-0 text-[1.15rem] font-semibold text-[var(--cosci-recents-heading)] ' +
  'min-[1181px]:!text-[1.22rem] min-[1181px]:!font-medium ' +
  'min-[1181px]:!leading-[1.2]';

const RECENTS_LIST_CLASSES = `min-[1181px]:!gap-[2.65rem] ${HOME_RECENTS_LIST_CLASSES}`;

const EMPTY_RECENTS_PANEL_CLASSES = `${RECENTS_PANEL_CLASSES} grid-rows-[auto_1fr] self-stretch pb-8`;

const EMPTY_RECENTS_LIST_CLASSES = `${RECENTS_LIST_CLASSES} h-full !max-h-none !overflow-hidden !p-0`;

const EMPTY_RECENTS_ITEM_CLASSES = 'h-full min-h-0';

const EMPTY_RECENTS_CLASSES =
  'reference-recents-empty box-border grid h-full min-h-[25rem] w-full ' +
  'place-items-center content-center gap-4 rounded-[1.35rem] border-[1.5px] ' +
  'border-dashed border-[#c7c9cc] bg-transparent p-6 text-center ' +
  'text-[#5f6368] dark:border-[#53565a] dark:text-[#bdc1c6]';

const EMPTY_RECENTS_ICON_CLASSES =
  'reference-recents-empty-icon block h-[1.95rem] w-[2.1rem] ' +
  'text-[var(--cosci-teal)] dark:text-[#7fd7bf]';

const EMPTY_RECENTS_COPY_CLASSES =
  'max-w-[17rem] text-base leading-[1.35] font-[650] text-inherit';

const RECENT_CARD_CLASSES =
  'reference-recent-card grid min-h-[15.75rem] w-full content-start gap-[0.7rem] ' +
  'rounded-[0.8rem] border border-[var(--cosci-recent-card-border)] ' +
  'bg-[var(--cosci-recent-card-bg)] p-[1.05rem_1.2rem] text-left ' +
  'text-[var(--cosci-recent-card-text)] no-underline shadow-[var(--cosci-recent-card-shadow)] ' +
  'cursor-pointer min-[1181px]:!min-h-0 min-[1181px]:!rounded-2xl ' +
  'min-[1181px]:!border-[#eef1f4] min-[1181px]:!px-[1.15rem] ' +
  'min-[1181px]:!pt-[1.05rem] min-[1181px]:!pb-[1.12rem] ' +
  'min-[1181px]:hover:!border-[#dadce0] min-[1181px]:hover:!bg-[#f8fafd] ' +
  'min-[1181px]:focus-visible:!border-[#dadce0] ' +
  'min-[1181px]:focus-visible:!bg-[#f8fafd] ' +
  'dark:min-[1181px]:!border-transparent dark:min-[1181px]:!bg-[#17191c] ' +
  'dark:min-[1181px]:hover:!border-[#3c4043] ' +
  'dark:min-[1181px]:hover:!bg-[#202124] ' +
  'dark:min-[1181px]:focus-visible:!border-[#3c4043] ' +
  'dark:min-[1181px]:focus-visible:!bg-[#202124]';

const ACTIVE_RECENT_CARD_CLASSES = `${RECENT_CARD_CLASSES} is-active-run`;

const RECENT_META_CLASSES =
  'reference-recent-meta flex flex-wrap gap-[0.35rem]';

const RECENT_META_CHIP_CLASSES =
  'rounded-[0.35rem] bg-[var(--cosci-recent-meta-bg)] px-[0.48rem] ' +
  'py-[0.32rem] text-[0.75rem] font-semibold text-[var(--cosci-recent-meta-text)] ' +
  'min-[1181px]:!bg-[#f1f4f7] min-[1181px]:!px-[0.62rem] ' +
  'min-[1181px]:!py-[0.38rem] min-[1181px]:!text-[0.78rem] ' +
  'min-[1181px]:!leading-[1.1] min-[1181px]:!text-[#3c4043] ' +
  'dark:min-[1181px]:!bg-[#303335] dark:min-[1181px]:!text-[#f1f3f4]';

const RECENT_TITLE_CLASSES =
  'text-[1.02rem] leading-[1.35] min-[1181px]:!text-[1.08rem]';

const RECENT_DESCRIPTION_CLASSES =
  'line-clamp-4 overflow-hidden text-[0.9rem] leading-[1.35] ' +
  'text-[var(--cosci-recent-card-copy)] min-[1181px]:!text-[0.94rem] ' +
  'min-[1181px]:!leading-[1.34] min-[1181px]:!line-clamp-3';

const RECENT_CHIPS_CLASSES =
  'reference-recent-chips flex flex-nowrap items-center gap-[0.35rem]';

const RECENT_CHIP_CLASSES =
  'inline-flex items-center gap-1 rounded-[0.35rem] bg-[var(--cosci-recent-chip-bg)] ' +
  'px-[0.48rem] py-[0.32rem] text-[0.75rem] font-semibold ' +
  'text-[var(--cosci-recent-chip-text)] min-[1181px]:!flex-none ' +
  'min-[1181px]:!min-h-[1.62rem] ' +
  'min-[1181px]:!px-[0.42rem] min-[1181px]:!py-[0.26rem] ' +
  'min-[1181px]:!text-[0.68rem] min-[1181px]:!leading-none ' +
  'min-[1181px]:!whitespace-nowrap dark:min-[1181px]:!bg-[#0b8043] ' +
  'dark:min-[1181px]:!text-[#e6f4ea]';

const RECENT_CHIP_ICON_CLASSES = '[--md-icon-size:16px]';

const ACTIVE_PROGRESS_CLASSES =
  'reference-active-progress min-[1181px]:!mt-[0.05rem] min-[1181px]:!flex ' +
  'min-[1181px]:!items-center min-[1181px]:!gap-[0.65rem] ' +
  'min-[1181px]:!text-[0.92rem] min-[1181px]:!font-medium ' +
  'min-[1181px]:!leading-[1.25] min-[1181px]:!text-[#1967d2] ' +
  'dark:min-[1181px]:!text-[#8fd8c7]';

const ACTIVE_PROGRESS_DOT_CLASSES =
  'min-[1181px]:!block min-[1181px]:!size-[0.7rem] ' +
  'min-[1181px]:!shrink-0 min-[1181px]:!rounded-full ' +
  'min-[1181px]:!bg-current';

const WINNER_LIST_CLASSES =
  'reference-winner-list m-[0.15rem_0_0] grid list-none gap-[0.65rem] p-0 ' +
  'text-[0.78rem] leading-[1.35] text-[var(--cosci-recent-card-text)] ' +
  'min-[1181px]:!gap-2 min-[1181px]:!text-[0.84rem] ' +
  'min-[1181px]:!leading-[1.25] min-[1181px]:!text-[#202124] ' +
  'dark:min-[1181px]:!text-[#f1f3f4]';

const WINNER_LIST_ITEM_CLASSES =
  'min-[1181px]:!grid min-[1181px]:!grid-cols-[1.4rem_minmax(0,1fr)] ' +
  'min-[1181px]:!gap-[0.2rem]';

const GENERATING_ROW_CLASSES =
  'reference-generating-row min-[1181px]:!grid ' +
  'min-[1181px]:!grid-cols-[0.75rem_minmax(0,1fr)] ' +
  'min-[1181px]:!items-center min-[1181px]:!gap-[0.65rem] ' +
  'min-[1181px]:!font-medium min-[1181px]:!text-[#137333] ' +
  'dark:min-[1181px]:!text-[#8fd8c7]';

const GENERATING_DOT_CLASSES =
  'min-[1181px]:!block min-[1181px]:!size-[0.6rem] ' +
  'min-[1181px]:!shrink-0 min-[1181px]:!rounded-full ' +
  'min-[1181px]:!bg-current min-[1181px]:!opacity-70';

const REFERENCE_COMPOSER_ATTACHED_CLASSES =
  'has-attachments !min-h-[13.5rem] !pt-4';

const ATTACHMENT_STRIP_CLASSES =
  'reference-attachment-strip flex min-w-0 gap-[0.8rem] overflow-x-auto ' +
  'pb-[1.35rem] pointer-events-auto [scrollbar-width:none] ' +
  '[&::-webkit-scrollbar]:hidden';

const ATTACHMENT_CARD_CLASSES =
  'reference-attachment-card group relative box-border grid h-[4.85rem] ' +
  'w-[13.75rem] flex-none items-center rounded-2xl border-0 bg-[#eef2f8] ' +
  'py-[0.85rem] pr-[3.2rem] pl-4 text-[#202124] dark:bg-[#303335] ' +
  'dark:text-[#f1f3f4]';

const ATTACHMENT_IMAGE_CARD_CLASSES =
  'reference-attachment-card reference-attachment-card--image group relative ' +
  'box-border grid size-[4.85rem] flex-none items-center overflow-hidden ' +
  'rounded-2xl border-0 bg-[#eef2f8] p-0 text-[#202124] dark:bg-[#303335] ' +
  'dark:text-[#f1f3f4]';

const ATTACHMENT_PREVIEW_IMAGE_CLASSES = 'block size-full object-cover';

const ATTACHMENT_TEXT_CLASSES =
  'reference-attachment-text grid min-w-0 gap-[0.48rem]';

const ATTACHMENT_NAME_CLASSES =
  'overflow-hidden text-ellipsis whitespace-nowrap text-base font-medium ' +
  'leading-[1.15]';

const ATTACHMENT_META_CLASSES =
  'flex min-w-0 items-center gap-[0.55rem] text-[0.9rem] leading-[1.2] ' +
  'text-[#202124] dark:text-[#e8eaed]';

const ATTACHMENT_EXTENSION_CLASSES =
  'reference-attachment-extension inline-grid h-[1.35rem] min-w-[1.35rem] ' +
  'place-items-center rounded-[0.18rem] bg-[#7d8797] text-[0.48rem] ' +
  'leading-none font-bold text-white';

const ATTACHMENT_REMOVE_BUTTON_CLASSES =
  'absolute top-[0.62rem] right-[0.62rem] grid size-[2.05rem] ' +
  'cursor-pointer place-items-center rounded-full border-0 bg-white p-0 ' +
  'text-[#3c4043] opacity-0 group-hover:opacity-100 ' +
  'group-focus-within:opacity-100 hover:bg-[#f8fafd] ' +
  'focus-visible:bg-[#f8fafd] focus-visible:outline-none dark:bg-[#202124] ' +
  'dark:text-[#e8eaed] dark:hover:bg-[#3c4043] ' +
  'dark:focus-visible:bg-[#3c4043]';

const ATTACHMENT_REMOVE_ICON_CLASSES = 'text-[1.35rem]';

/** The three phases of a session, shown on the home screen. */
const SESSION_STEPS: ReadonlyArray<{
  n: number;
  title: string;
  body: string;
}> = [
  {
    n: 1,
    title: 'Frame the research goal',
    body: 'Describe the question, add useful context, and define what a strong hypothesis should satisfy.',
  },
  {
    n: 2,
    title: 'Generate hypotheses',
    body: 'Co-Scientist explores mechanisms, evidence, and candidate explanations for the topic.',
  },
  {
    n: 3,
    title: 'Pressure-test the best ideas',
    body: 'Hypotheses are compared against the criteria so the strongest directions rise to the top.',
  },
];

type ActiveMessageMode = 'qa' | 'steering';

interface ComposerAttachment {
  id: string;
  name: string;
  badge: string;
  kind: string;
  isImage: boolean;
  previewUrl: string | null;
}
type ChatWorkspaceLocationState = {
  cosciAction?: 'new-chat' | 'focus-composer';
};

function id(prefix: string): string {
  return `${prefix}-${Date.now()}-${Math.random().toString(16).slice(2)}`;
}

function inferActiveMessageMode(text: string): ActiveMessageMode {
  const trimmed = text.trim();
  if (
    trimmed.endsWith('?') ||
    /^(why|what|how|when|who|which|explain|tell me|can you|could you)\b/i.test(
      trimmed,
    )
  ) {
    return 'qa';
  }
  return 'steering';
}

function formatHomeRunDate(timestamp: number): string {
  return new Intl.DateTimeFormat(undefined, {
    month: 'long',
    day: 'numeric',
    year: 'numeric',
  }).format(new Date(timestamp * 1000));
}

function formatDurationLabel(seconds: number): string {
  const minutes = Math.max(1, Math.round(seconds / 60));
  if (minutes >= 90) {
    const hours = Math.max(1, Math.round(minutes / 60));
    return `${hours} hour${hours === 1 ? '' : 's'}`;
  }
  return `${minutes} minute${minutes === 1 ? '' : 's'}`;
}

function formatHomeRunDuration(run: Run): string {
  const endTime = run.completed_at ?? run.updated_at;
  if (endTime && endTime > run.created_at) {
    return formatDurationLabel(endTime - run.created_at);
  }
  if (run.status === 'completed') {
    return formatDurationLabel(60);
  }
  if (['running', 'queued', 'synthesizing'].includes(run.status)) {
    return 'In progress';
  }
  return run.status.charAt(0).toUpperCase() + run.status.slice(1);
}

function formatHomeRunElapsed(run: Run): string {
  const elapsedSeconds = Math.max(
    0,
    (run.updated_at || Date.now() / 1000) - run.created_at,
  );
  if (elapsedSeconds < 60) return '< 1 minute';
  return formatDurationLabel(elapsedSeconds);
}

function formatHomeRunTimeChip(run: Run): string {
  if (run.status === 'completed') {
    return `Total time: ${formatHomeRunDuration(run)}`;
  }
  if (['running', 'queued', 'synthesizing'].includes(run.status)) {
    return `Time elapsed: ${formatHomeRunElapsed(run)}`;
  }
  return `Status: ${formatHomeRunStatus(run)}`;
}

function formatHomeRunStatus(run: Run): string {
  return run.status.charAt(0).toUpperCase() + run.status.slice(1);
}

async function copyText(text: string) {
  if (navigator.clipboard?.writeText) {
    await navigator.clipboard.writeText(text);
  }
}

function downloadText(
  filename: string,
  text: string,
  type = 'text/markdown;charset=utf-8',
) {
  const blob = new Blob([text], {type});
  const url = URL.createObjectURL(blob);
  const anchor = document.createElement('a');
  anchor.href = url;
  anchor.download = filename;
  anchor.click();
  URL.revokeObjectURL(url);
}

function emitDiagnosticEvent({
  stage,
  run,
  level = 'info',
  payload = {},
}: {
  stage: string;
  run?: string;
  level?: 'info' | 'success' | 'error';
  payload?: Record<string, unknown>;
}) {
  window.dispatchEvent(
    new CustomEvent('cosci-diagnostic-event', {
      detail: {stage, run, level, payload},
    }),
  );
}

function topEloFromHypotheses(hypotheses: Hypothesis[]): number {
  const ratings = hypotheses
    .map(hypothesis => hypothesis.elo_rating)
    .filter(Number.isFinite);
  if (!ratings.length) return BASELINE_ELO_RATING;
  return Math.max(...ratings);
}

function homeRunScore(
  run: Run,
  scoresByRunId: Record<string, number | null>,
): number | null {
  if (run.status !== 'completed') return null;
  return Object.prototype.hasOwnProperty.call(scoresByRunId, run.id)
    ? scoresByRunId[run.id]
    : null;
}

function homeRunProgress(run: Run): number {
  if (run.status === 'completed') return 100;
  const elapsedMinutes = Math.max(
    0,
    Math.round(((run.updated_at || Date.now() / 1000) - run.created_at) / 60),
  );
  if (run.status === 'queued') {
    return Math.max(8, Math.min(18, 8 + elapsedMinutes));
  }
  if (run.status === 'synthesizing') {
    return Math.max(72, Math.min(94, 72 + elapsedMinutes * 2));
  }
  return Math.max(18, Math.min(86, 18 + elapsedMinutes * 3));
}

function isActiveHomeRun(run: Run): boolean {
  return ['running', 'queued', 'synthesizing'].includes(run.status);
}

function homeRunIdeaTitles(goal: string): string[] {
  const normalized = goal.toLowerCase();
  if (normalized.includes('ferroptosis') || normalized.includes('pancreatic')) {
    return [
      'Mitochondrial feedback rescue hypothesis',
      'Lipid peroxide buffering threshold hypothesis',
      'Iron-trafficking checkpoint hypothesis',
    ];
  }
  if (
    normalized.includes('fibrosis') ||
    normalized.includes('mash') ||
    normalized.includes('masld')
  ) {
    return [
      'Epigenetic stromal reversal hypothesis',
      'Fibrotic memory erasure hypothesis',
      'Macrophage remodeling checkpoint hypothesis',
    ];
  }
  if (
    normalized.includes('m.tuberculosis') ||
    normalized.includes('tuberculosis')
  ) {
    return [
      'Metabolic refuge disruption hypothesis',
      'Biofilm redox-state vulnerability hypothesis',
      'Quorum-linked susceptibility restoration hypothesis',
    ];
  }
  if (normalized.includes('synaptic') || normalized.includes('pruning')) {
    return [
      'Microglial timing-window pruning hypothesis',
      'Complement-gated flexibility hypothesis',
      'Activity-dependent dendritic retention hypothesis',
    ];
  }
  return [
    conciseTitle(goal),
    'Mechanistic differentiation hypothesis',
    'Evidence-guided intervention hypothesis',
  ];
}

/**
 * Renders the chat-first AI Co-Scientist workspace.
 */
export function ChatWorkspace() {
  const location = useLocation();
  const navigate = useNavigate();
  const [input, setInput] = useState('');
  const [draftSpec, setDraftSpec] = useState<InferredRunSpec | null>(null);
  const [draftSpecCreatedAt, setDraftSpecCreatedAt] = useState<number | null>(
    null,
  );
  const [confirmedSpec, setConfirmedSpec] = useState<InferredRunSpec | null>(
    null,
  );
  const [confirmedSpecCreatedAt, setConfirmedSpecCreatedAt] = useState<
    number | null
  >(null);
  const [startedSession, setStartedSession] = useState<StartedSession | null>(
    null,
  );
  const [isStarting, setIsStarting] = useState(false);
  const [messages, setMessages] = useState<ChatEntry[]>([]);
  const [history, setHistory] = useState<Run[]>([]);
  const [homeScores, setHomeScores] = useState<Record<string, number | null>>(
    {},
  );
  const [error, setError] = useState<string | null>(null);
  const [hoveredSuggestion, setHoveredSuggestion] = useState<string | null>(
    null,
  );
  const [showAllRecents, setShowAllRecents] = useState(false);
  const [toast, setToast] = useState<string | null>(null);
  const [pubmedEnabled, setPubmedEnabled] = useState(true);
  const scrollRef = useRef<HTMLDivElement>(null);
  const previousTimelineSignature = useRef('');

  useEffect(() => {
    if (!toast) return;
    const timer = window.setTimeout(() => setToast(null), 3000);
    return () => window.clearTimeout(timer);
  }, [toast]);

  const loadHistory = useCallback(async () => {
    const [ownedRuns, demoRuns] = await Promise.all([
      listRuns().catch(() => [] as Run[]),
      listDemoRuns().catch(() => [] as Run[]),
    ]);
    const byId = new Map<string, Run>();
    for (const item of [...ownedRuns, ...demoRuns]) {
      byId.set(item.id, item);
    }
    setHistory([...byId.values()].sort((a, b) => b.updated_at - a.updated_at));
  }, []);

  const resetWorkspace = useCallback(() => {
    setInput('');
    setDraftSpec(null);
    setDraftSpecCreatedAt(null);
    setConfirmedSpec(null);
    setConfirmedSpecCreatedAt(null);
    setStartedSession(null);
    setIsStarting(false);
    setMessages([]);
    setError(null);
    setToast(null);
    void loadHistory();
  }, [loadHistory]);

  const focusComposer = useCallback(() => {
    window.requestAnimationFrame(() => {
      const composer = document.querySelector<HTMLTextAreaElement>(
        '.reference-composer textarea',
      );
      composer?.focus();
    });
  }, []);

  useEffect(() => {
    void loadHistory();
  }, [loadHistory]);

  useEffect(() => {
    const completedRuns = history
      .filter(run => run.status === 'completed')
      .slice(0, 10);
    if (!completedRuns.length) {
      setHomeScores({});
      return;
    }

    let cancelled = false;
    void Promise.all(
      completedRuns.map(async run => {
        try {
          const hypotheses = await getHypotheses(run.id);
          return [run.id, topEloFromHypotheses(hypotheses)] as const;
        } catch {
          return [run.id, null] as const;
        }
      }),
    ).then(entries => {
      if (cancelled) return;
      setHomeScores(Object.fromEntries(entries));
    });

    return () => {
      cancelled = true;
    };
  }, [history]);

  useEffect(() => {
    window.addEventListener('cosci-new-chat', resetWorkspace);
    window.addEventListener('cosci-focus-composer', focusComposer);
    return () => {
      window.removeEventListener('cosci-new-chat', resetWorkspace);
      window.removeEventListener('cosci-focus-composer', focusComposer);
    };
  }, [focusComposer, resetWorkspace]);

  useEffect(() => {
    const state = location.state as ChatWorkspaceLocationState | null;
    if (!state?.cosciAction) return;
    if (state.cosciAction === 'new-chat') resetWorkspace();
    if (state.cosciAction === 'focus-composer') focusComposer();
    void navigate(location.pathname, {replace: true, state: null});
  }, [
    focusComposer,
    location.pathname,
    location.state,
    navigate,
    resetWorkspace,
  ]);

  const hasConversation =
    messages.length > 0 ||
    Boolean(draftSpec) ||
    Boolean(confirmedSpec) ||
    Boolean(startedSession);

  useEffect(() => {
    const title = draftSpec
      ? conciseTitle(draftSpec.goal)
      : startedSession
        ? startedSession.title
        : '';
    window.dispatchEvent(
      new CustomEvent('cosci-header-title', {detail: title}),
    );
    return () => {
      window.dispatchEvent(new CustomEvent('cosci-header-title', {detail: ''}));
    };
  }, [draftSpec, startedSession]);

  function appendAssistant(
    content: string,
    createdAt = Date.now() / 1000,
  ): number {
    setMessages(prev => [
      ...prev,
      {id: id('assistant'), role: 'assistant', content, created_at: createdAt},
    ]);
    return createdAt;
  }

  function appendUser(content: string, createdAt = Date.now() / 1000): number {
    setMessages(prev => [
      ...prev,
      {id: id('user'), role: 'user', content, created_at: createdAt},
    ]);
    return createdAt;
  }

  function handleRetryMessage(message: ChatEntry) {
    appendAssistant(message.content);
  }

  function handleEditMessage(message: ChatEntry) {
    setInput(message.content);
    focusComposer();
  }

  async function handleCopyRequest(message: ChatEntry) {
    await copyText(message.content);
    const copiedSpec = inferRunSpec(message.content);
    const createdAt = Date.now() / 1000;
    setDraftSpec(copiedSpec);
    setDraftSpecCreatedAt(createdAt);
    setConfirmedSpec(null);
    setConfirmedSpecCreatedAt(null);
    setStartedSession(null);
    setToast(null);
    emitDiagnosticEvent({
      stage: 'CHAT',
      run: referenceSetupTitle(copiedSpec.goal),
      payload: {event: 'prompt_copied_to_plan'},
    });
  }

  function handleRetryDraftSpec() {
    if (!draftSpec) return;
    setDraftSpec(inferRunSpec(draftSpec.goal));
    setDraftSpecCreatedAt(Date.now() / 1000);
  }

  function handleCancelDraftSpec() {
    const title = draftSpec ? referenceSetupTitle(draftSpec.goal) : undefined;
    setInput('');
    setDraftSpec(null);
    setDraftSpecCreatedAt(null);
    setConfirmedSpec(null);
    setConfirmedSpecCreatedAt(null);
    setStartedSession(null);
    setMessages([]);
    setError(null);
    setToast('The session was canceled');
    emitDiagnosticEvent({
      stage: 'LIFECYCLE',
      run: title,
      payload: {event: 'draft_cancelled'},
    });
  }

  function handleEditPlan(spec: InferredRunSpec) {
    setDraftSpec(spec);
    setDraftSpecCreatedAt(Date.now() / 1000);
    setConfirmedSpec(null);
    setConfirmedSpecCreatedAt(null);
    setStartedSession(null);
    focusComposer();
    emitDiagnosticEvent({
      stage: 'CHAT',
      run: referenceSetupTitle(spec.goal),
      payload: {event: 'plan_edit_requested'},
    });
  }

  async function handleSubmit(e: FormEvent<HTMLFormElement>) {
    e.preventDefault();
    const text = input.trim();
    if (!text) return;
    setInput('');
    setError(null);
    setToast(null);

    if (draftSpec) {
      const sentAt = appendUser(text);
      const next = reviseRunSpec(draftSpec, text);
      setDraftSpec(next);
      setDraftSpecCreatedAt(sentAt + 0.001);
      setConfirmedSpec(null);
      setConfirmedSpecCreatedAt(null);
      appendAssistant(
        'I updated the run setup. Start it when the spec looks right.',
        sentAt + 0.002,
      );
      emitDiagnosticEvent({
        stage: 'CHAT',
        run: referenceSetupTitle(next.goal),
        payload: {event: 'draft_revised'},
      });
      return;
    }

    const sentAt = appendUser(text);
    const next = inferRunSpec(text);
    setDraftSpec(next);
    setDraftSpecCreatedAt(sentAt + 0.001);
    setConfirmedSpec(null);
    setConfirmedSpecCreatedAt(null);
    emitDiagnosticEvent({
      stage: 'LIFECYCLE',
      run: referenceSetupTitle(next.goal),
      payload: {event: 'draft_created'},
    });
  }

  async function handleStartRun() {
    if (!draftSpec) return;
    const specToStart = draftSpec;
    const specCreatedAt = draftSpecCreatedAt ?? Date.now() / 1000;
    setIsStarting(true);
    setError(null);
    setToast(null);
    emitDiagnosticEvent({
      stage: 'LIFECYCLE',
      run: referenceSetupTitle(specToStart.goal),
      payload: {event: 'start_requested'},
    });
    try {
      const created = await createRun({
        research_goal: specToStart.goal,
        requirements: specToStart.requirements,
        attributes: specToStart.attributes,
        criteria: specToStart.criteria,
        focus: specToStart.focus,
        tier: specToStart.tier,
        enable_literature_review: pubmedEnabled,
        notes: [
          `Requirements: ${specToStart.requirements.join(' | ')}`,
          `Attributes: ${specToStart.attributes.join(' | ')}`,
          `Criteria: ${specToStart.criteria.join(' | ')}`,
          `Focus: ${specToStart.focus}`,
          `Tier: ${specToStart.tier}`,
        ].join('\n'),
      });
      const session: StartedSession = {
        id: created.id,
        title: referenceSetupTitle(specToStart.goal),
        at: Date.now() / 1000,
      };
      setConfirmedSpec(specToStart);
      setConfirmedSpecCreatedAt(specCreatedAt);
      setDraftSpec(null);
      setDraftSpecCreatedAt(null);
      await startRun(created.id);
      setStartedSession(session);
      await loadHistory();
      emitDiagnosticEvent({
        stage: 'LIFECYCLE',
        run: session.title,
        level: 'success',
        payload: {event: 'start_queued', run_id: created.id},
      });
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
      emitDiagnosticEvent({
        stage: 'LIFECYCLE',
        run: referenceSetupTitle(specToStart.goal),
        level: 'error',
        payload: {
          event: 'start_failed',
          message: err instanceof Error ? err.message : String(err),
        },
      });
    } finally {
      setIsStarting(false);
    }
  }

  const timelineItems: TimelineItem[] = [];
  for (const [index, message] of messages.entries()) {
    timelineItems.push({
      id: `local-message-${message.id}`,
      at: message.created_at,
      order: index,
      node: (
        <ChatBubble
          message={message}
          onEdit={() => handleEditMessage(message)}
          onCopyRequest={() => void handleCopyRequest(message)}
          onRetry={() => handleRetryMessage(message)}
        />
      ),
    });
  }
  if (draftSpec && draftSpecCreatedAt !== null) {
    timelineItems.push({
      id: 'draft-spec',
      at: draftSpecCreatedAt,
      order: 50,
      node: (
        <RunSpecCard
          spec={draftSpec}
          isStarting={isStarting}
          onFocusChange={focus =>
            setDraftSpec(current => (current ? {...current, focus} : current))
          }
          onTierChange={tier =>
            setDraftSpec(current => (current ? {...current, tier} : current))
          }
          onCancel={handleCancelDraftSpec}
          onEdit={() => handleEditPlan(draftSpec)}
          onRetry={() => handleRetryDraftSpec()}
          onStart={() => void handleStartRun()}
        />
      ),
    });
  }
  if (confirmedSpec && confirmedSpecCreatedAt !== null) {
    timelineItems.push({
      id: 'confirmed-spec',
      at: confirmedSpecCreatedAt,
      order: 50,
      node: (
        <RunSpecCard
          spec={confirmedSpec}
          isStarting={false}
          locked
          onFocusChange={() => undefined}
          onTierChange={() => undefined}
          onCancel={() => undefined}
          onEdit={() => handleEditPlan(confirmedSpec)}
          onRetry={() => {
            setDraftSpec(confirmedSpec);
            setDraftSpecCreatedAt(Date.now() / 1000);
            setConfirmedSpec(null);
            setConfirmedSpecCreatedAt(null);
          }}
          onStart={() => undefined}
        />
      ),
    });
  }
  if (startedSession) {
    timelineItems.push({
      id: `started-session-${startedSession.id}`,
      at: startedSession.at,
      order: 60,
      node: (
        <StartedSessionCard
          session={startedSession}
          onOpen={() => void navigate(`/runs/${startedSession.id}/details`)}
          onRetry={() =>
            setStartedSession(current =>
              current ? {...current, at: Date.now() / 1000} : current,
            )
          }
          onNewTopic={() => {
            resetWorkspace();
            focusComposer();
          }}
        />
      ),
    });
  }
  timelineItems.sort((a, b) => a.at - b.at || a.order - b.order);
  const timelineSignature = timelineItems
    .map(item => `${item.id}:${item.at}`)
    .join('|');
  const latestTimelineItemId =
    timelineItems.length > 0 ? timelineItems[timelineItems.length - 1].id : '';
  const timelineAnchorMode = startedSession
    ? 'bottom'
    : latestTimelineItemId === 'draft-spec' ||
        latestTimelineItemId === 'confirmed-spec'
      ? 'top'
      : 'bottom';

  useEffect(() => {
    const scroller = scrollRef.current;
    if (!scroller || previousTimelineSignature.current === timelineSignature) {
      return;
    }
    previousTimelineSignature.current = timelineSignature;
    const timeout = window.setTimeout(() => {
      scroller.scrollTop =
        timelineAnchorMode === 'top' ? 0 : scroller.scrollHeight;
    }, 0);
    return () => window.clearTimeout(timeout);
  }, [timelineAnchorMode, timelineSignature]);

  useEffect(() => {
    const scroller = scrollRef.current;
    if (!startedSession || !scroller) {
      return;
    }
    const timeout = window.setTimeout(() => {
      scroller.scrollTop = scroller.scrollHeight;
    }, 0);
    return () => window.clearTimeout(timeout);
  }, [startedSession]);

  const homeRecentRuns = showAllRecents ? history : history.slice(0, 4);
  const hasHomeRecentRuns = homeRecentRuns.length > 0;
  const hasExtraRecents = history.length > 4;
  const recentsPanelClassName = hasHomeRecentRuns
    ? RECENTS_PANEL_CLASSES
    : EMPTY_RECENTS_PANEL_CLASSES;
  const recentsListClassName = hasHomeRecentRuns
    ? RECENTS_LIST_CLASSES
    : EMPTY_RECENTS_LIST_CLASSES;
  return (
    <div className={HOME_WORKSPACE_CLASSES}>
      <main className={HOME_WORKSPACE_MAIN_CLASSES}>
        {!hasConversation ? (
          <section className={HOME_STAGE_CLASSES}>
            <div className={HOME_MAIN_CLASSES}>
              <h1 className={HOME_TITLE_CLASSES}>
                What breakthrough should we make today?
              </h1>

              <ol className={HOME_STEP_TIMELINE_CLASSES}>
                {SESSION_STEPS.map((step, index) => (
                  <li
                    key={step.n}
                    className={[
                      HOME_STEP_ITEM_CLASSES,
                      index === 1 ? HOME_STEP_ITEM_CENTER_CLASSES : '',
                      index === 2 ? HOME_STEP_ITEM_END_CLASSES : '',
                    ]
                      .filter(Boolean)
                      .join(' ')}
                  >
                    <span className={HOME_STEP_NUMBER_CLASSES}>{step.n}</span>
                    <div>
                      <h2 className={HOME_STEP_HEADING_CLASSES}>
                        {step.title}
                      </h2>
                      <p className={HOME_STEP_BODY_CLASSES}>{step.body}</p>
                    </div>
                  </li>
                ))}
              </ol>

              <div className={HOME_SUGGESTION_ROW_CLASSES}>
                {SUGGESTIONS.map((suggestion, index) => {
                  const isPreviewed = hoveredSuggestion === suggestion.full;
                  const previewPositionClass =
                    index === 0
                      ? HOME_SUGGESTION_PREVIEW_START_CLASSES
                      : index === 1
                        ? HOME_SUGGESTION_PREVIEW_CENTER_CLASSES
                        : HOME_SUGGESTION_PREVIEW_END_CLASSES;
                  return (
                    <div
                      key={suggestion.short}
                      className={HOME_SUGGESTION_SLOT_CLASSES}
                    >
                      <p
                        className={[
                          HOME_SUGGESTION_PREVIEW_CLASSES,
                          previewPositionClass,
                          isPreviewed
                            ? HOME_SUGGESTION_PREVIEW_VISIBLE_CLASSES
                            : '',
                        ]
                          .filter(Boolean)
                          .join(' ')}
                        aria-hidden={!isPreviewed}
                      >
                        {suggestion.full}
                      </p>
                      <button
                        type="button"
                        className={[
                          HOME_SUGGESTION_BUTTON_CLASSES,
                          isPreviewed
                            ? HOME_SUGGESTION_BUTTON_PREVIEWED_CLASSES
                            : '',
                        ]
                          .filter(Boolean)
                          .join(' ')}
                        onMouseEnter={() =>
                          setHoveredSuggestion(suggestion.full)
                        }
                        onMouseLeave={() => setHoveredSuggestion(null)}
                        onPointerEnter={() =>
                          setHoveredSuggestion(suggestion.full)
                        }
                        onPointerLeave={() => setHoveredSuggestion(null)}
                        onFocus={() => setHoveredSuggestion(suggestion.full)}
                        onBlur={() => setHoveredSuggestion(null)}
                        onClick={() => {
                          setInput(suggestion.full);
                          setHoveredSuggestion(null);
                        }}
                      >
                        <span className={HOME_SUGGESTION_TEXT_CLASSES}>
                          {suggestion.short}
                        </span>
                      </button>
                    </div>
                  );
                })}
              </div>

              <Composer
                input={input}
                setInput={setInput}
                isEditingSpec={false}
                disabled={false}
                large
                reference
                pubmedEnabled={pubmedEnabled}
                onPubmedEnabledChange={setPubmedEnabled}
                onSubmit={handleSubmit}
                onSuggestion={suggestion => setInput(suggestion)}
              />
            </div>

            <aside className={recentsPanelClassName} aria-label="Recent runs">
              <div className={HOME_RECENTS_HEADING_ROW_CLASSES}>
                <md-icon
                  aria-hidden="true"
                  className={RECENTS_HEADING_ICON_CLASSES}
                >
                  history
                </md-icon>
                <h2 className={RECENTS_HEADING_CLASSES}>Recents</h2>
              </div>
              <ol className={recentsListClassName}>
                {hasHomeRecentRuns ? (
                  homeRecentRuns.map(run => {
                    const topIdeas = homeRunIdeaTitles(run.research_goal);
                    const isActiveRun = isActiveHomeRun(run);
                    const topScore = homeRunScore(run, homeScores);
                    return (
                      <li key={run.id}>
                        <Link
                          to={`/runs/${run.id}/details`}
                          className={
                            isActiveRun
                              ? ACTIVE_RECENT_CARD_CLASSES
                              : RECENT_CARD_CLASSES
                          }
                          title={run.research_goal}
                        >
                          <span className={RECENT_META_CLASSES}>
                            <span className={RECENT_META_CHIP_CLASSES}>
                              {formatHomeRunDate(run.updated_at)}
                            </span>
                            <span className={RECENT_META_CHIP_CLASSES}>
                              {formatHomeRunTimeChip(run)}
                            </span>
                          </span>
                          <strong className={RECENT_TITLE_CLASSES}>
                            {conciseTitle(run.research_goal)}
                          </strong>
                          <span className={RECENT_DESCRIPTION_CLASSES}>
                            {run.research_goal}
                          </span>
                          {isActiveRun ? (
                            <div className={ACTIVE_PROGRESS_CLASSES}>
                              <span
                                aria-hidden="true"
                                className={ACTIVE_PROGRESS_DOT_CLASSES}
                              />
                              <span>In Progress: {homeRunProgress(run)}%</span>
                            </div>
                          ) : (
                            <span className={RECENT_CHIPS_CLASSES}>
                              <span className={RECENT_CHIP_CLASSES}>
                                <md-icon
                                  aria-hidden="true"
                                  className={RECENT_CHIP_ICON_CLASSES}
                                >
                                  emoji_events
                                </md-icon>
                                Winning ideas
                              </span>
                              {topScore !== null && (
                                <span className={RECENT_CHIP_CLASSES}>
                                  <md-icon
                                    aria-hidden="true"
                                    className={RECENT_CHIP_ICON_CLASSES}
                                  >
                                    stars
                                  </md-icon>
                                  Top score: {topScore}
                                </span>
                              )}
                            </span>
                          )}
                          <ol className={WINNER_LIST_CLASSES}>
                            {isActiveRun ? (
                              <li className={GENERATING_ROW_CLASSES}>
                                <span
                                  aria-hidden="true"
                                  className={GENERATING_DOT_CLASSES}
                                />
                                <span>Generating hypotheses</span>
                              </li>
                            ) : (
                              topIdeas.map((idea, index) => (
                                <li
                                  key={idea}
                                  className={WINNER_LIST_ITEM_CLASSES}
                                >
                                  <span>{index + 1}.</span>
                                  <span>{idea}</span>
                                </li>
                              ))
                            )}
                          </ol>
                        </Link>
                      </li>
                    );
                  })
                ) : (
                  <li className={EMPTY_RECENTS_ITEM_CLASSES}>
                    <div className={EMPTY_RECENTS_CLASSES}>
                      <GoogleLabsIcon
                        aria-hidden="true"
                        className={EMPTY_RECENTS_ICON_CLASSES}
                      />
                      <strong className={EMPTY_RECENTS_COPY_CLASSES}>
                        You have not started any sessions yet.
                      </strong>
                    </div>
                  </li>
                )}
                {hasExtraRecents && (
                  <li className={HOME_LOAD_MORE_ITEM_CLASSES}>
                    <button
                      type="button"
                      className={HOME_LOAD_MORE_BUTTON_CLASSES}
                      onClick={() => setShowAllRecents(current => !current)}
                    >
                      {showAllRecents ? 'Show less' : 'Show more'}
                    </button>
                  </li>
                )}
              </ol>
            </aside>
          </section>
        ) : (
          <>
            <section ref={scrollRef} className={CHAT_TIMELINE_CLASSES}>
              <div className={CHAT_COLUMN_CLASSES}>
                {timelineItems.map(item => (
                  <Fragment key={item.id}>{item.node}</Fragment>
                ))}

                {error && (
                  <div
                    role="alert"
                    className="rounded-md border p-3 text-sm"
                    style={{
                      borderColor: 'var(--md-sys-color-error)',
                      color: 'var(--md-sys-color-error)',
                    }}
                  >
                    {error}
                  </div>
                )}
              </div>
            </section>
            <div className={CHAT_COMPOSER_CLASSES}>
              <div className={CHAT_COLUMN_CLASSES}>
                <Composer
                  input={input}
                  setInput={setInput}
                  isEditingSpec={false}
                  activeMessageMode={inferActiveMessageMode(input)}
                  setupDraftMode={Boolean(draftSpec || startedSession)}
                  disabled={isStarting}
                  reference
                  pubmedEnabled={pubmedEnabled}
                  onPubmedEnabledChange={setPubmedEnabled}
                  onSubmit={handleSubmit}
                  onSuggestion={suggestion => setInput(suggestion)}
                />
              </div>
            </div>
          </>
        )}
        {toast && (
          <div className={HOME_TOAST_CLASSES} role="status">
            {toast}
          </div>
        )}
      </main>
    </div>
  );
}

function fileToAttachment(file: File): ComposerAttachment {
  const extension = fileExtension(file.name);
  const isImage = file.type.startsWith('image/');
  return {
    id: `${file.name}-${file.lastModified}-${Math.random().toString(36).slice(2)}`,
    name: file.name,
    badge: fileBadge(extension),
    kind: fileKind(file, extension),
    isImage,
    previewUrl: isImage ? URL.createObjectURL(file) : null,
  };
}

function fileExtension(name: string) {
  const extension = name.split('.').pop()?.trim();
  return extension ? extension.slice(0, 8).toLowerCase() : '';
}

function fileBadge(extension: string) {
  if (['md', 'mkdn', 'markdown', 'txt'].includes(extension)) return 'TXT';
  return extension ? extension.slice(0, 4).toUpperCase() : 'FILE';
}

function fileKind(file: File, extension: string) {
  if (['md', 'mkdn', 'markdown'].includes(extension)) return 'Markdown';
  if (file.type.startsWith('text/') || extension === 'txt') return 'Text';
  if (extension === 'pdf') return 'PDF';
  if (extension === 'csv') return 'CSV';
  return (
    file.type
      .split('/')
      .pop()
      ?.replace(/[-+].*/, '')
      .toUpperCase() ?? 'File'
  );
}

function Composer({
  input,
  setInput,
  isEditingSpec,
  activeRunId = null,
  activeMessageMode = 'steering',
  canSteerActiveRun = false,
  isAnswering = false,
  setupDraftMode = false,
  disabled,
  large = false,
  reference = false,
  pubmedEnabled = true,
  onPubmedEnabledChange,
  onSubmit,
  onSuggestion,
}: {
  input: string;
  setInput: (value: string) => void;
  isEditingSpec: boolean;
  activeRunId?: string | null;
  activeMessageMode?: ActiveMessageMode;
  canSteerActiveRun?: boolean;
  isAnswering?: boolean;
  setupDraftMode?: boolean;
  disabled: boolean;
  large?: boolean;
  reference?: boolean;
  pubmedEnabled?: boolean;
  onPubmedEnabledChange?: (value: boolean) => void;
  onSubmit: (e: FormEvent<HTMLFormElement>) => void;
  onSuggestion: (value: string) => void;
}) {
  const fileInputRef = useRef<HTMLInputElement>(null);
  const sourceControlsRef = useRef<HTMLDivElement>(null);
  const attachmentRef = useRef<ComposerAttachment[]>([]);
  const [attachments, setAttachments] = useState<ComposerAttachment[]>([]);
  const [connectorsOpen, setConnectorsOpen] = useState(false);

  function onKeyDown(e: KeyboardEvent<HTMLTextAreaElement>) {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      e.currentTarget.form?.requestSubmit();
    }
  }

  function onFilesChanged(e: ChangeEvent<HTMLInputElement>) {
    const nextAttachments = Array.from(e.target.files ?? []).map(file =>
      fileToAttachment(file),
    );
    setAttachments(current => [...current, ...nextAttachments]);
    e.target.value = '';
  }

  function removeAttachment(id: string) {
    setAttachments(current => {
      const attachment = current.find(item => item.id === id);
      if (attachment?.previewUrl) URL.revokeObjectURL(attachment.previewUrl);
      return current.filter(item => item.id !== id);
    });
  }

  useEffect(() => {
    attachmentRef.current = attachments;
  }, [attachments]);

  useEffect(() => {
    return () => {
      attachmentRef.current.forEach(attachment => {
        if (attachment.previewUrl) URL.revokeObjectURL(attachment.previewUrl);
      });
    };
  }, []);

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

  const hasRunContext = Boolean(activeRunId);
  const referenceLabel = hasRunContext
    ? isEditingSpec
      ? 'Type to edit session details'
      : 'Ask Co-Scientist'
    : setupDraftMode
      ? 'Type to edit session details'
      : 'Start a new research goal to begin';
  const placeholder = isEditingSpec
    ? 'Describe the change to the run setup...'
    : setupDraftMode
      ? ''
      : hasRunContext
        ? activeMessageMode === 'qa' || !canSteerActiveRun
          ? 'Ask what this run is doing...'
          : 'Ask a question or steer the active run...'
        : '';
  const submitLabel = hasRunContext
    ? isAnswering
      ? 'Answering...'
      : activeMessageMode === 'qa' || !canSteerActiveRun
        ? 'Ask'
        : 'Send'
    : 'Send';

  if (reference) {
    return (
      <form
        onSubmit={onSubmit}
        className={[
          COMPOSER_BASE_CLASSES,
          input.trim() ? 'has-input' : '',
          large ? HOME_COMPOSER_CLASSES : '',
          attachments.length ? REFERENCE_COMPOSER_ATTACHED_CLASSES : '',
        ]
          .filter(Boolean)
          .join(' ')}
      >
        {attachments.length > 0 ? (
          <div className={ATTACHMENT_STRIP_CLASSES} aria-label="Attachments">
            {attachments.map(attachment =>
              attachment.isImage && attachment.previewUrl ? (
                <div
                  className={tooltipClassNames({
                    className: ATTACHMENT_IMAGE_CARD_CLASSES,
                    placement: 'top',
                    wrap: true,
                  })}
                  key={attachment.id}
                  data-tooltip={attachment.name}
                >
                  <img
                    src={attachment.previewUrl}
                    alt={attachment.name}
                    className={ATTACHMENT_PREVIEW_IMAGE_CLASSES}
                  />
                  <button
                    type="button"
                    className={tooltipClassNames({
                      className: ATTACHMENT_REMOVE_BUTTON_CLASSES,
                      placement: 'top',
                    })}
                    aria-label={`Remove ${attachment.name}`}
                    data-tooltip={`Remove ${attachment.name}`}
                    onClick={() => removeAttachment(attachment.id)}
                  >
                    <md-icon
                      aria-hidden="true"
                      className={ATTACHMENT_REMOVE_ICON_CLASSES}
                    >
                      close
                    </md-icon>
                  </button>
                </div>
              ) : (
                <div
                  className={tooltipClassNames({
                    className: ATTACHMENT_CARD_CLASSES,
                    placement: 'top',
                    wrap: true,
                  })}
                  key={attachment.id}
                  data-tooltip={attachment.name}
                >
                  <div className={ATTACHMENT_TEXT_CLASSES}>
                    <strong className={ATTACHMENT_NAME_CLASSES}>
                      {attachment.name}
                    </strong>
                    <span className={ATTACHMENT_META_CLASSES}>
                      <span className={ATTACHMENT_EXTENSION_CLASSES}>
                        {attachment.badge}
                      </span>
                      {attachment.kind}
                    </span>
                  </div>
                  <button
                    type="button"
                    className={tooltipClassNames({
                      className: ATTACHMENT_REMOVE_BUTTON_CLASSES,
                      placement: 'top',
                    })}
                    aria-label={`Remove ${attachment.name}`}
                    data-tooltip={`Remove ${attachment.name}`}
                    onClick={() => removeAttachment(attachment.id)}
                  >
                    <md-icon
                      aria-hidden="true"
                      className={ATTACHMENT_REMOVE_ICON_CLASSES}
                    >
                      close
                    </md-icon>
                  </button>
                </div>
              ),
            )}
          </div>
        ) : null}
        <label className={COMPOSER_LABEL_CLASSES}>
          <span
            className={[
              COMPOSER_LABEL_TEXT_CLASSES,
              input.trim() ? COMPOSER_LABEL_TEXT_HIDDEN_CLASSES : '',
            ]
              .filter(Boolean)
              .join(' ')}
          >
            <md-icon aria-hidden="true" className={COMPOSER_LABEL_ICON_CLASSES}>
              shield
            </md-icon>
            {referenceLabel}
          </span>
          <textarea
            rows={large ? 4 : 3}
            value={input}
            disabled={disabled}
            className={[
              COMPOSER_TEXTAREA_CLASSES,
              large ? HOME_COMPOSER_TEXTAREA_CLASSES : '',
            ]
              .filter(Boolean)
              .join(' ')}
            onChange={e => setInput(e.target.value)}
            onKeyDown={onKeyDown}
            placeholder={placeholder}
          />
        </label>
        <div className={COMPOSER_ACTIONS_CLASSES}>
          <div
            className={COMPOSER_SOURCE_CONTROLS_CLASSES}
            ref={sourceControlsRef}
          >
            <input
              ref={fileInputRef}
              className={COMPOSER_FILE_INPUT_CLASSES}
              type="file"
              multiple
              aria-label="Upload files"
              onChange={onFilesChanged}
              tabIndex={-1}
            />
            <button
              type="button"
              className={tooltipClassNames({
                className: COMPOSER_SOURCE_BUTTON_CLASSES,
                placement: 'top',
              })}
              aria-label="Files"
              data-tooltip="Files"
              disabled={disabled}
              onClick={() => fileInputRef.current?.click()}
            >
              <md-icon
                aria-hidden="true"
                className={COMPOSER_SOURCE_ICON_CLASSES}
              >
                add
              </md-icon>
            </button>
            <button
              type="button"
              className={tooltipClassNames({
                className: COMPOSER_SOURCE_BUTTON_CLASSES,
                placement: 'top',
              })}
              aria-label="Connectors"
              aria-expanded={connectorsOpen}
              data-tooltip="Connectors"
              disabled={disabled}
              onClick={() => setConnectorsOpen(open => !open)}
            >
              <md-icon
                aria-hidden="true"
                className={COMPOSER_SOURCE_ICON_CLASSES}
              >
                database
              </md-icon>
            </button>
            {connectorsOpen ? (
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
                    <md-icon
                      className={CONNECTOR_ICON_CLASSES}
                      aria-hidden="true"
                    >
                      article
                    </md-icon>
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
            ) : null}
          </div>
          <button
            type="submit"
            className={tooltipClassNames({
              className: COMPOSER_SUBMIT_BUTTON_CLASSES,
              placement: 'top',
            })}
            aria-label={submitLabel}
            data-tooltip="Submit"
            disabled={!input.trim() || disabled}
          >
            <md-icon aria-hidden="true">send</md-icon>
          </button>
        </div>
      </form>
    );
  }

  return (
    <form
      onSubmit={onSubmit}
      className="rounded-xl border p-3"
      style={{
        borderColor: 'var(--md-sys-color-outline-variant)',
        backgroundColor: 'var(--md-sys-color-surface-container-low)',
      }}
    >
      <textarea
        className="block w-full resize-none bg-transparent text-base outline-none placeholder:text-[color:var(--md-sys-color-on-surface-variant)]"
        rows={large ? 5 : 3}
        value={input}
        disabled={disabled}
        onChange={e => setInput(e.target.value)}
        onKeyDown={onKeyDown}
        placeholder={placeholder}
        style={{
          color: 'var(--md-sys-color-on-surface)',
          minHeight: large ? '9rem' : '5.5rem',
        }}
      />
      <div className="flex flex-col gap-2 pt-3 sm:flex-row sm:items-center sm:justify-between">
        <div className="flex flex-wrap items-center gap-2">
          {large && (
            <div className="hidden md:flex flex-wrap gap-1.5">
              {SUGGESTIONS.map(suggestion => (
                <button
                  key={suggestion.short}
                  type="button"
                  onClick={() => onSuggestion(suggestion.full)}
                  className="cursor-pointer rounded-full border px-2.5 py-1 text-xs"
                  style={{
                    borderColor: 'var(--md-sys-color-outline-variant)',
                    color: 'var(--md-sys-color-on-surface-variant)',
                  }}
                >
                  {suggestion.short}
                </button>
              ))}
            </div>
          )}
        </div>
        <md-filled-button
          type="submit"
          disabled={!input.trim() || disabled || undefined}
        >
          <md-icon slot="icon" aria-hidden="true">
            arrow_upward
          </md-icon>
          {submitLabel}
        </md-filled-button>
      </div>
    </form>
  );
}

interface MessageAction {
  icon: string;
  label: string;
  onClick: () => void;
}

function MessageActionRow({
  actions,
  align = 'start',
}: {
  actions: MessageAction[];
  align?: 'start' | 'end';
}) {
  return (
    <div
      className={
        align === 'end' ? MESSAGE_ACTIONS_END_CLASSES : MESSAGE_ACTIONS_CLASSES
      }
    >
      {actions.map(action => (
        <button
          key={action.label}
          type="button"
          className={tooltipClassNames({
            className: MESSAGE_ACTION_BUTTON_CLASSES,
            placement: 'top',
          })}
          aria-label={action.label}
          data-tooltip={action.label}
          onClick={action.onClick}
        >
          <md-icon aria-hidden="true" className={MESSAGE_ACTION_ICON_CLASSES}>
            {action.icon}
          </md-icon>
        </button>
      ))}
    </div>
  );
}

function ChatBubble({
  message,
  onEdit,
  onCopyRequest,
  onRetry,
}: {
  message: ChatEntry;
  onEdit: () => void;
  onCopyRequest: () => void;
  onRetry: () => void;
}) {
  const isUser = message.role === 'user';
  const textRef = useRef<HTMLSpanElement>(null);
  const [canCollapse, setCanCollapse] = useState(false);
  const [expanded, setExpanded] = useState(false);

  useLayoutEffect(() => {
    if (!isUser || !textRef.current) {
      setCanCollapse(false);
      return;
    }
    const element = textRef.current;
    const styles = window.getComputedStyle(element);
    const fontSize = Number.parseFloat(styles.fontSize) || 16;
    const lineHeight =
      Number.parseFloat(styles.lineHeight) || Math.round(fontSize * 1.45);
    const naturalHeight = element.scrollHeight;
    const exceedsThreeLines = naturalHeight > lineHeight * 3 + 2;
    setCanCollapse(exceedsThreeLines || message.content.length > 140);
    setExpanded(false);
  }, [isUser, message.content]);

  const bubbleClassName = isUser ? USER_BUBBLE_CLASSES : MODEL_BUBBLE_CLASSES;

  return (
    <div
      className={
        isUser ? CHAT_BUBBLE_USER_ROW_CLASSES : CHAT_BUBBLE_ROW_CLASSES
      }
    >
      <div className={bubbleClassName}>
        <span
          ref={isUser ? textRef : undefined}
          className={
            isUser && canCollapse && !expanded
              ? USER_BUBBLE_TEXT_COLLAPSED_CLASSES
              : USER_BUBBLE_TEXT_CLASSES
          }
        >
          {message.content}
        </span>
        {isUser && canCollapse && (
          <button
            type="button"
            className={USER_COLLAPSE_BUTTON_CLASSES}
            aria-label={expanded ? 'Collapse request' : 'Expand request'}
            title={expanded ? 'Collapse request' : 'Expand request'}
            onClick={() => setExpanded(current => !current)}
          >
            <md-icon aria-hidden="true">
              {expanded ? 'expand_less' : 'expand_more'}
            </md-icon>
          </button>
        )}
      </div>
      {isUser ? (
        <MessageActionRow
          align="end"
          actions={[
            {
              icon: 'edit',
              label: 'Edit request',
              onClick: onEdit,
            },
            {
              icon: 'content_copy',
              label: 'Copy request',
              onClick: onCopyRequest,
            },
          ]}
        />
      ) : (
        <MessageActionRow
          actions={[
            {icon: 'refresh', label: 'Retry response', onClick: onRetry},
            {
              icon: 'content_copy',
              label: 'Copy response',
              onClick: () => void copyText(message.content),
            },
            {
              icon: 'download',
              label: 'Download response',
              onClick: () =>
                downloadText('co-scientist-response.md', message.content),
            },
          ]}
        />
      )}
    </div>
  );
}

function RunSpecCard({
  spec,
  isStarting,
  locked = false,
  onFocusChange,
  onTierChange,
  onCancel,
  onEdit,
  onRetry,
  onStart,
}: {
  spec: InferredRunSpec;
  isStarting: boolean;
  locked?: boolean;
  onFocusChange: (focus: RunFocus) => void;
  onTierChange: (tier: RunTier) => void;
  onCancel: () => void;
  onEdit: () => void;
  onRetry: () => void;
  onStart: () => void;
}) {
  const responseText = formatRunSpecResponse(spec);

  return (
    <section className={SETUP_MESSAGE_CLASSES} aria-label="Inferred run setup">
      <p className={SETUP_PARAGRAPH_CLASSES}>
        Okay, I've drafted the requirements to propose a novel, testable
        hypothesis for this research session. Let me know if you have any
        suggestions.
      </p>
      <p className={`reference-review-copy ${SETUP_PARAGRAPH_CLASSES}`}>
        Please review or edit the details below as needed. Once ready, click
        "Start research" to start generating hypotheses.
      </p>
      <div className={PLAN_HEADING_CLASSES}>
        <h2 className={PLAN_TITLE_CLASSES}>Research plan</h2>
        <button
          type="button"
          className={tooltipClassNames({
            className: PLAN_EDIT_BUTTON_CLASSES,
            placement: 'top',
          })}
          aria-label="Edit research plan"
          data-tooltip="Edit research plan"
          onClick={onEdit}
        >
          <md-icon aria-hidden="true" className={PLAN_EDIT_ICON_CLASSES}>
            edit
          </md-icon>
        </button>
      </div>
      <p className={PLAN_SUBHEADING_CLASSES}>
        Here's my plan to tackle the topic:
      </p>
      <div className={SETUP_DOCUMENT_CLASSES}>
        <h3 className={SETUP_DOCUMENT_TITLE_CLASSES}>
          {referenceSetupTitle(spec.goal)}
        </h3>
        <dl className={SPEC_GRID_CLASSES}>
          <SpecRow label="Goal">{spec.goal}</SpecRow>
          <SpecList label="Requirements" values={spec.requirements} />
          <SpecList label="Attributes" values={spec.attributes} />
          <SpecList label="Criteria" values={spec.criteria} />
        </dl>
        <RunOptionGroup
          label="Focus"
          name="focus"
          value={spec.focus}
          options={FOCUS_OPTIONS}
          disabled={locked}
          onChange={value => onFocusChange(value as RunFocus)}
        />
        <RunOptionGroup
          label="Tier"
          name="tier"
          value={spec.tier}
          options={TIER_OPTIONS}
          disabled={locked}
          onChange={value => onTierChange(value as RunTier)}
        />
        <div className={SETUP_ACTIONS_CLASSES}>
          {!locked && (
            <button
              type="button"
              className={SETUP_SECONDARY_BUTTON_CLASSES}
              onClick={onCancel}
              disabled={isStarting}
            >
              Cancel
            </button>
          )}
          <button
            type="button"
            className={SETUP_PRIMARY_BUTTON_CLASSES}
            onClick={onStart}
            disabled={isStarting || locked}
          >
            {isStarting ? 'Starting...' : 'Start research'}
          </button>
        </div>
      </div>
      <MessageActionRow
        actions={[
          {icon: 'refresh', label: 'Retry response', onClick: onRetry},
          {
            icon: 'content_copy',
            label: 'Copy response',
            onClick: () => void copyText(responseText),
          },
          {
            icon: 'download',
            label: 'Download response',
            onClick: () =>
              downloadText('co-scientist-research-plan.md', responseText),
          },
        ]}
      />
    </section>
  );
}

function formatRunSpecResponse(spec: InferredRunSpec): string {
  return [
    `# ${referenceSetupTitle(spec.goal)}`,
    '',
    "I've drafted the requirements to propose a novel, testable hypothesis for this research session.",
    '',
    '## Goal',
    spec.goal,
    '',
    '## Requirements',
    ...spec.requirements.map(value => `* ${value}`),
    '',
    '## Attributes',
    ...spec.attributes.map(value => `* ${value}`),
    '',
    '## Criteria',
    ...spec.criteria.map(value => `* ${value}`),
    '',
    '## Setup Options',
    `* **Focus:** ${runOptionLabel(FOCUS_OPTIONS, spec.focus)}`,
    `* **Tier:** ${runOptionLabel(TIER_OPTIONS, spec.tier)}`,
  ].join('\n');
}

function runOptionLabel(
  options: ReadonlyArray<{id: string; label: string}>,
  value: string,
): string {
  return options.find(option => option.id === value)?.label || value;
}

function StartedSessionCard({
  session,
  onOpen,
  onRetry,
  onNewTopic,
}: {
  session: StartedSession;
  onOpen: () => void;
  onRetry: () => void;
  onNewTopic: () => void;
}) {
  const responseText = formatStartedSessionResponse(session);

  return (
    <section
      className={STARTED_MESSAGE_CLASSES}
      aria-label="Started research session"
    >
      <div className={STARTED_COPY_CLASSES}>
        <p className={STARTED_COPY_PARAGRAPH_CLASSES}>
          Your session has been started and Co-Scientist has started research!
        </p>
        <p className={STARTED_COPY_PARAGRAPH_CLASSES}>
          You can view and interact with your session at any time, but note that
          it might take a few minutes for the first ideas to be ready to view.
        </p>
      </div>
      <button
        type="button"
        className={STARTED_SESSION_CARD_CLASSES}
        onClick={onOpen}
      >
        <span>
          <strong className={STARTED_SESSION_TITLE_CLASSES}>
            {session.title}
          </strong>
          <small className={STARTED_SESSION_META_CLASSES}>
            Research session
          </small>
        </span>
        <span className={STARTED_OPEN_CLASSES}>Open</span>
      </button>
      <div className={STARTED_NEXT_CLASSES}>
        <p className={STARTED_NEXT_COPY_CLASSES}>
          What would you like to do next?
        </p>
        <button
          type="button"
          className={STARTED_NEXT_BUTTON_CLASSES}
          onClick={onOpen}
        >
          View session details
        </button>
        <button
          type="button"
          className={STARTED_NEXT_BUTTON_CLASSES}
          onClick={onNewTopic}
        >
          Start a new research goal session on a new topic
        </button>
      </div>
      <MessageActionRow
        actions={[
          {icon: 'refresh', label: 'Retry response', onClick: onRetry},
          {
            icon: 'content_copy',
            label: 'Copy response',
            onClick: () => void copyText(responseText),
          },
          {
            icon: 'download',
            label: 'Download response',
            onClick: () =>
              downloadText('co-scientist-session-started.md', responseText),
          },
        ]}
      />
    </section>
  );
}

function formatStartedSessionResponse(session: StartedSession): string {
  return [
    `# ${session.title}`,
    '',
    'Your session has been started and Co-Scientist has started research.',
    '',
    '## Status',
    'You can view and interact with your session at any time, but note that it might take a few minutes for the first ideas to be ready to view.',
    '',
    '* **Type:** Research session',
    '* **Action:** Open the session details when you want to inspect progress.',
  ].join('\n');
}

function referenceSetupTitle(goal: string): string {
  if (/liver fibrosis|MASLD|MASH/i.test(goal)) {
    return 'Reversing MASLD/MASH Fibrosis Hypothesis';
  }
  return conciseTitle(goal);
}

function SpecRow({label, children}: {label: string; children: ReactNode}) {
  return (
    <div className={SPEC_ROW_CLASSES}>
      <dt className={SPEC_TERM_CLASSES}>{label}:</dt>
      <dd className={SPEC_DETAIL_CLASSES}>{children}</dd>
    </div>
  );
}

function SpecList({label, values}: {label: string; values: string[]}) {
  return (
    <SpecRow label={label}>
      <ul className={SPEC_LIST_CLASSES}>
        {values.map(value => (
          <li key={value}>{value}</li>
        ))}
      </ul>
    </SpecRow>
  );
}

function RunOptionGroup({
  label,
  name,
  value,
  options,
  disabled = false,
  onChange,
}: {
  label: string;
  name: string;
  value: string;
  options: ReadonlyArray<{id: string; label: string; description: string}>;
  disabled?: boolean;
  onChange: (value: string) => void;
}) {
  return (
    <fieldset className={OPTION_GROUP_CLASSES} aria-label={label}>
      <legend className={OPTION_GROUP_LEGEND_CLASSES}>{label}</legend>
      <div className={OPTION_GRID_CLASSES}>
        {options.map(option => (
          <label
            key={option.id}
            className={[
              OPTION_CARD_BASE_CLASSES,
              disabled ? 'cursor-default' : 'cursor-pointer',
              option.id === value ? OPTION_CARD_SELECTED_CLASSES : '',
            ]
              .filter(Boolean)
              .join(' ')}
          >
            <input
              type="radio"
              className={OPTION_INPUT_CLASSES}
              name={name}
              value={option.id}
              checked={option.id === value}
              disabled={disabled}
              onChange={() => onChange(option.id)}
            />
            <span
              className={[
                OPTION_MARKER_CLASSES,
                option.id === value ? OPTION_MARKER_SELECTED_CLASSES : '',
              ]
                .filter(Boolean)
                .join(' ')}
              aria-hidden="true"
            />
            <strong className={OPTION_LABEL_CLASSES}>{option.label}</strong>
            <small className={OPTION_DESCRIPTION_CLASSES}>
              {option.description}
            </small>
          </label>
        ))}
      </div>
    </fieldset>
  );
}
