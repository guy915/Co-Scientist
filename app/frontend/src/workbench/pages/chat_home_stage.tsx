import {type FormEvent, useState, Fragment, useEffect} from 'react';
import {
  type Run,
  isActiveStatus,
  isCompletedStatus,
  type ChatSummary,
} from '@/api/runs';
import {joinClasses} from '../classes';
import {useIsMobile} from '../hooks/dom';
import {Composer, type ConnectorToggleProps} from './chat_composer';
import {useChatHistoryContext} from '../hooks/history_context';
import {GoogleLabsIcon} from '../layout_primitives';
import {Icon, type IconName} from '@/components/icon';
import {smoothScrollToSection} from '@/lib/smooth_scroll';
import {TruncatedLabel} from '../components/truncated_label';
import {Link} from 'react-router-dom';
import {
  firstSentenceClause,
  formatDurationPhrase,
  capitalizeTerm,
} from '@/lib/text';
import {useNowTick} from '@/workbench/hooks/timers';
import {preferredSessionSide} from '../layout_session_switch';

/** Inputs for the home composer and its recent runs. */
export interface HomeStageProps {
  input: string;
  setInput: (value: string) => void;
  connectors: ConnectorToggleProps;
  onSubmit: (e: FormEvent<HTMLFormElement>, files: File[]) => void;
  runs: Run[];
  showAllRecents: boolean;
  onToggleShowAll: () => void;
}

// The one line under the composer that says there is more below: the
// landing page (home_landing.tsx), rendered after this stage. Quiet on
// purpose, so the home still reads as the chat it opens on.
function HomeScrollHint() {
  const onClick = () => {
    const reduce = window.matchMedia?.(
      '(prefers-reduced-motion: reduce)',
    ).matches;
    // Scroll the home page pane itself: scrollIntoView would also scroll
    // the shell's clipped ancestors and shift the whole app up.
    smoothScrollToSection(
      'landing',
      0,
      '.ucs-page--home',
      reduce ? 'auto' : 'smooth',
    );
  };
  return (
    <button
      type="button"
      className="reference-home-scroll-hint"
      onClick={onClick}
    >
      Scroll to see how Co-Scientist works
      <Icon aria-hidden="true" name="expand_more" />
    </button>
  );
}

/**
 * Renders the session-home surface shown before any conversation has
 * started: the greeting title, the desktop onboarding timeline, the
 * suggestion prompt row, the composer (in its roomy `large` mode), and the
 * desktop-only recents panel (HomeRecentsPanel). Rendered by ChatWorkspace
 * when `hasConversation` is false.
 */
export function HomeStage(props: HomeStageProps) {
  // Tracks which suggestion (by its preview text, used as the identity key) is
  // currently hovered/focused, to show that suggestion's preview bubble and its
  // "previewed" button styling.
  const [hoveredSuggestion, setHoveredSuggestion] = useState<string | null>(
    null,
  );
  // Mobile shows suggestions as a single-line glyph list, so the label
  // truncates to one line (word-level, via TruncatedLabel); desktop keeps the
  // two-line card. Tracks viewport width so the line budget follows the
  // active layout.
  const isMobile = useIsMobile();
  const {chats} = useChatHistoryContext();

  return (
    <section className="reference-home-stage">
      <div className="reference-home-main">
        <HomeGreeting isMobile={isMobile} />
        <HomeSuggestionRow
          isMobile={isMobile}
          suggestions={SUGGESTIONS}
          hoveredSuggestion={hoveredSuggestion}
          onPreview={setHoveredSuggestion}
          onSelect={prompt => {
            props.setInput(prompt);
            setHoveredSuggestion(null);
          }}
        />
        <Composer
          input={props.input}
          setInput={props.setInput}
          busy={false}
          large
          connectors={props.connectors}
          onSubmit={props.onSubmit}
        />
        <HomeScrollHint />
      </div>
      {!isMobile && (
        <HomeRecentsPanel
          runs={props.runs}
          showAll={props.showAllRecents}
          onToggleShowAll={props.onToggleShowAll}
          chats={chats}
        />
      )}
    </section>
  );
}

// Renders the heading block above the suggestion row: the phone-only flask
// mark (the desktop header lockup already carries the mark), the greeting
// title, and the desktop-only 1-2-3 onboarding timeline (mobile drops it
// entirely to free vertical space).
function HomeGreeting({isMobile}: {isMobile: boolean}) {
  return (
    <>
      {isMobile && (
        <GoogleLabsIcon aria-hidden="true" className="reference-home-logo" />
      )}
      <h1 className="reference-home-title">
        What breakthrough should we make today?
      </h1>
      {!isMobile && (
        <ol className="reference-step-timeline">
          {SESSION_STEPS.map((step, index) => (
            <li
              key={step.n}
              className={joinClasses(
                'reference-step-item',
                index === 1 && 'reference-step-item--center',
                index === 2 && 'reference-step-item--end',
              )}
            >
              <span className="reference-step-number">{step.n}</span>
              <div>
                <h2 className="reference-step-heading">{step.title}</h2>
                <p className="reference-step-body">{step.body}</p>
              </div>
            </li>
          ))}
        </ol>
      )}
    </>
  );
}

// Renders the suggestion prompt row: one SuggestionCard per entry in
// SUGGESTIONS, wired to the shared hover/preview state and the handler that
// fills the composer when a card is selected.
function HomeSuggestionRow({
  isMobile,
  suggestions,
  hoveredSuggestion,
  onPreview,
  onSelect,
}: {
  isMobile: boolean;
  suggestions: readonly Suggestion[];
  hoveredSuggestion: string | null;
  onPreview: (text: string | null) => void;
  onSelect: (text: string) => void;
}) {
  return (
    <div className="reference-suggestion-row">
      {suggestions.map((suggestion, index) => (
        <SuggestionCard
          key={suggestion.preview}
          suggestion={suggestion}
          index={index}
          isMobile={isMobile}
          isPreviewed={hoveredSuggestion === suggestion.preview}
          onPreview={onPreview}
          onSelect={onSelect}
        />
      ))}
    </div>
  );
}

// The preview bubble's anchor class for a suggestion card's column position
// (first/middle/last), so it stays roughly centered over the row rather than
// overflowing past the viewport edge for the first/last card.
function suggestionPreviewPositionClass(index: number) {
  if (index === 0) return 'reference-suggestion-preview--start';
  if (index === 1) return 'reference-suggestion-preview--center';
  return 'reference-suggestion-preview--end';
}

// Renders one suggestion card in the home-stage suggestion row: the
// hover/focus-revealed one-sentence preview bubble (SuggestionPreviewBubble),
// and the button that fills the composer with the suggestion's full prompt
// when selected (SuggestionTriggerButton).
function SuggestionCard({
  suggestion,
  index,
  isMobile,
  isPreviewed,
  onPreview,
  onSelect,
}: {
  suggestion: Suggestion;
  index: number;
  isMobile: boolean;
  isPreviewed: boolean;
  onPreview: (preview: string | null) => void;
  onSelect: (prompt: string) => void;
}) {
  // The preview bubble anchors differently per column (start/center/end) so
  // it stays roughly centered over the row rather than overflowing past the
  // viewport edge for the first/last card.
  const previewPositionClass = suggestionPreviewPositionClass(index);

  return (
    <div className="reference-suggestion-slot">
      <SuggestionPreviewBubble
        text={suggestion.preview}
        isPreviewed={isPreviewed}
        positionClass={previewPositionClass}
      />
      <SuggestionTriggerButton
        suggestion={suggestion}
        isMobile={isMobile}
        isPreviewed={isPreviewed}
        onPreview={onPreview}
        onSelect={onSelect}
      />
    </div>
  );
}

// One-sentence preview bubble revealed above a suggestion card on hover/focus.
function SuggestionPreviewBubble({
  text,
  isPreviewed,
  positionClass,
}: {
  text: string;
  isPreviewed: boolean;
  positionClass: string;
}) {
  return (
    <p
      className={joinClasses(
        'reference-suggestion-preview',
        positionClass,
        isPreviewed && 'visible',
      )}
      aria-hidden={!isPreviewed}
    >
      {text}
    </p>
  );
}

// Props for SuggestionTriggerButton, named at module level per the
// destructured prop signature otherwise pushing the component past the line
// cap.
interface SuggestionTriggerButtonProps {
  suggestion: Suggestion;
  isMobile: boolean;
  isPreviewed: boolean;
  onPreview: (preview: string | null) => void;
  onSelect: (prompt: string) => void;
}

// The suggestion's clickable trigger: fills the composer with the
// suggestion's full prompt when clicked, and drives the preview bubble's
// visibility on hover/pointer/focus so touch/keyboard users get the same
// one-sentence preview that mouse hover provides.
function SuggestionTriggerButton(props: SuggestionTriggerButtonProps) {
  const {suggestion, isMobile, isPreviewed, onPreview, onSelect} = props;
  return (
    <button
      type="button"
      className={joinClasses(
        'reference-suggestion-button',
        isPreviewed && 'is-previewed',
      )}
      onPointerEnter={() => onPreview(suggestion.preview)}
      onPointerLeave={() => onPreview(null)}
      onFocus={() => onPreview(suggestion.preview)}
      onBlur={() => onPreview(null)}
      onClick={() => onSelect(suggestion.prompt)}
    >
      {/* Leading glyph is part of the phone list layout only; desktop cards
          are text-only. */}
      {isMobile && (
        <Icon
          aria-hidden="true"
          className="reference-suggestion-icon"
          name={suggestion.icon}
        />
      )}
      <TruncatedLabel
        className="reference-suggestion-text"
        text={suggestion.preview}
        lines={isMobile ? 1 : 2}
      />
    </button>
  );
}

// Each suggestion carries two strings with distinct jobs. `preview` is a
// one-sentence teaser shown on the card (truncated to the card width via
// TruncatedLabel) and in the hover bubble. `prompt` is the full, well-formed
// research goal dropped into the composer on click — modelled on the
// Co-Scientist input anatomy (a title line, a goal with an explicit output
// format, novelty/feasibility constraints, and the reasoning the system should
// perform), so a scientist starts from a real prompt rather than a teaser.
// `icon` is the leading glyph shown in the mobile list layout.
export const SUGGESTIONS: readonly {
  preview: string;
  prompt: string;
  icon: IconName;
}[] = [
  {
    preview: 'Repurpose an approved drug to slow glioblastoma progression.',
    prompt:
      'Repurposing an approved drug for glioblastoma.\n\n' +
      'Suggest an existing, approved drug that could be repurposed to slow ' +
      'the progression of glioblastoma, and provide experimentally ' +
      'testable concentrations for an in-vitro proliferation assay in ' +
      'patient-derived glioblastoma cells. The drug should cross the ' +
      'blood-brain barrier and inhibit tumor cell growth.\n\n' +
      'The drug should have minimal cytotoxicity in healthy neural and glial ' +
      'cells, and should not have been experimentally tested for ' +
      'glioblastoma before.\n\n' +
      'Reason about the drug’s molecular mechanism, impacted pathways, and ' +
      'effect on tumor-cell proliferation. Describe the mechanism of ' +
      'action in detail, and reason about safety and toxicity, stating ' +
      'where no safety data exists.',
    icon: 'search',
  },
  {
    preview:
      'Find a mechanistic link between gut-microbiome metabolites and ' +
      'Parkinson’s.',
    prompt:
      'A novel hypothesis for gut-microbiome metabolites in Parkinson’s ' +
      'disease progression.\n\n' +
      'Develop a novel, mechanistic hypothesis explaining how specific ' +
      'gut-microbiome-derived metabolites influence the progression of ' +
      'Parkinson’s disease, focusing on the gut–brain axis and α-synuclein ' +
      'aggregation. Explain the mechanism of action in detail, from the ' +
      'metabolite to the molecular pathway to the neuronal phenotype.\n\n' +
      'Prioritize hypotheses that are novel — not already established in the ' +
      'literature — and consistent with known human and model-organism ' +
      'evidence.\n\n' +
      'Include a feasible experiment to test the hypothesis, specifying the ' +
      'model system (for example gnotobiotic mice or enteric neuron ' +
      'cultures) and the measurable readout.',
    icon: 'lightbulb',
  },
  {
    preview:
      'Resensitize multidrug-resistant Gram-negative bacteria to an ' +
      'antibiotic.',
    prompt:
      'A strategy to resensitize multidrug-resistant Gram-negative ' +
      'bacteria.\n\n' +
      'Propose a novel strategy to resensitize multidrug-resistant ' +
      'Gram-negative bacteria (for example carbapenem-resistant Klebsiella ' +
      'pneumoniae) to an existing antibiotic. The strategy should target a ' +
      'specific resistance mechanism — such as an efflux pump, β-lactamase ' +
      'activity, or outer-membrane permeability — and restore the potency ' +
      'of a clinically used drug.\n\n' +
      'The approach should be feasible with current laboratory techniques ' +
      'and should not depend on developing an entirely new class of ' +
      'antibiotic.\n\n' +
      'Explain the molecular mechanism in detail, reason about how readily ' +
      'resistance could emerge against the strategy itself, and outline an ' +
      'experimentally testable assay (for example a checkerboard MIC ' +
      'assay) to validate the resensitization.',
    icon: 'stars',
  },
];

export type Suggestion = (typeof SUGGESTIONS)[number];

// Copy for the desktop-only 1-2-3 onboarding timeline rendered below the
// title (hidden on mobile to save vertical space; see the `!isMobile` guard).
export const SESSION_STEPS: readonly {
  n: number;
  title: string;
  body: string;
}[] = [
  {
    n: 1,
    title: 'Frame the research goal',
    body:
      'Describe the question, add useful context, and define what a ' +
      'strong hypothesis should satisfy.',
  },
  {
    n: 2,
    title: 'Generate hypotheses',
    body:
      'Co-Scientist explores mechanisms, evidence, and candidate ' +
      'explanations for the topic.',
  },
  {
    n: 3,
    title: 'Pressure-test the best ideas',
    body:
      'Hypotheses are compared against the criteria so the strongest ' +
      'directions rise to the top.',
  },
];

interface HomeRecentsPanelProps {
  runs: Run[];
  showAll: boolean;
  onToggleShowAll: () => void;
  chats?: readonly ChatSummary[];
}

export function HomeRecentsPanel({
  runs,
  showAll,
  onToggleShowAll,
  chats = [],
}: HomeRecentsPanelProps) {
  const visibleRuns = showAll ? runs : runs.slice(0, 4);
  const empty = visibleRuns.length === 0;
  return (
    <aside
      className={`reference-recents reference-recents-panel${empty ? ' reference-recents--empty' : ''}`}
      aria-label="Recent runs"
    >
      <div className="reference-recents-heading">
        <Icon
          aria-hidden="true"
          className="reference-recents-heading-icon"
          name="history"
        />
        <h2 className="reference-recents-heading-title">Recents</h2>
      </div>
      <ol
        className={`reference-recents-list${empty ? ' reference-recents-list--empty' : ''}`}
      >
        {empty ? (
          <li className="reference-recents-empty-item">
            <div className="reference-recents-empty-state">
              <GoogleLabsIcon
                aria-hidden="true"
                className="reference-recents-empty-icon"
              />
              <strong className="reference-recents-empty-copy">
                You have not started any sessions yet.
              </strong>
            </div>
          </li>
        ) : (
          visibleRuns.map(run => (
            <RecentRunCard key={run.id} run={run} chats={chats} />
          ))
        )}
        {runs.length > 4 && (
          <li className="reference-load-more-item">
            <button
              type="button"
              className="reference-load-more"
              onClick={onToggleShowAll}
            >
              {showAll ? 'Show less' : 'Show more'}
              <Icon
                aria-hidden="true"
                name={showAll ? 'expand_less' : 'expand_more'}
              />
            </button>
          </li>
        )}
      </ol>
    </aside>
  );
}

function RecentCardMeta({run}: {run: Run}) {
  const nowSeconds = useNowTick(1000);
  return (
    <span className="reference-recent-meta">
      <span className="reference-recent-meta-chip">
        {formatHomeRunDate(run.updated_at)}
      </span>
      <span className="reference-recent-meta-chip">
        {formatHomeRunTimeChip(run, nowSeconds)}
      </span>
    </span>
  );
}

function RecentRunCard({
  run,
  chats,
}: {
  run: Run;
  chats: readonly ChatSummary[];
}) {
  // Resolve the remembered Chat/Results side from the current chat list.
  const chat =
    preferredSessionSide(run.id) === 'chat'
      ? chats.find(entry => entry.run_id === run.id)
      : undefined;
  const active = isActiveStatus(run.status);
  return (
    <li>
      <Link
        to={chat ? `/chats/${chat.id}` : `/runs/${run.id}/details`}
        className={`reference-recent-card${active ? ' is-active-run' : ''}`}
        title={run.research_goal}
      >
        <RecentCardMeta run={run} />
        <TruncatedLabel
          className="reference-recent-title"
          text={
            run.title ||
            firstSentenceClause(run.research_goal) ||
            'Untitled session'
          }
          lines={2}
        />
        <TruncatedLabel
          className="reference-recent-description"
          text={run.research_goal}
          lines={3}
        />
        {active ? (
          <RunStepFlow run={run} />
        ) : (
          isCompletedStatus(run.status) && <RecentRunResults run={run} />
        )}
      </Link>
    </li>
  );
}

function RecentRunResults({run}: {run: Run}) {
  const topIdeas = run.top_hypotheses ?? [];
  const topScore = run.top_elo ?? null;
  return (
    <>
      <span className="reference-recent-chips">
        <span className="reference-recent-chip">
          <Icon
            aria-hidden="true"
            className="reference-recent-chip-icon"
            name="emoji_events"
          />
          Winning ideas
        </span>
        {topScore !== null && (
          <span className="reference-recent-chip">
            <Icon
              aria-hidden="true"
              className="reference-recent-chip-icon"
              name="stars"
            />
            Top score: {topScore}
          </span>
        )}
      </span>
      {topIdeas.length > 0 && (
        <ol className="reference-winner-list">
          {topIdeas.map((idea, index) => (
            <li key={idea} className="reference-winner-list-item">
              <span>{index + 1}.</span>
              <TruncatedLabel
                className="reference-winner-list-text"
                text={idea}
                lines={2}
              />
            </li>
          ))}
        </ol>
      )}
    </>
  );
}

const HOME_RUN_DATE_FMT = new Intl.DateTimeFormat(undefined, {
  month: 'short',
  day: 'numeric',
  year: 'numeric',
});

export function formatHomeRunDate(timestamp: number): string {
  return HOME_RUN_DATE_FMT.format(new Date(timestamp * 1000));
}

export function formatHomeRunTimeChip(run: Run, nowSeconds: number): string {
  if (isCompletedStatus(run.status)) {
    const endTime = run.completed_at ?? run.updated_at;
    const duration = endTime ? endTime - run.created_at : -1;
    return `Total time: ${duration < 0 ? capitalizeTerm(run.status) : formatDurationPhrase(duration, {subMinute: true})}`;
  }
  if (isActiveStatus(run.status)) {
    return `Time elapsed: ${formatDurationPhrase(Math.max(0, nowSeconds - run.created_at), {subMinute: true})}`;
  }
  return `Status: ${capitalizeTerm(run.status)}`;
}

// Both leased tasks and stage events name the same work. Routing between
// agents has no phase; after tournament, the remaining work stays at step 4.
const TASK_PHASE: Record<string, number | null> = {
  bootstrap: 1,
  supervisor: 1,
  orchestrator: null,
  generate: 2,
  generation: 2,
  literature_review: 2,
  reflection: 3,
  comprehensive_reflection: 3,
  review: 3,
  verification: 3,
  deep_verification: 3,
  safety_screen: 3,
  ranking: 4,
  proximity: 4,
  evolve: 4,
  meta_review: 4,
  research_overview: 4,
  finalize: 4,
};

const STAGE_TYPES = new Set([
  'supervisor.plan',
  'literature_review',
  'generate',
  'reflection',
  'proximity',
  'ranking',
  'evolve',
  'meta_review',
  'deep_verification',
  'research_overview',
]);

/** The current 1–4 phase, or null between tasks; later cycles may go backward. */
export function homeRunStepIndex(run: Run): number | null {
  if (run.status === 'queued') return 1;
  if (run.status === 'synthesizing') return 4;
  const task = run.execution_progress?.active_task;
  if (task) {
    const [, first = '', second = ''] = task.split('.');
    const phase =
      TASK_PHASE[first === 'node' || first === 'fanout' ? second : first] ??
      null;
    if (phase !== null) return phase;
  }
  const stage = run.latest_stage;
  if (!stage || !STAGE_TYPES.has(stage)) return null;
  return TASK_PHASE[stage === 'supervisor.plan' ? 'supervisor' : stage] ?? null;
}

// The four phases of a live run, each with the glyph it shows in the flow.
// A run's real unit of work is mapped onto one of these by homeRunStepIndex.
const RUN_STEPS: {icon: IconName; label: string}[] = [
  {icon: 'summarize', label: 'Exploring focus areas'},
  {icon: 'rate_review', label: 'Generating hypotheses'},
  {icon: 'reviews', label: 'Reviewing hypotheses'},
  {icon: 'chess', label: 'Playing tournament'},
];

/**
 * Renders the live flow for an active run: an "In Progress" row carrying the
 * spinner, then the phases up to the one the run is currently in.
 *
 * The phase comes from the run's own reported progress, so the flow tracks
 * real work rather than a timer. It shows the *latest* reported phase, not
 * the furthest one ever reached: a run genuinely returns to earlier phases
 * (every new work cycle re-enters generation/review, and proximity follows
 * the tournament), and retaining the furthest phase masked those backward
 * steps instead of reporting them. Rows appearing and disappearing as the
 * phase moves is the honest signal.
 *
 * @param run The active run to show progress for.
 */
export function RunStepFlow({run}: {run: Run}) {
  const phase = homeRunStepIndex(run);
  // A run reports no phase while routing between agents and in the gaps
  // between leased tasks. Hold the last phase actually observed so those gaps
  // read as the work continuing, rather than snapping back to the first step.
  // A *reported* phase replaces it outright — see the docstring for why the
  // flow no longer retains the furthest phase seen.
  const [currentPhase, setCurrentPhase] = useState(phase ?? 1);
  useEffect(() => {
    if (phase === null) return;
    setCurrentPhase(phase);
  }, [phase]);
  const revealed = RUN_STEPS.slice(0, currentPhase);

  return (
    <div className="reference-run-steps">
      <div className="reference-run-step-list">
        <div className="reference-run-step">
          <span
            aria-hidden="true"
            className="reference-run-step-spinner reference-run-step-glyph"
          />
          <span className="reference-run-step-label">In Progress</span>
        </div>
        <div aria-hidden="true" className="reference-run-step-delimiter" />
        {revealed.map((step, index) => (
          <Fragment key={step.label}>
            <RunStepItem icon={step.icon} label={step.label} />
            {index < revealed.length - 1 && (
              <div
                aria-hidden="true"
                className="reference-run-step-delimiter"
              />
            )}
          </Fragment>
        ))}
      </div>
    </div>
  );
}

// One phase's glyph and label. A row's presence is the whole signal: the flow
// only lists phases the run has entered, and its single spinner lives in the
// In Progress row. There is deliberately no per-row done/current marker (the
// .reference-run-step-done check style is kept for a future one).
function RunStepItem({icon, label}: {icon: IconName; label: string}) {
  return (
    <div className="reference-run-step">
      <Icon
        aria-hidden="true"
        className="reference-run-step-icon"
        name={icon}
      />
      <span className="reference-run-step-label">{label}</span>
    </div>
  );
}

// The active-task label: the humanized durable-task-lease signal
// (`execution_progress.active_task`) when one is present, else the
// humanized stage-event signal (`latest_stage`) when that is present
// instead, else a neutral placeholder while neither signal has arrived yet.
function activeTaskLabel(run: Run): string {
  const activeTask = run.execution_progress?.active_task;
  if (activeTask) return humanizeTask(activeTask);
  if (run.latest_stage) return humanizeTask(run.latest_stage);
  return 'Waiting for Supervisor allocation';
}

// Committed-task counts for the "N of M complete" line, only while the
// Supervisor's progress is determinate.
function committedTaskCounts(run: Run): {
  completed: number;
  total: number;
  queued: number;
} | null {
  const progress = run.execution_progress;
  if (!progress?.determinate) return null;
  return {
    completed: progress.completed_tasks,
    total: progress.total_tasks,
    queued: progress.queued_tasks,
  };
}

/**
 * Renders truthful task-queue progress for a live run: what it is working on
 * now, and how much of the Supervisor's committed task budget is done. Both
 * are stated in words -- a bar was removed because its fraction is only known
 * once the budget is committed, so most of a run it read as motion without
 * information.
 */
export function RunExecutionProgress({run}: {run: Run}) {
  const activeTask = activeTaskLabel(run);
  const counts = committedTaskCounts(run);

  return (
    <section className="mt-4" aria-label="Run execution progress">
      <strong className="block text-xs font-medium text-cosci-fg">
        {activeTask}
      </strong>
      {counts ? (
        <p className="mt-2 text-xs text-cosci-muted">
          {counts.completed} of {counts.total} committed tasks complete ·{' '}
          {counts.queued} queued
        </p>
      ) : null}
    </section>
  );
}

function humanizeTask(value: string): string {
  return value
    .replaceAll('.', ' ')
    .replaceAll('_', ' ')
    .replace(/\b\w/g, letter => letter.toUpperCase());
}
