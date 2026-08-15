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

test('renders assistant markdown, and leaves user text literal', () => {
  // The two roles carry different things: an assistant bubble shows model
  // prose, which is markdown now, while a user bubble shows what the
  // scientist typed and must never reinterpret it as markup.
  renderBubble({role: 'assistant', content: 'Use **primary** cells'});
  expect(screen.getByText('primary').tagName).toBe('STRONG');

  renderBubble({role: 'user', content: 'Use **primary** cells'});
  expect(screen.getByText('Use **primary** cells')).toBeInTheDocument();
});
