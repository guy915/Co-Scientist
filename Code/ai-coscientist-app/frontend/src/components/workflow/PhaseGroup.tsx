import React, { forwardRef } from "react";
import { Badge } from "@/components/ui/badge";
import type { PhaseInfo } from "@/utils/phaseDetection";

export interface PhaseGroupProps {
  phase: PhaseInfo;
  children: React.ReactNode;
}

/**
 * group component for a workflow phase - always expanded
 */
export const PhaseGroup = forwardRef<HTMLDivElement, PhaseGroupProps>(
  ({ phase, children }, ref) => {
    return (
      <div
        ref={ref}
        className="border rounded-lg overflow-hidden mb-5"
        style={{
          borderLeftWidth: "3px",
          borderLeftColor: phase.color,
        }}
      >
        {/* Header */}
        <div
          className="w-full px-4 py-3 flex items-center justify-between gap-4"
          style={{ backgroundColor: phase.color }}
        >
          <div className="flex items-center gap-3 flex-1">
            <h3 className="font-bold text-lg text-white">{phase.name}</h3>
            <Badge variant="secondary" className="bg-th-muted text-th-fg border-th-muted">
              {phase.agentCount} agents
            </Badge>
          </div>

          <div className="flex items-center gap-2">
            <span className="text-sm text-white/90">{phase.summary}</span>
          </div>
        </div>

        {/* Content - always visible */}
        <div className="p-4 space-y-3">{children}</div>
      </div>
    );
  }
);

PhaseGroup.displayName = "PhaseGroup";
