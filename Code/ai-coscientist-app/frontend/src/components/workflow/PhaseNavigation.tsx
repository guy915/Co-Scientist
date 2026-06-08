import React from "react";
import { Sparkles, Trophy, RefreshCw } from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import type { PhaseInfo } from "@/utils/phaseDetection";
import { cn } from "@/lib/utils";

export interface PhaseNavigationProps {
  phases: PhaseInfo[];
  selectedPhaseId: string | null;
  onSelectPhase: (phaseId: string) => void;
}

const phaseIcons: Record<string, typeof Sparkles> = {
  Sparkles,
  Trophy,
  RefreshCw,
};

/**
 * Navigation component for switching between workflow phases
 */
export function PhaseNavigation({ phases, selectedPhaseId, onSelectPhase }: PhaseNavigationProps) {
  return (
    <div className="flex flex-wrap gap-2 p-4 pl-0 rounded-lg">
      {phases.map((phase) => {
        const Icon = phaseIcons[phase.icon] || Sparkles;
        const isSelected = selectedPhaseId === phase.id;

        return (
          <Button
            key={phase.id}
            variant={isSelected ? "default" : "outline"}
            size="sm"
            onClick={() => onSelectPhase(phase.id)}
            className={cn("flex items-center gap-2", isSelected && "shadow-lg")}
            style={
              isSelected
                ? {
                    backgroundColor: phase.color,
                    borderColor: phase.color,
                    color: "white",
                  }
                : {}
            }
          >
            <Icon className="w-4 h-4" />
            <span>{phase.name}</span>
            <Badge variant="secondary" className="ml-1">
              {phase.agentCount}
            </Badge>
          </Button>
        );
      })}
    </div>
  );
}
