import {fireEvent, screen} from '@testing-library/react';
import {afterEach, expect, test, vi} from 'vitest';
import {FALLBACK_NOTICE_TEXT} from './chat_timeline_bubble';
import {renderBubble} from './chat_timeline_bubble_test_support';

afterEach(() => {
  vi.unstubAllGlobals();
});

test('renders an assistant message with the response action row', () => {
  const {onRetry} = renderBubble({
    role: 'assistant',
    content: 'A short reply.',
  });
  expect(screen.getByText('A short reply.')).toBeInTheDocument();
  expect(screen.getByLabelText('Retry response')).toBeInTheDocument();
  expect(screen.getByLabelText('Copy response')).toBeInTheDocument();
  expect(screen.getByLabelText('Download response')).toBeInTheDocument();
  expect(screen.queryByLabelText('Edit prompt')).not.toBeInTheDocument();
  expect(screen.queryByLabelText('Expand')).not.toBeInTheDocument();

  fireEvent.click(screen.getByLabelText('Retry response'));
  expect(onRetry).toHaveBeenCalledOnce();
});

test('renders a short user message with the request action row', () => {
  renderBubble({role: 'user', content: 'Short question?'});
  expect(screen.getByLabelText('Edit prompt')).toBeInTheDocument();
  expect(screen.getByLabelText('Copy prompt')).toBeInTheDocument();
  expect(screen.queryByLabelText('Expand')).not.toBeInTheDocument();
});

test('shows the fallback notice on a scripted assistant turn (A16)', () => {
  // The keyless interview degrades to a deterministic question script; the
  // turns it authors must be visibly marked so they are never read as model
  // output.
  renderBubble({
    role: 'assistant',
    content: 'Which scientific mechanisms should this research prioritize?',
    fallback: true,
  });
  expect(screen.getByText(FALLBACK_NOTICE_TEXT)).toBeInTheDocument();
});

test('omits the fallback notice on model-driven turns', () => {
  renderBubble({role: 'assistant', content: 'A model reply.'});
  expect(screen.queryByText(FALLBACK_NOTICE_TEXT)).not.toBeInTheDocument();
});

test('renders assistant markdown, and leaves user text literal', async () => {
  // The two roles carry different things: an assistant bubble shows model
  // prose, which is markdown now, while a user bubble shows what the
  // scientist typed and must never reinterpret it as markup.
  renderBubble({role: 'assistant', content: 'Use **primary** cells'});
  expect((await screen.findByText('primary')).tagName).toBe('STRONG');

  renderBubble({role: 'user', content: 'Use **primary** cells'});
  expect(screen.getByText('Use **primary** cells')).toBeInTheDocument();
});

test('does not render assistant markdown under pre-wrap whitespace', async () => {
  // React-markdown puts a literal newline text node between adjacent blocks,
  // so pre-wrap paints a whole extra line at every paragraph boundary and the
  // reply reads as double-spaced. The user bubble keeps pre-wrap (the test
  // below it), which is exactly the divergence: one shows rendered blocks,
  // the other a plain-text span whose typed line breaks must survive.
  const {container} = renderBubble({
    role: 'assistant',
    content: 'First para.\n\nSecond para.',
  });
  await screen.findByText('First para.');
  const wrapper = container.querySelector('.reference-model-bubble-text');
  expect(wrapper).not.toBeNull();
  expect(wrapper?.className).not.toContain('whitespace-pre-wrap');
  expect(wrapper?.className).toContain('whitespace-normal');
  expect(container.querySelectorAll('p')).toHaveLength(2);
});
