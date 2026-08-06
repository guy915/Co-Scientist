import {fireEvent, screen, waitFor} from '@testing-library/react';
import {beforeEach, expect, it, vi} from 'vitest';
import {
  apiMock,
  installChatWorkspaceMocks,
  renderWorkspace,
} from './chat_workspace_test_helpers';

beforeEach(() => {
  installChatWorkspaceMocks();
});

/** The research goal every run-flow suite drives the workspace with. */
const RESEARCH_GOAL = 'Investigate glucose homeostasis under cold stress.';

/** Sentinel object URL returned by the stubbed `URL.createObjectURL`. */
const RESPONSE_BLOB_URL = 'blob:co-scientist-response';

/**
 * Types the research goal into the composer and submits it.
 *
 * @param goal The research goal to enter; defaults to {@link RESEARCH_GOAL}.
 */
function submitResearchGoal(goal = RESEARCH_GOAL) {
  const input = screen.getByRole('textbox');
  fireEvent.change(input, {target: {value: goal}});
  fireEvent.submit(input.closest('form')!);
}

/**
 * Installs clipboard, object-URL, and anchor-download spies used by the
 * transcript action-control assertions.
 *
 * @returns The installed spies and the captured download filenames.
 */
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

/**
 * Renders the workspace, submits the research goal, and waits for the inferred
 * run-spec setup card to appear.
 */
async function driveToRunSpec() {
  renderWorkspace();
  submitResearchGoal();
  expect(
    await screen.findByText(
      /Review the four fields and select a focus and run type/,
    ),
  ).toBeInTheDocument();
}

/**
 * Selects the Ultra run type, confirms the spec, and waits for the durable run
 * to be created and started.
 */
async function startRunFromSpec() {
  fireEvent.click(screen.getByLabelText(/Ultra/i));
  fireEvent.click(screen.getByText('Start research'));
  await waitFor(() => {
    expect(apiMock.createRun).toHaveBeenCalledWith(
      expect.objectContaining({
        research_goal: RESEARCH_GOAL,
        interview_id: 'interview-1',
        requirements: ['Prioritize mechanistic novelty'],
        attributes: ['Cold-stress glucose regulation'],
        criteria: [],
        focus: 'balance',
        tier: 'ultra',
      }),
    );
    expect(apiMock.startRun).toHaveBeenCalledWith('run-1');
  });
}

it('shows request and response controls in the transcript', async () => {
  const spies = installClipboardAndDownloadSpies();

  renderWorkspace();
  submitResearchGoal();

  // Wait for the turn to resolve first: the optimistic prompt bubble is
  // replaced by the durable turn it became, so a node grabbed before then is
  // detached by the time it is asserted on.
  expect(
    await screen.findByRole('heading', {name: 'Research plan'}),
  ).toBeInTheDocument();
  expect(screen.getByLabelText('Copy prompt')).toBeInTheDocument();
  expect(screen.getByLabelText('Edit prompt')).toBeInTheDocument();
  expect(screen.getAllByLabelText('Retry response')).not.toHaveLength(0);
  expect(screen.getAllByLabelText('Copy response')).not.toHaveLength(0);
  expect(screen.getAllByLabelText('Download response')).not.toHaveLength(0);

  // Editing opens on the message itself, prefilled, rather than pushing the
  // prompt back down into the composer.
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
  expect(screen.getByLabelText(/Standard/i)).toBeChecked();
});

it('starts the durable run on confirmation', async () => {
  await driveToRunSpec();
  await startRunFromSpec();

  expect(screen.getByTestId('location')).toHaveTextContent('/');
  expect(
    await screen.findByText(
      /Your session has been started and Co-Scientist has started research/,
    ),
  ).toBeInTheDocument();
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

it('locks the composer once the run starts and posts no further turns', async () => {
  await driveToRunSpec();
  await startRunFromSpec();

  // The interview the composer posts to is completed server-side once the
  // run starts, so every affordance that would create another turn locks,
  // and the placeholder says why.
  const composer = screen.getByRole('textbox');
  expect(composer).toBeDisabled();
  expect(screen.getByRole('button', {name: 'Send'})).toBeDisabled();
  expect(screen.getByRole('button', {name: 'Files'})).toBeDisabled();
  expect(screen.getByRole('button', {name: 'Connectors'})).toBeDisabled();
  expect(
    screen.getByText('Session started — start a new chat'),
  ).toBeInTheDocument();

  // Even a direct form submission (bypassing the disabled controls) never
  // reaches the interview-turn API. Call counts are compared against the
  // baseline because this suite's api mock accumulates calls across tests.
  const interviewCalls = apiMock.createInterview.mock.calls.length;
  fireEvent.submit(composer.closest('form')!);
  expect(apiMock.addInterviewTurn).not.toHaveBeenCalled();
  expect(apiMock.createInterview).toHaveBeenCalledTimes(interviewCalls);
});

it('re-enables the composer when a started session starts a new chat', async () => {
  await driveToRunSpec();
  await startRunFromSpec();
  expect(screen.getByRole('textbox')).toBeDisabled();

  fireEvent.click(
    screen.getByRole('button', {
      name: 'Start a new research goal session on a new topic',
    }),
  );

  // The reset returns the workspace to the home stage with a live composer.
  const composer = screen.getByRole('textbox');
  expect(composer).toBeEnabled();
  expect(
    screen.getByText('Start a new research goal to begin'),
  ).toBeInTheDocument();
});
