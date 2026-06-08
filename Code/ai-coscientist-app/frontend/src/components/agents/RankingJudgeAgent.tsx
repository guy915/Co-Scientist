import React, { useState } from "react";
import { Trophy, ChevronDown, TrendingUp, TrendingDown } from "lucide-react";
import { Card } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import type { AgentOutput } from "@/types/agents";
import { cn } from "@/lib/utils";
import { useDomainText } from "@/hooks/useDomainText";
import { getAgentColor } from "@/utils/agentFormatters";

export interface RankingJudgeAgentProps {
  output: AgentOutput;
}

interface TournamentMatchup {
  winner: string;
  reasoning?: string;
  decision_summary?: string;
  hypothesis_a?: string;
  hypothesis_a_text?: string;
  hypothesis_b?: string;
  hypothesis_b_text?: string;
  confidence?: number;
  winner_elo_before?: number;
  winner_elo_after?: number;
  loser_elo_before?: number;
  loser_elo_after?: number;
}

interface MatchupCardProps {
  matchup: TournamentMatchup;
  index: number;
  timestamp: number;
}

function MatchupCard({ matchup, index, timestamp }: MatchupCardProps) {
  const { t } = useDomainText();
  const [showDetails, setShowDetails] = useState(false);
  const winner = matchup.winner?.toUpperCase() || "N/A";
  const hypothesisA = matchup.hypothesis_a_text || matchup.hypothesis_a || "";
  const hypothesisB = matchup.hypothesis_b_text || matchup.hypothesis_b || "";
  const reasoning = matchup.reasoning || matchup.decision_summary || "";

  const eloChangeWinner =
    matchup.winner_elo_after && matchup.winner_elo_before
      ? matchup.winner_elo_after - matchup.winner_elo_before
      : null;
  const eloChangeLoser =
    matchup.loser_elo_after && matchup.loser_elo_before
      ? matchup.loser_elo_after - matchup.loser_elo_before
      : null;

  return (
    <div className="border rounded-lg p-3 space-y-2">
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-2">
          <span className="font-medium text-sm">Ranking Judge {index + 1}</span>
          <Badge variant="success" className="text-xs">
            Winner: {winner}
          </Badge>
        </div>
        <Badge variant="outline" className="text-xs">
          {new Date(timestamp).toLocaleTimeString()}
        </Badge>
      </div>

      <button
        onClick={() => setShowDetails(!showDetails)}
        className="text-sm text-th-link hover:text-th-link-hover flex items-center gap-1"
      >
        <ChevronDown className={cn("w-4 h-4 transition-transform", showDetails && "rotate-180")} />
        {showDetails ? "Hide" : "Show"} Comparison
      </button>

      {showDetails && (
        <div className="space-y-3 pt-2 border-t text-sm">
          {hypothesisA && (
            <div>
              <div className="flex items-center gap-2 mb-1">
                <span className="font-medium">{t("hypothesis_a_label")}:</span>
                {eloChangeWinner !== null && winner === "A" && (
                  <Badge variant="outline" className="text-xs text-th-success">
                    <TrendingUp className="w-3 h-3 mr-1" style={{ color: "var(--color-green-500)" }} />
                    {matchup.winner_elo_before} → {matchup.winner_elo_after} (+{eloChangeWinner})
                  </Badge>
                )}
                {eloChangeLoser !== null && winner === "B" && (
                  <Badge variant="outline" className="text-xs text-th-destructive">
                    <TrendingDown className="w-3 h-3 mr-1" style={{ color: "var(--color-red-500)" }} />
                    {matchup.loser_elo_before} → {matchup.loser_elo_after} ({eloChangeLoser})
                  </Badge>
                )}
              </div>
              <p className="text-muted-foreground">{hypothesisA}</p>
            </div>
          )}
          {hypothesisB && (
            <div>
              <div className="flex items-center gap-2 mb-1">
                <span className="font-medium">{t("hypothesis_b_label")}:</span>
                {eloChangeWinner !== null && winner === "B" && (
                  <Badge variant="outline" className="text-xs text-th-success">
                    <TrendingUp className="w-3 h-3 mr-1" style={{ color: "var(--color-green-500)" }} />
                    {matchup.winner_elo_before} → {matchup.winner_elo_after} (+{eloChangeWinner})
                  </Badge>
                )}
                {eloChangeLoser !== null && winner === "A" && (
                  <Badge variant="outline" className="text-xs text-destructive">
                    <TrendingDown className="w-3 h-3 mr-1" style={{ color: "var(--color-red-500)" }} />
                    {matchup.loser_elo_before} → {matchup.loser_elo_after} ({eloChangeLoser})
                  </Badge>
                )}
              </div>
              <p className="text-muted-foreground">{hypothesisB}</p>
            </div>
          )}
          {reasoning && (
            <div>
              <span className="font-medium">Decision:</span>
              <p className="text-muted-foreground mt-1">{reasoning}</p>
            </div>
          )}
        </div>
      )}
    </div>
  );
}

export function RankingJudgeAgent({ output }: RankingJudgeAgentProps) {
  const data = output.parsed;
  const matchups: TournamentMatchup[] = data?.matchups || [];

  if (matchups.length === 0) {
    return (
      <Card className="p-4">
        <div className="flex items-start gap-3">
          <Trophy className="w-5 h-5 shrink-0 mt-0.5" style={{ color: getAgentColor("RankingJudge") }} />
          <div className="flex-1">
            <p className="text-sm text-muted-foreground">Tournament in progress...</p>
          </div>
        </div>
      </Card>
    );
  }

  return (
    <Card className="p-4 border-none shadow-none">
      <div className="flex items-start gap-3">
        {/* <Trophy className="w-5 h-5 shrink-0 mt-0.5" style={{ color: '#ff3b30' }} /> */}
        <div className="flex-1 space-y-3">
          <div className="flex items-center justify-between">
            <span className="text-sm text-muted-foreground">
              {matchups.length} tournament round{matchups.length !== 1 ? "s" : ""}
            </span>
          </div>

          <div className="space-y-2">
            {matchups.map((matchup, index) => (
              <MatchupCard
                key={index}
                matchup={matchup}
                index={index}
                timestamp={output.timestamp}
              />
            ))}
          </div>
        </div>
      </div>
    </Card>
  );
}
