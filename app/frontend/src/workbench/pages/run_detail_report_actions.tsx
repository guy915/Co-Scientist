import {useCallback, useEffect, useRef, useState, type RefObject} from 'react';
import {fetchReportMarkdown} from '@/api/runs';
import {Icon} from '@/components/icon';
import {downloadTextFile} from '@/lib/download';
import {filenameSlug} from '@/lib/text';
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
