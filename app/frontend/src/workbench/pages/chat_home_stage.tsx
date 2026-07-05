import {type FormEvent, useState} from 'react';
import {type Run} from '@/api/runs';
import {
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
import {TruncatedLabel} from '../components/truncated_label';

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

  return (
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
                <h2 className={HOME_STEP_HEADING_CLASSES}>{step.title}</h2>
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
                    isPreviewed ? HOME_SUGGESTION_PREVIEW_VISIBLE_CLASSES : '',
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
                    isPreviewed ? HOME_SUGGESTION_BUTTON_PREVIEWED_CLASSES : '',
                  ]
                    .filter(Boolean)
                    .join(' ')}
                  onMouseEnter={() => setHoveredSuggestion(suggestion.full)}
                  onMouseLeave={() => setHoveredSuggestion(null)}
                  onPointerEnter={() => setHoveredSuggestion(suggestion.full)}
                  onPointerLeave={() => setHoveredSuggestion(null)}
                  onFocus={() => setHoveredSuggestion(suggestion.full)}
                  onBlur={() => setHoveredSuggestion(null)}
                  onClick={() => {
                    setInput(suggestion.full);
                    setHoveredSuggestion(null);
                  }}
                >
                  <TruncatedLabel
                    className={HOME_SUGGESTION_TEXT_CLASSES}
                    text={suggestion.short}
                    lines={2}
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

      <HomeRecentsPanel
        runs={runs}
        scoresByRunId={scoresByRunId}
        showAll={showAllRecents}
        onToggleShowAll={onToggleShowAll}
      />
    </section>
  );
}
