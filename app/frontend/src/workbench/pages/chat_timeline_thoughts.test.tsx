import {fireEvent, render, screen} from '@testing-library/react';
import {expect, test} from 'vitest';
import {ThoughtsDisclosure} from './chat_timeline_thoughts';

// The dots are decorative and aria-hidden, so they are found by their class
// rather than by role or text.
const DOTS = '.reference-thinking-dots';

test('counts dots and stands open while the turn is still being written', () => {
  const {container} = render(
    <ThoughtsDisclosure reasoning="Weighing two mechanisms." live />,
  );

  expect(container.querySelector(DOTS)).not.toBeNull();
  expect(container.querySelector('details')?.open).toBe(true);
  expect(screen.getByText('Weighing two mechanisms.')).toBeInTheDocument();
  // Real periods in the label's own type, not drawn circles.
  expect(container.querySelector(DOTS)?.textContent).toBe('...');
});

test('lets the thinking run as plain text, uncapped and unquoted', () => {
  const {container} = render(
    <ThoughtsDisclosure reasoning="A long thought." live />,
  );
  const trail = container.querySelector('.reference-thoughts-trail');

  // It is the Agent's own thinking, not a quotation, and a reader following
  // a live turn should not have to scroll a box inside the scrolling page.
  expect(trail?.className).not.toMatch(/border-l|max-h-|overflow-y/);
});

test('shows the label before the first thought arrives', () => {
  const {container} = render(<ThoughtsDisclosure reasoning="" live />);

  expect(screen.getByText('Thinking')).toBeInTheDocument();
  expect(container.querySelector(DOTS)).not.toBeNull();
  // No empty trail: the text block appears with the first fragment.
  expect(container.querySelector('.reference-thoughts-trail')).toBeNull();
});

test('drops the dots and closes once the turn has landed', () => {
  const {container} = render(
    <ThoughtsDisclosure reasoning="Weighing two mechanisms." />,
  );

  // Same word, same control -- the dots stopping and the panel closing are
  // the whole difference between the two states.
  expect(screen.getByText('Thinking')).toBeInTheDocument();
  expect(container.querySelector(DOTS)).toBeNull();
  expect(container.querySelector('details')?.open).toBe(false);
});

test('folds itself away as soon as the answer starts arriving', () => {
  // Not when the turn ends: the first token of the reply is what makes the
  // thinking stale, and leaving it open until then buries the answer being
  // written under a wall of reasoning.
  const {container, rerender} = render(
    <ThoughtsDisclosure reasoning="A thought." live />,
  );
  expect(container.querySelector('details')?.open).toBe(true);

  rerender(<ThoughtsDisclosure reasoning="A thought." live answering />);

  expect(container.querySelector('details')?.open).toBe(false);
});

test('renders nothing for a finished turn that produced no reasoning', () => {
  const {container} = render(<ThoughtsDisclosure reasoning="   " />);
  expect(container).toBeEmptyDOMElement();
});

test('lets the reader close the panel while the Agent is still writing', () => {
  const {container} = render(
    <ThoughtsDisclosure reasoning="A thought." live />,
  );
  const details = container.querySelector('details');

  // jsdom does not implement the summary click that toggles a details, so
  // the open state is driven the way the browser would drive it.
  if (details) {
    details.open = false;
    fireEvent(details, new Event('toggle'));
  }

  expect(details?.open).toBe(false);
});

test('announces the live label only, never the raw chain of thought', () => {
  render(<ThoughtsDisclosure reasoning="A thought." live />);

  expect(
    screen.getByText('Thinking').closest('[role="status"]'),
  ).not.toBeNull();
  // Announcing the trail would re-read the whole thing on every token.
  expect(screen.getByText('A thought.').closest('[aria-live]')).toBeNull();
});

test('does not announce a finished turn as a live status', () => {
  render(<ThoughtsDisclosure reasoning="A thought." />);
  expect(screen.getByText('Thinking').closest('[role="status"]')).toBeNull();
});
