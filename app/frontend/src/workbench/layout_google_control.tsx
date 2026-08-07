import {GOOGLE_PROPOSALS} from './audience_content';
import {HeaderControlLink} from './layout_primitives';

/**
 * The Google team's header control, replacing Logs: a link straight to the
 * proposals graph.
 *
 * This slot used to hold a popover with a personal note whose only
 * destination was the same page, so reaching the proposals cost a click on
 * a panel nobody came for. The control now is the destination.
 *
 * Takes no props on purpose. The audience table types every control as one
 * that may open a popover; this one never does, and ignoring the popover
 * props is what says so.
 */
export function GoogleTeamControl() {
  return (
    <HeaderControlLink
      icon="lightbulb"
      label={GOOGLE_PROPOSALS.label}
      to={GOOGLE_PROPOSALS.to}
      lang="he"
    />
  );
}
