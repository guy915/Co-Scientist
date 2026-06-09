import { type FormEvent, useState } from "react";
import { useNavigate } from "react-router-dom";
import { createRun, type RunProfile, startRun } from "@/api/runs";

const SUGGESTED = [
  "Identify novel mechanisms of selective autophagy in aging neural tissue.",
  "Propose drug repurposing candidates for triple-negative breast cancer that act through mitochondrial biogenesis.",
  "Investigate how cold-stress reshapes glucose homeostasis via brown adipose signalling.",
];

export function NewRun() {
  const navigate = useNavigate();
  const [goal, setGoal] = useState("");
  const [profile, setProfile] = useState<RunProfile>("standard");
  const [advanced, setAdvanced] = useState(false);
  const [initialCount, setInitialCount] = useState<number | "">("");
  const [maxIters, setMaxIters] = useState<number | "">("");
  const [evolutionCount, setEvolutionCount] = useState<number | "">("");
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function onSubmit(e: FormEvent<HTMLFormElement>) {
    e.preventDefault();
    setError(null);
    if (!goal.trim()) {
      setError("Provide a research goal.");
      return;
    }
    setSubmitting(true);
    try {
      const run = await createRun({
        research_goal: goal.trim(),
        profile,
        initial_hypotheses_count: typeof initialCount === "number" ? initialCount : undefined,
        max_iterations: typeof maxIters === "number" ? maxIters : undefined,
        evolution_max_count: typeof evolutionCount === "number" ? evolutionCount : undefined,
      });
      await startRun(run.id);
      navigate(`/runs/${run.id}`);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
      setSubmitting(false);
    }
  }

  return (
    <div className="max-w-3xl mx-auto space-y-6">
      <header>
        <h1 className="text-2xl font-semibold tracking-tight">New research run</h1>
        <p className="text-sm" style={{ color: "var(--color-th-muted-fg)" }}>
          Frame a research goal. The supervisor will scope it, retrieve evidence, generate candidate
          hypotheses, debate them in an Elo tournament, and synthesize a report.
        </p>
      </header>

      <form
        onSubmit={onSubmit}
        className="space-y-5 rounded border p-5"
        style={{
          borderColor: "var(--color-th-border)",
          backgroundColor: "var(--color-th-card)",
        }}
      >
        <div className="space-y-1.5">
          <label htmlFor="goal" className="text-sm font-medium">
            Research goal
          </label>
          <textarea
            id="goal"
            value={goal}
            onChange={(e) => setGoal(e.target.value)}
            placeholder="Investigate the mechanism of glucose homeostasis under cold stress…"
            rows={4}
            className="w-full rounded border px-3 py-2 text-sm"
            style={{
              borderColor: "var(--color-th-input)",
              backgroundColor: "var(--color-th-bg)",
            }}
          />
          <div className="text-xs space-x-2" style={{ color: "var(--color-th-muted-fg)" }}>
            <span>Try:</span>
            {SUGGESTED.map((s) => (
              <button
                key={s}
                type="button"
                className="underline underline-offset-2 hover:no-underline"
                onClick={() => setGoal(s)}
              >
                {s.length > 60 ? s.slice(0, 60) + "…" : s}
              </button>
            ))}
          </div>
        </div>

        <fieldset className="space-y-2">
          <legend className="text-sm font-medium">Profile</legend>
          <div className="grid grid-cols-2 gap-3">
            <label
              className="flex items-start gap-2 rounded border p-3 cursor-pointer"
              style={{
                borderColor:
                  profile === "standard" ? "var(--color-th-primary)" : "var(--color-th-border)",
              }}
            >
              <input
                type="radio"
                name="profile"
                value="standard"
                checked={profile === "standard"}
                onChange={() => setProfile("standard")}
              />
              <span>
                <div className="font-medium">Standard</div>
                <div className="text-xs" style={{ color: "var(--color-th-muted-fg)" }}>
                  Fast scoping. 5 hypotheses, 1 iteration of evolve, 6 tournament pairs.
                </div>
              </span>
            </label>
            <label
              className="flex items-start gap-2 rounded border p-3 cursor-pointer"
              style={{
                borderColor:
                  profile === "advanced" ? "var(--color-th-primary)" : "var(--color-th-border)",
              }}
            >
              <input
                type="radio"
                name="profile"
                value="advanced"
                checked={profile === "advanced"}
                onChange={() => setProfile("advanced")}
              />
              <span>
                <div className="font-medium">Advanced</div>
                <div className="text-xs" style={{ color: "var(--color-th-muted-fg)" }}>
                  Deeper run. 8 hypotheses, 2 iterations, 12 tournament pairs, more evidence.
                </div>
              </span>
            </label>
          </div>
        </fieldset>

        <details
          className="rounded border"
          style={{ borderColor: "var(--color-th-border)" }}
          open={advanced}
          onToggle={(e) => setAdvanced((e.target as HTMLDetailsElement).open)}
        >
          <summary className="px-3 py-2 cursor-pointer text-sm font-medium">
            Configuration overrides
          </summary>
          <div className="grid grid-cols-3 gap-3 p-3 pt-0">
            <NumberField
              label="Initial hypotheses"
              value={initialCount}
              onChange={setInitialCount}
            />
            <NumberField label="Max iterations" value={maxIters} onChange={setMaxIters} />
            <NumberField
              label="Evolution top-k"
              value={evolutionCount}
              onChange={setEvolutionCount}
            />
          </div>
        </details>

        {error && (
          <div
            role="alert"
            className="text-sm rounded border p-2"
            style={{
              borderColor: "var(--color-th-destructive)",
              color: "var(--color-th-destructive)",
            }}
          >
            {error}
          </div>
        )}

        <div className="flex justify-end">
          <button
            type="submit"
            disabled={submitting}
            className="px-4 py-2 rounded text-sm font-medium disabled:opacity-50"
            style={{
              backgroundColor: "var(--color-th-primary)",
              color: "var(--color-th-primary-fg)",
            }}
          >
            {submitting ? "Starting…" : "Start run"}
          </button>
        </div>
      </form>
    </div>
  );
}

function NumberField({
  label,
  value,
  onChange,
}: {
  label: string;
  value: number | "";
  onChange: (v: number | "") => void;
}) {
  return (
    <label className="text-sm">
      <span className="block mb-1">{label}</span>
      <input
        type="number"
        value={value}
        min={1}
        max={20}
        onChange={(e) => {
          const v = e.target.value;
          onChange(v === "" ? "" : Number(v));
        }}
        className="w-full rounded border px-2 py-1.5 text-sm"
        style={{
          borderColor: "var(--color-th-input)",
          backgroundColor: "var(--color-th-bg)",
        }}
      />
    </label>
  );
}
