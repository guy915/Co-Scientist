import {screen} from '@testing-library/react';
import {afterEach, beforeEach, expect, it, vi} from 'vitest';
import {installLayoutMocks, renderLayout} from './layout_test_support';

// The app deliberately binds no keyboard shortcuts. It used to carry two --
// "g n" for home and ArrowLeft/ArrowRight to cycle a run's report tabs --
// bound on `document` regardless of focus, which is exactly what makes them
// hard to notice coming back: nothing on screen changes when one is added,
// and the only symptom is a keypress doing something unasked for. Spying on
// the registration is the one check that fails the moment a document-level
// binding returns.
//
// Dialog keys are a different thing and are not covered here: Escape closing
// an open dialog and Tab staying inside it are that dialog's own semantics
// (useEscapeKey, useFocusTrap in dialog_accessibility.ts), they register only while it is open, and
// removing them would be an accessibility regression rather than honoring
// this rule.
let addEventListener: ReturnType<typeof vi.spyOn>;

beforeEach(() => {
  installLayoutMocks();
  addEventListener = vi.spyOn(document, 'addEventListener');
});

afterEach(() => {
  addEventListener.mockRestore();
});

// The keydown events the removed shortcuts listened for, so a reintroduction
// under a different key name still has to pass the registration check above.
function keydownRegistrations(): unknown[] {
  return addEventListener.mock.calls.filter(
    ([type]: [string, ...unknown[]]) => type === 'keydown',
  );
}

it('registers no document keydown handler on the shell', async () => {
  renderLayout('/');
  expect(await screen.findByText('Workspace content')).toBeInTheDocument();

  expect(keydownRegistrations()).toEqual([]);
});

it('registers no document keydown handler on a run route', async () => {
  renderLayout('/runs/run-1/details');
  expect(await screen.findByText('Workspace content')).toBeInTheDocument();

  expect(keydownRegistrations()).toEqual([]);
});
