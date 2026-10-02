import {SETUP_SECONDARY_BUTTON_CLASSES} from './chat_classes';

type LookupStatus = 'checking' | 'error' | 'cancelled' | undefined;

export function RecoveryLookupStatus({
  status,
  onRetry,
}: {
  status: LookupStatus;
  onRetry?: () => void;
}) {
  if (status === 'checking') {
    return (
      <p role="status" aria-live="polite" className="text-sm text-cosci-muted">
        Checking saved research session status…
      </p>
    );
  }
  if (status === 'error') {
    return (
      <div
        role="alert"
        className="text-sm"
        style={{color: 'var(--md-sys-color-error)'}}
      >
        <p>Could not verify the saved run status.</p>
        <button
          type="button"
          className={SETUP_SECONDARY_BUTTON_CLASSES}
          onClick={onRetry}
        >
          Retry status check
        </button>
      </div>
    );
  }
  if (status === 'cancelled') {
    return (
      <p role="status" className="text-sm text-cosci-muted">
        The linked research session was cancelled.
      </p>
    );
  }
  return null;
}
