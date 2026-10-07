import type {ReactElement} from 'react';
import {fireEvent, screen, render} from '@testing-library/react';
import {expect, it, vi, describe} from 'vitest';
import {
  buildTimelineItems,
  type BuildTimelineItemsArgs,
} from './chat_workspace_timeline';
import {makeMessage, makeSpec} from '@/test_fixtures';
import {MemoryRouter, type NavigateFunction} from 'react-router-dom';

vi.mock('@/shared/hooks/system_status_context', () => ({
  useSystemStatus: () => ({
    status: {email_notifications_available: true},
    unreachable: false,
  }),
}));

describe('chat workspace timeline', () => {
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

  it('renders a confirmed plan read-only, retryable, with inert actions', () => {
    const spec = makeSpec({goal: 'Confirmed goal'});
    const args = baseArgs({confirmed: {spec, createdAt: 9}});
    const items = buildTimelineItems(args);
    renderItems(items);

    expect(screen.queryByText('Cancel')).not.toBeInTheDocument();
    expect(screen.queryByLabelText('Edit plan')).not.toBeInTheDocument();
    expect(screen.getByText('Start research')).toBeDisabled();

    fireEvent.click(screen.getByLabelText('Retry response'));
    expect(args.stageDraftSpec).toHaveBeenCalledWith(spec);

    const card = items[0].node as ReactElement<Record<string, () => void>>;
    for (const inert of [
      'onFocusChange',
      'onTierChange',
      'onNotificationChange',
      'onFieldsChange',
      'onCancel',
      'onStart',
    ]) {
      expect(() => card.props[inert]()).not.toThrow();
    }
  });

  it('places the started card right after the start request despite clock skew', () => {
    const items = buildTimelineItems(
      baseArgs({
        // The client clock runs 30 s behind the server rows.
        startedSession: {id: 'run-1', title: 'Research', at: 70},
        messages: [
          makeMessage({id: 'setup', turnId: 1, created_at: 50}),
          makeMessage({id: 'start', startRequest: true, created_at: 100}),
          makeMessage({id: 'qa', messageId: 4, created_at: 101}),
        ],
      }),
    );
    expect(items.map(item => item.id)).toEqual([
      'local-message-setup',
      'local-message-start',
      'started-session-run-1',
      'local-message-qa',
    ]);
  });

  it('keeps bubbles in transcript order when clocks disagree', () => {
    const items = buildTimelineItems(
      baseArgs({
        isAwaitingAgent: true,
        messages: [
          makeMessage({id: 'server', created_at: 200}),
          makeMessage({id: 'client', created_at: 150}),
        ],
      }),
    );
    expect(items.map(item => item.id)).toEqual([
      'local-message-server',
      'local-message-client',
      'agent-turn-in-flight',
    ]);
  });

  // jsdom cannot measure spacing; matching the ordinary assistant wrapper
  // guards its structure.
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
