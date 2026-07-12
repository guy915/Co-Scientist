import {fireEvent, screen, waitFor} from '@testing-library/react';
import {beforeEach, describe, expect, it, vi} from 'vitest';
import {
  apiMock,
  installChatWorkspaceMocks,
  renderWorkspace,
} from './chat_workspace_test_helpers';

beforeEach(() => {
  installChatWorkspaceMocks();
});

describe('ChatWorkspace run flow', () => {
  it('shows request and response action controls in the chat transcript', async () => {
    const writeText = vi.fn().mockResolvedValue(undefined);
    Object.defineProperty(navigator, 'clipboard', {
      configurable: true,
      value: {writeText},
    });
    const createObjectURL = vi.fn((blob: Blob) => {
      expect(blob).toBeInstanceOf(Blob);
      return 'blob:co-scientist-response';
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

    renderWorkspace();

    const input = screen.getByRole('textbox');
    fireEvent.change(input, {
      target: {value: 'Investigate glucose homeostasis under cold stress.'},
    });
    fireEvent.submit(input.closest('form')!);

    expect(await screen.findByLabelText('Copy prompt')).toBeInTheDocument();
    expect(screen.getByLabelText('Edit prompt')).toBeInTheDocument();
    expect(screen.getByLabelText('Retry response')).toBeInTheDocument();
    expect(screen.getByLabelText('Copy response')).toBeInTheDocument();
    expect(screen.getByLabelText('Download response')).toBeInTheDocument();

    fireEvent.click(screen.getByLabelText('Edit prompt'));
    expect(screen.getByRole('textbox')).toHaveValue(
      'Investigate glucose homeostasis under cold stress.',
    );

    fireEvent.click(screen.getByLabelText('Copy prompt'));
    await waitFor(() => {
      expect(writeText).toHaveBeenCalledWith(
        'Investigate glucose homeostasis under cold stress.',
      );
    });
    expect(
      screen.getByRole('heading', {name: 'Research plan'}),
    ).toBeInTheDocument();

    fireEvent.click(screen.getByLabelText('Copy response'));
    await waitFor(() => {
      expect(writeText).toHaveBeenCalledWith(
        expect.stringContaining(
          '# Investigate glucose homeostasis under cold stress',
        ),
      );
    });

    fireEvent.click(screen.getByLabelText('Download response'));
    expect(createObjectURL).toHaveBeenCalled();
    expect(createObjectURL.mock.calls[0][0].type).toBe(
      'text/markdown;charset=utf-8',
    );
    expect(downloadedNames).toContain('co-scientist-research-plan.md');
    expect(anchorClick).toHaveBeenCalled();
    expect(revokeObjectURL).toHaveBeenCalledWith('blob:co-scientist-response');
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

  it('infers a run spec in chat and starts the durable run on confirmation', async () => {
    renderWorkspace();

    const input = screen.getByRole('textbox');
    fireEvent.change(input, {
      target: {value: 'Investigate glucose homeostasis under cold stress.'},
    });
    fireEvent.submit(input.closest('form')!);

    expect(
      await screen.findByText(/Please review or edit the details below/),
    ).toBeInTheDocument();
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
          name: 'Investigate glucose homeostasis under cold stress',
        })
        .closest('.reference-setup-document'),
    ).not.toBeNull();
    expect(screen.getByText('Cancel')).toBeInTheDocument();
    expect(
      screen.queryByRole('group', {name: 'Focus'}),
    ).not.toBeInTheDocument();
    expect(screen.getByRole('group', {name: 'Run type'})).toBeInTheDocument();
    expect(screen.getByLabelText(/Standard Run/i)).toBeChecked();

    fireEvent.click(screen.getByLabelText(/Advanced Run/i));

    fireEvent.click(screen.getByText('Start research'));

    await waitFor(() => {
      expect(apiMock.createRun).toHaveBeenCalledWith(
        expect.objectContaining({
          research_goal: 'Investigate glucose homeostasis under cold stress.',
          requirements: expect.arrayContaining([
            expect.stringContaining('mechanistic novelty'),
          ]),
          attributes: expect.arrayContaining(['Mechanistically specific']),
          criteria: expect.arrayContaining(['Scientific soundness']),
          tier: 'advanced',
        }),
      );
      expect(apiMock.startRun).toHaveBeenCalledWith('run-1');
    });

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
        name: 'Investigate glucose homeostasis under cold stress',
      }),
    ).toBeInTheDocument();
    expect(screen.getByRole('button', {name: 'Start research'})).toBeDisabled();
    expect(screen.getByText('Research session')).toBeInTheDocument();
    expect(screen.getByRole('button', {name: /Open/i})).toBeInTheDocument();
    expect(
      screen.getByRole('button', {name: 'View session details'}),
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

    fireEvent.click(screen.getByRole('button', {name: /Open/i}));

    await waitFor(() => {
      expect(screen.getByTestId('location')).toHaveTextContent(
        '/runs/run-1/details',
      );
    });
  });
});
