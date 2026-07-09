import {type FormEvent, useState} from 'react';
import {type Run} from '@/api/runs';
import {Icon, type IconName} from '@/components/icon';
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
import {GoogleLabsIcon} from '../components/google_labs_icon';
import {TruncatedLabel} from '../components/truncated_label';

// Single source of truth: the full prompt. The card truncates it to the real
// available width via TruncatedLabel, and the hover preview shows it in full.
// (Do not add a hand-shortened variant — a pre-truncated string fed to a
// width-aware truncator can never fill the actual card space.) Each carries a
// leading glyph shown in the mobile list layout.
const SUGGESTIONS: ReadonlyArray<{text: string; icon: IconName}> = [
  {
    text: 'Find new therapeutic targets for M.tuberculosis by combining host-pathogen interaction datasets with recent literature.',
    icon: 'search',
  },
  {
    text: 'Generate novel hypotheses for the link between synaptic pruning and treatment-resistant neuroinflammation.',
    icon: 'lightbulb',
  },
  {
    text: 'Propose new mechanisms to explain why some patients fail to respond to checkpoint inhibitor therapy.',
    icon: 'stars',
  },
];

// Copy for the desktop-only 1-2-3 onboarding timeline rendered below the
// title (hidden on mobile to save vertical space; see the `!isMobile` guard).
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

/**
 * Renders the session-home surface shown before any conversation has
 * started: the greeting title, the desktop onboarding timeline, the
 * suggestion prompt row, the composer (in its roomy `large` mode), and the
 * desktop-only recents panel (HomeRecentsPanel). Rendered by ChatWorkspace
 * when `hasConversation` is false.
 *
 * @param input Controlled composer value, owned by the parent session state.
 * @param setInput Updates the controlled composer value.
 * @param pubmedEnabled Whether the PubMed connector toggle is on.
 * @param onPubmedEnabledChange Callback fired when the PubMed toggle changes.
 * @param onSubmit Form submit handler for the composer.
 * @param runs Recent runs to list in the recents panel.
 * @param scoresByRunId Top Elo score per run id, keyed for the recents panel.
 * @param showAllRecents Whether the recents panel is expanded past the cap.
 * @param onToggleShowAll Toggles the recents panel's expanded state.
 */
export function HomeStage({
  input,
  setInput,
  pubmedEnabled,
  onPubmedEnabledChange,
  onSubmit,
  runs,
  scoresByRunId,
  showAllRecents,
  onToggleShowAll,
}: {
  input: string;
  setInput: (value: string) => void;
  pubmedEnabled: boolean;
  onPubmedEnabledChange: (enabled: boolean) => void;
  onSubmit: (e: FormEvent<HTMLFormElement>) => void;
  runs: Run[];
  scoresByRunId: Record<string, number | null>;
  showAllRecents: boolean;
  onToggleShowAll: () => void;
}) {
  // Tracks which suggestion (by its full text, used as the identity key) is
  // currently hovered/focused, to show that suggestion's full-text preview
  // bubble and its "previewed" button styling.
  const [hoveredSuggestion, setHoveredSuggestion] = useState<string | null>(
    null,
  );
  // Mobile shows suggestions as a single-line glyph list, so the label
  // truncates to one line (word-level, via TruncatedLabel); desktop keeps the
  // two-line card. Tracks viewport width so the line budget follows the
  // active layout.
  const isMobile = useIsMobile();

  // Filling the composer from a suggestion also dismisses that suggestion's
  // preview bubble, since the row is about to lose focus/hover anyway.
  function selectSuggestion(text: string) {
    setInput(text);
    setHoveredSuggestion(null);
  }

  return (
    <section className={HOME_STAGE_CLASSES}>
      <div className={HOME_MAIN_CLASSES}>
        <HomeGreeting isMobile={isMobile} />
        <HomeSuggestionRow
          isMobile={isMobile}
          hoveredSuggestion={hoveredSuggestion}
          onPreview={setHoveredSuggestion}
          onSelect={selectSuggestion}
        />
        <Composer
          input={input}
          setInput={setInput}
          disabled={false}
          large
          pubmedEnabled={pubmedEnabled}
          onPubmedEnabledChange={onPubmedEnabledChange}
          onSubmit={onSubmit}
        />
      </div>
      <HomeRecentsRegion
        isMobile={isMobile}
        runs={runs}
        scoresByRunId={scoresByRunId}
        showAllRecents={showAllRecents}
        onToggleShowAll={onToggleShowAll}
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
  hoveredSuggestion,
  onPreview,
  onSelect,
}: {
  isMobile: boolean;
  hoveredSuggestion: string | null;
  onPreview: (text: string | null) => void;
  onSelect: (text: string) => void;
}) {
  return (
    <div className={HOME_SUGGESTION_ROW_CLASSES}>
      {SUGGESTIONS.map((suggestion, index) => (
        <SuggestionCard
          key={suggestion.text}
          suggestion={suggestion}
          index={index}
          isMobile={isMobile}
          isPreviewed={hoveredSuggestion === suggestion.text}
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

// Renders one suggestion card in the home-stage suggestion row: the
// hover/focus-revealed full-text preview bubble, and the button that fills
// the composer with the suggestion's text when selected.
function SuggestionCard({
  suggestion,
  index,
  isMobile,
  isPreviewed,
  onPreview,
  onSelect,
}: {
  suggestion: {text: string; icon: IconName};
  index: number;
  isMobile: boolean;
  isPreviewed: boolean;
  onPreview: (text: string | null) => void;
  onSelect: (text: string) => void;
}) {
  // The preview bubble anchors differently per column (start/center/end) so
  // it stays roughly centered over the row rather than overflowing past the
  // viewport edge for the first/last card.
  const previewPositionClass =
    index === 0
      ? HOME_SUGGESTION_PREVIEW_START_CLASSES
      : index === 1
        ? HOME_SUGGESTION_PREVIEW_CENTER_CLASSES
        : HOME_SUGGESTION_PREVIEW_END_CLASSES;

  return (
    <div className={HOME_SUGGESTION_SLOT_CLASSES}>
      <p
        className={[
          HOME_SUGGESTION_PREVIEW_CLASSES,
          previewPositionClass,
          isPreviewed ? HOME_SUGGESTION_PREVIEW_VISIBLE_CLASSES : '',
        ]
          .filter(Boolean)
          .join(' ')}
        aria-hidden={!isPreviewed}
      >
        {suggestion.text}
      </p>
      <button
        type="button"
        className={[
          HOME_SUGGESTION_BUTTON_CLASSES,
          isPreviewed ? HOME_SUGGESTION_BUTTON_PREVIEWED_CLASSES : '',
        ]
          .filter(Boolean)
          .join(' ')}
        // Mouse/pointer and focus/blur handlers both drive the same preview
        // state, so touch/keyboard users get the same full-text preview that
        // mouse hover provides.
        onMouseEnter={() => onPreview(suggestion.text)}
        onMouseLeave={() => onPreview(null)}
        onPointerEnter={() => onPreview(suggestion.text)}
        onPointerLeave={() => onPreview(null)}
        onFocus={() => onPreview(suggestion.text)}
        onBlur={() => onPreview(null)}
        // Clicking a suggestion fills the composer with its full text rather
        // than submitting immediately.
        onClick={() => onSelect(suggestion.text)}
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
          text={suggestion.text}
          lines={isMobile ? 1 : 2}
        />
      </button>
    </div>
  );
}
