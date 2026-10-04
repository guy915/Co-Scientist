import {act, fireEvent, screen, waitFor} from '@testing-library/react';
import {beforeEach, expect, it, vi} from 'vitest';
import {
  ANNOUNCEMENT_TEXT,
  apiMock,
  installChatWorkspaceMocks,
  renderWorkspace,
} from './chat_workspace_test_helpers';
import {STARTED_SESSION_STANDBY_COPY} from './chat_timeline_run_spec_card';

beforeEach(() => {
  installChatWorkspaceMocks();
});

const RESEARCH_GOAL = 'Investigate glucose homeostasis under cold stress.';

const RESPONSE_BLOB_URL = 'blob:co-scientist-response';

function submitResearchGoal(goal = RESEARCH_GOAL) {
  const input = screen.getByRole('textbox');
  fireEvent.change(input, {target: {value: goal}});
  fireEvent.submit(input.closest('form')!);
}

// Completion email adds another textbox; identify the composer by its element
// type.
function getComposer(): HTMLElement {
  return screen.getAllByRole('textbox').find(el => el.tagName === 'TEXTAREA')!;
}

function installClipboardAndDownloadSpies() {
  const writeText = vi.fn().mockResolvedValue(undefined);
  Object.defineProperty(navigator, 'clipboard', {
    configurable: true,
    value: {writeText},
  });
  const createObjectURL = vi.fn((blob: Blob) => {
    expect(blob).toBeInstanceOf(Blob);
    return RESPONSE_BLOB_URL;
  });
  const revokeObjectURL = vi.fn();
  Object.defineProperty(URL, 'createObjectURL', {
    configurable: true,
    value: createObjectURL,
  });
  Object.defineProperty(URL, 'revokeObjectURL', {
    configurable: true,
    value: revokeObjectURL,
  });
  const downloadedNames: string[] = [];
  const anchorClick = vi
    .spyOn(HTMLAnchorElement.prototype, 'click')
    .mockImplementation(function (this: HTMLAnchorElement) {
      downloadedNames.push(this.download);
    });
  return {
    writeText,
    createObjectURL,
    revokeObjectURL,
    downloadedNames,
    anchorClick,
  };
}

async function driveToRunSpec() {
  renderWorkspace();
  submitResearchGoal();
  expect(
    await screen.findByText(
      /Review the four fields and select a focus and run type/,
    ),
  ).toBeInTheDocument();
}

async function startRunFromSpec({
  waitForSessionCard = true,
}: {waitForSessionCard?: boolean} = {}) {
  fireEvent.click(screen.getByLabelText(/Ultra/i));
  fireEvent.click(screen.getByText('Start research'));
  await waitFor(() => {
    expect(apiMock.createRun).toHaveBeenCalled();
    const [payload, options] = apiMock.createRun.mock.calls.at(-1)!;
    expect(payload).toStrictEqual({
      research_goal: RESEARCH_GOAL,
      interview_id: 'interview-1',
      requirements: ['Prioritize mechanistic novelty'],
      attributes: ['Cold-stress glucose regulation'],
      criteria: [],
      focus: 'balance',
      tier: 'ultra',
      notify_on_completion: false,
      enable_literature_review: true,
      enable_web_search: true,
      document_ids: [],
    });
    expect(options).toEqual({
      idempotencyKey: expect.stringMatching(/^run-create-/),
    });
    expect(apiMock.startRun).toHaveBeenCalledWith('run-1');
  });
  if (!waitForSessionCard) return;
  expect(await screen.findByText('Research session')).toBeInTheDocument();
}

it('shows request and response controls in the transcript', async () => {
  const spies = installClipboardAndDownloadSpies();

  renderWorkspace();
  submitResearchGoal();

  // Optimistic bubbles are replaced by durable turns; wait before retaining
  // their DOM node.
  expect(
    await screen.findByRole('heading', {name: 'Research plan'}),
  ).toBeInTheDocument();
  expect(screen.getByLabelText('Copy prompt')).toBeInTheDocument();
  expect(screen.getByLabelText('Edit prompt')).toBeInTheDocument();
  expect(screen.getAllByLabelText('Retry response')).not.toHaveLength(0);
  expect(screen.getAllByLabelText('Copy response')).not.toHaveLength(0);
  expect(screen.getAllByLabelText('Download response')).not.toHaveLength(0);

  fireEvent.click(screen.getByLabelText('Edit prompt'));
  expect(screen.getByLabelText('Edit prompt')).toHaveValue(RESEARCH_GOAL);
  fireEvent.click(screen.getByLabelText('Cancel edit'));

  fireEvent.click(screen.getByLabelText('Copy prompt'));
  await waitFor(() => {
    expect(spies.writeText).toHaveBeenCalledWith(RESEARCH_GOAL);
  });
  expect(
    screen.getByRole('heading', {name: 'Research plan'}),
  ).toBeInTheDocument();

  fireEvent.click(screen.getAllByLabelText('Copy response').at(-1)!);
  await waitFor(() => {
    expect(spies.writeText).toHaveBeenCalledWith(
      expect.stringContaining('# Cold-stress glucose homeostasis'),
    );
  });

  fireEvent.click(screen.getAllByLabelText('Download response').at(-1)!);
  expect(spies.createObjectURL).toHaveBeenCalled();
  expect(spies.createObjectURL.mock.calls[0][0].type).toBe(
    'text/markdown;charset=utf-8',
  );
  expect(spies.downloadedNames).toContain('co-scientist-research-plan.md');
  expect(spies.anchorClick).toHaveBeenCalled();
  expect(spies.revokeObjectURL).toHaveBeenCalledWith(RESPONSE_BLOB_URL);
});

it('cancels a draft setup back to the home screen with a toast', async () => {
  renderWorkspace();

  const input = screen.getByRole('textbox');
  fireEvent.change(input, {
    target: {value: 'Investigate glucose homeostasis under cold stress.'},
  });
  fireEvent.submit(input.closest('form')!);

  expect(
    await screen.findByRole('heading', {name: 'Research plan'}),
  ).toBeInTheDocument();

  fireEvent.click(screen.getByText('Cancel'));

  expect(
    screen.getByRole('heading', {
      name: 'What breakthrough should we make today?',
    }),
  ).toBeInTheDocument();
  expect(screen.getByText('The session was canceled')).toBeInTheDocument();
  expect(screen.queryByRole('heading', {name: 'Research plan'})).toBeNull();
});

it('infers a run spec in chat from the research goal', async () => {
  await driveToRunSpec();

  expect(screen.queryByText('AI Co-Scientist')).toBeNull();
  expect(
    screen.getByRole('heading', {name: 'Research plan'}),
  ).toBeInTheDocument();
  expect(
    screen.getByText("Here's my plan to tackle the topic:"),
  ).toBeInTheDocument();
  expect(
    screen
      .getByRole('heading', {
        name: 'Cold-stress glucose homeostasis',
      })
      .closest('.reference-setup-document'),
  ).not.toBeNull();
  expect(screen.getByText('Cancel')).toBeInTheDocument();
  expect(screen.getByRole('group', {name: 'Focus'})).toBeInTheDocument();
  expect(screen.getByRole('group', {name: 'Run type'})).toBeInTheDocument();
  expect(screen.getByLabelText(/Express/i)).toBeChecked();
  expect(screen.getByLabelText(/Standard/i)).toBeDisabled();
});

it('starts the durable run on confirmation', async () => {
  await driveToRunSpec();
  await startRunFromSpec();

  expect(screen.getByTestId('location')).toHaveTextContent('/');
  expect(await screen.findByText(ANNOUNCEMENT_TEXT)).toBeInTheDocument();
  expect(apiMock.announceRunStart).toHaveBeenCalledWith(
    'run-1',
    'Start research',
    expect.anything(),
    expect.anything(),
  );
  expect(screen.getAllByText('Start research').length).toBeGreaterThan(1);
  expect(
    screen.getByRole('heading', {name: 'Research plan'}),
  ).toBeInTheDocument();
  expect(
    screen.getByRole('heading', {
      name: 'Cold-stress glucose homeostasis',
    }),
  ).toBeInTheDocument();
  expect(screen.getByRole('button', {name: 'Start research'})).toBeDisabled();
  expect(screen.getByText('Research session')).toBeInTheDocument();
  expect(screen.getByRole('link', {name: /Open/i})).toBeInTheDocument();
  expect(
    screen.getByRole('link', {name: 'View session details'}),
  ).toBeInTheDocument();
  expect(
    screen.getByRole('button', {
      name: 'Start a new research goal session on a new topic',
    }),
  ).toBeInTheDocument();
  expect(screen.queryByText('Report ready')).not.toBeInTheDocument();
  expect(
    screen.queryByText('Mitochondrial feedback hypothesis'),
  ).not.toBeInTheDocument();
});

it('does not repeat the start exchange the live tab already shows', async () => {
  // Fetching newly linked persisted exchanges must not duplicate their live
  // copies.
  apiMock.listInterviews.mockResolvedValue([
    {
      id: 'interview-1',
      title: 'Cold-stress glucose homeostasis',
      challenge: 'Investigate glucose homeostasis.',
      status: 'completed',
      run_id: 'run-1',
      created_at: 1,
      updated_at: 3,
    },
  ]);
  apiMock.getRunMessages.mockResolvedValue([
    {
      id: 8,
      run_id: 'run-1',
      sender: 'user',
      content: 'Start research',
      kind: 'start',
      created_at: 8,
      applied: false,
      meta: null,
    },
    {
      id: 9,
      run_id: 'run-1',
      sender: 'system',
      content: ANNOUNCEMENT_TEXT,
      kind: 'start',
      created_at: 9,
      applied: false,
      meta: null,
    },
  ]);

  await driveToRunSpec();
  await startRunFromSpec();

  expect(await screen.findByText(ANNOUNCEMENT_TEXT)).toBeInTheDocument();
  await waitFor(() => {
    expect(
      screen
        .getAllByText('Start research')
        .filter(node => node.closest('button') === null),
    ).toHaveLength(1);
  });
  expect(screen.getAllByText(ANNOUNCEMENT_TEXT)).toHaveLength(1);
});

it('withholds the session block until the reply has been written', async () => {
  let finishAnnouncement: (() => void) | undefined;
  apiMock.announceRunStart.mockImplementation(
    async (
      _runId: string,
      _prompt: string,
      sinks: {onChunk?: (fragment: string) => void} = {},
    ) =>
      new Promise<{fallback: boolean}>(resolve => {
        finishAnnouncement = () => {
          sinks.onChunk?.(ANNOUNCEMENT_TEXT);
          resolve({fallback: false});
        };
      }),
  );

  await driveToRunSpec();
  await startRunFromSpec({waitForSessionCard: false});
  await waitFor(() => {
    expect(apiMock.announceRunStart).toHaveBeenCalled();
  });

  expect(screen.queryByText('Research session')).not.toBeInTheDocument();
  expect(
    screen.queryByRole('link', {name: 'View session details'}),
  ).not.toBeInTheDocument();

  await act(async () => {
    finishAnnouncement?.();
  });

  expect(await screen.findByText(ANNOUNCEMENT_TEXT)).toBeInTheDocument();
  expect(screen.getByText('Research session')).toBeInTheDocument();
  expect(
    screen.getByRole('link', {name: 'View session details'}),
  ).toBeInTheDocument();
});

it('falls back to the standby copy when no reply is written', async () => {
  apiMock.announceRunStart.mockRejectedValue(new Error('provider down'));

  await driveToRunSpec();
  await startRunFromSpec();

  expect(
    await screen.findByText(
      /Your session has been started and Co-Scientist has started research/,
    ),
  ).toBeInTheDocument();
  expect(screen.queryByRole('alert')).not.toBeInTheDocument();
  expect(STARTED_SESSION_STANDBY_COPY).toContain('a few minutes');
});

it('drops a half-written reply the scientist stopped', async () => {
  apiMock.announceRunStart.mockImplementation(
    async (
      _runId: string,
      _prompt: string,
      sinks: {onChunk?: (fragment: string) => void} = {},
    ) => {
      sinks.onChunk?.('Your session is un');
      throw new DOMException('aborted', 'AbortError');
    },
  );

  await driveToRunSpec();
  await startRunFromSpec();

  expect(
    await screen.findByText(
      /Your session has been started and Co-Scientist has started research/,
    ),
  ).toBeInTheDocument();
  expect(screen.queryByText(/Your session is un$/)).not.toBeInTheDocument();
});

it('opens the started run detail from the session card', async () => {
  await driveToRunSpec();
  await startRunFromSpec();

  fireEvent.click(screen.getByRole('link', {name: /Open/i}));

  await waitFor(() => {
    expect(screen.getByTestId('location')).toHaveTextContent(
      '/runs/run-1/details',
    );
  });
});

it('keeps the composer live once the run starts, asking it instead of the interview', async () => {
  await driveToRunSpec();
  await startRunFromSpec();

  const composer = getComposer();
  expect(composer).toBeEnabled();
  expect(screen.getByRole('button', {name: 'Files'})).toBeEnabled();
  expect(screen.getByRole('button', {name: 'Connectors'})).toBeEnabled();
  expect(
    screen.getByText('Ask a question about this research session'),
  ).toBeInTheDocument();
  expect(
    screen.queryByText('Session started — start a new chat'),
  ).not.toBeInTheDocument();

  apiMock.askRunQuestion.mockResolvedValue(1);
  fireEvent.change(composer, {
    target: {value: 'Which hypothesis ranked highest?'},
  });
  fireEvent.submit(composer.closest('form')!);

  await waitFor(() => {
    expect(apiMock.askRunQuestion).toHaveBeenCalledWith(
      'run-1',
      'Which hypothesis ranked highest?',
      expect.any(Object),
      expect.any(AbortSignal),
    );
  });
  expect(apiMock.addInterviewTurn).not.toHaveBeenCalled();
});

it('streams a run Q&A answer into a growing assistant bubble', async () => {
  await driveToRunSpec();
  await startRunFromSpec();

  let sinks: {onChunk?: (fragment: string) => void} = {};
  let resolveAsk: (() => void) | undefined;
  apiMock.askRunQuestion.mockImplementation(
    (_id: string, _q: string, s: typeof sinks) =>
      new Promise<number>(resolve => {
        sinks = s;
        resolveAsk = () => resolve(3);
      }),
  );

  const composer = getComposer();
  fireEvent.change(composer, {target: {value: 'Why?'}});
  fireEvent.submit(composer.closest('form')!);

  expect(await screen.findByText('Why?')).toBeInTheDocument();
  sinks.onChunk?.('Because ');
  sinks.onChunk?.('the evidence supports it.');
  expect(
    await screen.findByText('Because the evidence supports it.'),
  ).toBeInTheDocument();

  resolveAsk?.();
  await waitFor(() => {
    expect(
      screen.getByText('Because the evidence supports it.'),
    ).toBeInTheDocument();
  });
});

it('re-enables the composer when a started session starts a new chat', async () => {
  await driveToRunSpec();
  await startRunFromSpec();
  expect(
    screen.getByText('Ask a question about this research session'),
  ).toBeInTheDocument();

  fireEvent.click(
    screen.getByRole('button', {
      name: 'Start a new research goal session on a new topic',
    }),
  );

  const composer = screen.getByRole('textbox');
  expect(composer).toBeEnabled();
  expect(
    screen.getByText('Start a new research goal to begin'),
  ).toBeInTheDocument();
});
