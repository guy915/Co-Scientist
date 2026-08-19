import {useRef, useState} from 'react';
import {useNavigate} from 'react-router-dom';
import {createRun, startRun} from '@/api/runs';
import {Icon} from '@/components/icon';
import {useAudience} from '../audience_context';
import {useBackgroundInert} from '../hooks/use_background_inert';
import {useEscapeKey} from '../hooks/use_escape_key';
import {useFocusTrap} from '../hooks/use_focus_trap';
import {useRestoreFocusOnClose} from '../hooks/use_restore_focus_on_close';
import {SETUP_PRIMARY_BUTTON_CLASSES} from '../pages/chat_setup_classes';
import {
  BudgetFields,
  type DraftChange,
  ObjectiveFields,
  ProgramFields,
} from './discovery_dialog_fields';
import {
  type DiscoveryDraft,
  draftProblems,
  draftToSpec,
  EMPTY_DRAFT,
} from './discovery_draft';

// The draft, its per-field setter, and what is currently wrong with it.
function useDiscoveryDraft() {
  const [draft, setDraft] = useState<DiscoveryDraft>(EMPTY_DRAFT);
  const onChange: DraftChange = (key, value) =>
    setDraft(current => ({...current, [key]: value}));
  return {draft, onChange};
}

function DialogHeader({onClose}: {onClose: () => void}) {
  return (
    <header className="ucs-settings-dialog-header">
      <h2 className="ucs-settings-dialog-title">Evolve a program</h2>
      <button
        type="button"
        className="ucs-settings-dialog-close"
        aria-label="Close"
        onClick={onClose}
      >
        <Icon aria-hidden="true" name="close" />
      </button>
    </header>
  );
}

// The problems list, or the start button. Shown only after a failed
// attempt: listing everything missing on an untouched form reads as
// error rather than as guidance.
function DialogFooter({
  problems,
  busy,
  onStart,
}: {
  problems: string[];
  busy: boolean;
  onStart: () => void;
}) {
  return (
    <footer className="mt-4 flex items-center justify-between gap-4">
      <ul className="m-0 list-none p-0 text-sm text-th-error" role="alert">
        {problems.map(problem => (
          <li key={problem}>{problem}</li>
        ))}
      </ul>
      <button
        type="button"
        className={`${SETUP_PRIMARY_BUTTON_CLASSES} shrink-0`}
        onClick={onStart}
        disabled={busy}
      >
        {busy ? 'Starting...' : 'Start the search'}
      </button>
    </footer>
  );
}

/**
 * The dialog that starts a computational-discovery run.
 *
 * The only surface in the product that creates one: without it the whole
 * discovery path -- sandbox, proposal agent, archive, report -- is
 * reachable from the API and the CLI alone.
 *
 * It sends the run and starts it in one action rather than leaving a
 * draft behind, because a discovery run has no interview step to return
 * to: a spec is either startable or it is not, and the form already
 * said which.
 *
 * @param props The close callback.
 */
export function DiscoveryDialog({onClose}: {onClose: () => void}) {
  const {draft, onChange} = useDiscoveryDraft();
  const [problems, setProblems] = useState<string[]>([]);
  const [busy, setBusy] = useState(false);
  const rootRef = useRef<HTMLDivElement>(null);
  const navigate = useNavigate();
  const {audience} = useAudience();

  useRestoreFocusOnClose();
  useFocusTrap(rootRef);
  useBackgroundInert(rootRef);
  useEscapeKey(onClose, true);

  async function onStart() {
    const found = draftProblems(draft);
    setProblems(found);
    if (found.length > 0) return;
    setBusy(true);
    try {
      const run = await createRun({
        research_goal: draft.goal.trim(),
        discovery: draftToSpec(draft),
        ...(audience ? {audience} : {}),
      });
      await startRun(run.id);
      void navigate(`/runs/${run.id}/variants`);
      onClose();
    } catch (error) {
      setProblems([`Could not start the run: ${String(error)}`]);
      setBusy(false);
    }
  }

  return (
    <div className="ucs-settings-dialog-root" ref={rootRef}>
      <div
        className="ucs-settings-dialog-scrim"
        aria-hidden="true"
        onClick={onClose}
      />
      <div
        className="ucs-settings-dialog"
        role="dialog"
        aria-modal="true"
        aria-label="Evolve a program"
      >
        <DialogHeader onClose={onClose} />
        <div className="ucs-settings-dialog-panel">
          <section className="ucs-settings-card">
            <h3 className="ucs-settings-card-title">What are you doing?</h3>
            <p className="ucs-settings-card-copy">
              One line, the way you would describe it to a colleague. It titles
              the run and is what the model is told it is working on.
            </p>
            <input
              className="ucs-settings-field-input"
              value={draft.goal}
              placeholder="Find a faster prime sieve"
              onChange={event => onChange('goal', event.target.value)}
            />
          </section>
          <ObjectiveFields draft={draft} onChange={onChange} />
          <ProgramFields draft={draft} onChange={onChange} />
          <BudgetFields draft={draft} onChange={onChange} />
        </div>
        <DialogFooter
          problems={problems}
          busy={busy}
          onStart={() => void onStart()}
        />
      </div>
    </div>
  );
}
