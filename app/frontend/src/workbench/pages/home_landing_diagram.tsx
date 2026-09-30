// The "How it works" system diagram, laid out after the architecture figure
// in "Towards an AI co-scientist" (Gottweis et al., 2025): the scientist's
// goal flows through configuration to the Supervisor, which assigns the six
// specialist agents to workers, and the run returns a research overview.
// Wires carry a moving dash, and a highlight walks through the agents; hover
// or focus an agent to hold it and read what it does. Phones get the same
// flow as a stacked list.

import {useEffect, useState} from 'react';
import {joinClasses} from '../classes';
import {LANDING_AGENTS, type LandingAgent} from './home_landing_content';

// The six specialists sit in the paper's two-column grid, row by row.
const GRID: readonly (readonly [string, string])[] = [
  ['Generation', 'Proximity'],
  ['Reflection', 'Meta-review'],
  ['Ranking', 'Evolution'],
];
const SPECIALISTS = LANDING_AGENTS.slice(1);
const COLUMN_X = [280, 590];
const ROW_Y = [212, 322, 432];
const CELL_W = 240;
const CELL_H = 58;
const STEP_MS = 1800;

function agentByName(name: string): LandingAgent {
  return SPECIALISTS.find(agent => agent.name === name) ?? SPECIALISTS[0];
}

// Walks the highlight through the specialists unless one is held.
function useWalkingHighlight(
  held: string | null,
  reduceMotion: boolean,
): string {
  const [index, setIndex] = useState(0);
  useEffect(() => {
    if (held || reduceMotion) return;
    const timer = window.setInterval(
      () => setIndex(i => (i + 1) % SPECIALISTS.length),
      STEP_MS,
    );
    return () => window.clearInterval(timer);
  }, [held, reduceMotion]);
  return held ?? SPECIALISTS[index].name;
}

interface NodeProps {
  x: number;
  y: number;
  w: number;
  h: number;
  className?: string;
  lines: string[];
}

// A labeled box; one line of text centers, two stack.
function DiagramNode({x, y, w, h, className, lines}: NodeProps) {
  const cy = y + h / 2 - (lines.length - 1) * 10 + 5;
  return (
    <g className={joinClasses('ucs-landing-node', className)}>
      <rect x={x} y={y} width={w} height={h} rx={Math.min(h / 2, 22)} />
      {lines.map((line, i) => (
        <text key={line} x={x + w / 2} y={cy + i * 20} textAnchor="middle">
          {line}
        </text>
      ))}
    </g>
  );
}

function AgentCell({
  agent,
  x,
  y,
  active,
  onHold,
}: {
  agent: LandingAgent;
  x: number;
  y: number;
  active: boolean;
  onHold: (name: string | null) => void;
}) {
  return (
    <g
      className={joinClasses(
        'ucs-landing-agent-cell',
        `tone-${agent.tone}`,
        active && 'is-active',
      )}
      tabIndex={0}
      aria-label={`${agent.name} agent: ${agent.summary}`}
      onPointerEnter={() => onHold(agent.name)}
      onPointerLeave={() => onHold(null)}
      onFocus={() => onHold(agent.name)}
      onBlur={() => onHold(null)}
    >
      <rect x={x} y={y} width={CELL_W} height={CELL_H} rx={CELL_H / 2} />
      <text x={x + CELL_W / 2} y={y + CELL_H / 2 + 6} textAnchor="middle">
        {agent.name} agent
      </text>
    </g>
  );
}

// Arrows inside the agents box: down each column, across each row, and the
// paper's crossing links between the lower rows.
const INNER_WIRES = [
  'M400 270 V322',
  'M400 380 V432',
  'M710 270 V322',
  'M710 380 V432',
  'M524 241 H586',
  'M524 351 H586',
  'M524 461 H586',
  'M590 330 L522 262',
  'M522 380 L590 432',
  'M590 380 L522 432',
];

// The paper draws each row's pair as a two-way exchange.
const TWO_WAY = new Set(INNER_WIRES.filter(d => d.includes(' H586')));

// Arrows outside it: goal to configuration to Supervisor, Supervisor down
// into the agents and across to the overview, out to the workers and
// memory, the workers' results back up, and the overview back to you.
const OUTER_WIRES = [
  'M340 96 H384',
  'M556 96 H600',
  'M720 124 V184',
  'M842 96 H924',
  'M862 342 H916',
  'M862 478 H916',
  'M916 508 H864',
  'M1036 262 C1036 190 920 150 846 118',
  'M1040 64 V34 H70 V52',
  'M70 174 C70 200 64 220 70 244',
  'M200 296 C232 296 230 372 246 372',
];

function DiagramWires({wires}: {wires: readonly string[]}) {
  return (
    <>
      {wires.map(d => (
        <path
          key={d}
          className={joinClasses(
            'ucs-landing-wire',
            TWO_WAY.has(d) && 'is-two-way',
          )}
          d={d}
        />
      ))}
    </>
  );
}

function DiagramFrame() {
  return (
    <>
      <defs>
        <marker
          id="ucs-landing-arrow"
          viewBox="0 0 10 10"
          refX="8"
          refY="5"
          markerWidth="7"
          markerHeight="7"
          orient="auto-start-reverse"
        >
          <path d="M0 0 L10 5 L0 10 z" />
        </marker>
      </defs>
      <rect
        className="ucs-landing-box"
        x="250"
        y="186"
        width="612"
        height="370"
        rx="32"
      />
      <text
        className="ucs-landing-box-label"
        x="556"
        y="536"
        textAnchor="middle"
      >
        Co-Scientist specialized agents
      </text>
      <text className="ucs-landing-wire-label" x="734" y="160">
        assigns agents to workers
      </text>
      <circle className="ucs-landing-person" cx="70" cy="96" r="40" />
      <path
        className="ucs-landing-person-glyph"
        d="M70 76 a12 12 0 1 1 0 24 a12 12 0 1 1 0 -24 M48 124 c4 -14 40 -14 44 0 z"
      />
      <text
        className="ucs-landing-caption-text"
        x="70"
        y="164"
        textAnchor="middle"
      >
        You
      </text>
    </>
  );
}

function DiagramNodes() {
  return (
    <>
      <DiagramNode
        x={170}
        y={70}
        w={170}
        h={52}
        className="is-you"
        lines={['Research goal']}
      />
      <DiagramNode x={390} y={70} w={166} h={52} lines={['Configuration']} />
      <DiagramNode
        x={604}
        y={66}
        w={238}
        h={60}
        className="is-supervisor"
        lines={['Supervisor agent']}
      />
      <DiagramNode
        x={928}
        y={64}
        w={228}
        h={76}
        className="is-output"
        lines={['Research overview', 'and ranked ideas']}
      />
      <DiagramNode
        x={24}
        y={250}
        w={176}
        h={52}
        className="is-you"
        lines={['Your feedback']}
      />
      {[0, 1, 2, 3].map(i => (
        <DiagramNode
          key={i}
          x={920}
          y={270 + i * 44}
          w={232}
          h={36}
          className="is-worker"
          lines={['Worker']}
        />
      ))}
      <DiagramNode
        x={920}
        y={458}
        w={232}
        h={70}
        className="is-worker"
        lines={['Context', 'memory']}
      />
    </>
  );
}

function DiagramSvg({
  active,
  onHold,
}: {
  active: string;
  onHold: (name: string | null) => void;
}) {
  return (
    <svg
      className="ucs-landing-diagram-svg"
      viewBox="0 0 1180 570"
      role="group"
      aria-label="System diagram: you set a research goal and configuration; the Supervisor agent assigns the Generation, Reflection, Ranking, Evolution, Proximity and Meta-review agents to workers that share a context memory; the run returns a research overview with ranked ideas, and your feedback flows back in."
    >
      <DiagramFrame />
      <DiagramWires wires={OUTER_WIRES} />
      <DiagramWires wires={INNER_WIRES} />
      <DiagramNodes />
      {GRID.map((row, r) =>
        row.map((name, c) => (
          <AgentCell
            key={name}
            agent={agentByName(name)}
            x={COLUMN_X[c]}
            y={ROW_Y[r]}
            active={active === name}
            onHold={onHold}
          />
        )),
      )}
    </svg>
  );
}

// The phone layout: the same flow, top to bottom.
function DiagramList({active}: {active: string}) {
  return (
    <ol className="ucs-landing-flow" aria-hidden="true">
      <li className="is-you">
        <b>You</b>set the research goal and configuration
      </li>
      <li className="is-supervisor">
        <b>Supervisor agent</b>plans the run and assigns agents to workers
      </li>
      <li className="ucs-landing-flow-ring">
        {SPECIALISTS.map(agent => (
          <span
            key={agent.name}
            className={joinClasses(
              `tone-${agent.tone}`,
              active === agent.name && 'is-active',
            )}
          >
            {agent.name}
          </span>
        ))}
        <em>Repeats until the rankings settle</em>
      </li>
      <li className="is-output">
        <b>Research overview and ranked ideas</b>what you get back
      </li>
    </ol>
  );
}

/** The system diagram with its live caption. */
export function LandingDiagram({reduceMotion}: {reduceMotion: boolean}) {
  const [held, setHeld] = useState<string | null>(null);
  const active = useWalkingHighlight(held, reduceMotion);
  const agent = agentByName(active);
  return (
    <figure className="ucs-landing-diagram">
      <DiagramSvg active={active} onHold={setHeld} />
      <DiagramList active={active} />
      <figcaption className="ucs-landing-diagram-caption">
        <b>{agent.name} agent</b>
        <span>{agent.summary}</span>
      </figcaption>
    </figure>
  );
}
