import {Link} from 'react-router-dom';
import {TruncatedLabel} from '../components/truncated_label';
import {
  STARTED_COPY_CLASSES,
  STARTED_COPY_PARAGRAPH_CLASSES,
  STARTED_MESSAGE_CLASSES,
  STARTED_NEXT_BUTTON_CLASSES,
  STARTED_NEXT_CLASSES,
  STARTED_NEXT_COPY_CLASSES,
  STARTED_OPEN_CLASSES,
  STARTED_SESSION_CARD_CLASSES,
  STARTED_SESSION_META_CLASSES,
  STARTED_SESSION_TITLE_CLASSES,
} from './chat_setup_classes';
import {
  MessageActionRow,
  responseActions,
} from './chat_timeline_message_actions';

/** A run that has been started, as shown by the timeline's terminal card. */
export interface StartedSession {
  id: string;
  title: string;
  at: number;
}

/**
 * Renders the terminal timeline card shown once a research run has actually
 * been started: confirmation copy, a clickable card linking to the run's
 * detail page, and "what next" actions (open details, or start a new topic).
 *
 * @param session The started session (id, title, start timestamp) to display.
 * @param href Route of the run's detail page. A URL rather than an open
 *   handler so both affordances below can be real links, which a middle- or
 *   cmd-click opens in a new browser tab.
 * @param onRetry Handler to re-timestamp/re-surface this card (see its call
 *   site for why: bumping `at` re-sorts it to the current time).
 * @param onNewTopic Handler to reset the workspace and start a fresh topic.
 */
export function StartedSessionCard({
  session,
  href,
  onRetry,
  onNewTopic,
}: {
  session: StartedSession;
  href: string;
  onRetry: () => void;
  onNewTopic: () => void;
}) {
  const responseText = formatStartedSessionResponse(session);

  return (
    <section
      className={STARTED_MESSAGE_CLASSES}
      aria-label="Started research session"
    >
      <div className={STARTED_COPY_CLASSES}>
        <p className={STARTED_COPY_PARAGRAPH_CLASSES}>
          Your session has been started and Co-Scientist has started research!
        </p>
        <p className={STARTED_COPY_PARAGRAPH_CLASSES}>
          You can view and interact with your session at any time, but note that
          it might take a few minutes for the first ideas to be ready to view.
        </p>
      </div>
      <SessionLinkCard session={session} href={href} />
      <SessionNextActions href={href} onNewTopic={onNewTopic} />
      <MessageActionRow
        actions={responseActions(
          onRetry,
          responseText,
          'co-scientist-session-started.md',
        )}
      />
    </section>
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
// for the card's copy/download actions (see responseActions).
function formatStartedSessionResponse(session: StartedSession): string {
  return [
    `# ${session.title}`,
    '',
    'Your session has been started and Co-Scientist has started research.',
    '',
    '## Status',
    'You can view and interact with your session at any time, but note that ' +
      'it might take a few minutes for the first ideas to be ready to view.',
    '',
    '* **Type:** Research session',
    '* **Action:** Open the session details when you want to inspect progress.',
  ].join('\n');
}
