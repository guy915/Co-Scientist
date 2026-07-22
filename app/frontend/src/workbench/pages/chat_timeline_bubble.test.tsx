import {fireEvent, screen} from '@testing-library/react';
import {afterEach, expect, test, vi} from 'vitest';
import {renderBubble} from './chat_timeline_bubble_test_support';

afterEach(() => {
  vi.unstubAllGlobals();
});

test('renders an assistant message with the response action row and no collapse affordance', () => {
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

test('renders a short user message with the request action row and no collapse affordance', () => {
  renderBubble({role: 'user', content: 'Short question?'});
  expect(screen.getByLabelText('Edit prompt')).toBeInTheDocument();
  expect(screen.getByLabelText('Copy prompt')).toBeInTheDocument();
  expect(screen.queryByLabelText('Expand')).not.toBeInTheDocument();
});
