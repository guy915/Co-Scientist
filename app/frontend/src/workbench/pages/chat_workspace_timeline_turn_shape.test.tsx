import {expect, it, vi} from 'vitest';
import {screen} from '@testing-library/react';
import {buildTimelineItems} from './chat_workspace_timeline';
import type {SpecStage} from '../hooks/chat_session_types';
import {
  baseArgs,
  renderItems,
  transcriptArgs,
} from './chat_workspace_timeline_test_support';
import {makeSpec} from '@/test_fixtures';

// The plan card's completion-email opt-in is gated on the server actually
// having an SMTP transport; these tests are about the turn's shape, not the
// probe.
vi.mock('../hooks/system_status_context', () => ({
  useSystemStatus: () => ({
    status: {email_notifications_available: true},
    unreachable: false,
  }),
}));

// The parts of one assistant turn, in the order the DOM holds them. A turn
// is reasoning, then prose, then its inline attachment, then its actions --
// and that order is what must not change as the turn settles or the run
// starts (the disclosure used to be a timeline item of its own, so it moved
// from above the plan to below it the moment the draft became confirmed).
const PART_SELECTORS = [
  ['reasoning', '.ucs-thoughts'],
  ['prose', '.reference-model-bubble-text'],
  ['attachment', '.reference-message-attachment'],
  ['actions', '.reference-message-actions'],
] as const;

function turnParts(container: HTMLElement): string[] {
  const row = container.querySelector('.reference-bubble-row:not(.user)');
  if (!row) return [];
  const found = PART_SELECTORS.flatMap(([name, selector]) =>
    [...row.querySelectorAll(selector)].map(node => ({name, node})),
  );
  return found
    .sort((a, b) =>
      a.node.compareDocumentPosition(b.node) & Node.DOCUMENT_POSITION_FOLLOWING
        ? -1
        : 1,
    )
    .map(entry => entry.name);
}

const CLOSING_TURN = 'The scope is settled. Start whenever you are ready.';

const planStage: SpecStage = {
  spec: makeSpec({goal: 'Reverse liver fibrosis'}),
  createdAt: 5,
  intro: CLOSING_TURN,
  reasoning: 'Every field is filled, so complete the interview.',
  turnId: 4,
};

it('renders a plan turn as reasoning, prose, attachment, actions', () => {
  const items = buildTimelineItems(baseArgs({draft: planStage}));
  // One entry: the disclosure is part of the message, not a timeline item of
  // its own with the column's gap around it.
  expect(items).toHaveLength(1);

  const {container} = renderItems(items);
  expect(turnParts(container)).toEqual([
    'reasoning',
    'prose',
    'attachment',
    'actions',
  ]);
});

it('keeps the plan turn intact once the run has started', () => {
  // Clicking Start research swaps the draft stage for the confirmed one. The
  // turn behind it is the same turn, so it must keep the same parts in the
  // same order and the same words -- the closing message used to be dropped
  // here, replaced by generic copy, and its thinking jumped below the plan.
  const {container} = renderItems(
    buildTimelineItems(baseArgs({confirmed: planStage})),
  );

  expect(turnParts(container)).toEqual([
    'reasoning',
    'prose',
    'attachment',
    'actions',
  ]);
  expect(screen.getByText(CLOSING_TURN)).toBeVisible();
  expect(
    screen.getByText('Every field is filled, so complete the interview.'),
  ).toBeInTheDocument();
});

it('streams a turn in progress into one message, not three items', () => {
  // While the Agent writes, its thinking and its reply are parts of the same
  // message -- not separate timeline entries with the column's own gap
  // between them, which is what made the spacing above the reply collapse
  // the moment the turn resolved.
  const items = buildTimelineItems(
    baseArgs({
      isAwaitingAgent: true,
      agentReasoning: 'Ask about the model system.',
      agentDraft: 'Which model system should this be built around?',
    }),
  );
  expect(items).toHaveLength(1);

  const {container} = renderItems(items);
  expect(turnParts(container)).toEqual(['reasoning', 'prose']);

  const settled = renderItems(
    buildTimelineItems(transcriptArgs()),
  ).container.querySelector('.reference-bubble-row:not(.user)');
  expect(container.querySelector('.reference-bubble-row')?.className).toBe(
    settled?.className,
  );
});

it('keeps a reply-in-progress out of the accessibility tree', () => {
  // A partial sentence per token is not what a screen reader should read;
  // the durable turn that replaces this message moments later is. The
  // disclosure above it stays exposed -- it is the same control the settled
  // turn keeps.
  const {container} = renderItems(
    buildTimelineItems(
      baseArgs({
        isAwaitingAgent: true,
        agentReasoning: 'Ask about the model system.',
        agentDraft: 'Which model system?',
      }),
    ),
  );

  expect(
    container.querySelector('.reference-model-bubble[aria-hidden="true"]'),
  ).not.toBeNull();
  expect(screen.getByText('Thinking').closest('[aria-hidden]')).toBeNull();
});
