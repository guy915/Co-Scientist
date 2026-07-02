import '@material/web/icon/icon.js';

import {type ReactNode, useLayoutEffect, useRef, useState} from 'react';
import {type RunFocus, type RunTier} from '@/api/runs';
import {conciseTitle} from '@/lib/text';
import {FOCUS_OPTIONS, type InferredRunSpec, TIER_OPTIONS} from '../run_spec';
import {tooltipClassNames} from '../tooltip';
import {
  CHAT_BUBBLE_ROW_CLASSES,
  CHAT_BUBBLE_USER_ROW_CLASSES,
  MESSAGE_ACTION_BUTTON_CLASSES,
  MESSAGE_ACTION_ICON_CLASSES,
  MESSAGE_ACTIONS_CLASSES,
  MESSAGE_ACTIONS_END_CLASSES,
  MODEL_BUBBLE_CLASSES,
  OPTION_CARD_BASE_CLASSES,
  OPTION_CARD_SELECTED_CLASSES,
  OPTION_DESCRIPTION_CLASSES,
  OPTION_GRID_CLASSES,
  OPTION_GROUP_CLASSES,
  OPTION_GROUP_LEGEND_CLASSES,
  OPTION_INPUT_CLASSES,
  OPTION_LABEL_CLASSES,
  OPTION_MARKER_CLASSES,
  OPTION_MARKER_SELECTED_CLASSES,
  PLAN_EDIT_BUTTON_CLASSES,
  PLAN_EDIT_ICON_CLASSES,
  PLAN_HEADING_CLASSES,
  PLAN_SUBHEADING_CLASSES,
  PLAN_TITLE_CLASSES,
  SETUP_ACTIONS_CLASSES,
  SETUP_DOCUMENT_CLASSES,
  SETUP_DOCUMENT_TITLE_CLASSES,
  SETUP_MESSAGE_CLASSES,
  SETUP_PARAGRAPH_CLASSES,
  SETUP_PRIMARY_BUTTON_CLASSES,
  SETUP_SECONDARY_BUTTON_CLASSES,
  SPEC_DETAIL_CLASSES,
  SPEC_GRID_CLASSES,
  SPEC_LIST_CLASSES,
  SPEC_ROW_CLASSES,
  SPEC_TERM_CLASSES,
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
  USER_BUBBLE_CLASSES,
  USER_BUBBLE_TEXT_CLASSES,
  USER_BUBBLE_TEXT_COLLAPSED_CLASSES,
  USER_COLLAPSE_BUTTON_CLASSES,
} from './chat_setup_classes';

export interface ChatEntry {
  id: string;
  role: 'user' | 'assistant';
  content: string;
  created_at: number;
}

export interface StartedSession {
  id: string;
  title: string;
  at: number;
}

interface MessageAction {
  icon: string;
  label: string;
  onClick: () => void;
}

export async function copyText(text: string) {
  if (navigator.clipboard?.writeText) {
    await navigator.clipboard.writeText(text);
  }
}

export function referenceSetupTitle(goal: string): string {
  if (/liver fibrosis|MASLD|MASH/i.test(goal)) {
    return 'Reversing MASLD/MASH Fibrosis Hypothesis';
  }
  return conciseTitle(goal);
}

function downloadText(
  filename: string,
  text: string,
  type = 'text/markdown;charset=utf-8',
) {
  const blob = new Blob([text], {type});
  const url = URL.createObjectURL(blob);
  const anchor = document.createElement('a');
  anchor.href = url;
  anchor.download = filename;
  anchor.click();
  URL.revokeObjectURL(url);
}

function MessageActionRow({
  actions,
  align = 'start',
}: {
  actions: MessageAction[];
  align?: 'start' | 'end';
}) {
  return (
    <div
      className={
        align === 'end' ? MESSAGE_ACTIONS_END_CLASSES : MESSAGE_ACTIONS_CLASSES
      }
    >
      {actions.map(action => (
        <button
          key={action.label}
          type="button"
          className={tooltipClassNames({
            className: MESSAGE_ACTION_BUTTON_CLASSES,
            placement: 'top',
          })}
          aria-label={action.label}
          data-tooltip={action.label}
          onClick={action.onClick}
        >
          <md-icon aria-hidden="true" className={MESSAGE_ACTION_ICON_CLASSES}>
            {action.icon}
          </md-icon>
        </button>
      ))}
    </div>
  );
}

export function ChatBubble({
  message,
  onEdit,
  onCopyRequest,
  onRetry,
}: {
  message: ChatEntry;
  onEdit: () => void;
  onCopyRequest: () => void;
  onRetry: () => void;
}) {
  const isUser = message.role === 'user';
  const textRef = useRef<HTMLSpanElement>(null);
  const [canCollapse, setCanCollapse] = useState(false);
  const [expanded, setExpanded] = useState(false);

  useLayoutEffect(() => {
    if (!isUser || !textRef.current) {
      setCanCollapse(false);
      return;
    }
    const element = textRef.current;
    const styles = window.getComputedStyle(element);
    const fontSize = Number.parseFloat(styles.fontSize) || 16;
    const lineHeight =
      Number.parseFloat(styles.lineHeight) || Math.round(fontSize * 1.45);
    const naturalHeight = element.scrollHeight;
    const exceedsThreeLines = naturalHeight > lineHeight * 3 + 2;
    setCanCollapse(exceedsThreeLines || message.content.length > 140);
    setExpanded(false);
  }, [isUser, message.content]);

  const bubbleClassName = isUser ? USER_BUBBLE_CLASSES : MODEL_BUBBLE_CLASSES;

  return (
    <div
      className={
        isUser ? CHAT_BUBBLE_USER_ROW_CLASSES : CHAT_BUBBLE_ROW_CLASSES
      }
    >
      <div className={bubbleClassName}>
        <span
          ref={isUser ? textRef : undefined}
          className={
            isUser && canCollapse && !expanded
              ? USER_BUBBLE_TEXT_COLLAPSED_CLASSES
              : USER_BUBBLE_TEXT_CLASSES
          }
        >
          {message.content}
        </span>
        {isUser && canCollapse && (
          <button
            type="button"
            className={USER_COLLAPSE_BUTTON_CLASSES}
            aria-label={expanded ? 'Collapse request' : 'Expand request'}
            title={expanded ? 'Collapse request' : 'Expand request'}
            onClick={() => setExpanded(current => !current)}
          >
            <md-icon aria-hidden="true">
              {expanded ? 'expand_less' : 'expand_more'}
            </md-icon>
          </button>
        )}
      </div>
      {isUser ? (
        <MessageActionRow
          align="end"
          actions={[
            {
              icon: 'edit',
              label: 'Edit request',
              onClick: onEdit,
            },
            {
              icon: 'content_copy',
              label: 'Copy request',
              onClick: onCopyRequest,
            },
          ]}
        />
      ) : (
        <MessageActionRow
          actions={[
            {icon: 'refresh', label: 'Retry response', onClick: onRetry},
            {
              icon: 'content_copy',
              label: 'Copy response',
              onClick: () => void copyText(message.content),
            },
            {
              icon: 'download',
              label: 'Download response',
              onClick: () =>
                downloadText('co-scientist-response.md', message.content),
            },
          ]}
        />
      )}
    </div>
  );
}

export function RunSpecCard({
  spec,
  isStarting,
  locked = false,
  onFocusChange,
  onTierChange,
  onCancel,
  onEdit,
  onRetry,
  onStart,
}: {
  spec: InferredRunSpec;
  isStarting: boolean;
  locked?: boolean;
  onFocusChange: (focus: RunFocus) => void;
  onTierChange: (tier: RunTier) => void;
  onCancel: () => void;
  onEdit: () => void;
  onRetry: () => void;
  onStart: () => void;
}) {
  const responseText = formatRunSpecResponse(spec);

  return (
    <section className={SETUP_MESSAGE_CLASSES} aria-label="Inferred run setup">
      <p className={SETUP_PARAGRAPH_CLASSES}>
        Okay, I've drafted the requirements to propose a novel, testable
        hypothesis for this research session. Let me know if you have any
        suggestions.
      </p>
      <p className={`reference-review-copy ${SETUP_PARAGRAPH_CLASSES}`}>
        Please review or edit the details below as needed. Once ready, click
        "Start research" to start generating hypotheses.
      </p>
      <div className={PLAN_HEADING_CLASSES}>
        <h2 className={PLAN_TITLE_CLASSES}>Research plan</h2>
        <button
          type="button"
          className={tooltipClassNames({
            className: PLAN_EDIT_BUTTON_CLASSES,
            placement: 'top',
          })}
          aria-label="Edit research plan"
          data-tooltip="Edit research plan"
          onClick={onEdit}
        >
          <md-icon aria-hidden="true" className={PLAN_EDIT_ICON_CLASSES}>
            edit
          </md-icon>
        </button>
      </div>
      <p className={PLAN_SUBHEADING_CLASSES}>
        Here's my plan to tackle the topic:
      </p>
      <div className={SETUP_DOCUMENT_CLASSES}>
        <h3 className={SETUP_DOCUMENT_TITLE_CLASSES}>
          {referenceSetupTitle(spec.goal)}
        </h3>
        <dl className={SPEC_GRID_CLASSES}>
          <SpecRow label="Goal">{spec.goal}</SpecRow>
          <SpecList label="Requirements" values={spec.requirements} />
          <SpecList label="Attributes" values={spec.attributes} />
          <SpecList label="Criteria" values={spec.criteria} />
        </dl>
        <RunOptionGroup
          label="Focus"
          name="focus"
          value={spec.focus}
          options={FOCUS_OPTIONS}
          disabled={locked}
          onChange={value => onFocusChange(value as RunFocus)}
        />
        <RunOptionGroup
          label="Tier"
          name="tier"
          value={spec.tier}
          options={TIER_OPTIONS}
          disabled={locked}
          onChange={value => onTierChange(value as RunTier)}
        />
        <div className={SETUP_ACTIONS_CLASSES}>
          {!locked && (
            <button
              type="button"
              className={SETUP_SECONDARY_BUTTON_CLASSES}
              onClick={onCancel}
              disabled={isStarting}
            >
              Cancel
            </button>
          )}
          <button
            type="button"
            className={SETUP_PRIMARY_BUTTON_CLASSES}
            onClick={onStart}
            disabled={isStarting || locked}
          >
            {isStarting ? 'Starting...' : 'Start research'}
          </button>
        </div>
      </div>
      <MessageActionRow
        actions={[
          {icon: 'refresh', label: 'Retry response', onClick: onRetry},
          {
            icon: 'content_copy',
            label: 'Copy response',
            onClick: () => void copyText(responseText),
          },
          {
            icon: 'download',
            label: 'Download response',
            onClick: () =>
              downloadText('co-scientist-research-plan.md', responseText),
          },
        ]}
      />
    </section>
  );
}

export function StartedSessionCard({
  session,
  onOpen,
  onRetry,
  onNewTopic,
}: {
  session: StartedSession;
  onOpen: () => void;
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
      <button
        type="button"
        className={STARTED_SESSION_CARD_CLASSES}
        onClick={onOpen}
      >
        <span>
          <strong className={STARTED_SESSION_TITLE_CLASSES}>
            {session.title}
          </strong>
          <small className={STARTED_SESSION_META_CLASSES}>
            Research session
          </small>
        </span>
        <span className={STARTED_OPEN_CLASSES}>Open</span>
      </button>
      <div className={STARTED_NEXT_CLASSES}>
        <p className={STARTED_NEXT_COPY_CLASSES}>
          What would you like to do next?
        </p>
        <button
          type="button"
          className={STARTED_NEXT_BUTTON_CLASSES}
          onClick={onOpen}
        >
          View session details
        </button>
        <button
          type="button"
          className={STARTED_NEXT_BUTTON_CLASSES}
          onClick={onNewTopic}
        >
          Start a new research goal session on a new topic
        </button>
      </div>
      <MessageActionRow
        actions={[
          {icon: 'refresh', label: 'Retry response', onClick: onRetry},
          {
            icon: 'content_copy',
            label: 'Copy response',
            onClick: () => void copyText(responseText),
          },
          {
            icon: 'download',
            label: 'Download response',
            onClick: () =>
              downloadText('co-scientist-session-started.md', responseText),
          },
        ]}
      />
    </section>
  );
}

function formatRunSpecResponse(spec: InferredRunSpec): string {
  return [
    `# ${referenceSetupTitle(spec.goal)}`,
    '',
    "I've drafted the requirements to propose a novel, testable hypothesis for this research session.",
    '',
    '## Goal',
    spec.goal,
    '',
    '## Requirements',
    ...spec.requirements.map(value => `* ${value}`),
    '',
    '## Attributes',
    ...spec.attributes.map(value => `* ${value}`),
    '',
    '## Criteria',
    ...spec.criteria.map(value => `* ${value}`),
    '',
    '## Setup Options',
    `* **Focus:** ${runOptionLabel(FOCUS_OPTIONS, spec.focus)}`,
    `* **Tier:** ${runOptionLabel(TIER_OPTIONS, spec.tier)}`,
  ].join('\n');
}

function formatStartedSessionResponse(session: StartedSession): string {
  return [
    `# ${session.title}`,
    '',
    'Your session has been started and Co-Scientist has started research.',
    '',
    '## Status',
    'You can view and interact with your session at any time, but note that it might take a few minutes for the first ideas to be ready to view.',
    '',
    '* **Type:** Research session',
    '* **Action:** Open the session details when you want to inspect progress.',
  ].join('\n');
}

function runOptionLabel(
  options: ReadonlyArray<{id: string; label: string}>,
  value: string,
): string {
  return options.find(option => option.id === value)?.label || value;
}

function SpecRow({label, children}: {label: string; children: ReactNode}) {
  return (
    <div className={SPEC_ROW_CLASSES}>
      <dt className={SPEC_TERM_CLASSES}>{label}:</dt>
      <dd className={SPEC_DETAIL_CLASSES}>{children}</dd>
    </div>
  );
}

function SpecList({label, values}: {label: string; values: string[]}) {
  return (
    <SpecRow label={label}>
      <ul className={SPEC_LIST_CLASSES}>
        {values.map(value => (
          <li key={value}>{value}</li>
        ))}
      </ul>
    </SpecRow>
  );
}

function RunOptionGroup({
  label,
  name,
  value,
  options,
  disabled = false,
  onChange,
}: {
  label: string;
  name: string;
  value: string;
  options: ReadonlyArray<{id: string; label: string; description: string}>;
  disabled?: boolean;
  onChange: (value: string) => void;
}) {
  return (
    <fieldset className={OPTION_GROUP_CLASSES} aria-label={label}>
      <legend className={OPTION_GROUP_LEGEND_CLASSES}>{label}</legend>
      <div className={OPTION_GRID_CLASSES}>
        {options.map(option => (
          <label
            key={option.id}
            className={[
              OPTION_CARD_BASE_CLASSES,
              disabled ? 'cursor-default' : 'cursor-pointer',
              option.id === value ? OPTION_CARD_SELECTED_CLASSES : '',
            ]
              .filter(Boolean)
              .join(' ')}
          >
            <input
              type="radio"
              className={OPTION_INPUT_CLASSES}
              name={name}
              value={option.id}
              checked={option.id === value}
              disabled={disabled}
              onChange={() => onChange(option.id)}
            />
            <span
              className={[
                OPTION_MARKER_CLASSES,
                option.id === value ? OPTION_MARKER_SELECTED_CLASSES : '',
              ]
                .filter(Boolean)
                .join(' ')}
              aria-hidden="true"
            />
            <strong className={OPTION_LABEL_CLASSES}>{option.label}</strong>
            <small className={OPTION_DESCRIPTION_CLASSES}>
              {option.description}
            </small>
          </label>
        ))}
      </div>
    </fieldset>
  );
}
