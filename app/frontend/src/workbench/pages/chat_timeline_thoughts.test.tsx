import {fireEvent, render, screen} from '@testing-library/react';
import {expect, test} from 'vitest';
import {ThoughtsDisclosure} from './chat_timeline_thoughts';

// Decorative dots are aria-hidden, so query their class rather than their role.
const DOTS = '.reference-thinking-dots';

function isOpen(container: HTMLElement): boolean {
  return (
    container.querySelector('button')?.getAttribute('aria-expanded') === 'true'
  );
}

test('counts dots and stands open while the turn is still being written', () => {
  const {container} = render(
    <ThoughtsDisclosure reasoning="Weighing two mechanisms." live />,
  );

  expect(container.querySelector(DOTS)).not.toBeNull();
  expect(isOpen(container)).toBe(true);
  expect(screen.getByText('Weighing two mechanisms.')).toBeInTheDocument();
  expect(container.querySelector(DOTS)?.textContent).toBe('...');
});

test('shows the label before the first thought arrives', () => {
  const {container} = render(<ThoughtsDisclosure reasoning="" live />);

  expect(screen.getByText('Thinking')).toBeInTheDocument();
  expect(container.querySelector(DOTS)).not.toBeNull();
  expect(container.querySelector('.reference-thoughts-trail')).toBeNull();
});

test('drops the dots and closes once the turn has landed', () => {
  const {container} = render(
    <ThoughtsDisclosure reasoning="Weighing two mechanisms." />,
  );

  expect(screen.getByText('Thinking')).toBeInTheDocument();
  expect(container.querySelector(DOTS)).toBeNull();
  expect(isOpen(container)).toBe(false);
});

test('folds itself away as soon as the answer starts arriving', () => {
  // The first reply token makes thinking stale; waiting until completion buries
  // the answer.
  const {container, rerender} = render(
    <ThoughtsDisclosure reasoning="A thought." live />,
  );
  expect(isOpen(container)).toBe(true);

  rerender(<ThoughtsDisclosure reasoning="A thought." live answering />);

  expect(isOpen(container)).toBe(false);
});

test('renders nothing for a finished turn that produced no reasoning', () => {
  const {container} = render(<ThoughtsDisclosure reasoning="   " />);
  expect(container).toBeEmptyDOMElement();
});

test('lets the reader close the panel while the Agent is still writing', () => {
  const {container} = render(
    <ThoughtsDisclosure reasoning="A thought." live />,
  );
  expect(isOpen(container)).toBe(true);

  fireEvent.click(screen.getByRole('button'));

  expect(isOpen(container)).toBe(false);
});

test('announces the live label only, never the raw chain of thought', () => {
  render(<ThoughtsDisclosure reasoning="A thought." live />);

  expect(
    screen.getByText('Thinking').closest('[role="status"]'),
  ).not.toBeNull();
  // Live announcements would reread reasoning on every token.
  expect(screen.getByText('A thought.').closest('[aria-live]')).toBeNull();
});

test('does not announce a finished turn as a live status', () => {
  render(<ThoughtsDisclosure reasoning="A thought." />);
  expect(screen.getByText('Thinking').closest('[role="status"]')).toBeNull();
});

test('animates between the two states rather than snapping', () => {
  // Grid-track disclosure animates growing reasoning without measuring it.
  const {container} = render(
    <ThoughtsDisclosure reasoning="A thought." live />,
  );
  const panel = container.querySelector('[id]');

  expect(panel?.className).toContain('transition-');
  expect(panel?.className).toContain('grid-rows-[1fr]');

  fireEvent.click(screen.getByRole('button'));

  expect(panel?.className).toContain('grid-rows-[0fr]');
  expect(panel?.hasAttribute('inert')).toBe(true);
});
