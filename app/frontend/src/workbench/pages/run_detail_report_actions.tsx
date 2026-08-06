import {useCallback, useEffect, useRef, useState, type RefObject} from 'react';
import {useNavigate} from 'react-router-dom';
import {deleteRun, fetchReportMarkdown} from '@/api/runs';
import {Icon} from '@/components/icon';
import {downloadTextFile} from '@/lib/download';
import {filenameSlug} from '@/lib/text';
import {RUNS_CHANGED_EVENT} from '../dom_events';
import {useToast} from '../hooks/use_toast';
import {tooltipClassNames} from '../tooltip';
import {RunToast} from './run_detail_shell';
import {ShareReportPanel} from './run_detail_share_panel';

// Titlebar icon buttons follow the back arrow's quiet treatment: circular,
// muted, neutral hover wash (see DESIGN.md's icon-button rules).
const ACTION_BUTTON_CLASSES =
  'grid h-10 w-10 shrink-0 cursor-pointer place-items-center rounded-full ' +
  'border-0 bg-transparent text-cosci-muted hover:bg-cosci-hover ' +
  'disabled:cursor-default disabled:opacity-60';

// The actions row is the share popover's positioned ancestor.
const ACTIONS_ROW_CLASSES = 'relative flex shrink-0 items-center gap-1';

/**
 * Closes an open transient panel on a pointerdown outside `containerRef` or
 * on Escape. The listener exists only while the panel is open, matching the
 * shell's own popover dismissal (layout_hooks.useDismissPanelOnOutsideClick).
 */
function useDismissOnOutside(
  open: boolean,
  containerRef: RefObject<HTMLDivElement | null>,
  onClose: () => void,
) {
  useEffect(() => {
    if (!open) return;
    function onPointerDown(event: PointerEvent) {
      if (!containerRef.current?.contains(event.target as Node)) onClose();
    }
    function onKeyDown(event: KeyboardEvent) {
      if (event.key === 'Escape') onClose();
    }
    document.addEventListener('pointerdown', onPointerDown);
    document.addEventListener('keydown', onKeyDown);
    return () => {
      document.removeEventListener('pointerdown', onPointerDown);
      document.removeEventListener('keydown', onKeyDown);
    };
  }, [open, containerRef, onClose]);
}

/**
 * Report-level actions for a completed run's titlebar: downloading the Goal
 * Report as Markdown and managing public share links. Rendered only when the
 * run is completed and its report exists — both actions are properties of a
 * finished report (the share endpoint 409s and the download 404s otherwise).
 */
export function ReportActions({
  runId,
  runTitle,
}: {
  runId: string;
  runTitle: string;
}) {
  const [shareOpen, setShareOpen] = useState(false);
  const [downloading, setDownloading] = useState(false);
  const {toast, setToast} = useToast();
  const containerRef = useRef<HTMLDivElement>(null);

  const closeSharePanel = useCallback(() => setShareOpen(false), []);
  useDismissOnOutside(shareOpen, containerRef, closeSharePanel);

  const onDownload = useCallback(() => {
    void downloadReport(runId, runTitle, {
      setDownloading,
      setToast: message => setToast(message),
    });
  }, [runId, runTitle, setToast]);

  return (
    <div className={ACTIONS_ROW_CLASSES} ref={containerRef}>
      <button
        type="button"
        className={tooltipClassNames({
          className: ACTION_BUTTON_CLASSES,
          placement: 'bottom',
        })}
        aria-label="Download report"
        data-tooltip="Download report (Markdown)"
        disabled={downloading}
        onClick={onDownload}
      >
        <Icon aria-hidden="true" name="download" />
      </button>
      <button
        type="button"
        className={tooltipClassNames({
          className: ACTION_BUTTON_CLASSES,
          placement: 'bottom',
        })}
        aria-label="Share report"
        data-tooltip="Share report"
        aria-expanded={shareOpen}
        onClick={() => setShareOpen(open => !open)}
      >
        <Icon aria-hidden="true" name="share" />
      </button>
      {shareOpen && <ShareReportPanel runId={runId} />}
      {toast && <RunToast message={toast.message} />}
    </div>
  );
}

// The confirm popover floats off the delete button, matching the share
// popover's positioning and width behavior.
const DELETE_POPOVER_CLASSES =
  'ucs-popover right-0 top-[calc(100%+0.55rem)] gap-3 ' +
  '!w-[min(20rem,calc(100vw-2rem))] max-[720px]:right-[-0.5rem]';

const DELETE_CONFIRM_BUTTON_CLASSES =
  'inline-flex min-h-[2.25rem] cursor-pointer items-center justify-center ' +
  'rounded-full border-0 bg-th-destructive px-4 font-[inherit] text-sm ' +
  'font-medium text-th-destructive-fg hover:opacity-90 ' +
  'disabled:cursor-default disabled:opacity-60';

const DELETE_CANCEL_BUTTON_CLASSES =
  'inline-flex min-h-[2.25rem] cursor-pointer items-center justify-center ' +
  'rounded-full border border-cosci-btn-outline-border bg-transparent px-4 ' +
  'font-[inherit] text-sm font-medium text-cosci-btn-outline-fg ' +
  'hover:bg-cosci-btn-outline-hover-bg disabled:cursor-default ' +
  'disabled:opacity-60';

// Normalizes a thrown value into the message shown to the person deleting
// the run.
function deleteErrorMessage(err: unknown): string {
  return err instanceof Error ? err.message : String(err);
}

/**
 * Permanent-delete affordance for a settled run (N3): a titlebar icon
 * button that opens an inline confirm popover before calling the DELETE
 * endpoint. Rendered only for a terminal run (see `reportActionsFor`) --
 * the API 409s on an active one, so the button never gets that far in
 * practice, but the confirm copy still names the run's report and ideas
 * so the action reads as irreversible before it is taken.
 */
export function DeleteRunButton({runId}: {runId: string}) {
  const [confirmOpen, setConfirmOpen] = useState(false);
  const [deleting, setDeleting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const containerRef = useRef<HTMLDivElement>(null);
  const navigate = useNavigate();

  const closeConfirm = useCallback(() => setConfirmOpen(false), []);
  useDismissOnOutside(confirmOpen, containerRef, closeConfirm);

  async function onConfirmDelete(): Promise<void> {
    setDeleting(true);
    setError(null);
    try {
      await deleteRun(runId);
      window.dispatchEvent(new Event(RUNS_CHANGED_EVENT));
      void navigate('/');
    } catch (err) {
      setError(deleteErrorMessage(err));
      setDeleting(false);
    }
  }

  return (
    <div className={ACTIONS_ROW_CLASSES} ref={containerRef}>
      <button
        type="button"
        className={tooltipClassNames({
          className: ACTION_BUTTON_CLASSES,
          placement: 'bottom',
        })}
        aria-label="Delete run"
        data-tooltip="Delete run"
        aria-expanded={confirmOpen}
        onClick={() => setConfirmOpen(open => !open)}
      >
        <Icon aria-hidden="true" name="delete_forever" />
      </button>
      {confirmOpen && (
        <div
          className={DELETE_POPOVER_CLASSES}
          role="dialog"
          aria-label="Confirm delete run"
        >
          <p className="m-0 text-sm">
            Permanently delete this run, its report, ideas, and evidence? This
            cannot be undone.
          </p>
          {error && (
            <p role="alert" className="m-0 text-sm text-th-destructive">
              {error}
            </p>
          )}
          <div className="flex justify-end gap-2">
            <button
              type="button"
              className={DELETE_CANCEL_BUTTON_CLASSES}
              disabled={deleting}
              onClick={closeConfirm}
            >
              Cancel
            </button>
            <button
              type="button"
              className={DELETE_CONFIRM_BUTTON_CLASSES}
              disabled={deleting}
              onClick={() => void onConfirmDelete()}
            >
              {deleting ? 'Deleting…' : 'Delete permanently'}
            </button>
          </div>
        </div>
      )}
    </div>
  );
}

/**
 * Downloads the Goal Report Markdown through the authenticated API (never a
 * direct URL — see fetchReportMarkdown) and hands it to the browser as a
 * file named after the run title, falling back to the run id.
 */
async function downloadReport(
  runId: string,
  runTitle: string,
  deps: {
    setDownloading: (value: boolean) => void;
    setToast: (message: string) => void;
  },
): Promise<void> {
  deps.setDownloading(true);
  try {
    const markdown = await fetchReportMarkdown(runId);
    if (markdown === null) {
      deps.setToast('The report is not available for download yet.');
      return;
    }
    const filename = `${filenameSlug(runTitle) || runId}.md`;
    downloadTextFile(filename, markdown);
  } catch (err) {
    deps.setToast(
      `Download failed: ${err instanceof Error ? err.message : String(err)}`,
    );
  } finally {
    deps.setDownloading(false);
  }
}
