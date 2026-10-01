import type {ShapeName} from '../shared/Shape';
import type {Tone} from '../shared/tokens';

// The seven agents, with the shape and tone the landing page gives each
// (LANDING_AGENTS in home_landing_content.ts).
export const AGENTS: {name: string; shape: ShapeName; tone: Tone}[] = [
  {name: 'Supervisor', shape: 'cookie12', tone: 'teal'},
  {name: 'Generation', shape: 'flower', tone: 'blue'},
  {name: 'Reflection', shape: 'gem', tone: 'red'},
  {name: 'Ranking', shape: 'pill', tone: 'yellow'},
  {name: 'Evolution', shape: 'clover', tone: 'green'},
  {name: 'Proximity', shape: 'cookie7', tone: 'blue'},
  {name: 'Meta-review', shape: 'sunny', tone: 'teal'},
];
