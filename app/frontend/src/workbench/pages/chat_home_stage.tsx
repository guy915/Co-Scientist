import {type FormEvent, useState} from 'react';
import type {Run} from '@/api/runs';
import {joinClasses} from '../classes';
import {useIsMobile} from '../hooks/use_is_mobile';
import {Composer} from './chat_composer';
import type {ConnectorToggleProps} from './chat_composer_connectors';
import {useChatHistoryContext} from '../hooks/chat_history_context';
import {HomeRecentsPanel} from './home_recents';
import {GoogleLabsIcon} from '../components/google_labs_icon';
import {Icon, type IconName} from '@/components/icon';
import {smoothScrollToSection} from '@/lib/smooth_scroll';
import {TruncatedLabel} from '../components/truncated_label';

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
