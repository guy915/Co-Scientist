import type {ReactElement} from 'react';
import {fireEvent, screen, render} from '@testing-library/react';
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

  it('renders nothing once the turn resolves', () => {
    renderItems(
      buildTimelineItems(
        baseArgs({isAwaitingAgent: false, agentReasoning: 'stale thought'}),
      ),
    );

    expect(screen.queryByText('Thinking')).toBeNull();
    expect(screen.queryByText('stale thought')).toBeNull();
  });

  it('shows the model reasoning a live post-run Q&A turn has streamed so far', () => {
    renderItems(
      buildTimelineItems(
        baseArgs({
          startedSession: {id: 'run-9', title: 'A run', at: 100},
          isAwaitingAgent: true,
          agentReasoning: 'Checking the tournament record first.',
          agentDraft: '',
        }),
      ),
    );

    expect(screen.getByText('Thinking')).toBeInTheDocument();
    expect(
      screen.getByText('Checking the tournament record first.'),
    ).toBeInTheDocument();
  });

  it('wires each bubble to its own edit/copy/retry handlers', () => {
    const args = transcriptArgs();
    renderItems(buildTimelineItems(args));

    fireEvent.click(screen.getByLabelText('Edit prompt'));
    const editor = screen.getByLabelText('Edit prompt');
    fireEvent.change(editor, {target: {value: 'A better question'}});
    fireEvent.click(screen.getByLabelText('Send edited prompt'));
    expect(args.handleEditMessage).toHaveBeenCalledWith(
      expect.objectContaining({id: 'u1'}),
      'A better question',
    );

    fireEvent.click(screen.getByLabelText('Copy prompt'));
    expect(args.handleCopyRequest).toHaveBeenCalledWith(
      expect.objectContaining({id: 'u1'}),
    );

    fireEvent.click(screen.getByLabelText('Retry response'));
    expect(args.handleRetryMessage).toHaveBeenCalledWith(
      expect.objectContaining({id: 'a1'}),
    );
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

  it('persists completion-notification opt-in and address in the draft', () => {
    const spec = makeSpec();
    const draft: SpecStage = {spec, createdAt: 5};
    const args = baseArgs({draft});
    renderItems(buildTimelineItems(args));

    fireEvent.change(
      screen.getByLabelText('Email me when the Goal Report is ready'),
      {target: {value: 'scientist@example.com'}},
    );
    const enableUpdater = vi.mocked(args.setDraft).mock.calls[0][0] as (
      current: SpecStage | null,
    ) => SpecStage | null;
    expect(enableUpdater(draft)?.spec.notifyOnCompletion).toBe(true);
    expect(enableUpdater(draft)?.spec.completionEmail).toBe(
      'scientist@example.com',
    );
  });

  it('wires composer and spec actions to the session handlers', async () => {
    const spec = makeSpec();
    const draft: SpecStage = {spec, createdAt: 5};
    const args = baseArgs({draft});
    const items = buildTimelineItems(args);
    expect(items).toHaveLength(1);
    renderItems(items);

    fireEvent.click(screen.getByLabelText(/Prefer novelty/i));
    const focusUpdater = vi.mocked(args.setDraft).mock
      .calls[0][0] as unknown as (
      current: SpecStage | null,
    ) => SpecStage | null;
    expect(focusUpdater(draft)).toEqual({
      ...draft,
      spec: {...spec, focus: 'prefer_novelty'},
    });

    fireEvent.click(screen.getByLabelText(/Ultra/i));
    const tierUpdater = vi.mocked(args.setDraft).mock
      .calls[1][0] as unknown as (
      current: SpecStage | null,
    ) => SpecStage | null;
    expect(tierUpdater(draft)).toEqual({
      ...draft,
      spec: {...spec, tier: 'ultra'},
    });

    fireEvent.click(screen.getByLabelText('Retry response'));
    expect(args.handleRetryDraftSpec).toHaveBeenCalledOnce();

    fireEvent.click(screen.getByText('Cancel'));
    expect(args.handleCancelDraftSpec).toHaveBeenCalledOnce();

    fireEvent.click(screen.getByText('Start research'));
    expect(args.handleStartRun).toHaveBeenCalledOnce();
  });

  it('renders nothing when there is no staged draft', () => {
    const items = buildTimelineItems(baseArgs({draft: null}));
    expect(items).toHaveLength(0);
  });

  it('renders read-only with retry and inert no-ops', () => {
    const spec = makeSpec({goal: 'Confirmed goal'});
    const args = baseArgs({confirmed: {spec, createdAt: 9}});
    const items = buildTimelineItems(args);
    expect(items).toHaveLength(1);
    renderItems(items);

    expect(screen.queryByText('Cancel')).not.toBeInTheDocument();
    expect(screen.getByText('Start research')).toBeDisabled();

    expect(screen.queryByLabelText('Edit plan')).not.toBeInTheDocument();

    fireEvent.click(screen.getByLabelText('Retry response'));
    expect(args.stageDraftSpec).toHaveBeenCalledWith(spec);

    const cardElement = items[0].node as ReactElement<{
      onTierChange: (tier: string) => void;
      onCancel: () => void;
      onStart: () => void;
    }>;
    expect(() => cardElement.props.onTierChange('standard')).not.toThrow();
    expect(() => cardElement.props.onCancel()).not.toThrow();
    expect(() => cardElement.props.onStart()).not.toThrow();
  });

  it('offers an explicit continue action for a linked draft', () => {
    const args = baseArgs({
      confirmed: {spec: makeSpec(), createdAt: 9},
      linkedDraftRecovery: {
        canContinueLinkedDraft: true,
        spec: makeSpec(),
        status: undefined,
        retryStatusLookup: vi.fn(),
      },
    });
    renderItems(buildTimelineItems(args));

    const button = screen.getByRole('button', {name: 'Continue research'});
    expect(button).toBeEnabled();
    expect(screen.queryByLabelText('Retry response')).not.toBeInTheDocument();
    fireEvent.click(button);
    expect(args.handleStartRun).toHaveBeenCalledOnce();
  });

  it('announces linked-draft recovery while the start request is loading', () => {
    renderItems(
      buildTimelineItems(
        baseArgs({
          confirmed: {spec: makeSpec(), createdAt: 9},
          linkedDraftRecovery: {
            canContinueLinkedDraft: true,
            spec: makeSpec(),
            status: undefined,
            retryStatusLookup: vi.fn(),
          },
          isStarting: true,
        }),
      ),
    );

    const button = screen.getByRole('button', {name: 'Continuing...'});
    expect(button).toBeDisabled();
    expect(button).toHaveAttribute('aria-busy', 'true');
    expect(screen.getByRole('status')).toHaveTextContent('Continuing research');
  });

  it('keeps a linked run locked and offers a status retry on lookup failure', () => {
    const retryStatusLookup = vi.fn();
    renderItems(
      buildTimelineItems(
        baseArgs({
          confirmed: {spec: makeSpec(), createdAt: 9},
          linkedDraftRecovery: {
            canContinueLinkedDraft: false,
            status: 'error',
            retryStatusLookup,
          },
        }),
      ),
    );

    expect(screen.getByRole('alert')).toHaveTextContent(
      'Could not verify the saved run status.',
    );
    expect(screen.getByRole('button', {name: 'Start research'})).toBeDisabled();
    expect(
      screen.queryByRole('button', {name: 'Continue research'}),
    ).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', {name: 'Retry status check'}));
    expect(retryStatusLookup).toHaveBeenCalledOnce();
  });

  it('announces a linked run status lookup while keeping Start disabled', () => {
    renderItems(
      buildTimelineItems(
        baseArgs({
          confirmed: {spec: makeSpec(), createdAt: 9},
          linkedDraftRecovery: {
            canContinueLinkedDraft: false,
            status: 'checking',
            retryStatusLookup: vi.fn(),
          },
        }),
      ),
    );

    expect(screen.getByRole('status')).toHaveTextContent(
      'Checking saved research session status…',
    );
    expect(screen.getByRole('button', {name: 'Start research'})).toBeDisabled();
  });

  it('renders nothing when there is no confirmed spec', () => {
    const items = buildTimelineItems(baseArgs({confirmed: null}));
    expect(items).toHaveLength(0);
  });

  const startedSession: StartedSession = {
    id: 'run-9',
    title: 'Investigate glucose homeostasis',
    at: 100,
  };

  it('links to the run and leaves the chat on a new topic', () => {
    const args = baseArgs({startedSession});
    const items = buildTimelineItems(args);
    expect(items).toHaveLength(1);
    renderItems(items);

    for (const name of [/Open$/, /View session details/]) {
      expect(screen.getByRole('link', {name})).toHaveAttribute(
        'href',
        '/runs/run-9/details',
      );
    }

    expect(screen.queryByLabelText('Retry response')).toBeNull();

    fireEvent.click(
      screen.getByText('Start a new research goal session on a new topic'),
    );
    expect(args.resetWorkspace).toHaveBeenCalledOnce();
    // Leaving the chat route prevents rehydration from reattaching the session
    // after reset.
    expect(args.navigate).toHaveBeenCalledWith('/');
    expect(args.focusComposer).toHaveBeenCalledOnce();
  });

  it('renders nothing when there is no started session', () => {
    const items = buildTimelineItems(baseArgs({startedSession: null}));
    expect(items).toHaveLength(0);
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

  it('re-signs the session card as its announcement is written', () => {
    // Growing start cards keep their id/time; revision signals their geometry
    // changed.
    const signature = (intro: string) =>
      buildTimelineItems(
        baseArgs({
          startedSession: announcingSession({intro, announcing: true}),
        }),
      ).find(item => item.id === 'started-session-run-1')?.revision;

    expect(signature('Cold-stress')).not.toEqual(signature('Cold-stress work'));
  });

  it('falls back to the standby copy for a card with no reply', () => {
    renderItems(
      buildTimelineItems(baseArgs({startedSession: announcingSession()})),
    );

    expect(screen.getByText(/Co-Scientist has started research/)).toBeVisible();
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
  it('wraps the plan and started-session turns in the same row a plain reply uses', () => {
    const replyRow = renderItems(
      buildTimelineItems(transcriptArgs()),
    ).container.querySelector('.reference-bubble-row:not(.user)');
    expect(replyRow).not.toBeNull();

    const draftRow = renderItems(
      buildTimelineItems(baseArgs({draft: {spec: makeSpec(), createdAt: 5}})),
    ).container.querySelector('.reference-bubble-row');
    expect(draftRow?.className).toBe(replyRow?.className);

    const startedRow = renderItems(
      buildTimelineItems(baseArgs({startedSession})),
    ).container.querySelector('.reference-bubble-row');
    expect(startedRow?.className).toBe(replyRow?.className);
  });
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
