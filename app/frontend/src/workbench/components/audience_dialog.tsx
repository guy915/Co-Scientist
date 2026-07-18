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
    <div className="ucs-settings-dialog-root">
      <div
        className="ucs-settings-dialog-scrim"
        onClick={dismissible ? onDismiss : undefined}
        aria-hidden="true"
      />
      <div
        role="dialog"
        aria-modal="true"
        aria-label="Choose your affiliation"
        className="ucs-settings-dialog-panel mx-auto grid max-w-md content-center gap-4 p-6"
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
    </div>
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
