// BODY N BRAIN — evaluation + alpha-beta search
import {
  N,
  legalMoves,
  applyMove,
  movesOrPass,
  isOver,
  ownerOf,
  isBody,
  isBrain,
  isStack,
  xOf,
  yOf,
  ORTHO,
  onBoard,
  idx,
  goalRank,
} from "./engine.mjs";

export const WIN = 100000;

// Distance from the nearest wall: 0 on the rim, 1 in the 2x2 centre.
const RIM = new Int8Array(N);
for (let i = 0; i < N; i++) {
  const x = xOf(i);
  const y = yOf(i);
  RIM[i] = Math.min(x, 3 - x, y, 3 - y);
}

const V_BODY = 100;
const V_STACK_BONUS = 55; // being mounted is worth roughly half a BODY
const V_CENTRE = 8;
const V_MOBILITY = 3;
const V_LONE_BRAIN = -30; // an unmounted BRAIN is a liability
const V_WALL_BRAIN = -22; // a mounted BRAIN on the rim can be tackled off the board
const V_ADVANCE = 14; // per rank the BRAIN has pushed toward the enemy home rank
const V_ON_GOAL = 220; // sitting on the goal rank: one survived turn from winning

/** Static evaluation from the point of view of `me`. */
export function evaluate(s, me) {
  if (s.winner !== null) {
    if (s.winner === -1) return 0;
    return s.winner === me ? WIN : -WIN;
  }
  const c = s.cells;
  let score = 0;
  for (let i = 0; i < N; i++) {
    const cell = c[i];
    if (cell === 0) continue;
    const o = ownerOf(cell);
    const sign = o === me ? 1 : -1;
    let v = 0;
    if (isBody(cell)) v += V_BODY;
    else if (isBrain(cell)) v += V_LONE_BRAIN;
    else if (isStack(cell)) {
      v += V_BODY + V_STACK_BONUS;
      if (RIM[i] === 0) v += V_WALL_BRAIN;
    }
    if (s.rules.invasion !== "none" && (isBrain(cell) || isStack(cell))) {
      const scores = s.rules.invasion === "any" || isBrain(cell);
      const progress = 3 - Math.abs(yOf(i) - goalRank(o));
      v += V_ADVANCE * progress;
      if (progress === 3 && scores) v += V_ON_GOAL;
    }
    v += V_CENTRE * RIM[i];
    score += sign * v;
  }
  // mobility of the side to move (cheap proxy for initiative)
  const mob = legalMoves(s, s.turn).length;
  score += (s.turn === me ? 1 : -1) * V_MOBILITY * mob;
  return score;
}

function scoreMove(s, m) {
  // cheap move ordering: wins first, then captures, then tackles
  if (m.kind === "tackle") return m.push < 0 ? 9000 : 400;
  if (m.capture) return isBrain(m.capture) ? 9000 : 500;
  if (m.mount) return 200;
  return 0;
}

export function search(s, depth, me, alpha = -Infinity, beta = Infinity) {
  if (isOver(s) || depth === 0) return { score: evaluate(s, me), move: null };

  const moves = movesOrPass(s);
  moves.sort((a, b) => scoreMove(s, b) - scoreMove(s, a));

  const maximizing = s.turn === me;
  let best = null;
  let bestScore = maximizing ? -Infinity : Infinity;

  for (const m of moves) {
    const ns = applyMove(s, m);
    const r = search(ns, depth - 1, me, alpha, beta);
    // prefer faster wins / slower losses
    const sc = r.score > WIN / 2 ? r.score - 1 : r.score < -WIN / 2 ? r.score + 1 : r.score;
    if (maximizing) {
      if (sc > bestScore) (bestScore = sc), (best = m);
      alpha = Math.max(alpha, bestScore);
    } else {
      if (sc < bestScore) (bestScore = sc), (best = m);
      beta = Math.min(beta, bestScore);
    }
    if (beta <= alpha) break;
  }
  return { score: bestScore, move: best };
}

/**
 * Pick a move for the side to move.
 * `temperature` (0..1) mixes in near-optimal alternatives so that repeated
 * self-play games do not all follow the same line.
 */
export function chooseMove(s, depth, rng = Math.random, temperature = 0) {
  const me = s.turn;
  const moves = movesOrPass(s);
  if (moves.length === 1) return moves[0];
  const scored = moves.map((m) => {
    const ns = applyMove(s, m);
    const r = search(ns, depth - 1, me);
    return { m, score: r.score };
  });
  scored.sort((a, b) => b.score - a.score);
  if (temperature <= 0) {
    const top = scored.filter((x) => x.score === scored[0].score);
    return top[(rng() * top.length) | 0].m;
  }
  const slack = temperature * 60;
  const pool = scored.filter((x) => x.score >= scored[0].score - slack);
  return pool[(rng() * pool.length) | 0].m;
}

/** Squares from which an enemy BODY could tackle the stack at `i` fatally. */
export function fatalTackleSquares(s, i) {
  const out = [];
  for (const [dx, dy] of ORTHO) {
    const fx = xOf(i) - dx;
    const fy = yOf(i) - dy;
    if (!onBoard(fx, fy)) continue;
    const px = xOf(i) + dx;
    const py = yOf(i) + dy;
    const blocked = !onBoard(px, py) || s.cells[idx(px, py)] !== 0;
    if (blocked) out.push(idx(fx, fy));
  }
  return out;
}
