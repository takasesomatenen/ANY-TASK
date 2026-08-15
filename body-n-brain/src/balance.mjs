// BODY N BRAIN — self-play balance harness.
//
//   node src/balance.mjs [games] [depth] [temperature]
//
// Reports first-player win rate, draw rate, game length and how games end.
// A healthy configuration sits near 50/50 with few draws, a game length that
// leaves room for a plan, and a mix of endings (no single mechanic dominating).

import {
  initialState,
  applyMove,
  movesOrPass,
  isOver,
  hashState,
  moveText,
  makeRules,
  DEFAULT_RULES,
  judge,
} from "./engine.mjs";
import { chooseMove } from "./ai.mjs";

export function mulberry32(a) {
  return function () {
    a |= 0;
    a = (a + 0x6d2b79f5) | 0;
    let t = Math.imul(a ^ (a >>> 15), 1 | a);
    t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t;
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}

export function playGame({
  rules = DEFAULT_RULES,
  depth = 3,
  depths, // optional [blueDepth, redDepth] for skill-gap matches
  rng,
  temperature = 0.35,
  trace,
} = {}) {
  let s = initialState(rules);
  const seen = new Map();
  const log = [];
  while (!isOver(s)) {
    const moves = movesOrPass(s);
    const d = depths ? depths[s.turn] : depth;
    const m = moves.length === 1 ? moves[0] : chooseMove(s, d, rng, temperature);
    if (trace) log.push(`${s.ply + 1}. ${s.turn === 0 ? "BLUE" : "RED "} ${moveText(m)}`);
    s = applyMove(s, m);
    const h = hashState(s);
    const c = (seen.get(h) || 0) + 1;
    seen.set(h, c);
    if (c >= 3) {
      s = { ...s, winner: judge(s).winner, reason: "repetition" };
      break;
    }
  }
  return { winner: s.winner, reason: s.reason, plies: s.ply, log };
}

export function measure({
  rules,
  games = 120,
  depth = 3,
  depths,
  temperature = 0.35,
  seed = 20260815,
}) {
  const rng = mulberry32(seed);
  const tally = { 0: 0, 1: 0, "-1": 0 };
  const reasons = {};
  let plies = 0;
  for (let g = 0; g < games; g++) {
    const r = playGame({ rules, depth, depths, rng, temperature });
    tally[r.winner] += 1;
    reasons[r.reason || "?"] = (reasons[r.reason || "?"] || 0) + 1;
    plies += r.plies;
  }
  const decisive = tally[0] + tally[1];
  return {
    games,
    p0: tally[0],
    p1: tally[1],
    draws: tally["-1"],
    firstPlayerShare: decisive ? tally[0] / decisive : 0.5,
    drawRate: tally["-1"] / games,
    avgPlies: plies / games,
    reasons,
  };
}

export function report(label, m) {
  const pct = (x) => (100 * x).toFixed(1).padStart(5) + "%";
  console.log(
    `${label.padEnd(46)} 先手${pct(m.firstPlayerShare)}  引分${pct(m.drawRate)}  ` +
      `平均${m.avgPlies.toFixed(1).padStart(5)}手  ${JSON.stringify(m.reasons)}`
  );
}

function main() {
  const games = Number(process.argv[2] || 120);
  const depth = Number(process.argv[3] || 3);
  const temperature = Number(process.argv[4] ?? 0.35);
  const m = measure({ rules: makeRules(), games, depth, temperature });
  report("DEFAULT_RULES", m);
}

if (import.meta.url === `file://${process.argv[1]}`) main();
