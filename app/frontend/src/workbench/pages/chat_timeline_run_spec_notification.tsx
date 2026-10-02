import {isValidCompletionEmail, type InferredRunSpec} from '../run_spec';
import {useSystemStatus} from '../hooks/system_status_context';
import {
  OPTION_GROUP_CLASSES,
  OPTION_GROUP_LEGEND_CLASSES,
} from './chat_classes';

const EMAIL_ROW_CLASSES = 'mt-3 grid gap-1 text-sm';

const EMAIL_LABEL_CLASSES = 'text-cosci-fg';

const EMAIL_INPUT_CLASSES =
  'w-full rounded-xl border border-cosci-border bg-transparent p-3';

/**
 * The completion-email opt-in.
 *
 * There is no separate checkbox: the address field is always present, and
 * notification is simply whichever way a valid address makes it -- typing
 * one on turns it on, clearing or breaking it turns it off. Gated on the
 * server actually having an SMTP transport (`/status`'s
 * `email_notifications_available`): with none configured the durable send
 * task can only raise, exhaust its retries, and fail somewhere the scientist
 * never looks, so an editable field would promise a message that is never
 * coming. Unavailable, the row states that plainly rather than disappearing
 * -- the feature exists, this deployment just cannot send.
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
  const available = status?.email_notifications_available ?? false;
  return (
    <fieldset className={OPTION_GROUP_CLASSES}>
      <legend className={OPTION_GROUP_LEGEND_CLASSES}>Notification</legend>
      <NotificationEmail
        spec={spec}
        disabled={disabled}
        available={available}
        onChange={onChange}
      />
      <UnavailableNote available={available} />
    </fieldset>
  );
}

// Says why the field is inert, so an unconfigured server reads as a
// deployment fact rather than a control that ignores keystrokes.
function UnavailableNote({available}: {available: boolean}) {
  if (available) return null;
  return (
    <p className="text-xs text-cosci-muted">
      Email delivery is not configured on this server.
    </p>
  );
}

// The address the Goal Report notice goes to. Always on screen -- entering
// a valid one is the opt-in, an invalid or blank one is a silent opt-out,
// and neither state is announced as an error.
function NotificationEmail({
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
  return (
    <label className={EMAIL_ROW_CLASSES}>
      <span className={EMAIL_LABEL_CLASSES}>
        Email me when the Goal Report is ready
      </span>
      <input
        type="email"
        disabled={disabled || !available}
        placeholder="you@example.com — leave blank for no email"
        className={EMAIL_INPUT_CLASSES}
        value={spec.completionEmail || ''}
        onChange={event => {
          const email = event.currentTarget.value;
          onChange(isValidCompletionEmail(email), email);
        }}
      />
    </label>
  );
}
