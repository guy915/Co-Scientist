import {Link} from 'react-router-dom';
import {TruncatedLabel} from '../components/truncated_label';
import {
  STARTED_NEXT_BUTTON_CLASSES,
  STARTED_NEXT_CLASSES,
  STARTED_NEXT_COPY_CLASSES,
  STARTED_OPEN_CLASSES,
  STARTED_SESSION_CARD_CLASSES,
  STARTED_SESSION_META_CLASSES,
  STARTED_SESSION_TITLE_CLASSES,
} from './chat_setup_classes';
import {AssistantMessage, MessageAttachment} from './chat_timeline_bubble';
import {responseActions} from './chat_timeline_message_actions';

/** A run that has been started, as shown by the timeline's terminal card. */
export interface StartedSession {
  id: string;
  title: string;
  at: number;
  /**
   * The Agent's reply to the scientist's start request, shown as the card's
   * lead-in so a started run reads as one response rather than a card under
   * a canned notice. Written by the model and streamed in as it arrives
   * (see chat_session_start_run.ts), which is why it grows from empty.
   */
  intro?: string;
  /** The chain of thought behind that reply, disclosed above the card. */
  reasoning?: string;
  /**
   * True while the reply is still being written. It is what tells an empty
   * `intro` that is still filling from one that never will, so the standby
   * copy below does not flash in front of the model's own first sentence.
   */
  announcing?: boolean;
}

/**
 * What the card says when no reply was written for it: a run started before
 * this exchange existed and reopened since, a provider that could not be
 * reached, or a turn the scientist stopped.
 *
 * The wording the card carried unconditionally until the Agent started
 * answering for itself. It is the same substance the model is asked for
 * (run under way; open it whenever, first ideas take a few minutes), because
 * the run did start in every one of those cases and the scientist needs the
 * same two facts about it.
 */
export const STARTED_SESSION_STANDBY_COPY =
  'Your session has been started and Co-Scientist has started research!' +
  '\n\n' +
  'You can view and interact with your session at any time, but note that ' +
  'it might take a few minutes for the first ideas to be ready to view.';

// The lead-in text to render: the Agent's own reply, the standby copy once
// it is settled that there will not be one, and nothing at all while the
// reply is still on its way.
function introCopy(session: StartedSession): string {
  const written = session.intro?.trim();
  if (written) return written;
  return session.announcing ? '' : STARTED_SESSION_STANDBY_COPY;
}

/**
 * Renders the terminal timeline turn shown once a research run has actually
 * been started: the Agent's own confirmation as an ordinary assistant reply,
 * carrying the session link card and "what next" actions (open details, or
 * start a new topic) as its inline attachment.
 *
 * @param session The started session (id, title, start timestamp) to display.
 * @param href Route of the run's detail page. A URL rather than an open
 *   handler so both affordances below can be real links, which a middle- or
 *   cmd-click opens in a new browser tab.
 * @param onNewTopic Handler to reset the workspace and start a fresh topic.
 *
 * Carries copy/download but no retry: this card reports a run the server has
 * already started, so there is no response here to regenerate. The control
 * used to re-sort the card to the current time, which from a click looked
 * exactly like nothing happening.
 */
export function StartedSessionCard({
  session,
  href,
  onNewTopic,
}: {
  session: StartedSession;
  href: string;
  onNewTopic: () => void;
}) {
  const intro = introCopy(session);
  const responseText = formatStartedSessionResponse(session, intro);

  return (
    <AssistantMessage
      content={intro}
      ariaLabel="Started research session"
      attachment={
        // Withheld until the reply is written. The turn reads as an answer
        // that hands over the session, so the session block belongs after
        // the answer, not in front of a reply that has not started arriving
        // -- and it grew under the reader's eyes while the text streamed in
        // above it. A run reopened from history has no announcement to wait
        // for (`announcing` is unset) and shows it straight away.
        session.announcing ? undefined : (
          <MessageAttachment>
            <SessionLinkCard session={session} href={href} />
            <SessionNextActions href={href} onNewTopic={onNewTopic} />
          </MessageAttachment>
        )
      }
      actions={responseActions(
        null,
        responseText,
        'co-scientist-session-started.md',
      )}
    />
  );
}

// The clickable card linking to the started session's detail page: title
// (truncated) plus a "Research session" byline and an "Open" affordance.
function SessionLinkCard({
  session,
  href,
}: {
  session: StartedSession;
  href: string;
}) {
  return (
    <Link to={href} className={`${STARTED_SESSION_CARD_CLASSES} no-underline`}>
      <span className="block min-w-0">
        <strong className={STARTED_SESSION_TITLE_CLASSES}>
          <TruncatedLabel
            className="block min-w-0 overflow-hidden whitespace-nowrap"
            text={session.title}
          />
        </strong>
        <small className={STARTED_SESSION_META_CLASSES}>Research session</small>
      </span>
      <span className={STARTED_OPEN_CLASSES}>Open</span>
    </Link>
  );
}

// The "what next" block under a started session: view the session details,
// or start a fresh topic. The first is a navigation, so it is a link wearing
// the pill-button styling rather than a button.
function SessionNextActions({
  href,
  onNewTopic,
}: {
  href: string;
  onNewTopic: () => void;
}) {
  return (
    <div className={STARTED_NEXT_CLASSES}>
      <p className={STARTED_NEXT_COPY_CLASSES}>
        What would you like to do next?
      </p>
      <Link
        to={href}
        className={`${STARTED_NEXT_BUTTON_CLASSES} inline-flex items-center no-underline`}
      >
        View session details
      </Link>
      <button
        type="button"
        className={STARTED_NEXT_BUTTON_CLASSES}
        onClick={onNewTopic}
      >
        Start a new research goal session on a new topic
      </button>
    </div>
  );
}

// Renders the started-session card's content as a Markdown document, used
// for the card's copy/download actions (see responseActions). Carries the
// reply actually on screen -- the Agent's own, or the standby copy -- rather
// than a second wording of it that would drift from what was read.
function formatStartedSessionResponse(
  session: StartedSession,
  intro: string,
): string {
  return [
    `# ${session.title}`,
    '',
    intro || STARTED_SESSION_STANDBY_COPY,
    '',
    '* **Type:** Research session',
    '* **Action:** Open the session details when you want to inspect progress.',
  ].join('\n');
}
