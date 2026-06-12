/**
 * Copyright 2026 The Co-Scientist Authors
 *
 * Licensed under the Apache License, Version 2.0 (the "License");
 * you may not use this file except in compliance with the License.
 * You may obtain a copy of the License at
 *
 *     http://www.apache.org/licenses/LICENSE-2.0
 *
 * Unless required by applicable law or agreed to in writing, software
 * distributed under the License is distributed on an "AS IS" BASIS,
 * WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
 * See the License for the specific language governing permissions and
 * limitations under the License.
 */

import "@material/web/button/text-button.js";
import { useMemo } from "react";
import type { CitationRow, Evidence, Hypothesis, Review } from "@/api/runs";
import { MdDialog } from "@/md3/MdDialog";

export function IdeaModal({
  hypothesis,
  allHypotheses,
  reviews,
  citations,
  evidence,
  onClose,
}: {
  hypothesis: Hypothesis;
  allHypotheses: Hypothesis[];
  reviews: Review[];
  citations: CitationRow[];
  evidence: Evidence[];
  onClose: () => void;
}) {
  const evidenceById = useMemo(
    () => Object.fromEntries(evidence.map((e) => [e.id, e])),
    [evidence]
  );
  const parent = hypothesis.parent_id
    ? (allHypotheses.find((h) => h.id === hypothesis.parent_id) ?? null)
    : null;
  const children = allHypotheses.filter((h) => h.parent_id === hypothesis.id);

  return (
    <MdDialog
      open={true}
      onClose={onClose}
      headline={
        <div className="space-y-1">
          <div className="text-lg font-semibold leading-snug">{hypothesis.title}</div>
          <div
            className="flex flex-wrap gap-2 text-xs"
            style={{ color: "var(--md-sys-color-on-surface-variant)" }}
          >
            <span
              className="px-1.5 py-0.5 rounded font-mono"
              style={{ backgroundColor: "var(--md-sys-color-surface-variant)" }}
            >
              Elo {hypothesis.elo_rating}
            </span>
            <span>
              gen {hypothesis.generation} · {hypothesis.created_by_agent}
            </span>
            {hypothesis.win_count + hypothesis.loss_count > 0 && (
              <span>
                {hypothesis.win_count}W · {hypothesis.loss_count}L
              </span>
            )}
          </div>
        </div>
      }
      actions={<md-text-button onclick={onClose as EventListener}>Close</md-text-button>}
    >
      <div className="space-y-4 text-sm max-w-2xl">
        <section>
          <h3 className="font-medium mb-1">Statement</h3>
          <p>{hypothesis.statement}</p>
        </section>

        {hypothesis.mechanism && (
          <section>
            <h3 className="font-medium mb-1">Mechanism</h3>
            <p>{hypothesis.mechanism}</p>
          </section>
        )}

        {hypothesis.expected_effect && (
          <section>
            <h3 className="font-medium mb-1">Expected effect</h3>
            <p>{hypothesis.expected_effect}</p>
          </section>
        )}

        {hypothesis.experimental_context && (
          <section>
            <h3 className="font-medium mb-1">Experimental design</h3>
            <p>{hypothesis.experimental_context}</p>
          </section>
        )}

        {(parent || children.length > 0) && (
          <section>
            <h3 className="font-medium mb-1">Lineage</h3>
            <ul
              className="text-xs space-y-1"
              style={{ color: "var(--md-sys-color-on-surface-variant)" }}
            >
              {parent && <li>↑ Parent: {parent.title}</li>}
              {children.map((c) => (
                <li key={c.id}>↓ Child: {c.title}</li>
              ))}
            </ul>
          </section>
        )}

        {reviews.length > 0 && (
          <section>
            <h3 className="font-medium mb-1">Reviews &amp; critique</h3>
            <ul className="space-y-2">
              {reviews.map((r) => (
                <li
                  key={r.id}
                  className="rounded border p-2"
                  style={{ borderColor: "var(--md-sys-color-outline-variant)" }}
                >
                  <div
                    className="text-xs uppercase tracking-wide"
                    style={{ color: "var(--md-sys-color-on-surface-variant)" }}
                  >
                    {r.reviewer_agent}
                  </div>
                  <div className="font-medium">{r.summary}</div>
                  <p
                    className="text-xs mt-0.5"
                    style={{ color: "var(--md-sys-color-on-surface-variant)" }}
                  >
                    {r.critique}
                  </p>
                </li>
              ))}
            </ul>
          </section>
        )}

        {citations.length > 0 && (
          <section>
            <h3 className="font-medium mb-1">Citations</h3>
            <ul className="space-y-1.5">
              {citations.map((c) => {
                const ev = evidenceById[c.evidence_id];
                return (
                  <li key={c.id} className="text-xs flex items-start gap-2">
                    <span
                      className="px-1.5 py-0.5 rounded text-[10px] uppercase shrink-0"
                      style={{
                        backgroundColor:
                          c.state === "verified"
                            ? "var(--md-sys-color-primary-container)"
                            : c.state === "partial"
                              ? "var(--md-sys-color-tertiary-container)"
                              : c.state === "unsupported"
                                ? "var(--md-sys-color-error-container)"
                                : "var(--md-sys-color-surface-variant)",
                        color:
                          c.state === "verified"
                            ? "var(--md-sys-color-on-primary-container)"
                            : c.state === "partial"
                              ? "var(--md-sys-color-on-tertiary-container)"
                              : c.state === "unsupported"
                                ? "var(--md-sys-color-on-error-container)"
                                : "var(--md-sys-color-on-surface-variant)",
                      }}
                    >
                      {c.state}
                    </span>
                    <span>
                      {ev ? ev.title : c.evidence_id} — {c.claim}
                    </span>
                  </li>
                );
              })}
            </ul>
          </section>
        )}
      </div>
    </MdDialog>
  );
}
