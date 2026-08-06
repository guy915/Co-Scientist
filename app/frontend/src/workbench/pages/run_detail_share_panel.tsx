import {useCallback, useEffect, useState} from 'react';
import {
  createReportShare,
  listReportShares,
  type ReportShare,
  revokeReportShare,
} from '@/api/runs';
import {Icon} from '@/components/icon';
import {copyText} from '@/lib/clipboard';
import {useResetTimer} from '../hooks/use_reset_timer';
import {tooltipClassNames} from '../tooltip';

// The panel floats off the titlebar's share button, reusing the shell's
// popover chrome (positioned ancestor is the actions row). Width overrides
// the .ucs-popover default; under 720px it hugs the viewport edge instead.
const SHARE_POPOVER_CLASSES =
  'ucs-popover right-0 top-[calc(100%+0.55rem)] gap-3 ' +
  '!w-[min(22rem,calc(100vw-2rem))] max-[720px]:right-[-0.5rem]';

const SHARE_TITLE_CLASSES = 'font-gsans m-0 text-[16.8px] font-medium';

const SHARE_DESCRIPTION_CLASSES = 'm-0 text-sm text-cosci-muted';

const SHARE_CREATE_BUTTON_CLASSES =
  'inline-flex min-h-[2.25rem] cursor-pointer items-center justify-center ' +
  'rounded-full border border-cosci-btn-outline-border bg-transparent px-4 ' +
  'font-[inherit] text-sm font-medium text-cosci-btn-outline-fg ' +
  'hover:bg-cosci-btn-outline-hover-bg ' +
  'focus-visible:bg-cosci-btn-outline-hover-bg disabled:cursor-default ' +
  'disabled:border-cosci-btn-disabled-border ' +
  'disabled:bg-cosci-btn-disabled-bg disabled:text-cosci-btn-disabled-fg';

const SHARE_LIST_CLASSES = 'm-0 grid list-none gap-2 p-0';

const SHARE_ROW_CLASSES =
  'flex items-center justify-between gap-2 rounded-md border ' +
  'border-cosci-border px-3 py-2';

const SHARE_ROW_TEXT_CLASSES = 'grid min-w-0 gap-[0.1rem]';

const SHARE_ROW_LABEL_CLASSES = 'truncate text-sm';

const SHARE_ROW_META_CLASSES = 'text-[0.78rem] text-cosci-muted';

const SHARE_EMPTY_CLASSES =
  'm-0 rounded-md border border-cosci-border px-3 py-2 text-sm ' +
  'text-cosci-muted';

const SHARE_ERROR_CLASSES = 'm-0 text-sm text-th-destructive';

const SHARE_URL_ROW_CLASSES =
  'flex items-center gap-2 rounded-md bg-cosci-panel px-3 py-2';

const SHARE_URL_TEXT_CLASSES = 'min-w-0 flex-1 truncate text-sm';

const SHARE_COPY_BUTTON_CLASSES =
  'shrink-0 cursor-pointer rounded-full border border-cosci-btn-outline-border ' +
  'bg-transparent px-3 py-1 font-[inherit] text-sm font-medium ' +
  'text-cosci-btn-outline-fg hover:bg-cosci-btn-outline-hover-bg ' +
  'focus-visible:bg-cosci-btn-outline-hover-bg';

const SHARE_REVOKE_BUTTON_CLASSES =
  'grid h-8 w-8 shrink-0 place-items-center rounded-full text-cosci-muted ' +
  'hover:bg-cosci-hover disabled:cursor-default disabled:opacity-60';

/** How long the Copy button reads "Copied" before returning to "Copy". */
const COPIED_RESET_MS = 2_000;

/**
 * The public URL of a shared Goal Report. Shares are served by this same
 * frontend (the `/shared/:token` route fetches the API), so the link is
 * built from the current origin rather than the API base URL.
 */
export function sharedReportUrl(token: string): string {
  return `${window.location.origin}/shared/${token}`;
}

// Error text for a failed action, normalized from whatever was thrown.
function messageOf(err: unknown): string {
  return err instanceof Error ? err.message : String(err);
}

// A share row's creation timestamp as a local date/time phrase.
function formatShareDate(createdAt: number): string {
  return new Date(createdAt * 1000).toLocaleString();
}

/**
 * Management panel for a completed run's public Goal Report links: creates
 * links (showing the one-time URL with a copy action), lists active links,
 * and revokes them in place. The panel's parent owns open/dismissal.
 */
export function ShareReportPanel({runId}: {runId: string}) {
  const [shares, setShares] = useState<ReportShare[] | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [creating, setCreating] = useState(false);
  const [actionError, setActionError] = useState<string | null>(null);
  // Only a freshly created share carries its token (the list endpoint never
  // discloses tokens), so the copyable URL belongs to this one creation.
  const [freshShare, setFreshShare] = useState<ReportShare | null>(null);
  const [revokingId, setRevokingId] = useState<string | null>(null);

  const loadShares = useCallback(async () => {
    setLoadError(null);
    try {
      setShares(await listReportShares(runId));
    } catch (err) {
      setLoadError(messageOf(err));
    }
  }, [runId]);

  useEffect(() => {
    void loadShares();
  }, [loadShares]);

  return (
    <div className={SHARE_POPOVER_CLASSES} role="status">
      <h3 className={SHARE_TITLE_CLASSES}>Share report</h3>
      <p className={SHARE_DESCRIPTION_CLASSES}>
        Anyone with a link can view this goal report. Revoking a link removes
        its access immediately.
      </p>
      {actionError && (
        <p role="alert" className={SHARE_ERROR_CLASSES}>
          {actionError}
        </p>
      )}
      {freshShare?.token && (
        <CreatedLinkRow url={sharedReportUrl(freshShare.token)} />
      )}
      <button
        type="button"
        className={SHARE_CREATE_BUTTON_CLASSES}
        disabled={creating}
        onClick={() =>
          void createShare(runId, {
            setCreating,
            setActionError,
            setFreshShare,
            setShares,
          })
        }
      >
        {creating ? 'Creating link…' : 'Create public link'}
      </button>
      <ShareList
        shares={shares}
        loadError={loadError}
        revokingId={revokingId}
        onRetry={() => void loadShares()}
        onRevoke={share =>
          void revokeShare(runId, share, {
            setRevokingId,
            setActionError,
            setFreshShare,
            setShares,
          })
        }
      />
    </div>
  );
}

// State setters the create/revoke handlers update, bundled so the handlers
// stay within the argument ceiling. The fresh-share and list setters take
// updaters because both handlers must decide against the current value;
// only revoke touches the revoking-row marker.
interface ShareMutationSetters {
  setCreating?: (value: boolean) => void;
  setRevokingId?: (value: string | null) => void;
  setActionError: (value: string | null) => void;
  setFreshShare: (
    update: (prev: ReportShare | null) => ReportShare | null,
  ) => void;
  setShares: (update: (prev: ReportShare[] | null) => ReportShare[]) => void;
}

// Creates one public link and folds the server's confirmation into the panel
// state: the list gains the row and, while the response carries the one-time
// token, the copyable URL row appears.
async function createShare(
  runId: string,
  setters: ShareMutationSetters,
): Promise<void> {
  setters.setCreating?.(true);
  setters.setActionError(null);
  try {
    const share = await createReportShare(runId);
    setters.setFreshShare(() => share);
    setters.setShares(prev => [share, ...(prev ?? [])]);
  } catch (err) {
    setters.setActionError(messageOf(err));
  } finally {
    setters.setCreating?.(false);
  }
}

// Revokes one link and drops it from the panel in place; a revoked fresh
// link also takes its copyable URL with it (revoking any other link leaves
// the fresh one's URL alone).
async function revokeShare(
  runId: string,
  share: ReportShare,
  setters: ShareMutationSetters,
): Promise<void> {
  setters.setRevokingId?.(share.id);
  setters.setActionError(null);
  try {
    await revokeReportShare(runId, share.id);
    setters.setShares(prev =>
      (prev ?? []).filter(item => item.id !== share.id),
    );
    setters.setFreshShare(prev => (prev?.id === share.id ? null : prev));
  } catch (err) {
    setters.setActionError(messageOf(err));
  } finally {
    setters.setRevokingId?.(null);
  }
}

/**
 * The just-created link's public URL with a copy affordance. The token is
 * disclosed only by the create response, so this row exists only while the
 * creating session still holds it.
 */
function CreatedLinkRow({url}: {url: string}) {
  const [copied, setCopied] = useState(false);
  const timer = useResetTimer();

  async function onCopy() {
    await copyText(url);
    setCopied(true);
    timer.schedule(() => setCopied(false), COPIED_RESET_MS);
  }

  return (
    <div className={SHARE_URL_ROW_CLASSES}>
      <span className={SHARE_URL_TEXT_CLASSES} title={url}>
        {url}
      </span>
      <button
        type="button"
        className={SHARE_COPY_BUTTON_CLASSES}
        aria-label="Copy link"
        onClick={() => void onCopy()}
      >
        {copied ? 'Copied' : 'Copy'}
      </button>
    </div>
  );
}

// The panel's share listing in its four states: loading, failed (with a
// retry), empty, and the row list.
function ShareList({
  shares,
  loadError,
  revokingId,
  onRetry,
  onRevoke,
}: {
  shares: ReportShare[] | null;
  loadError: string | null;
  revokingId: string | null;
  onRetry: () => void;
  onRevoke: (share: ReportShare) => void;
}) {
  if (loadError) {
    return (
      <p className={SHARE_EMPTY_CLASSES}>
        Could not load share links ({loadError}).{' '}
        <button
          type="button"
          className="cursor-pointer rounded-full px-2 py-1 text-sm font-medium text-cosci-btn-outline-fg hover:bg-cosci-btn-outline-hover-bg"
          onClick={onRetry}
        >
          Try again
        </button>
      </p>
    );
  }
  if (shares === null) {
    return <div className="wb-skeleton h-9 w-full" aria-busy="true" />;
  }
  if (!shares.length) {
    return (
      <p className={SHARE_EMPTY_CLASSES}>
        No public links yet. Create one to share this report.
      </p>
    );
  }
  return (
    <ul className={SHARE_LIST_CLASSES} aria-label="Active public links">
      {shares.map(share => (
        <li key={share.id} className={SHARE_ROW_CLASSES}>
          <span className={SHARE_ROW_TEXT_CLASSES}>
            <span className={SHARE_ROW_LABEL_CLASSES}>Public link</span>
            <span className={SHARE_ROW_META_CLASSES}>
              Created {formatShareDate(share.created_at)}
            </span>
          </span>
          <button
            type="button"
            className={tooltipClassNames({
              className: SHARE_REVOKE_BUTTON_CLASSES,
              placement: 'left',
            })}
            aria-label="Revoke link"
            data-tooltip="Revoke link"
            disabled={revokingId === share.id}
            onClick={() => onRevoke(share)}
          >
            <Icon aria-hidden="true" name="close" />
          </button>
        </li>
      ))}
    </ul>
  );
}
