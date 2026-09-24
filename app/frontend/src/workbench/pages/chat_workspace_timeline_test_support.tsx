import type {ReactElement} from 'react';
import {render} from '@testing-library/react';
import {MemoryRouter, type NavigateFunction} from 'react-router-dom';
import {vi} from 'vitest';
import {type BuildTimelineItemsArgs} from './chat_workspace_timeline';
import {makeMessage} from '@/test_fixtures';

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
