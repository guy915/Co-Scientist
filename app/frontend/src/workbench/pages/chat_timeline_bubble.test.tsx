import {fireEvent, screen, render} from '@testing-library/react';
import {afterEach, expect, test, vi, beforeEach, describe} from 'vitest';
import {
  FALLBACK_NOTICE_TEXT,
  ChatBubble,
  type ChatEntry,
} from './chat_timeline_bubble';
import {makeMessage as makeSharedMessage} from '@/test_fixtures';

describe('chat timeline bubble', () => {
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
    // Scientist text remains literal while assistant output renders Markdown.
    renderBubble({role: 'assistant', content: 'Use **primary** cells'});
    expect((await screen.findByText('primary')).tagName).toBe('STRONG');

    renderBubble({role: 'user', content: 'Use **primary** cells'});
    expect(screen.getByText('Use **primary** cells')).toBeInTheDocument();
  });

  test('does not render assistant markdown under pre-wrap whitespace', async () => {
    // Markdown adds newline nodes; pre-wrap would double paragraph spacing.
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
});

describe('chat timeline bubble collapse', () => {
  const longContent = 'Long line of chat text. '.repeat(40);

  afterEach(() => {
    vi.unstubAllGlobals();
  });

  beforeEach(() => {
    // jsdom heights are zero; provide overflowing geometry to expose the
    // toggle.
    Object.defineProperty(HTMLElement.prototype, 'scrollHeight', {
      configurable: true,
      value: 500,
    });
  });

  afterEach(() => {
    Reflect.deleteProperty(HTMLElement.prototype, 'scrollHeight');
  });

  test('toggles expand/collapse under prefers-reduced-motion', () => {
    vi.stubGlobal(
      'matchMedia',
      vi.fn().mockReturnValue({matches: true}) as unknown as (
        query: string,
      ) => MediaQueryList,
    );
    const {container} = renderBubble({content: longContent});

    const textSpan = container.querySelector('span')!;
    expect(textSpan.className).toContain('whitespace-normal');

    const expandButton = screen.getByLabelText('Expand');
    const blurSpy = vi.spyOn(expandButton, 'blur');

    fireEvent.click(expandButton, {detail: 1});

    expect(blurSpy).toHaveBeenCalledOnce();
    const collapseButton = screen.getByLabelText('Collapse');
    expect(textSpan.className).toContain('whitespace-pre-wrap');
    expect(textSpan.style.maxHeight).toBe('');

    fireEvent.click(collapseButton, {detail: 0});
    expect(blurSpy).toHaveBeenCalledOnce();
    expect(screen.getByLabelText('Expand')).toBeInTheDocument();
    expect(textSpan.className).toContain('whitespace-normal');
  });

  test('animates expand/collapse, settling on transition end', () => {
    vi.stubGlobal('matchMedia', undefined);
    vi.stubGlobal('requestAnimationFrame', (cb: FrameRequestCallback) => {
      cb(0);
      return 0;
    });
    const {container} = renderBubble({content: longContent});
    const textSpan = container.querySelector('span')!;

    fireEvent.click(screen.getByLabelText('Expand'), {detail: 1});
    const expanded = screen.getByLabelText('Collapse');
    expect(expanded).toBeInTheDocument();
    expect(textSpan.style.maxHeight).toBe('500px');

    fireEvent.transitionEnd(textSpan, {propertyName: 'opacity'});
    expect(textSpan.style.maxHeight).toBe('500px');

    fireEvent.transitionEnd(textSpan, {propertyName: 'max-height'});
    expect(textSpan.style.maxHeight).toBe('');

    fireEvent.click(screen.getByLabelText('Collapse'), {detail: 1});
    expect(screen.getByLabelText('Expand')).toBeInTheDocument();
    fireEvent.transitionEnd(textSpan, {propertyName: 'max-height'});
    expect(textSpan.className).toContain('whitespace-normal');
  });
});

export function makeMessage(overrides: Partial<ChatEntry> = {}): ChatEntry {
  return makeSharedMessage({content: 'Hello there', ...overrides});
}

export function renderBubble(
  overrides: Partial<ChatEntry> = {},
  revisable = true,
) {
  const onSubmitEdit = vi.fn();
  const onCopyRequest = vi.fn();
  const onRetry = vi.fn();
  const message = makeMessage(overrides);
  const utils = render(
    <ChatBubble
      message={message}
      revisable={revisable}
      onSubmitEdit={onSubmitEdit}
      onCopyRequest={onCopyRequest}
      onRetry={onRetry}
    />,
  );
  return {...utils, onSubmitEdit, onCopyRequest, onRetry, message};
}
