import {render, screen, waitFor} from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import type {ReactNode} from 'react';
import {beforeEach, describe, expect, it, vi} from 'vitest';
import {AudienceProvider} from './audience_context';
import {PilotControl} from './layout_pilot_control';

const apiMock = vi.hoisted(() => ({submitFeedback: vi.fn()}));
vi.mock('@/api/feedback', () => apiMock);

function renderPanel() {
  return render(
    <AudienceProvider initialAudience="sbi_ucd">
      <PilotControl
        open={true}
        onToggle={() => {}}
        renderPopover={(children: ReactNode) => children}
      />
    </AudienceProvider>,
  );
}

describe('PilotControl feedback form', () => {
  beforeEach(() => {
    window.localStorage.clear();
    apiMock.submitFeedback.mockReset();
    apiMock.submitFeedback.mockResolvedValue({id: 1});
  });

  it('submits the note with its category and audience', async () => {
    renderPanel();
    await userEvent.click(screen.getByRole('radio', {name: /Suggestion/i}));
    await userEvent.type(
      screen.getByPlaceholderText(/What would you like us to know/i),
      'Add a compare view.',
    );
    await userEvent.click(screen.getByRole('button', {name: /^Send$/}));

    await waitFor(() =>
      expect(apiMock.submitFeedback).toHaveBeenCalledWith({
        message: 'Add a compare view.',
        category: 'suggestion',
        audience: 'sbi_ucd',
      }),
    );
  });

  it('confirms and clears the box after a successful send', async () => {
    renderPanel();
    const box = screen.getByPlaceholderText(/What would you like us to know/i);
    await userEvent.type(box, 'It hung on step 2.');
    await userEvent.click(screen.getByRole('button', {name: /^Send$/}));

    expect(await screen.findByText(/your feedback was sent/i)).toBeVisible();
    expect(box).toHaveValue('');
  });

  it('reports a failed send and keeps the note', async () => {
    apiMock.submitFeedback.mockRejectedValue(new Error('offline'));
    renderPanel();
    const box = screen.getByPlaceholderText(/What would you like us to know/i);
    await userEvent.type(box, 'Keep this text.');
    await userEvent.click(screen.getByRole('button', {name: /^Send$/}));

    expect(await screen.findByText(/could not send/i)).toBeVisible();
    expect(box).toHaveValue('Keep this text.');
  });

  it('disables sending an empty note', () => {
    renderPanel();
    expect(screen.getByRole('button', {name: /^Send$/})).toBeDisabled();
  });

  it('defaults to the bug category', () => {
    renderPanel();
    expect(screen.getByRole('radio', {name: /^Bug$/i})).toBeChecked();
  });
});
