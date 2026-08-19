import {
  type Dispatch,
  type FormEvent,
  type SetStateAction,
  useState,
} from 'react';
import {type Run} from '@/api/runs';
import {joinClasses} from '../classes';
import {DiscoveryDialog} from '../components/discovery_dialog';
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
  HOME_TITLE_CLASSES,
} from './chat_home_classes';
import {Composer} from './chat_composer';
import {type ConnectorToggleProps} from './chat_composer_connectors';
import {HomeRecentsPanel} from './home_recents';
import {
  SESSION_STEPS,
  type Suggestion,
  activeSuggestions,
} from './chat_home_suggestions';
import {HomeSuggestionRow} from './chat_home_suggestion_row';
import {useAudience} from '../audience_context';
import {GoogleLabsIcon} from '../components/google_labs_icon';

export {
  SUGGESTIONS,
  type Suggestion,
  activeSuggestions,
} from './chat_home_suggestions';

/**
 * Props for HomeStage, named at module level per the destructured prop
 * signature otherwise pushing the component past the line cap.
 *
 * `input`/`setInput` are the controlled composer value, owned by the parent
 * session state. `connectors` carries each connector toggle's state and
 * change callback. `onSubmit` is the composer's form submit handler.
 * `runs`/`scoresByRunId` feed the recents panel, and `showAllRecents`/
 * `onToggleShowAll` control its expanded state.
 */
export interface HomeStageProps {
  input: string;
  setInput: (value: string) => void;
  connectors: ConnectorToggleProps;
  onSubmit: (e: FormEvent<HTMLFormElement>, files: File[]) => void;
  runs: Run[];
  scoresByRunId: Record<string, number | null>;
  showAllRecents: boolean;
  onToggleShowAll: () => void;
}

/** The composer fields HomeStage passes straight through to Composer. */
type HomeComposerProps = Pick<
  HomeStageProps,
  'input' | 'setInput' | 'connectors' | 'onSubmit'
>;

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
  connectors,
  onSubmit,
}: HomeComposerProps) {
  return (
    <Composer
      input={input}
      setInput={setInput}
      busy={false}
      large
      connectors={connectors}
      onSubmit={onSubmit}
    />
  );
}

// The home stage's left column: the greeting, the suggestion prompt row, and
// the composer. Split out of HomeStage so it only needs the suggestion-row
// state as extra props on top of HomeStageProps' composer fields.
function HomeMainColumn(
  props: HomeComposerProps & {
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
      <DiscoveryEntry />
    </div>
  );
}

// The way into a computational-discovery run: it evolves a program
// against a measured objective rather than generating hypotheses, so it
// takes a spec the composer has no way to ask for. Beneath the composer
// and understated on purpose -- it is the second thing this product
// does, not a peer of the thing it opens on.
function DiscoveryEntry() {
  const [open, setOpen] = useState(false);
  return (
    <>
      <button
        type="button"
        className="reference-home-discovery-entry"
        onClick={() => setOpen(true)}
      >
        Or evolve a program against a measured objective
      </button>
      {open && <DiscoveryDialog onClose={() => setOpen(false)} />}
    </>
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
