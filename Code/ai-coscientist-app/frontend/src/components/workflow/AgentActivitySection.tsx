import React, { useState, useEffect, useRef } from "react";
import { Card } from "@/components/ui/card";
import { PhaseNavigation } from "./PhaseNavigation";
import { PhaseGroup } from "./PhaseGroup";
import { AgentGroup } from "./AgentGroup";
import { AgentDisplay } from "@/components/agents/AgentDisplay";
import type { AgentOutput } from "@/types/agents";
import { groupByPhase, groupAgentsByType } from "@/utils/phaseDetection";

export interface AgentActivitySectionProps {
  agentOutputs: AgentOutput[];
}

/**
 * Main component for displaying agent activity organized by phases
 */
export function AgentActivitySection({ agentOutputs }: AgentActivitySectionProps) {
  const [selectedPhaseId, setSelectedPhaseId] = useState<string | null>(null);
  const sectionRef = useRef<HTMLDivElement>(null);
  const phaseRefs = useRef<Map<string, HTMLDivElement>>(new Map());

  const phases = groupByPhase(agentOutputs);
  const lastPhaseIdRef = useRef<string | null>(null);

  // Auto-select the latest phase when a new one appears
  useEffect(() => {
    if (phases.length > 0) {
      const latestPhase = phases[phases.length - 1];

      // auto-select if this is a new phase (not seen before)
      if (latestPhase.id !== lastPhaseIdRef.current) {
        setSelectedPhaseId(latestPhase.id);
        lastPhaseIdRef.current = latestPhase.id;
      }
    }
  }, [phases]);

  // handle phase selection with toggle-off behavior
  const handleSelectPhase = (phaseId: string) => {
    if (selectedPhaseId === phaseId) {
      // clicking already selected phase toggles it off
      setSelectedPhaseId(null);
    } else {
      setSelectedPhaseId(phaseId);
    }
  };

  if (agentOutputs.length === 0) {
    return null;
  }

  return (
    <div ref={sectionRef} className="space-y-4">
      <div className="p-4 pl-0">
        <h2 className="text-3xl font-semibold mb-4">Agent Activity</h2>

        {/* Phase Navigation */}
        <PhaseNavigation
          phases={phases}
          selectedPhaseId={selectedPhaseId}
          onSelectPhase={handleSelectPhase}
        />
      </div>

      {/* Phase Groups - only render selected phase */}
      <div className="space-y-4">
        {phases
          .filter((phase) => phase.id === selectedPhaseId)
          .map((phase) => {
            const groupedAgents = groupAgentsByType(phase.agents);

            return (
              <PhaseGroup
                key={phase.id}
                ref={(el) => {
                  if (el) {
                    phaseRefs.current.set(phase.id, el);
                  } else {
                    phaseRefs.current.delete(phase.id);
                  }
                }}
                phase={phase}
              >
                {groupedAgents.map((item, agentIndex) => {
                  // check if it's a grouped agent or individual agent
                  if ("agents" in item) {
                    // it's an AgentGroup
                    return <AgentGroup key={agentIndex} group={item} />;
                  } else {
                    // it's an individual AgentOutput
                    return <AgentDisplay key={agentIndex} output={item} />;
                  }
                })}
              </PhaseGroup>
            );
          })}
      </div>
    </div>
  );
}
