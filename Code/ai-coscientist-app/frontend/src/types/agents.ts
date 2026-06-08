export interface AgentOutput {
  name: string;
  content: string;
  parsed: any;
  timestamp: number;
  phase?: string;
  iteration?: number;
  isPhaseMarker?: boolean;
  description?: string;
}

export interface AgentGroup {
  name: string;
  agents: AgentOutput[];
  summary: string;
}
