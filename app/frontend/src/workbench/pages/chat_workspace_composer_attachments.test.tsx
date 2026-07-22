import {fireEvent, screen} from '@testing-library/react';
import {beforeEach, expect, it, vi} from 'vitest';
import {
  installChatWorkspaceMocks,
  renderWorkspace,
} from './chat_workspace_test_helpers';

beforeEach(() => {
  installChatWorkspaceMocks();
});

it('shows uploaded file previews in the composer', async () => {
  renderWorkspace();

  const fileInput = screen.getByLabelText('Upload files');
  fireEvent.change(fileInput, {
    target: {
      files: [
        new File(['abstract'], 'deep-research-report.md', {
          type: 'text/markdown',
        }),
      ],
    },
  });

  const filename = screen.getByText('deep-research-report.md');
  expect(filename).toBeInTheDocument();
  expect(filename.closest('.reference-attachment-card')).toHaveAttribute(
    'data-tooltip',
    'deep-research-report.md',
  );
  expect(screen.getByText('TXT')).toBeInTheDocument();
  expect(screen.getByText('Markdown')).toBeInTheDocument();
  expect(
    screen.getByRole('button', {name: 'Remove deep-research-report.md'}),
  ).toHaveAttribute('data-tooltip', 'Remove deep-research-report.md');
});

it('shows uploaded image previews in the composer', async () => {
  const createObjectURL = vi.fn(() => 'blob:preview-image');
  const revokeObjectURL = vi.fn();
  vi.stubGlobal('URL', {
    ...URL,
    createObjectURL,
    revokeObjectURL,
  });
  renderWorkspace();

  const fileInput = screen.getByLabelText('Upload files');
  fireEvent.change(fileInput, {
    target: {
      files: [
        new File(['image'], 'reference-shot.png', {
          type: 'image/png',
        }),
      ],
    },
  });

  expect(screen.getByAltText('reference-shot.png')).toHaveAttribute(
    'src',
    'blob:preview-image',
  );

  fireEvent.click(
    screen.getByRole('button', {name: 'Remove reference-shot.png'}),
  );

  expect(screen.queryByAltText('reference-shot.png')).toBeNull();
  expect(revokeObjectURL).toHaveBeenCalledWith('blob:preview-image');
});
