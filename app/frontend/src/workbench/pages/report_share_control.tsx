import {useState} from 'react';
import {
  createReportShare,
  listReportShares,
  type ReportShare,
  revokeReportShare,
} from '@/api/runs';
import {copyText} from '@/lib/clipboard';

/** Enables, copies, and revokes public Goal Report capability links. */
export function ReportShareControl({
  runId,
  className,
}: {
  runId: string;
  className: string;
}) {
  const [open, setOpen] = useState(false);
  const [shares, setShares] = useState<ReportShare[]>([]);
  const [link, setLink] = useState('');
  const [message, setMessage] = useState('');

  async function toggle() {
    if (!open) {
      try {
        setShares(await listReportShares(runId));
      } catch (error) {
        setMessage(error instanceof Error ? error.message : 'Sharing failed');
      }
    }
    setOpen(value => !value);
  }

  async function create() {
    try {
      const share = await createReportShare(runId);
      const publicLink = `${window.location.origin}/shared/${share.token}`;
      setShares(current => [share, ...current]);
      setLink(publicLink);
      await copyText(publicLink);
      setMessage('Public link copied');
    } catch (error) {
      setMessage(error instanceof Error ? error.message : 'Sharing failed');
    }
  }

  async function revoke(shareId: string) {
    try {
      await revokeReportShare(runId, shareId);
      setShares(current => current.filter(share => share.id !== shareId));
      setLink('');
      setMessage('Public access revoked');
    } catch (error) {
      setMessage(error instanceof Error ? error.message : 'Revocation failed');
    }
  }

  return (
    <div className="relative">
      <button type="button" className={className} onClick={() => void toggle()}>
        Share
      </button>
      {open ? (
        <section
          aria-label="Share Goal Report"
          className="absolute top-full right-0 z-40 mt-2 grid w-72 gap-3 rounded-xl border border-cosci-border bg-cosci-bg p-4 text-sm"
        >
          <strong>Public sharing</strong>
          <p className="text-cosci-muted">
            Anyone with an active capability link can read this Goal Report.
          </p>
          <button
            type="button"
            className={className}
            onClick={() => void create()}
          >
            Create and copy link
          </button>
          {link ? (
            <input readOnly value={link} aria-label="Public link" />
          ) : null}
          {shares.map(share => (
            <button
              key={share.id}
              type="button"
              className={className}
              onClick={() => void revoke(share.id)}
            >
              Revoke public link
            </button>
          ))}
          {message ? <p role="status">{message}</p> : null}
        </section>
      ) : null}
    </div>
  );
}
