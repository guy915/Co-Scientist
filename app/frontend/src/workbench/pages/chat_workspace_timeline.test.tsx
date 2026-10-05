import type {ReactElement} from 'react';
import {screen, render} from '@testing-library/react';
import {expect, it, vi, describe} from 'vitest';
import {
  buildTimelineItems,
  type BuildTimelineItemsArgs,
} from './chat_workspace_timeline';
import type {StartedSession} from './chat_timeline_run_spec_card';
import type {SpecStage} from '../hooks/use_chat_session';
import {makeMessage, makeSpec} from '@/test_fixtures';
import {MemoryRouter, type NavigateFunction} from 'react-router-dom';

vi.mock('../hooks/system_status_context', () => ({
  useSystemStatus: () => ({
    status: {email_notifications_available: true},
    unreachable: false,
  }),
}));

describe('chat workspace timeline', () => {
  it('shows the model reasoning it has streamed so far', () => {
    renderItems(
      buildTimelineItems(
        baseArgs({
          isAwaitingAgent: true,
          agentReasoning: 'The scientist named no mechanism, so ask for one.',
        }),
      ),
    );

    expect(screen.getByText('Thinking')).toBeInTheDocument();
    expect(
      screen.getByText('The scientist named no mechanism, so ask for one.'),
    ).toBeInTheDocument();
  });

  it('shows only the label until the first reasoning arrives', () => {
    const {container} = renderItems(
      buildTimelineItems(baseArgs({isAwaitingAgent: true, agentReasoning: ''})),
    );

    expect(screen.getByText('Thinking')).toBeInTheDocument();
    expect(container.querySelector('.reference-thoughts-trail')).toBeNull();
  });

  it('keeps the streamed reasoning out of the announced live region', () => {
    renderItems(
      buildTimelineItems(
        baseArgs({
          isAwaitingAgent: true,
          agentReasoning: 'The scientist named no mechanism, so ask for one.',
        }),
      ),
    );

    const label = screen.getByText('Thinking');
    expect(label.closest('[role="status"], [aria-live]')).not.toBeNull();

    const trail = screen.getByText(
      'The scientist named no mechanism, so ask for one.',
    );
    // Announcing reasoning would reread it on every token.
    expect(trail.closest('[role="status"], [aria-live]')).toBeNull();
  });

  it('enables durable Q&A revisions after start and disables consumed setup', () => {
    const args = baseArgs({
      startedSession: {id: 'run-1', title: 'Research', at: 3},
      messages: [
        makeMessage({id: 'setup', turnId: 1}),
        makeMessage({id: 'qa-user', messageId: 4}),
        makeMessage({id: 'qa-answer', role: 'assistant', messageId: 5}),
      ],
    });
    renderItems(buildTimelineItems(args));
    expect(screen.getAllByRole('button', {name: 'Edit prompt'})).toHaveLength(
      1,
    );
    expect(
      screen.getAllByRole('button', {name: 'Retry response'}),
    ).toHaveLength(1);
  });

  it('offers no revision while a turn is in flight', () => {
    renderItems(buildTimelineItems(transcriptArgs({isAwaitingAgent: true})));

    expect(screen.queryByLabelText('Edit prompt')).toBeNull();
    expect(screen.queryByLabelText('Retry response')).toBeNull();
    expect(screen.getByLabelText('Copy prompt')).toBeInTheDocument();
  });

  it('offers no revision for a bubble with no durable turn', () => {
    renderItems(
      buildTimelineItems(
        baseArgs({messages: [makeMessage({id: 'u1', role: 'user'})]}),
      ),
    );

    expect(screen.queryByLabelText('Edit prompt')).toBeNull();
  });

  it('sorts chronologically, breaking ties on the `order` field', () => {
    const args = baseArgs({
      messages: [makeMessage({id: 'u1', created_at: 5})],
      draft: {spec: makeSpec(), createdAt: 5},
    });
    const items = buildTimelineItems(args);
    expect(items.map(item => item.id)).toEqual([
      'local-message-u1',
      'draft-spec',
    ]);
  });

  function announcingSession(
    overrides: Partial<StartedSession> = {},
  ): StartedSession {
    return {
      id: 'run-1',
      title: 'Cold-stress glucose homeostasis',
      at: 60,
      ...overrides,
    };
  }

  it('shows the start announcement as the session card lead-in', () => {
    renderItems(
      buildTimelineItems(
        baseArgs({
          startedSession: announcingSession({
            intro: 'Cold-stress work is under way.',
            reasoning: 'The run exists, so this confirms it.',
          }),
        }),
      ),
    );

    expect(screen.getByText('Cold-stress work is under way.')).toBeVisible();
    expect(screen.getByText('Thinking')).toBeVisible();
  });

  it('renders the plan card lead-in as markdown, like an ordinary reply', async () => {
    const draft: SpecStage = {
      spec: makeSpec(),
      createdAt: 5,
      intro: 'Use **primary** cells for this line of work.',
    };
    renderItems(buildTimelineItems(baseArgs({draft})));

    expect((await screen.findByText('primary')).tagName).toBe('STRONG');
  });

  // jsdom cannot measure spacing; matching the ordinary assistant wrapper
  // guards its structure.
});

describe('chat workspace timeline turn shape', () => {
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
        a.node.compareDocumentPosition(b.node) &
        Node.DOCUMENT_POSITION_FOLLOWING
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
    // Screen readers should receive durable turns rather than partial sentences
    // per token.
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
});

export function baseArgs(
  overrides: Partial<BuildTimelineItemsArgs> = {},
): BuildTimelineItemsArgs {
  return {
    messages: [],
    handleEditMessage: vi.fn(),
    handleCopyRequest: vi.fn().mockResolvedValue(undefined),
    handleRetryMessage: vi.fn(),
    draft: null,
    setDraft: vi.fn(),
    isStarting: false,
    isAwaitingAgent: false,
    agentReasoning: '',
    agentDraft: '',
    handleCancelDraftSpec: vi.fn(),
    handleRetryDraftSpec: vi.fn(),
    handleStartRun: vi.fn().mockResolvedValue(undefined),
    confirmed: null,
    linkedDraftRecovery: {
      canContinueLinkedDraft: false,
      status: undefined,
      retryStatusLookup: () => undefined,
    },
    stageDraftSpec: vi.fn(),
    startedSession: null,
    navigate: vi.fn() as unknown as NavigateFunction,
    resetWorkspace: vi.fn(),
    focusComposer: vi.fn(),
    ...overrides,
  };
}

export function renderItems(
  items: {id: string; node: ReactElement | unknown}[],
) {
  return render(
    <MemoryRouter>
      {items.map(item => (
        <div key={item.id}>{item.node as ReactElement}</div>
      ))}
    </MemoryRouter>,
  );
}

export function transcriptArgs(
  overrides: Partial<BuildTimelineItemsArgs> = {},
) {
  return baseArgs({
    messages: [
      makeMessage({id: 'u1', role: 'user', content: 'A question', turnId: 1}),
      makeMessage({
        id: 'a1',
        role: 'assistant',
        content: 'An answer',
        turnId: 2,
      }),
    ],
    ...overrides,
  });
}
