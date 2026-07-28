import {type InferredRunSpec} from '../run_spec';
import {useSystemStatus} from '../hooks/system_status_context';
import {
  OPTION_GROUP_CLASSES,
  OPTION_GROUP_LEGEND_CLASSES,
} from './chat_setup_classes';

const EMAIL_INPUT_CLASSES =
  'mt-3 w-full rounded-xl border border-cosci-border bg-transparent p-3';

/**
 * The completion-email opt-in.
 *
 * Gated on the server actually having an SMTP transport (`/status`'s
 * `email_notifications_available`): with none configured the durable send
 * task can only raise, exhaust its retries, and fail somewhere the scientist
 * never looks, so the checkbox promised a message that was never coming.
 * Unavailable, the row states that plainly rather than disappearing -- the
 * feature exists, this deployment just cannot send.
 */
export function CompletionNotification({
  spec,
  disabled,
  onChange,
}: {
  spec: InferredRunSpec;
  disabled: boolean;
  onChange: (enabled: boolean, email: string) => void;
}) {
  const {status} = useSystemStatus();
  return (
    <fieldset className={OPTION_GROUP_CLASSES}>
      <legend className={OPTION_GROUP_LEGEND_CLASSES}>Notification</legend>
      <NotificationControls
        spec={spec}
        disabled={disabled}
        available={status?.email_notifications_available ?? false}
        onChange={onChange}
      />
    </fieldset>
  );
}

// The opt-in checkbox plus whichever of the two follow-on rows applies: the
// address to send to, or why nothing can be sent.
function NotificationControls({
  spec,
  disabled,
  available,
  onChange,
}: {
  spec: InferredRunSpec;
  disabled: boolean;
  available: boolean;
  onChange: (enabled: boolean, email: string) => void;
}) {
  const enabled = available && Boolean(spec.notifyOnCompletion);
  return (
    <>
      <label className="flex items-center gap-3 text-sm">
        <input
          type="checkbox"
          checked={enabled}
          disabled={disabled || !available}
          onChange={event =>
            onChange(event.currentTarget.checked, spec.completionEmail || '')
          }
        />
        Email me when the Goal Report is ready
      </label>
      <UnavailableNote available={available} />
      <NotificationEmail
        spec={spec}
        disabled={disabled}
        shown={enabled}
        onChange={onChange}
      />
    </>
  );
}

// Says why the opt-in is inert, so an unconfigured server reads as a
// deployment fact rather than a control that ignores clicks.
function UnavailableNote({available}: {available: boolean}) {
  if (available) return null;
  return (
    <p className="text-xs text-cosci-muted">
      Email delivery is not configured on this server.
    </p>
  );
}

// The address the Goal Report notice goes to, shown once opted in.
function NotificationEmail({
  spec,
  disabled,
  shown,
  onChange,
}: {
  spec: InferredRunSpec;
  disabled: boolean;
  shown: boolean;
  onChange: (enabled: boolean, email: string) => void;
}) {
  if (!shown) return null;
  return (
    <input
      type="email"
      required
      disabled={disabled}
      aria-label="Completion notification email"
      className={EMAIL_INPUT_CLASSES}
      value={spec.completionEmail || ''}
      onChange={event => onChange(true, event.currentTarget.value)}
    />
  );
}
