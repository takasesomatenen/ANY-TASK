// BODY N BRAIN — rule sweep.
//
//   node src/sweep.mjs [games] [depth]
//
// Measures every candidate rule combination so the published ruleset is chosen
// from data rather than intuition.

import { makeRules } from "./engine.mjs";
import { measure, report } from "./balance.mjs";

const games = Number(process.argv[2] || 120);
const depth = Number(process.argv[3] || 3);

const variants = [];
for (const bodies of [2, 3]) {
  for (const stackRange of [1, 2]) {
    for (const stackCapturesStack of [false, true]) {
      for (const invasion of ["none", "lone", "any"]) {
        variants.push({ bodies, stackRange, stackCapturesStack, invasion });
      }
    }
  }
}

const label = (v) =>
  `body${v.bodies} range${v.stackRange} ${v.stackCapturesStack ? "SxS" : "---"} inv:${v.invasion}`;

console.log(`sweep: ${variants.length} variants x ${games} games @ depth ${depth}\n`);
const rows = [];
for (const v of variants) {
  const m = measure({ rules: makeRules(v), games, depth, temperature: 0.35 });
  rows.push({ v, m });
  report(label(v), m);
}

// Rank by how close a variant is to the design target:
//   50% first-player share, low draws, and games long enough to have a plan.
const cost = ({ m }) =>
  Math.abs(m.firstPlayerShare - 0.5) * 3 +
  m.drawRate * 1.5 +
  Math.max(0, 14 - m.avgPlies) * 0.03 +
  Math.max(0, m.avgPlies - 70) * 0.01;

rows.sort((a, b) => cost(a) - cost(b));
console.log("\n--- best balanced variants ---");
for (const r of rows.slice(0, 6)) {
  console.log(`  ${cost(r).toFixed(3)}  ${label(r.v)}`);
}
