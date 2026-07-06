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
  const [hoveredSuggestion, setHoveredSuggestion] = useState<string | null>(
    null,
  );
  // Mobile shows suggestions as a single-line glyph list, so the label truncates
  // to one line (word-level, via TruncatedLabel); desktop keeps the two-line
  // card. Tracks viewport width so the line budget follows the active layout.
  const isMobile = useIsMobile();

  return (
    <section className={HOME_STAGE_CLASSES}>
      <div className={HOME_MAIN_CLASSES}>
        {/* Phone-only flask mark above the title (Gemini-style greeting); the
            desktop header lockup already carries the mark. */}
        {isMobile && (
          <GoogleLabsIcon aria-hidden="true" className={HOME_LOGO_CLASSES} />
        )}
        <h1 className={HOME_TITLE_CLASSES}>
          What breakthrough should we make today?
        </h1>

        {/* The 1-2-3 onboarding timeline is desktop-only; mobile drops it
            entirely to free vertical space. */}
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

        <div className={HOME_SUGGESTION_ROW_CLASSES}>
          {SUGGESTIONS.map((suggestion, index) => {
            const isPreviewed = hoveredSuggestion === suggestion.text;
            const previewPositionClass =
              index === 0
                ? HOME_SUGGESTION_PREVIEW_START_CLASSES
                : index === 1
                  ? HOME_SUGGESTION_PREVIEW_CENTER_CLASSES
                  : HOME_SUGGESTION_PREVIEW_END_CLASSES;
            return (
              <div
                key={suggestion.text}
                className={HOME_SUGGESTION_SLOT_CLASSES}
              >
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
                  onMouseEnter={() => setHoveredSuggestion(suggestion.text)}
                  onMouseLeave={() => setHoveredSuggestion(null)}
                  onPointerEnter={() => setHoveredSuggestion(suggestion.text)}
                  onPointerLeave={() => setHoveredSuggestion(null)}
                  onFocus={() => setHoveredSuggestion(suggestion.text)}
                  onBlur={() => setHoveredSuggestion(null)}
                  onClick={() => {
                    setInput(suggestion.text);
                    setHoveredSuggestion(null);
                  }}
                >
                  {/* Leading glyph is part of the phone list layout only;
                      desktop cards are text-only. */}
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
          })}
        </div>

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

      {/* Recents is desktop-only; on phones recent runs live in the nav
          drawer's Chats list. */}
      {!isMobile && (
        <HomeRecentsPanel
          runs={runs}
          scoresByRunId={scoresByRunId}
          showAll={showAllRecents}
          onToggleShowAll={onToggleShowAll}
        />
      )}
    </section>
  );
}
