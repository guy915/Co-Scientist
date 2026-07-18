import {type Audience, useAudience} from '../audience_context';
import {AUDIENCE_OPTIONS} from '../audience_content';

/**
 * Renders the affiliation modal. Controlled purely by props; the gate below
 * decides when to show it.
 *
 * @param props.onChoose Called with the picked audience.
 * @param props.dismissible When true, Escape / scrim click closes without a
 *   forced choice (used by the Settings re-open path); the first-visit gate
 *   passes false so a concrete value is always set.
 * @param props.onDismiss Called when a dismissible dialog is closed.
 */
export function AudienceDialog({
  onChoose,
  dismissible = false,
  onDismiss,
}: {
  onChoose: (a: Audience) => void;
  dismissible?: boolean;
  onDismiss?: () => void;
}) {
  return (
    <>
      {/* Reuses the Settings scrim (fixed inset-0, z 70); the panel below sits
          one layer above it, matching .ucs-settings-dialog's z 71 without
          inheriting that window's fixed 52rem x 34rem size. */}
      <div
        className="ucs-settings-dialog-scrim"
        onClick={dismissible ? onDismiss : undefined}
        aria-hidden="true"
      />
      <div
        role="dialog"
        aria-modal="true"
        aria-label="Choose your affiliation"
        className="fixed top-1/2 left-1/2 z-[71] grid w-[min(28rem,calc(100vw-2rem))] -translate-x-1/2 -translate-y-1/2 gap-4 rounded-[1.75rem] bg-cosci-menu-bg p-6 text-cosci-menu-text"
      >
        <h2 className="text-2xl font-normal">Choose your affiliation</h2>
        <p className="text-cosci-muted">
          This tailors the workspace. You can change it later in Settings.
        </p>
        <div className="grid gap-3">
          {AUDIENCE_OPTIONS.map(option => (
            <button
              key={option.value}
              type="button"
              className="rounded-xl border border-cosci-border p-4 text-left hover:bg-cosci-hover"
              onClick={() => onChoose(option.value)}
            >
              <span className="block font-semibold">{option.title}</span>
              <span className="block text-cosci-muted">{option.blurb}</span>
            </button>
          ))}
        </div>
      </div>
    </>
  );
}

/**
 * First-visit gate: renders {@link AudienceDialog} until an audience is set.
 */
export function AudienceGate() {
  const {audience, setAudience} = useAudience();
  if (audience) return null;
  return <AudienceDialog onChoose={setAudience} />;
}
