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
  // The plan card's completion-email opt-in is gated on the server actually
  // having an SMTP transport; these tests are about the card, not the probe.

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
    // No empty reasoning trail before the model has produced any.
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
    // Announcing this too would re-read the whole raw chain of thought to a
    // screen reader on every streamed token -- it must stay visible without
    // being wired into any live region.
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

  // The owner's own complaint: after a run starts, the post-run Q&A chat must
  // show its live thinking exactly as the pre-run interview turn does above.
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

    // Editing happens inside the message: the bubble becomes an editor, and
    // sending from it revises that turn rather than starting another one.
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
    // Copy is unaffected: it needs nothing from the server.
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

    // Locked: no Cancel affordance, Start disabled.
    expect(screen.queryByText('Cancel')).not.toBeInTheDocument();
    expect(screen.getByText('Start research')).toBeDisabled();

    // Locked: no way into the field editor either -- the plan is the one the
    // run already started against.
    expect(screen.queryByLabelText('Edit plan')).not.toBeInTheDocument();

    fireEvent.click(screen.getByLabelText('Retry response'));
    expect(args.stageDraftSpec).toHaveBeenCalledWith(spec);

    // The locked card's tier/cancel handlers are inert no-ops that
    // can't be reached through disabled UI controls; invoke them directly
    // via the rendered element's props to cover their bodies.
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

    // Both open affordances are links to the run, not click handlers, so a
    // middle- or cmd-click opens the session in a new browser tab.
    for (const name of [/Open$/, /View session details/]) {
      expect(screen.getByRole('link', {name})).toHaveAttribute(
        'href',
        '/runs/run-9/details',
      );
    }

    // No retry: the run is already started, so there is no response here to
    // regenerate and the control could only ever appear to do nothing.
    expect(screen.queryByLabelText('Retry response')).toBeNull();

    fireEvent.click(
      screen.getByText('Start a new research goal session on a new topic'),
    );
    expect(args.resetWorkspace).toHaveBeenCalledOnce();
    // Leaving /chats/:id is what makes the reset stick: staying put lets the
    // rehydrator re-attach this chat's run and put the card straight back.
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

  // The started card's own group: the Agent's reply to "Start research" is the
  // card's lead-in and its thinking is disclosed above it, exactly as the
  // completing interview turn's are on the plan card.
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
    // The reply streams into a card whose id and timestamp never change, so
    // `revision` is the only thing that tells the auto-scroll it grew (see
    // chat_workspace.tsx).
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

  // The plan card's lead-in is the Agent's own closing interview message, and
  // must render like any other assistant reply's markdown -- this used to be
  // a plain <p>, so **bold** and similar syntax showed up as literal
  // characters instead of formatting.
  it('renders the plan card lead-in as markdown, like an ordinary reply', async () => {
    const draft: SpecStage = {
      spec: makeSpec(),
      createdAt: 5,
      intro: 'Use **primary** cells for this line of work.',
    };
    renderItems(buildTimelineItems(baseArgs({draft})));

    expect((await screen.findByText('primary')).tagName).toBe('STRONG');
  });

  // The plan and started-session cards should be ordinary assistant messages
  // that happen to carry an inline attachment -- not bespoke cards with their
  // own row/gap spacing. Both must share the exact wrapper class string a
  // plain assistant reply renders (CHAT_BUBBLE_ROW_CLASSES via
  // AssistantMessage), so a "space feels different" regression shows up here
  // as a class mismatch rather than only in a screenshot.
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
  // The plan card's completion-email opt-in is gated on the server actually
  // having an SMTP transport; these tests are about the turn's shape, not the
  // probe.

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
});

// Shared scaffolding for the timeline's own tests: a full argument bag with
// every collaborator stubbed, and a renderer that mounts every item's node so
// RTL queries see the whole timeline at once.

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

// The started-session card links to the run, so a router has to be in scope.
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
