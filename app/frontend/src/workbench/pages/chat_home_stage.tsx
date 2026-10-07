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

export interface HomeStageProps {
  input: string;
  setInput: (value: string) => void;
  connectors: ConnectorToggleProps;
  onSubmit: (e: FormEvent<HTMLFormElement>, files: File[]) => void;
  runs: Run[];
  showAllRecents: boolean;
  onToggleShowAll: () => void;
}

function HomeScrollHint() {
  const onClick = () => {
    const reduce = window.matchMedia?.(
      '(prefers-reduced-motion: reduce)',
    ).matches;
    // Scroll this pane; scrollIntoView also moves clipped shell ancestors.
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

export function HomeStage(props: HomeStageProps) {
  const [hoveredSuggestion, setHoveredSuggestion] = useState<string | null>(
    null,
  );
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
        {!isMobile && <HomeScrollHint />}
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

// Anchor edge previews inward so they cannot overflow the viewport.
function suggestionPreviewPositionClass(index: number) {
  if (index === 0) return 'reference-suggestion-preview--start';
  if (index === 1) return 'reference-suggestion-preview--center';
  return 'reference-suggestion-preview--end';
}

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

interface SuggestionTriggerButtonProps {
  suggestion: Suggestion;
  isMobile: boolean;
  isPreviewed: boolean;
  onPreview: (preview: string | null) => void;
  onSelect: (prompt: string) => void;
}

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

// Suggestion teasers are not research goals; send the full prompt with output
// and scientific constraints.
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

// 701-1180px keeps recents at natural height below the first screen rather
// than a desktop-style scroller; 1181px+ fills the stage column. Mobile never
// renders the panel.
const RECENTS_PANEL_CLASSES =
  'reference-recents-panel grid min-h-0 content-start gap-[1.3rem] overflow-hidden pt-1 ' +
  'min-[701px]:mt-4 min-[701px]:min-h-auto min-[701px]:w-[min(100%,43rem)] min-[701px]:grid-rows-[auto_auto] min-[701px]:overflow-visible ' +
  'min-[1181px]:mt-0 min-[1181px]:h-full min-[1181px]:min-h-0 min-[1181px]:w-full min-[1181px]:max-h-[calc(100vh-4.5rem)] min-[1181px]:supports-[height:100dvh]:max-h-[calc(100dvh-4.5rem)] min-[1181px]:grid-rows-[auto_minmax(0,1fr)] min-[1181px]:justify-self-end min-[1181px]:gap-[1.55rem] min-[1181px]:pt-[clamp(0.35rem,1vh,0.75rem)] min-[1181px]:pb-[clamp(1.35rem,3.2vh,2.25rem)]';

const RECENTS_PANEL_EMPTY_CLASSES = 'grid-rows-[auto_1fr] self-stretch pb-8';

const RECENTS_LIST_CLASSES =
  'm-0 grid min-h-0 list-none gap-[2.6rem] min-[1181px]:scroll-p-[0.55rem_0.55rem_2.15rem] min-[1181px]:gap-[2.65rem]';

// Background-independent masks soften the scroll edge in both themes without
// matching surface colors; symmetric 1181px+ insets leave scrollbar slack so
// narrowed cards cannot overflow horizontally.
const RECENTS_LIST_SCROLL_CLASSES =
  'overflow-y-auto p-0 pr-[0.6rem] [mask-image:linear-gradient(to_bottom,#000_calc(100%-2.25rem),transparent)] [-webkit-mask-image:linear-gradient(to_bottom,#000_calc(100%-2.25rem),transparent)] ' +
  'max-h-[calc(100vh-12rem)] supports-[height:100dvh]:max-h-[calc(100dvh-12rem)] min-[701px]:max-h-none min-[701px]:overflow-visible min-[1181px]:overflow-y-auto min-[1181px]:p-[0.55rem_0.55rem_2.15rem]';

// The empty state is not a scroller; a mask would dim the card itself.
const RECENTS_LIST_EMPTY_CLASSES = 'h-full overflow-hidden p-0';

// Its transition stays in home_surface.css: the global unlayered `a` rule
// would beat a utility.
const RECENT_CARD_CLASSES =
  'reference-recent-card grid min-h-[15.75rem] w-full cursor-pointer content-start gap-[0.7rem] rounded-xl border border-(--cosci-suggestion-bg) bg-cosci-composer-bg p-4 text-left text-cosci-fg no-underline [box-shadow:0_1px_2px_rgb(0_0_0/15%),0_2px_10px_rgb(0_0_0/10%)] hover:bg-(--cosci-recent-card-hover-bg) focus-visible:bg-(--cosci-recent-card-hover-bg) min-[1181px]:min-h-0 min-[1181px]:border-transparent';

// Wrap whole chips rather than split duration labels inside their pills.
const RECENT_META_CHIP_CLASSES =
  'rounded-[0.3125rem] bg-cosci-recent-meta-bg px-2 py-1 text-[0.6875rem] font-medium tracking-[0.1px] whitespace-nowrap text-cosci-fg min-[1181px]:leading-[1.45]';

const RECENT_CHIP_CLASSES =
  'inline-flex items-center gap-1 rounded-[0.3125rem] bg-(--cosci-recent-chip-bg) px-2 py-1 text-[0.6875rem] font-medium tracking-[0.1px] text-cosci-fg min-[1181px]:min-h-[1.62rem] min-[1181px]:flex-none min-[1181px]:leading-[1.45] min-[1181px]:whitespace-nowrap';

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
      className={joinClasses(
        RECENTS_PANEL_CLASSES,
        empty && RECENTS_PANEL_EMPTY_CLASSES,
      )}
      aria-label="Recent runs"
    >
      <div className="flex items-center gap-2 text-th-muted-fg">
        <Icon
          aria-hidden="true"
          className="size-5 min-[1181px]:size-[1.375rem]"
          name="history"
        />
        <h2 className="m-0 text-[1.15rem] font-semibold text-cosci-fg min-[1181px]:text-[1rem] min-[1181px]:leading-[1.5] min-[1181px]:font-medium">
          Recents
        </h2>
      </div>
      <ol
        className={joinClasses(
          RECENTS_LIST_CLASSES,
          empty ? RECENTS_LIST_EMPTY_CLASSES : RECENTS_LIST_SCROLL_CLASSES,
        )}
      >
        {empty ? (
          <li className="h-full min-h-0">
            <div className="box-border grid h-full min-h-[25rem] w-full place-items-center content-center gap-4 rounded-[1.35rem] border-[1.5px] border-dashed border-cosci-border p-6 text-center text-cosci-muted">
              <GoogleLabsIcon
                aria-hidden="true"
                className="block h-[1.95rem] w-[2.1rem] text-(--cosci-accent)"
              />
              <strong className="max-w-[17rem] text-[1rem] leading-[1.35] font-[650] text-inherit">
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
          <li className="flex justify-center pt-1 pb-2">
            <button
              type="button"
              className="inline-flex cursor-pointer items-center gap-1 justify-self-center border-0 bg-transparent px-2 py-1 text-[0.9rem] font-medium text-(--cosci-idea-ref-blue) hover:underline focus-visible:underline dark:text-cosci-blue"
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
    <span className="flex flex-wrap gap-[0.35rem]">
      <span className={RECENT_META_CHIP_CLASSES}>
        {formatHomeRunDate(run.updated_at)}
      </span>
      <span className={RECENT_META_CHIP_CLASSES}>
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
  const chat =
    preferredSessionSide(run.id) === 'chat'
      ? chats.find(entry => entry.run_id === run.id)
      : undefined;
  const active = isActiveStatus(run.status);
  return (
    <li>
      <Link
        to={
          run.is_demo
            ? `/examples/${run.id}`
            : chat
              ? `/chats/${chat.id}`
              : `/runs/${run.id}/details`
        }
        className={joinClasses(RECENT_CARD_CLASSES, active && 'is-active-run')}
        title={run.research_goal}
      >
        <RecentCardMeta run={run} />
        <TruncatedLabel
          className="line-clamp-2 text-[1rem] leading-[1.5] font-medium"
          text={
            run.title ||
            firstSentenceClause(run.research_goal) ||
            'Untitled session'
          }
          lines={2}
        />
        <TruncatedLabel
          className="reference-recent-description line-clamp-3 text-[0.9rem] leading-[1.35] text-cosci-shell-icon min-[1181px]:text-[0.94rem] min-[1181px]:leading-[1.34]"
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
      <span className="flex flex-nowrap items-center gap-[0.35rem]">
        <span className={RECENT_CHIP_CLASSES}>
          <Icon aria-hidden="true" className="size-4" name="emoji_events" />
          Winning ideas
        </span>
        {topScore !== null && (
          <span className={RECENT_CHIP_CLASSES}>
            <Icon aria-hidden="true" className="size-4" name="stars" />
            Top score: {topScore}
          </span>
        )}
      </span>
      {topIdeas.length > 0 && (
        <ol className="m-0 mt-[0.15rem] grid list-none gap-[0.65rem] p-0 text-[0.75rem] leading-[1.33] tracking-[0.1px] text-cosci-fg min-[1181px]:gap-2">
          {topIdeas.map((idea, index) => (
            <li
              key={idea}
              className="grid grid-cols-[1.4rem_minmax(0,1fr)] gap-[0.2rem]"
            >
              <span>{index + 1}.</span>
              <TruncatedLabel
                className="line-clamp-2 min-w-0"
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

// Routing has no phase; leased tasks and stage events describe the same work.
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

const RUN_STEPS: {icon: IconName; label: string}[] = [
  {icon: 'summarize', label: 'Exploring focus areas'},
  {icon: 'rate_review', label: 'Generating hypotheses'},
  {icon: 'reviews', label: 'Reviewing hypotheses'},
  {icon: 'chess', label: 'Playing tournament'},
];

const RUN_STEP_CLASSES =
  'flex items-center gap-[0.6rem] text-[0.85rem] leading-[1.2] font-medium text-cosci-fg';

const RUN_STEP_DELIMITER_CLASSES =
  'm-[0.2rem_0_0.2rem_0.625rem] h-3 border-s border-s-cosci-border';

// Show the latest phase, not the furthest: later cycles legitimately return to
// generation and review.
export function RunStepFlow({run}: {run: Run}) {
  const phase = homeRunStepIndex(run);
  // Hold the last observed phase through routing gaps; a reported phase
  // replaces it even when it moves backward.
  const [currentPhase, setCurrentPhase] = useState(phase ?? 1);
  useEffect(() => {
    if (phase === null) return;
    setCurrentPhase(phase);
  }, [phase]);
  const revealed = RUN_STEPS.slice(0, currentPhase);

  return (
    <div className="mt-[0.1rem] grid gap-[0.7rem]">
      <div className="grid">
        <div className={RUN_STEP_CLASSES}>
          <span
            aria-hidden="true"
            className="size-5 shrink-0 animate-[reference-run-step-spin_0.8s_linear_infinite] rounded-[9999px] border-2 border-[color:color-mix(in_srgb,var(--color-th-primary)_28%,transparent)] border-t-th-primary motion-reduce:animate-none"
          />
          <span className="reference-run-step-label min-w-0">In Progress</span>
        </div>
        <div aria-hidden="true" className={RUN_STEP_DELIMITER_CLASSES} />
        {revealed.map((step, index) => (
          <Fragment key={step.label}>
            <RunStepItem icon={step.icon} label={step.label} />
            {index < revealed.length - 1 && (
              <div aria-hidden="true" className={RUN_STEP_DELIMITER_CLASSES} />
            )}
          </Fragment>
        ))}
      </div>
    </div>
  );
}

function RunStepItem({icon, label}: {icon: IconName; label: string}) {
  return (
    <div className={RUN_STEP_CLASSES}>
      <Icon
        aria-hidden="true"
        className="reference-run-step-icon size-5 shrink-0 text-cosci-shell-icon"
        name={icon}
      />
      <span className="reference-run-step-label min-w-0">{label}</span>
    </div>
  );
}

function activeTaskLabel(run: Run): string {
  const activeTask = run.execution_progress?.active_task;
  if (activeTask) return humanizeTask(activeTask);
  if (run.latest_stage) return humanizeTask(run.latest_stage);
  return 'Waiting for Supervisor allocation';
}

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

// Only show determinate queue progress; an uncommitted task budget cannot
// justify a progress fraction.
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
