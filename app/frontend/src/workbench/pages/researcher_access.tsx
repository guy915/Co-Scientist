import {type FormEvent, useState} from 'react';
import {useNavigate} from 'react-router-dom';
import {exchangeAccessCode} from '@/api/runs';
import {setAccessToken} from '@/lib/client_id';

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
    <main className="mx-auto grid min-h-full w-[min(100%_-_2rem,34rem)] content-center gap-6 py-12">
      <div>
        <h1 className="font-gsans text-4xl font-normal">Researcher access</h1>
        <p className="mt-3 text-cosci-muted">
          Co-Scientist is intended for authorized scientific researchers. Enter
          the access code supplied with your invitation.
        </p>
      </div>
      <form className="grid gap-4" onSubmit={event => void submit(event)}>
        <label className="grid gap-2">
          <span>Access code</span>
          <input
            autoComplete="one-time-code"
            className="rounded-xl border border-cosci-border bg-transparent px-4 py-3"
            onChange={event => setCode(event.currentTarget.value)}
            required
            type="password"
            value={code}
          />
        </label>
        {error ? <p role="alert">{error}</p> : null}
        <button
          className="w-fit rounded-full bg-cosci-primary px-5 py-3 text-cosci-on-primary disabled:opacity-50"
          disabled={busy || !code}
          type="submit"
        >
          {busy ? 'Verifying…' : 'Continue'}
        </button>
      </form>
    </main>
  );
}
