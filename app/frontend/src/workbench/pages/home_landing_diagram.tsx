// The "How it works" system diagram, laid out after the architecture figure
// in "Towards an AI co-scientist" (Gottweis et al., 2025): the scientist's
// goal flows through configuration to the Supervisor, which assigns the six
// specialist agents to workers, and the run returns a research overview.
// Nothing moves on its own: hover, focus, or tap an agent to highlight it
// and read what it does. Phones get the same flow as a stacked list.

import {useState} from 'react';
import {joinClasses} from '../classes';
import {LANDING_AGENTS, type LandingAgent} from './home_landing_content';

// The six specialists sit in the paper's two-column grid, row by row.
const GRID: readonly (readonly [string, string])[] = [
  ['Generation', 'Proximity'],
  ['Reflection', 'Meta-review'],
  ['Ranking', 'Evolution'],
];
const SPECIALISTS = LANDING_AGENTS.slice(1);
const COLUMN_X = [280, 560];
const ROW_Y = [214, 314, 414];
const CELL_W = 240;
const CELL_H = 56;

function agentByName(name: string): LandingAgent {
  return SPECIALISTS.find(agent => agent.name === name) ?? SPECIALISTS[0];
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
  'M400 270 V310',
  'M400 370 V410',
  'M680 270 V310',
  'M680 370 V410',
  'M524 242 H556',
  'M524 342 H556',
  'M524 442 H556',
  'M562 316 L524 274',
  'M522 372 L558 412',
  'M558 372 L522 412',
];

// The paper draws each row's pair as a two-way exchange.
const TWO_WAY = new Set(INNER_WIRES.filter(d => d.endsWith(' H556')));

// Arrows outside it: you to goal to configuration to Supervisor, Supervisor
// down into the agents and across to the overview, out to the workers and
// memory, the workers' results back up to the Supervisor, the overview back
// to you, and your feedback into the agents.
const OUTER_WIRES = [
  'M100 88 H136',
  'M310 88 H346',
  'M516 88 H552',
  'M671 118 V186',
  'M786 88 H942',
  'M830 273 H876',
  'M830 440 H876',
  'M880 470 H834',
  'M1000 210 V150 H740 V122',
  'M1053 54 V24 H64 V50',
  'M64 156 V296',
  'M196 326 H246',
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
        y="190"
        width="580"
        height="340"
        rx="32"
      />
      <text
        className="ucs-landing-box-label"
        x="540"
        y="508"
        textAnchor="middle"
      >
        Co-Scientist specialized agents
      </text>
      <text className="ucs-landing-wire-label" x="660" y="160" textAnchor="end">
        assigns agents to workers
      </text>
      <circle className="ucs-landing-person" cx="64" cy="88" r="34" />
      <path
        className="ucs-landing-person-glyph"
        d="M64 70 a10 10 0 1 1 0 20 a10 10 0 1 1 0 -20 M46 110 c4 -14 32 -14 36 0 z"
      />
      <text
        className="ucs-landing-caption-text"
        x="64"
        y="146"
        textAnchor="middle"
      >
        You
      </text>
    </>
  );
}

// Every box outside the agents grid: [x, y, width, height, class, lines].
const NODES: readonly (readonly [
  number,
  number,
  number,
  number,
  string,
  string[],
])[] = [
  [140, 62, 170, 52, 'is-you', ['Research goal']],
  [350, 62, 166, 52, '', ['Configuration']],
  [556, 58, 230, 60, 'is-supervisor', ['Supervisor agent']],
  [946, 54, 214, 68, 'is-output', ['Research overview', 'and ranked ideas']],
  [20, 300, 176, 52, 'is-you', ['Your feedback']],
  [880, 214, 240, 34, 'is-worker', ['Worker']],
  [880, 256, 240, 34, 'is-worker', ['Worker']],
  [880, 298, 240, 34, 'is-worker', ['Worker']],
  [880, 340, 240, 34, 'is-worker', ['Worker']],
  [880, 420, 240, 70, 'is-worker', ['Context', 'memory']],
];

function DiagramNodes() {
  return (
    <>
      {NODES.map(([x, y, w, h, className, lines]) => (
        <DiagramNode
          key={`${x}-${y}`}
          x={x}
          y={y}
          w={w}
          h={h}
          className={className}
          lines={lines}
        />
      ))}
    </>
  );
}

function DiagramSvg({
  active,
  onHold,
}: {
  active: string | null;
  onHold: (name: string | null) => void;
}) {
  return (
    <svg
      className="ucs-landing-diagram-svg"
      viewBox="0 0 1180 540"
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
function DiagramList({
  active,
  onHold,
}: {
  active: string | null;
  onHold: (name: string | null) => void;
}) {
  return (
    <ol className="ucs-landing-flow">
      <li className="is-you">
        <b>You</b>set the research goal and configuration
      </li>
      <li className="is-supervisor">
        <b>Supervisor agent</b>plans the run and assigns agents to workers
      </li>
      <li className="ucs-landing-flow-ring">
        {SPECIALISTS.map(agent => (
          <button
            key={agent.name}
            type="button"
            aria-pressed={active === agent.name}
            className={joinClasses(
              `tone-${agent.tone}`,
              active === agent.name && 'is-active',
            )}
            onClick={() => onHold(agent.name)}
          >
            {agent.name}
          </button>
        ))}
        <em>Repeats until the rankings settle</em>
      </li>
      <li className="is-output">
        <b>Research overview and ranked ideas</b>what you get back
      </li>
    </ol>
  );
}

// The caption under the diagram: the chosen agent's job, or a prompt to
// choose one.
function DiagramCaption({active}: {active: string | null}) {
  if (!active) {
    return (
      <figcaption className="ucs-landing-diagram-caption">
        <span>Hover or tap an agent to see what it does.</span>
      </figcaption>
    );
  }
  const agent = agentByName(active);
  return (
    <figcaption className="ucs-landing-diagram-caption">
      <b>{agent.name} agent</b>
      <span>{agent.summary}</span>
    </figcaption>
  );
}

/**
 * The system diagram with its caption. Nothing moves on its own: the
 * highlight follows the agent last hovered, focused, or tapped, and stays
 * there so the caption can be read.
 */
export function LandingDiagram() {
  const [active, setActive] = useState<string | null>(null);
  const choose = (name: string | null) => {
    if (name) setActive(name);
  };
  return (
    <figure className="ucs-landing-diagram">
      <DiagramSvg active={active} onHold={choose} />
      <DiagramList active={active} onHold={choose} />
      <DiagramCaption active={active} />
    </figure>
  );
}
