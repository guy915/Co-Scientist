import {fireEvent, screen} from '@testing-library/react';
import {beforeEach, expect, it} from 'vitest';
import {
  installChatWorkspaceMocks,
  renderWorkspace,
} from './chat_workspace_test_helpers';
import {SUGGESTIONS} from './chat_home_stage';

// The exact suggestion copy lives in one place (SUGGESTIONS); reference it by
// index here so re-wording a prompt never breaks these interaction tests.
const [FIRST_SUGGESTION, SECOND_SUGGESTION] = SUGGESTIONS;

beforeEach(() => {
  installChatWorkspaceMocks();
});

it('previews a suggestion without moving the composer', async () => {
  renderWorkspace();

  const composer = await screen.findByRole('textbox');
  const originalComposerTop = composer
    .closest('.reference-composer')
    ?.getBoundingClientRect().top;

  const suggestion = screen.getByRole('button', {
    name: FIRST_SUGGESTION.preview,
  });

  fireEvent.pointerEnter(suggestion);

  const preview = screen.getByText(FIRST_SUGGESTION.preview, {
    selector: '.reference-suggestion-preview',
  });
  expect(preview).toBeInTheDocument();
  expect(preview).toHaveClass('visible');
  expect(preview.closest('.reference-suggestion-slot')).toContainElement(
    suggestion,
  );
  expect(
    composer.closest('.reference-composer')?.getBoundingClientRect().top,
  ).toBe(originalComposerTop);

  fireEvent.pointerLeave(suggestion);
  expect(preview).not.toHaveClass('visible');
});

it('fills the composer from a suggested prompt', () => {
  renderWorkspace();

  const suggestion = screen.getByRole('button', {
    name: FIRST_SUGGESTION.preview,
  });

  fireEvent.click(suggestion);

  // The card previews one sentence, but selecting it fills the full prompt.
  expect(screen.getByRole('textbox')).toHaveValue(FIRST_SUGGESTION.prompt);
  expect(suggestion).not.toHaveClass('selected');
  expect(suggestion).not.toHaveClass('is-previewed');
});

it('hides the suggestion preview after selecting a suggested prompt', () => {
  renderWorkspace();

  const suggestion = screen.getByRole('button', {
    name: SECOND_SUGGESTION.preview,
  });

  fireEvent.pointerEnter(suggestion);

  const preview = screen.getByText(SECOND_SUGGESTION.preview, {
    selector: '.reference-suggestion-preview',
  });
  expect(preview).toHaveClass('visible');

  fireEvent.click(suggestion);

  expect(preview).not.toHaveClass('visible');
  expect(suggestion).not.toHaveClass('is-previewed');
});
