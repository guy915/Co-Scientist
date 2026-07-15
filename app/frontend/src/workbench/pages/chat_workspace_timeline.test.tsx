import type {ReactElement} from 'react';
import {fireEvent, render, screen} from '@testing-library/react';
import type {NavigateFunction} from 'react-router-dom';
import {describe, expect, it, vi} from 'vitest';
import {
  buildTimelineItems,
  type BuildTimelineItemsArgs,
} from './chat_workspace_timeline';
import type {ChatEntry, StartedSession} from './chat_timeline_cards';
import type {InferredRunSpec} from '../run_spec';
import type {SpecStage} from '../hooks/chat_session_types';

function makeSpec(overrides: Partial<InferredRunSpec> = {}): InferredRunSpec {
  return {
    goal: 'Study liver fibrosis',
    requirements: ['Req A'],
    attributes: ['Attr A'],
    criteria: ['Crit A'],
    focus: 'balance',
    tier: 'standard',
    ...overrides,
  };
}

function makeMessage(overrides: Partial<ChatEntry> = {}): ChatEntry {
  return {
    id: 'm1',
    role: 'user',
    content: 'Hello',
    created_at: 1,
    ...overrides,
  };
}

function baseArgs(
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
    handleCancelDraftSpec: vi.fn(),
    handleEditPlan: vi.fn(),
    handleRetryDraftSpec: vi.fn(),
    handleStartRun: vi.fn().mockResolvedValue(undefined),
    confirmed: null,
    stageDraftSpec: vi.fn(),
    startedSession: null,
    setStartedSession: vi.fn(),
    navigate: vi.fn() as unknown as NavigateFunction,
    resetWorkspace: vi.fn(),
    focusComposer: vi.fn(),
    ...overrides,
  };
}

// Renders every item's node so RTL queries see the whole timeline at once.
function renderItems(items: {id: string; node: ReactElement | unknown}[]) {
  return render(
    <>
      {items.map(item => (
        <div key={item.id}>{item.node as ReactElement}</div>
      ))}
    </>,
  );
}

describe('messageTimelineItems', () => {
  it('wires each bubble to the edit/copy/retry handlers for its own message', () => {
    const args = baseArgs({
      messages: [
        makeMessage({id: 'u1', role: 'user', content: 'A question'}),
        makeMessage({id: 'a1', role: 'assistant', content: 'An answer'}),
      ],
    });
    const items = buildTimelineItems(args);
    renderItems(items);

    fireEvent.click(screen.getByLabelText('Edit prompt'));
    expect(args.handleEditMessage).toHaveBeenCalledWith(
      expect.objectContaining({id: 'u1'}),
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
});

describe('draftTimelineItems', () => {
  it('persists completion-notification opt-in and address in the draft', () => {
    const spec = makeSpec();
    const draft: SpecStage = {spec, createdAt: 5};
    const args = baseArgs({draft});
    renderItems(buildTimelineItems(args));

    fireEvent.click(
      screen.getByLabelText('Email me when the Goal Report is ready'),
    );
    const enableUpdater = vi.mocked(args.setDraft).mock.calls[0][0] as (
      current: SpecStage | null,
    ) => SpecStage | null;
    expect(enableUpdater(draft)?.spec.notifyOnCompletion).toBe(true);
  });

  it('wires the focus/tier/edit/retry/cancel/start actions to the session handlers', async () => {
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

    fireEvent.click(screen.getByLabelText('Edit research plan'));
    expect(args.handleEditPlan).toHaveBeenCalledWith(spec);

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
});

describe('confirmedSpecTimelineItems', () => {
  it('renders read-only with edit/retry and inert tier/cancel/start no-ops', () => {
    const spec = makeSpec({goal: 'Confirmed goal'});
    const args = baseArgs({confirmed: {spec, createdAt: 9}});
    const items = buildTimelineItems(args);
    expect(items).toHaveLength(1);
    renderItems(items);

    // Locked: no Cancel affordance, Start disabled.
    expect(screen.queryByText('Cancel')).not.toBeInTheDocument();
    expect(screen.getByText('Start research')).toBeDisabled();

    fireEvent.click(screen.getByLabelText('Edit research plan'));
    expect(args.handleEditPlan).toHaveBeenCalledWith(spec);

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

  it('renders nothing when there is no confirmed spec', () => {
    const items = buildTimelineItems(baseArgs({confirmed: null}));
    expect(items).toHaveLength(0);
  });
});

describe('startedTimelineItems', () => {
  const startedSession: StartedSession = {
    id: 'run-9',
    title: 'Investigate glucose homeostasis',
    at: 100,
  };

  it('wires open/retry/new-topic to navigate/setStartedSession/resetWorkspace', () => {
    const args = baseArgs({startedSession});
    const items = buildTimelineItems(args);
    expect(items).toHaveLength(1);
    renderItems(items);

    fireEvent.click(screen.getByText('View session details'));
    expect(args.navigate).toHaveBeenCalledWith('/runs/run-9/details');

    fireEvent.click(screen.getByLabelText('Retry response'));
    expect(args.setStartedSession).toHaveBeenCalled();
    const updater = vi.mocked(args.setStartedSession).mock
      .calls[0][0] as unknown as (
      current: StartedSession | null,
    ) => StartedSession | null;
    const updated = updater(startedSession);
    expect(updated).toMatchObject({id: 'run-9', title: startedSession.title});
    expect(updated?.at).not.toBe(startedSession.at);
    expect(updater(null)).toBeNull();

    fireEvent.click(
      screen.getByText('Start a new research goal session on a new topic'),
    );
    expect(args.resetWorkspace).toHaveBeenCalledOnce();
    expect(args.focusComposer).toHaveBeenCalledOnce();
  });

  it('renders nothing when there is no started session', () => {
    const items = buildTimelineItems(baseArgs({startedSession: null}));
    expect(items).toHaveLength(0);
  });
});

describe('buildTimelineItems ordering', () => {
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
});
