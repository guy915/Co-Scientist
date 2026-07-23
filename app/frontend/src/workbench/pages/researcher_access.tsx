import {type FormEvent, useState} from 'react';
import {useNavigate} from 'react-router-dom';
import {exchangeAccessCode} from '@/api/runs';
import {setAccessToken} from '@/lib/client_id';

const CODE_INPUT_CLASSES =
  'rounded-xl border border-cosci-border bg-transparent px-4 py-3';
const SUBMIT_BUTTON_CLASSES =
  'w-fit rounded-full bg-cosci-primary px-5 py-3 text-cosci-on-primary ' +
  'disabled:opacity-50';
const PAGE_CLASSES =
  'mx-auto grid min-h-full w-[min(100%_-_2rem,34rem)] content-center gap-6 ' +
  'py-12';

// The static heading/blurb above the access-code form.
function AccessIntro() {
  return (
    <div>
      <h1 className="font-gsans text-4xl font-normal">Researcher access</h1>
      <p className="mt-3 text-cosci-muted">
        Co-Scientist is intended for authorized scientific researchers. Enter
        the access code supplied with your invitation.
      </p>
    </div>
  );
}

interface AccessFormProps {
  code: string;
  error: string | null;
  busy: boolean;
  onCodeChange: (value: string) => void;
  onSubmit: (event: FormEvent<HTMLFormElement>) => Promise<void>;
}

// The access-code field, error message, and submit button. All state lives
// in ResearcherAccessPage; this only renders what it is handed.
function AccessForm({
  code,
  error,
  busy,
  onCodeChange,
  onSubmit,
}: AccessFormProps) {
  return (
    <form className="grid gap-4" onSubmit={event => void onSubmit(event)}>
      <label className="grid gap-2">
        <span>Access code</span>
        <input
          autoComplete="one-time-code"
          className={CODE_INPUT_CLASSES}
          onChange={event => onCodeChange(event.currentTarget.value)}
          required
          type="password"
          value={code}
        />
      </label>
      {error ? <p role="alert">{error}</p> : null}
      <button
        className={SUBMIT_BUTTON_CLASSES}
        disabled={busy || !code}
        type="submit"
      >
        {busy ? 'Verifying…' : 'Continue'}
      </button>
    </form>
  );
}

/** Restricted researcher-access exchange for the private workbench. */
export function ResearcherAccessPage() {
  const navigate = useNavigate();
  const [code, setCode] = useState('');
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setBusy(true);
    setError(null);
    try {
      const session = await exchangeAccessCode(code);
      setAccessToken(session.access_token);
      void navigate('/', {replace: true});
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : 'Access denied');
    } finally {
      setBusy(false);
    }
  }

  return (
    <main className={PAGE_CLASSES}>
      <AccessIntro />
      <AccessForm
        code={code}
        error={error}
        busy={busy}
        onCodeChange={setCode}
        onSubmit={submit}
      />
    </main>
  );
}
