import {
  type Dispatch,
  type FormEvent,
  type SetStateAction,
  useState,
} from 'react';
import {type Run} from '@/api/runs';
import {Icon, type IconName} from '@/components/icon';
import {joinClasses} from '../classes';
import {useIsMobile} from '../hooks/use_is_mobile';
import {
  HOME_LOGO_CLASSES,
  HOME_MAIN_CLASSES,
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
  HOME_SUGGESTION_ICON_CLASSES,
  HOME_SUGGESTION_PREVIEW_CENTER_CLASSES,
  HOME_SUGGESTION_PREVIEW_CLASSES,
  HOME_SUGGESTION_PREVIEW_END_CLASSES,
  HOME_SUGGESTION_PREVIEW_START_CLASSES,
  HOME_SUGGESTION_PREVIEW_VISIBLE_CLASSES,
  HOME_SUGGESTION_ROW_CLASSES,
  HOME_SUGGESTION_SLOT_CLASSES,
  HOME_SUGGESTION_TEXT_CLASSES,
  HOME_TITLE_CLASSES,
} from './chat_home_classes';
import {Composer} from './chat_composer';
import {HomeRecentsPanel} from './home_recents';
import {type Audience, useAudience} from '../audience_context';
import {SBI_SUGGESTIONS} from '../audience_content';
import {GoogleLabsIcon} from '../components/google_labs_icon';
import {TruncatedLabel} from '../components/truncated_label';

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

type Suggestion = (typeof SUGGESTIONS)[number];

/** Home suggestions for an audience: SBI's tailored set, else the default. */
export function activeSuggestions(
  audience: Audience | null,
): readonly Suggestion[] {
  return audience === 'sbi_ucd' ? SBI_SUGGESTIONS : SUGGESTIONS;
}

// Copy for the desktop-only 1-2-3 onboarding timeline rendered below the
// title (hidden on mobile to save vertical space; see the `!isMobile` guard).
const SESSION_STEPS: readonly {
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

/**
 * Props for HomeStage, named at module level per the destructured prop
 * signature otherwise pushing the component past the line cap.
 *
 * `input`/`setInput` are the controlled composer value, owned by the parent
 * session state. The pubmed/webSearch/paperCorpus fields mirror each
 * connector toggle's state and change callback. `onSubmit` is the composer's
 * form submit handler. `runs`/`scoresByRunId` feed the recents panel, and
 * `showAllRecents`/`onToggleShowAll` control its expanded state.
 */
export interface HomeStageProps {
  input: string;
  setInput: (value: string) => void;
  pubmedEnabled: boolean;
  onPubmedEnabledChange: (enabled: boolean) => void;
  webSearchEnabled: boolean;
  onWebSearchEnabledChange: (enabled: boolean) => void;
  paperCorpusEnabled: boolean;
  onPaperCorpusEnabledChange: (enabled: boolean) => void;
  onSubmit: (e: FormEvent<HTMLFormElement>, files: File[]) => void;
  runs: Run[];
  scoresByRunId: Record<string, number | null>;
  showAllRecents: boolean;
  onToggleShowAll: () => void;
}

// Filling the composer from a suggestion drops in the full prompt (not the
// preview) and dismisses that suggestion's preview bubble, since the row is
// about to lose focus/hover anyway.
function selectHomeSuggestion(
  prompt: string,
  setInput: (value: string) => void,
  setHoveredSuggestion: Dispatch<SetStateAction<string | null>>,
): void {
  setInput(prompt);
  setHoveredSuggestion(null);
}

// The composer, wired to its busy/large defaults for the home stage.
function HomeComposer({
  input,
  setInput,
  pubmedEnabled,
  onPubmedEnabledChange,
  webSearchEnabled,
  onWebSearchEnabledChange,
  paperCorpusEnabled,
  onPaperCorpusEnabledChange,
  onSubmit,
}: Pick<
  HomeStageProps,
  | 'input'
  | 'setInput'
  | 'pubmedEnabled'
  | 'onPubmedEnabledChange'
  | 'webSearchEnabled'
  | 'onWebSearchEnabledChange'
  | 'paperCorpusEnabled'
  | 'onPaperCorpusEnabledChange'
  | 'onSubmit'
>) {
  return (
    <Composer
      input={input}
      setInput={setInput}
      busy={false}
      large
      pubmedEnabled={pubmedEnabled}
      onPubmedEnabledChange={onPubmedEnabledChange}
      webSearchEnabled={webSearchEnabled}
      onWebSearchEnabledChange={onWebSearchEnabledChange}
      paperCorpusEnabled={paperCorpusEnabled}
      onPaperCorpusEnabledChange={onPaperCorpusEnabledChange}
      onSubmit={onSubmit}
    />
  );
}

// The home stage's left column: the greeting, the suggestion prompt row, and
// the composer. Split out of HomeStage so it only needs the suggestion-row
// state as extra props on top of HomeStageProps' composer fields.
function HomeMainColumn(
  props: Pick<
    HomeStageProps,
    | 'input'
    | 'setInput'
    | 'pubmedEnabled'
    | 'onPubmedEnabledChange'
    | 'webSearchEnabled'
    | 'onWebSearchEnabledChange'
    | 'paperCorpusEnabled'
    | 'onPaperCorpusEnabledChange'
    | 'onSubmit'
  > & {
    isMobile: boolean;
    suggestions: readonly Suggestion[];
    hoveredSuggestion: string | null;
    onPreview: (text: string | null) => void;
    onSelect: (prompt: string) => void;
  },
) {
  return (
    <div className={HOME_MAIN_CLASSES}>
      <HomeGreeting isMobile={props.isMobile} />
      <HomeSuggestionRow
        isMobile={props.isMobile}
        suggestions={props.suggestions}
        hoveredSuggestion={props.hoveredSuggestion}
        onPreview={props.onPreview}
        onSelect={props.onSelect}
      />
      <HomeComposer {...props} />
    </div>
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
  const {audience} = useAudience();
  const suggestions = activeSuggestions(audience);
  // Mobile shows suggestions as a single-line glyph list, so the label
  // truncates to one line (word-level, via TruncatedLabel); desktop keeps the
  // two-line card. Tracks viewport width so the line budget follows the
  // active layout.
  const isMobile = useIsMobile();

  return (
    <section className={HOME_STAGE_CLASSES}>
      <HomeMainColumn
        {...props}
        isMobile={isMobile}
        suggestions={suggestions}
        hoveredSuggestion={hoveredSuggestion}
        onPreview={setHoveredSuggestion}
        onSelect={prompt =>
          selectHomeSuggestion(prompt, props.setInput, setHoveredSuggestion)
        }
      />
      <HomeRecentsRegion
        isMobile={isMobile}
        runs={props.runs}
        scoresByRunId={props.scoresByRunId}
        showAllRecents={props.showAllRecents}
        onToggleShowAll={props.onToggleShowAll}
      />
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
        <GoogleLabsIcon aria-hidden="true" className={HOME_LOGO_CLASSES} />
      )}
      <h1 className={HOME_TITLE_CLASSES}>
        What breakthrough should we make today?
      </h1>
      {!isMobile && (
        <ol className={HOME_STEP_TIMELINE_CLASSES}>
          {SESSION_STEPS.map((step, index) => (
            <li
              key={step.n}
              className={joinClasses(
                HOME_STEP_ITEM_CLASSES,
                index === 1 && HOME_STEP_ITEM_CENTER_CLASSES,
                index === 2 && HOME_STEP_ITEM_END_CLASSES,
              )}
            >
              <span className={HOME_STEP_NUMBER_CLASSES}>{step.n}</span>
              <div>
                <h2 className={HOME_STEP_HEADING_CLASSES}>{step.title}</h2>
                <p className={HOME_STEP_BODY_CLASSES}>{step.body}</p>
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
    <div className={HOME_SUGGESTION_ROW_CLASSES}>
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

// Renders the desktop-only recents panel; on phones recent runs live in the
// nav drawer's Chats list instead, so this renders nothing on mobile.
function HomeRecentsRegion({
  isMobile,
  runs,
  scoresByRunId,
  showAllRecents,
  onToggleShowAll,
}: {
  isMobile: boolean;
  runs: Run[];
  scoresByRunId: Record<string, number | null>;
  showAllRecents: boolean;
  onToggleShowAll: () => void;
}) {
  if (isMobile) return null;
  return (
    <HomeRecentsPanel
      runs={runs}
      scoresByRunId={scoresByRunId}
      showAll={showAllRecents}
      onToggleShowAll={onToggleShowAll}
    />
  );
}

// The preview bubble's anchor class for a suggestion card's column position
// (first/middle/last), so it stays roughly centered over the row rather than
// overflowing past the viewport edge for the first/last card.
function suggestionPreviewPositionClass(index: number) {
  if (index === 0) return HOME_SUGGESTION_PREVIEW_START_CLASSES;
  if (index === 1) return HOME_SUGGESTION_PREVIEW_CENTER_CLASSES;
  return HOME_SUGGESTION_PREVIEW_END_CLASSES;
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
    <div className={HOME_SUGGESTION_SLOT_CLASSES}>
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
        HOME_SUGGESTION_PREVIEW_CLASSES,
        positionClass,
        isPreviewed && HOME_SUGGESTION_PREVIEW_VISIBLE_CLASSES,
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
        HOME_SUGGESTION_BUTTON_CLASSES,
        isPreviewed && HOME_SUGGESTION_BUTTON_PREVIEWED_CLASSES,
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
          className={HOME_SUGGESTION_ICON_CLASSES}
          name={suggestion.icon}
        />
      )}
      <TruncatedLabel
        className={HOME_SUGGESTION_TEXT_CLASSES}
        text={suggestion.preview}
        lines={isMobile ? 1 : 2}
      />
    </button>
  );
}
