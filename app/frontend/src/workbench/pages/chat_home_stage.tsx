import {type FormEvent, useState} from 'react';
import {type Run} from '@/api/runs';
import {joinClasses} from '../classes';
import {useIsMobile} from '../hooks/use_is_mobile';
import {Composer} from './chat_composer';
import {type ConnectorToggleProps} from './chat_composer_connectors';
import {useChatHistoryContext} from '../hooks/chat_history_context';
import {HomeRecentsPanel} from './home_recents';
import {SESSION_STEPS, SUGGESTIONS} from './chat_home_suggestions';
import {HomeSuggestionRow} from './chat_home_suggestion_row';
import {GoogleLabsIcon} from '../components/google_labs_icon';
import {Icon} from '@/components/icon';
import {smoothScrollToSection} from '@/lib/smooth_scroll';

export {SUGGESTIONS, type Suggestion} from './chat_home_suggestions';

/** Inputs for the home composer and its recent runs. */
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
          scoresByRunId={props.scoresByRunId}
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
