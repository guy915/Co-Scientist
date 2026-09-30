// The landing page's live tournament: a canvas of ideas that play Elo
// matches against their neighbors and drift up or down with their rating.
// Pointer movement stirs the field. The canvas only animates while it is on
// screen, and under reduced motion it renders one settled frame instead.

import {type RefObject, useEffect, useRef} from 'react';
import {INITIAL_ELO} from './home_landing_content';
import {
  type ArenaIdea,
  type ArenaSpark,
  playArenaMatch,
  seedArena,
} from './home_landing_elo';
import {useInView} from './home_landing_hooks';

// The four leaders glow in Google's four brand colors, in rank order.
const LEADER_COLORS = ['#4285f4', '#ea4335', '#fbbc04', '#34a853'];
const LABEL_FONT = '11px "Google Sans Code", ui-monospace, monospace';
const BAND_TOP = 72;
const BAND_BOTTOM = 40;
const OFF_FIELD = -1e4;

interface Arena {
  ideas: ArenaIdea[];
  sparks: ArenaSpark[];
  width: number;
  height: number;
  lo: number;
  hi: number;
  pointer: {x: number; y: number};
  matches: number;
}

// The y position that a rating settles at: the pool's best at the top of
// the band, its worst at the bottom.
function yForElo(arena: Arena, elo: number): number {
  const span = Math.max(40, arena.hi - arena.lo);
  const k = Math.max(0, Math.min(1, (elo - arena.lo) / span));
  const bottom = arena.height - BAND_BOTTOM;
  return bottom - k * (bottom - BAND_TOP);
}

function ranked(arena: Arena): ArenaIdea[] {
  return [...arena.ideas].sort((p, q) => q.elo - p.elo);
}

// Eases the rating window toward the pool's current extremes so the field
// rescales smoothly as the spread grows.
function trackSpread(arena: Arena, order: ArenaIdea[], ease: number) {
  arena.lo += (order[order.length - 1].elo - arena.lo) * ease;
  arena.hi += (order[0].elo - arena.hi) * ease;
}

function createArena(width: number, height: number): Arena {
  const count = width < 700 ? 60 : 96;
  const arena: Arena = {
    ideas: seedArena(count, width, height),
    sparks: [],
    width,
    height,
    lo: INITIAL_ELO - 50,
    hi: INITIAL_ELO + 50,
    pointer: {x: OFF_FIELD, y: OFF_FIELD},
    matches: 0,
  };
  // Warm up off screen so the first frame already shows a spread field.
  for (let i = 0; i < 1400; i++) playArenaMatch(arena.ideas);
  trackSpread(arena, ranked(arena), 1);
  for (const idea of arena.ideas) idea.y = yForElo(arena, idea.elo);
  return arena;
}

function drawSparks(ctx: CanvasRenderingContext2D, arena: Arena) {
  for (const spark of arena.sparks) {
    spark.age += 0.03;
    const alpha = Math.max(0, 1 - spark.age);
    ctx.strokeStyle = `rgba(255,255,255,${alpha * 0.35})`;
    ctx.lineWidth = 1;
    ctx.beginPath();
    ctx.moveTo(spark.a.x, spark.a.y);
    ctx.lineTo(spark.b.x, spark.b.y);
    ctx.stroke();
    ctx.fillStyle = `rgba(251,188,4,${alpha * 0.9})`;
    ctx.beginPath();
    ctx.arc(spark.winner.x, spark.winner.y, 3 + spark.age * 10, 0, 7);
    ctx.fill();
  }
  arena.sparks = arena.sparks.filter(spark => spark.age < 1);
}

// Pulls an idea toward its rating's height, adds a slow sideways drift, and
// pushes it away from the pointer. Wraps it around the field's sides.
function moveIdea(arena: Arena, idea: ArenaIdea, time: number) {
  idea.vy += (yForElo(arena, idea.elo) - idea.y) * 0.0009;
  idea.vx += Math.sin(time / 2400 + idea.phase) * 0.012;
  const dx = idea.x - arena.pointer.x;
  const dy = idea.y - arena.pointer.y;
  const d = Math.hypot(dx, dy);
  if (d < 140 && d > 0) {
    idea.vx += (dx / d) * 0.35;
    idea.vy += (dy / d) * 0.35;
  }
  idea.vx *= 0.94;
  idea.vy *= 0.94;
  idea.x = (idea.x + idea.vx + arena.width + 20) % (arena.width + 20);
  idea.y = Math.max(BAND_TOP - 12, Math.min(arena.height, idea.y + idea.vy));
}

function radiusFor(idea: ArenaIdea): number {
  return 1.4 + Math.max(0, (idea.elo - (INITIAL_ELO - 50)) / 50);
}

function drawLeader(
  ctx: CanvasRenderingContext2D,
  idea: ArenaIdea,
  color: string,
) {
  const r = radiusFor(idea);
  const glow = ctx.createRadialGradient(
    idea.x,
    idea.y,
    0,
    idea.x,
    idea.y,
    r * 7,
  );
  glow.addColorStop(0, color + 'aa');
  glow.addColorStop(1, color + '00');
  ctx.fillStyle = glow;
  ctx.beginPath();
  ctx.arc(idea.x, idea.y, r * 7, 0, 7);
  ctx.fill();
  ctx.fillStyle = color;
  ctx.beginPath();
  ctx.arc(idea.x, idea.y, r + 1.5, 0, 7);
  ctx.fill();
}

function drawIdea(ctx: CanvasRenderingContext2D, idea: ArenaIdea) {
  const lift = Math.min(
    0.6,
    Math.max(0, (idea.elo - (INITIAL_ELO - 50)) / 150),
  );
  ctx.fillStyle = `rgba(232,234,237,${0.25 + lift})`;
  ctx.beginPath();
  ctx.arc(idea.x, idea.y, radiusFor(idea), 0, 7);
  ctx.fill();
}

interface LabelBox {
  x: number;
  y: number;
  w: number;
}

// Whether a label at `box` would sit on top of one already placed.
function overlapsPlaced(box: LabelBox, placed: LabelBox[]): boolean {
  return placed.some(
    p =>
      Math.abs(p.y - box.y) < 16 &&
      box.x < p.x + p.w + 8 &&
      p.x < box.x + box.w + 8,
  );
}

// Places a leader's rating label on whichever side of it has room.
function labelBox(
  ctx: CanvasRenderingContext2D,
  arena: Arena,
  idea: ArenaIdea,
): LabelBox & {text: string} {
  const text = String(Math.round(idea.elo));
  const w = ctx.measureText(text).width;
  const gap = radiusFor(idea) * 3 + 10;
  const right = idea.x + gap + w <= arena.width - 6;
  return {text, w, y: idea.y, x: right ? idea.x + gap : idea.x - gap - w};
}

// Writes each leader's rating beside it, with a dark outline so it stays
// legible where it crosses another dot, skipping any label that would land
// on one already written.
function drawLeaderLabels(
  ctx: CanvasRenderingContext2D,
  arena: Arena,
  leaders: ArenaIdea[],
) {
  ctx.font = LABEL_FONT;
  ctx.lineWidth = 4;
  ctx.strokeStyle = '#0b0c0d';
  ctx.fillStyle = 'rgba(255,255,255,.8)';
  const placed: LabelBox[] = [];
  for (const idea of leaders) {
    const box = labelBox(ctx, arena, idea);
    if (overlapsPlaced(box, placed)) continue;
    placed.push(box);
    ctx.strokeText(box.text, box.x, box.y + 4);
    ctx.fillText(box.text, box.x, box.y + 4);
  }
}

function drawFrame(ctx: CanvasRenderingContext2D, arena: Arena, time: number) {
  ctx.clearRect(0, 0, arena.width, arena.height);
  const order = ranked(arena);
  trackSpread(arena, order, 0.05);
  drawSparks(ctx, arena);
  const leaders = order.slice(0, arena.width < 700 ? 2 : 4);
  for (const idea of arena.ideas) {
    moveIdea(arena, idea, time);
    if (!leaders.includes(idea)) drawIdea(ctx, idea);
  }
  leaders.forEach((idea, i) => drawLeader(ctx, idea, LEADER_COLORS[i]));
  drawLeaderLabels(ctx, arena, leaders);
}

// One animation tick: maybe play a match, then draw.
function tick(ctx: CanvasRenderingContext2D, arena: Arena, time: number) {
  if (Math.random() < 0.55) {
    const spark = playArenaMatch(arena.ideas);
    if (spark) {
      arena.sparks.push(spark);
      arena.matches++;
    }
  }
  drawFrame(ctx, arena, time);
}

// Sizes the canvas backing store to its CSS box at the device pixel ratio.
function fitCanvas(
  canvas: HTMLCanvasElement,
  ctx: CanvasRenderingContext2D,
): {width: number; height: number} {
  const dpr = Math.min(2, window.devicePixelRatio || 1);
  const width = canvas.clientWidth;
  const height = canvas.clientHeight;
  canvas.width = width * dpr;
  canvas.height = height * dpr;
  ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
  return {width, height};
}

function updateHud(arena: Arena, hud: HTMLElement | null) {
  if (!hud) return;
  const best = Math.round(ranked(arena)[0].elo);
  hud.textContent = `${arena.matches.toLocaleString()} matches · leader ${best}`;
}

// Runs the arena on `canvas` until the returned cleanup is called.
function runArena(
  canvas: HTMLCanvasElement,
  hud: HTMLElement | null,
  reduceMotion: boolean,
): () => void {
  const ctx = canvas.getContext('2d');
  if (!ctx) return () => undefined;
  const size = fitCanvas(canvas, ctx);
  const arena = createArena(size.width, size.height);
  const onMove = (e: PointerEvent) => {
    const box = canvas.getBoundingClientRect();
    arena.pointer = {x: e.clientX - box.left, y: e.clientY - box.top};
  };
  const onLeave = () => (arena.pointer = {x: OFF_FIELD, y: OFF_FIELD});
  const onResize = () => {
    Object.assign(arena, fitCanvas(canvas, ctx));
    if (reduceMotion) drawFrame(ctx, arena, 0);
  };
  canvas.addEventListener('pointermove', onMove);
  canvas.addEventListener('pointerleave', onLeave);
  window.addEventListener('resize', onResize);
  let frame = 0;
  const loop = (time: number) => {
    tick(ctx, arena, time);
    if (frame % 12 === 0) updateHud(arena, hud);
    frame = requestAnimationFrame(loop);
  };
  if (reduceMotion) drawFrame(ctx, arena, 0);
  else frame = requestAnimationFrame(loop);
  updateHud(arena, hud);
  return () => {
    cancelAnimationFrame(frame);
    canvas.removeEventListener('pointermove', onMove);
    canvas.removeEventListener('pointerleave', onLeave);
    window.removeEventListener('resize', onResize);
  };
}

function useArena(
  canvasRef: RefObject<HTMLCanvasElement | null>,
  hudRef: RefObject<HTMLElement | null>,
  active: boolean,
  reduceMotion: boolean,
) {
  useEffect(() => {
    const canvas = canvasRef.current;
    if (!active || !canvas) return;
    return runArena(canvas, hudRef.current, reduceMotion);
  }, [canvasRef, hudRef, active, reduceMotion]);
}

/** The live tournament panel. */
export function LandingArena({reduceMotion}: {reduceMotion: boolean}) {
  const panelRef = useRef<HTMLDivElement | null>(null);
  const canvasRef = useRef<HTMLCanvasElement | null>(null);
  const hudRef = useRef<HTMLSpanElement | null>(null);
  const visible = useInView(panelRef, {once: false, margin: '120px'});
  useArena(canvasRef, hudRef, visible, reduceMotion);
  return (
    <div ref={panelRef} className="ucs-landing-arena">
      <canvas ref={canvasRef} aria-hidden="true" />
      <div className="ucs-landing-arena-top">
        <span>Live tournament</span>
        <span ref={hudRef} className="ucs-landing-arena-hud" />
      </div>
      <p className="ucs-landing-arena-caption">
        Stylized simulation. Every idea starts at Elo {INITIAL_ELO}; higher
        means stronger. Move your pointer through the field to stir it.
      </p>
    </div>
  );
}
