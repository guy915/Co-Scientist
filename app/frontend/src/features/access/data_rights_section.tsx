import {useState} from 'react';
import {Link} from 'react-router-dom';
import {deleteMyData, exportMyData} from '@/shared/api/data_rights';
import {clearBrowserData} from '@/shared/lib/browser_data';
import {errorMessage} from '@/shared/lib/errors';
import {Button, TextField, cardClasses} from '@/shared/ui';

export function DataRightsSection({onOpenLegal}: {onOpenLegal: () => void}) {
  const [confirmation, setConfirmation] = useState('');
  const [busy, setBusy] = useState<'export' | 'delete' | null>(null);
  const [message, setMessage] = useState('');

  async function onExport() {
    setBusy('export');
    setMessage('');
    try {
      const blob = await exportMyData();
      const url = URL.createObjectURL(blob);
      const link = document.createElement('a');
      link.href = url;
      link.download = 'open-coscientist-data.zip';
      document.body.appendChild(link);
      link.click();
      link.remove();
      window.setTimeout(() => URL.revokeObjectURL(url), 60_000);
      setMessage(
        'Your JSON ZIP download is ready. Keep it private: it contains your research and browser identity.',
      );
    } catch (error) {
      setMessage(errorMessage(error));
    } finally {
      setBusy(null);
    }
  }

  async function onDelete() {
    setBusy('delete');
    setMessage('');
    try {
      const result = await deleteMyData();
      if (!result.deleted)
        throw new Error(
          'Deletion was not confirmed. Your browser settings have been kept.',
        );
      if (clearBrowserData()) {
        window.location.assign('/');
      } else {
        setMessage(
          'Server data was deleted. Browser storage could not be cleared; clear this site’s data in browser settings, then reload.',
        );
      }
    } catch (error) {
      setMessage(errorMessage(error));
    } finally {
      setBusy(null);
    }
  }

  return (
    <section
      className={cardClasses({tone: 'raised', size: 'panel'})}
      aria-labelledby="data-rights-title"
    >
      <h3
        id="data-rights-title"
        className="m-0 mb-4 font-gsans text-[1.05rem] font-medium"
      >
        Your data
      </h3>
      <p>
        Your saved work belongs to this browser’s private identity. These
        controls apply to its runs, chats, documents and settings. Export before
        deleting if you need a copy.
      </p>
      <Button onClick={onExport} disabled={busy !== null}>
        {busy === 'export' ? 'Preparing export…' : 'Export my data'}
      </Button>
      <p>
        The ZIP contains JSON records and extracted document text. It excludes
        provider keys and original upload bytes, which are not stored.
      </p>
      <h4>Delete this browser’s data</h4>
      <p>
        Deletion removes saved research, chats, documents, feedback and stored
        BYOK credentials, and stops background work. Browser keys and
        preferences are cleared before the workspace reloads. This cannot be
        undone.
      </p>
      <p>
        Older backups expire under the{' '}
        <Link to="/privacy" onClick={onOpenLegal}>
          privacy notice
        </Link>
        . We cannot recall requests already sent to model or source providers.
      </p>
      <label htmlFor="erase-confirmation">Type DELETE to confirm</label>
      <TextField
        id="erase-confirmation"
        value={confirmation}
        onChange={event => setConfirmation(event.target.value)}
        disabled={busy !== null}
        autoComplete="off"
      />
      <div className="mt-4">
        <Button
          variant="outlined"
          onClick={onDelete}
          disabled={confirmation !== 'DELETE' || busy !== null}
        >
          {busy === 'delete' ? 'Deleting…' : 'Delete all my data'}
        </Button>
      </div>
      {message && (
        <p role="status" className="mt-4 text-cosci-ink">
          {message}
        </p>
      )}
      <footer className="mt-6 flex flex-wrap gap-5">
        <Link to="/privacy" onClick={onOpenLegal}>
          Privacy notice
        </Link>
        <Link to="/terms" onClick={onOpenLegal}>
          Terms of use
        </Link>
      </footer>
    </section>
  );
}
