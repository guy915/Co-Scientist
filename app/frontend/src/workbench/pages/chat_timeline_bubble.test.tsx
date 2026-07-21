import {fireEvent, render, screen} from '@testing-library/react';
import {afterEach, beforeEach, describe, expect, it, vi} from 'vitest';
import {makeMessage as makeSharedMessage} from '@/test_fixtures';
import {ChatBubble, type ChatEntry} from './chat_timeline_bubble';

function makeMessage(overrides: Partial<ChatEntry> = {}): ChatEntry {
  return makeSharedMessage({content: 'Hello there', ...overrides});
}

function renderBubble(overrides: Partial<ChatEntry> = {}) {
  const onEdit = vi.fn();
  const onCopyRequest = vi.fn();
  const onRetry = vi.fn();
  const message = makeMessage(overrides);
  const utils = render(
    <ChatBubble
      message={message}
      onEdit={onEdit}
      onCopyRequest={onCopyRequest}
      onRetry={onRetry}
    />,
  );
  return {...utils, onEdit, onCopyRequest, onRetry, message};
}

afterEach(() => {
  vi.unstubAllGlobals();
});

describe('ChatBubble', () => {
  it('renders an assistant message with the response action row and no collapse affordance', () => {
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

  it('renders a short user message with the request action row and no collapse affordance', () => {
    renderBubble({role: 'user', content: 'Short question?'});
    expect(screen.getByLabelText('Edit prompt')).toBeInTheDocument();
    expect(screen.getByLabelText('Copy prompt')).toBeInTheDocument();
    expect(screen.queryByLabelText('Expand')).not.toBeInTheDocument();
  });

  describe('collapsible user bubble', () => {
    const longContent = 'Long line of chat text. '.repeat(40);

    beforeEach(() => {
      // jsdom performs no real layout, so scrollHeight is always 0. Force a
      // measured full height that exceeds the four-line collapsed height so
      // the collapse/expand affordance renders.
      Object.defineProperty(HTMLElement.prototype, 'scrollHeight', {
        configurable: true,
        value: 500,
      });
    });

    afterEach(() => {
      Reflect.deleteProperty(HTMLElement.prototype, 'scrollHeight');
    });

    it('toggles expand/collapse synchronously under prefers-reduced-motion', () => {
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
      // The toggle button persists across expand/collapse (same DOM node),
      // so a single spy tracks blur calls across both clicks below.
      const blurSpy = vi.spyOn(expandButton, 'blur');

      // A pointer click (detail > 0) should blur afterward.
      fireEvent.click(expandButton, {detail: 1});

      expect(blurSpy).toHaveBeenCalledOnce();
      const collapseButton = screen.getByLabelText('Collapse');
      expect(textSpan.className).toContain('whitespace-pre-wrap');
      // Settled immediately (no rAF wait needed) under reduced motion.
      expect(textSpan.style.maxHeight).toBe('');

      // A keyboard-style activation (detail 0) should not blur again.
      fireEvent.click(collapseButton, {detail: 0});
      expect(blurSpy).toHaveBeenCalledOnce();
      expect(screen.getByLabelText('Expand')).toBeInTheDocument();
      expect(textSpan.className).toContain('whitespace-normal');
    });

    it('animates expand/collapse via requestAnimationFrame otherwise, settling on transition end', () => {
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
      // Not settled yet: the inline max-height still caps the full height
      // until the transition-end handler fires.
      expect(textSpan.style.maxHeight).toBe('500px');

      // A transitionend for an unrelated property is ignored.
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
});
