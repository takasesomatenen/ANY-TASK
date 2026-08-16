// BODY N BRAIN — rule sweep.
//
//   node src/sweep.mjs [games] [depth] [mode]
//
// mode 'size'  (default) — board size x stack range, the question of how big
//                          the board should be
// mode 'rules'            — the mechanic flags, at the chosen board size
//
// Measures every candidate so the published ruleset is chosen from data rather
// than intuition.

import { makeRules } from "./engine.mjs";
import { measure, report } from "./balance.mjs";

const games = Number(process.argv[2] || 60);
const depth = Number(process.argv[3] || 3);
const mode = process.argv[4] || "size";

const variants = [];
if (mode === "size") {
  for (const size of [5, 6, 7]) {
    for (const stackRange of [1, 2]) {
      for (const invasionSurvive of [1, 2]) {
        // let the clock grow with the board so bigger boards are not cut short
        variants.push({ size, stackRange, invasionSurvive, maxPly: 30 * size });
      }
    }
  }
} else {
  for (const stackCapturesStack of [false, true]) {
    for (const invasion of ["none", "lone", "any"]) {
      for (const openingTax of [false, true]) {
        variants.push({ stackCapturesStack, invasion, openingTax });
      }
    }
  }
}

const label = (v) =>
  mode === "size"
    ? `${v.size}x${v.size} (${v.size * v.size}マス) range${v.stackRange} 侵攻${v.invasionSurvive}手守`
    : `${v.stackCapturesStack ? "SxS" : "---"} inv:${String(v.invasion).padEnd(4)} tax:${
        v.openingTax ? "on " : "off"
      }`;

console.log(`sweep[${mode}]: ${variants.length} variants x ${games} games @ depth ${depth}\n`);
const rows = [];
for (const v of variants) {
  // two seeds so a single lucky run cannot decide the winner
  const ms = [11, 22].map((seed) =>
    measure({ rules: makeRules(v), games: Math.round(games / 2), depth, temperature: 0.2, seed })
  );
  const m = {
    p0: ms[0].p0 + ms[1].p0,
    p1: ms[0].p1 + ms[1].p1,
    draws: ms[0].draws + ms[1].draws,
    avgPlies: (ms[0].avgPlies + ms[1].avgPlies) / 2,
    reasons: {},
  };
  for (const x of ms) for (const k in x.reasons) m.reasons[k] = (m.reasons[k] || 0) + x.reasons[k];
  m.games = m.p0 + m.p1 + m.draws;
  m.firstPlayerShare = m.p0 + m.p1 ? m.p0 / (m.p0 + m.p1) : 0.5;
  m.drawRate = m.draws / m.games;
  rows.push({ v, m });
  report(label(v), m);
}

// Rank by how close a variant is to the design target: an even first-player
// share, few draws, and games long enough to hold a plan but short enough to
// finish. A variety of endings means no single mechanic is dominating.
const endingSpread = (m) => {
  const total = Object.values(m.reasons).reduce((a, b) => a + b, 0) || 1;
  const share = Object.values(m.reasons).map((v) => v / total);
  return share.reduce((a, p) => a + (p > 0 ? -p * Math.log(p) : 0), 0); // entropy
};

const cost = ({ m }) =>
  Math.abs(m.firstPlayerShare - 0.5) * 3 +
  m.drawRate * 1.5 +
  Math.max(0, 20 - m.avgPlies) * 0.03 +
  Math.max(0, m.avgPlies - 90) * 0.01 +
  (1 - endingSpread(m) / Math.log(3)) * 0.3;

rows.sort((a, b) => cost(a) - cost(b));
console.log("\n--- best balanced variants ---");
for (const r of rows.slice(0, 6)) {
  console.log(
    `  ${cost(r).toFixed(3)}  ${label(r.v)}   (決着理由の広がり ${endingSpread(r.m).toFixed(2)})`
  );
}
