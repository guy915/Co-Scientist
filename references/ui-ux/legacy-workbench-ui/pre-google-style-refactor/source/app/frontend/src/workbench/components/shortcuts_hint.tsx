import '@material/web/iconbutton/icon-button.js';
import '@material/web/icon/icon.js';
import '@material/web/button/text-button.js';
import {useEffect, useState} from 'react';
import {MdDialog} from '@/md3/md_dialog';

const SHORTCUTS: {keys: string; description: string}[] = [
  {keys: '?', description: 'Open this shortcut help'},
  {keys: 'g d', description: 'Go to dashboard'},
  {keys: 'g n', description: 'Start a new run'},
  {keys: '← / →', description: 'Move between tabs (on a run page)'},
  {keys: 'Esc', description: 'Close any open dialog'},
];

/**
 * Renders a help button and dialog listing the keyboard shortcuts.
 */
export function ShortcutsHint() {
  const [open, setOpen] = useState(false);

  useEffect(() => {
    function onKey(e: KeyboardEvent) {
      const target = e.target as HTMLElement | null;
      if (
        target &&
        (target.tagName === 'INPUT' ||
          target.tagName === 'TEXTAREA' ||
          target.isContentEditable)
      ) {
        return;
      }
      if (e.key === '?') {
        e.preventDefault();
        setOpen(o => !o);
      } else if (e.key === 'Escape' && open) {
        setOpen(false);
      }
    }
    document.addEventListener('keydown', onKey);
    return () => document.removeEventListener('keydown', onKey);
  }, [open]);

  return (
    <>
      <md-icon-button
        onclick={(() => setOpen(true)) as EventListener}
        aria-label="Keyboard shortcuts"
        title="Keyboard shortcuts (press ?)"
      >
        <md-icon aria-hidden="true">keyboard</md-icon>
      </md-icon-button>
      <MdDialog
        open={open}
        onClose={() => setOpen(false)}
        headline="Keyboard shortcuts"
        actions={
          <md-text-button onclick={(() => setOpen(false)) as EventListener}>
            Close
          </md-text-button>
        }
      >
        <ul className="space-y-2 text-sm min-w-64">
          {SHORTCUTS.map(s => (
            <li
              key={s.keys}
              className="flex items-center justify-between gap-4"
            >
              <span style={{color: 'var(--md-sys-color-on-surface-variant)'}}>
                {s.description}
              </span>
              <kbd
                className="text-xs font-mono px-1.5 py-0.5 rounded border shrink-0"
                style={{
                  borderColor: 'var(--md-sys-color-outline-variant)',
                  backgroundColor: 'var(--md-sys-color-surface-variant)',
                }}
              >
                {s.keys}
              </kbd>
            </li>
          ))}
        </ul>
      </MdDialog>
    </>
  );
}
