import {render} from '@testing-library/react';
import {expect, it} from 'vitest';
import {useRestoreFocusOnClose} from './use_restore_focus_on_close';

function Dialog() {
  useRestoreFocusOnClose();
  return <div>dialog body</div>;
}

it('returns focus to the opener when it is still on the page', () => {
  const opener = document.createElement('button');
  document.body.append(opener);
  opener.focus();

  const view = render(<Dialog />);
  view.unmount();

  expect(document.activeElement).toBe(opener);
});

// The real path in this app: the rail's Settings menu is a popover that
// unmounts as soon as the dialog it launched opens, so by the time the
// dialog closes the captured opener is a detached node. `.focus()` on one is
// a silent no-op, which left focus on `<body>` -- verified in a browser
// before this fix -- restarting tabbing from the top of the page.
it('falls back to the nearest surviving ancestor when the opener is gone', () => {
  const rail = document.createElement('div');
  const popover = document.createElement('div');
  const menuItem = document.createElement('button');
  popover.append(menuItem);
  rail.append(popover);
  document.body.append(rail);
  menuItem.focus();

  const view = render(<Dialog />);
  // The popover (and the menu item inside it) closes behind the dialog.
  popover.remove();
  view.unmount();

  expect(document.activeElement).toBe(rail);
  expect(document.activeElement).not.toBe(document.body);
});
