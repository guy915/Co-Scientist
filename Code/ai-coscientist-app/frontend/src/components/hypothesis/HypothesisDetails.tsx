import React from "react";
import type { CitationSource } from "@/types/hypothesis";
import { CitedText } from "@/components/hypothesis/CitedText";
import { CitationList } from "@/components/hypothesis/CitationList";
import { DomainCustomFields } from "@/components/hypothesis/DomainCustomFields";

interface HypothesisDetailsProps {
  hypothesis: {
    text: string;
    explanation?: string;
    literature_grounding?: string;
    experiment?: string;
    citation_map?: Record<string, CitationSource>;
    [key: string]: unknown;
  };
  compact?: boolean;
  showAllFields?: boolean;
  /** UI location context — controls which customFields render and which hardcoded sections show. */
  location?: string;
  /**
   * Whether to render DomainCustomFields. Set to false when the parent already
   * renders them (e.g. ReflectionItem shows domain fields above the expand toggle
   * and should not show them again inside the expanded HypothesisDetails).
   */
  showDomainFields?: boolean;
}

// Helper to parse structured experiment format
function parseExperiment(experiment: string): { section: string; content: string }[] | null {
  const sections = ["Objective", "Models", "Datasets", "Methodology", "Metrics", "Validation"];
  const parsed: { section: string; content: string }[] = [];

  let hasStructure = false;
  for (const section of sections) {
    const regex = new RegExp(
      `${section}:\\s*(.+?)(?=\\n\\n|${sections.filter((s) => s !== section).join("|")}:|$)`,
      "is"
    );
    const match = experiment.match(regex);
    if (match) {
      hasStructure = true;
      parsed.push({ section, content: match[1].trim() });
    }
  }

  return hasStructure ? parsed : null;
}

/**
 * Reusable component for displaying hypothesis details with all 4 components
 */
export function HypothesisDetails({
  hypothesis,
  compact = false,
  showAllFields = true,
  location = "hypothesis",
  showDomainFields = true,
}: HypothesisDetailsProps) {
  const parsedExperiment = hypothesis.experiment ? parseExperiment(hypothesis.experiment) : null;

  if (compact) {
    // Compact view - just show hypothesis text
    return <span className="text-sm leading-relaxed">{hypothesis.text}</span>;
  }

  return (
    <div className="space-y-3">
      {showAllFields && hypothesis.explanation && (
        <div>
          <h5 className="text-sm font-semibold text-th-fg mb-1">Explanation</h5>
          <p className="text-xs leading-relaxed">{hypothesis.explanation}</p>
        </div>
      )}

      {showAllFields && hypothesis.literature_grounding && (
        <div>
          <h5 className="text-sm font-semibold text-th-fg mb-1">Literature Grounding</h5>
          <p className="text-xs leading-relaxed">
            <CitedText
              text={hypothesis.literature_grounding}
              citationMap={hypothesis.citation_map}
            />
          </p>
        </div>
      )}

      {showAllFields && hypothesis.experiment && (
        <div>
          <h5 className="text-sm font-semibold text-th-fg mb-1">Experiment Design</h5>
          {parsedExperiment ? (
            <div className="space-y-2">
              {parsedExperiment.map(({ section, content }) => (
                <div key={section} className="text-xs">
                  <span className="font-semibold text-th-fg">{section}:</span>{" "}
                  <span className="leading-relaxed">{content}</span>
                </div>
              ))}
            </div>
          ) : (
            <p className="text-xs leading-relaxed whitespace-pre-wrap">
              {hypothesis.experiment}
            </p>
          )}
        </div>
      )}

      {showAllFields &&
        location === "hypothesis" &&
        hypothesis.citation_map &&
        Object.keys(hypothesis.citation_map).length > 0 && (
          <CitationList citationMap={hypothesis.citation_map} compact />
        )}

      {showAllFields && showDomainFields && (
        <DomainCustomFields
          hypothesis={hypothesis as Record<string, unknown>}
          location={location}
          compact
        />
      )}
    </div>
  );
}
