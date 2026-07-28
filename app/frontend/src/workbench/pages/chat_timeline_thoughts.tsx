import {Icon} from '@/components/icon';

// Collapsed by default: the thinking is there to be checked, not read every
// time. The marker is suppressed so the summary can carry its own chevron.
const THOUGHTS_CLASSES = 'ucs-thoughts mt-1 mb-2 [&>summary]:list-none';

const THOUGHTS_SUMMARY_CLASSES =
  'inline-flex cursor-pointer items-center gap-1 rounded-full px-1 ' +
  'text-xs font-medium text-cosci-muted hover:text-cosci-fg ' +
  'focus-visible:text-cosci-fg';

// Matches the live "Thinking…" trail (chat_workspace_timeline) so a turn's
// reasoning looks the same before and after the answer lands.
const THOUGHTS_BODY_CLASSES =
  'mt-2 max-h-56 overflow-y-auto border-l-2 border-th-border pl-3 text-xs ' +
  'leading-relaxed whitespace-pre-wrap text-cosci-muted';

/**
 * A finished turn's chain of thought, collapsed under the message it
 * produced.
 *
 * The live "Thinking…" trail disappears the instant the reply arrives, which
 * threw away the one part of the turn that explains it. Keeping the
 * reasoning here means a scientist can go back to why the Agent asked what
 * it asked -- and mirrors the transcript the model itself is given, which
 * now carries the same reasoning.
 */
export function ThoughtsDisclosure({reasoning}: {reasoning?: string}) {
  if (!reasoning?.trim()) return null;
  return (
    <details className={THOUGHTS_CLASSES}>
      <summary className={THOUGHTS_SUMMARY_CLASSES}>
        <Icon aria-hidden="true" className="text-sm" name="neurology" />
        <span>Thoughts</span>
      </summary>
      <div className={THOUGHTS_BODY_CLASSES}>{reasoning}</div>
    </details>
  );
}
