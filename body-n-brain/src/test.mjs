// BODY N BRAIN — rule tests.  node src/test.mjs

import {
  initialState,
  legalMoves,
  applyMove,
  makeRules,
  idx,
  bodyOf,
  brainOf,
  stackOf,
  judge,
  EMPTY,
} from "./engine.mjs";

let pass = 0;
const fails = [];
function ok(name, cond) {
  if (cond) pass++;
  else fails.push(name);
}

/** Build a position from a {square: code} map. */
function pos(cells, turn = 0, over = {}) {
  const s = initialState(makeRules(over));
  s.cells.fill(EMPTY);
  for (const [i, v] of Object.entries(cells)) s.cells[i] = v;
  s.turn = turn;
  s.ply = 4; // past the opening tax
  return s;
}

const find = (s, pred) => legalMoves(s).find(pred);

// --- opening tax -----------------------------------------------------------
{
  const s = initialState(makeRules());
  const kinds = new Set(legalMoves(s).map((m) => m.kind));
  ok("opening tax: BLUE's first move is BODY-only", kinds.size === 1 && kinds.has("body"));
  ok(
    "opening tax: no mounting on move 1",
    legalMoves(s).every((m) => !m.mount)
  );
  const after = applyMove(s, legalMoves(s)[0]);
  ok(
    "opening tax: RED is unrestricted",
    new Set(legalMoves(after).map((m) => m.kind)).size > 1
  );
}

// --- mounting --------------------------------------------------------------
{
  // BRAIN b1 moves diagonally onto its own BODY at c2
  const s = pos({ [idx(1, 0)]: brainOf(0), [idx(2, 1)]: bodyOf(0), [idx(0, 3)]: brainOf(1) });
  const m = find(s, (x) => x.kind === "brain" && x.mount);
  ok("BRAIN mounts a friendly BODY diagonally", !!m);
  ok("mount produces a stack", applyMove(s, m).cells[idx(2, 1)] === stackOf(0));

  // BODY slides under its own lone BRAIN
  const s2 = pos({ [idx(1, 0)]: bodyOf(0), [idx(1, 1)]: brainOf(0), [idx(0, 3)]: brainOf(1) });
  const m2 = find(s2, (x) => x.kind === "body" && x.mount);
  ok("BODY slides under a friendly BRAIN", !!m2);
  ok("that also produces a stack", applyMove(s2, m2).cells[idx(1, 1)] === stackOf(0));
}

// --- BRAIN may never capture ----------------------------------------------
{
  const s = pos({ [idx(1, 1)]: brainOf(0), [idx(2, 2)]: bodyOf(1), [idx(0, 3)]: brainOf(1) });
  ok(
    "lone BRAIN cannot capture",
    !legalMoves(s).some((m) => m.kind === "brain" && m.to === idx(2, 2))
  );
}

// --- lone BODY cannot capture a stack, only tackle it ----------------------
{
  const s = pos({ [idx(1, 1)]: bodyOf(0), [idx(2, 1)]: stackOf(1), [idx(0, 0)]: brainOf(0) });
  const toStack = legalMoves(s).filter((m) => (m.to ?? m.target) === idx(2, 1));
  ok("BODY cannot capture a stack outright", !toStack.some((m) => m.kind === "body"));
  const t = toStack.find((m) => m.kind === "tackle");
  ok("BODY can tackle an adjacent stack", !!t);
  ok("tackle push square is one further along", t.push === idx(3, 1));

  const n = applyMove(s, t);
  ok("tackler does not move", n.cells[idx(1, 1)] === bodyOf(0));
  ok("tackled stack becomes a lone BODY", n.cells[idx(2, 1)] === bodyOf(1));
  ok("knocked-off BRAIN lands behind", n.cells[idx(3, 1)] === brainOf(1));
  ok("tackle alone does not end the game", n.winner === null);
}

// --- tackle into a wall destroys the BRAIN --------------------------------
{
  // BLUE body c2, RED stack d2 — nothing beyond d2, so the BRAIN is crushed
  const s = pos({ [idx(2, 1)]: bodyOf(0), [idx(3, 1)]: stackOf(1), [idx(0, 0)]: brainOf(0) });
  const t = find(s, (m) => m.kind === "tackle");
  ok("wall tackle is flagged as fatal", t && t.push === -1);
  const n = applyMove(s, t);
  ok("wall tackle wins the game", n.winner === 0 && n.reason === "brain");
}

// --- tackle into an occupied square also destroys the BRAIN ---------------
{
  const s = pos({
    [idx(1, 1)]: bodyOf(0),
    [idx(2, 1)]: stackOf(1),
    [idx(3, 1)]: bodyOf(0),
    [idx(0, 0)]: brainOf(0),
  });
  const t = find(s, (m) => m.kind === "tackle" && m.target === idx(2, 1));
  ok("blocked tackle is fatal", t && t.push === -1);
  ok("blocked tackle wins", applyMove(s, t).winner === 0);
}

// --- stack movement --------------------------------------------------------
{
  const s = pos({ [idx(1, 1)]: stackOf(0), [idx(0, 3)]: brainOf(1) });
  const dists = legalMoves(s)
    .filter((m) => m.kind === "stack")
    .map((m) => m.dist);
  ok("stack slides up to 2", Math.max(...dists) === 2);

  // a piece in the way blocks the far square
  const s2 = pos({ [idx(1, 1)]: stackOf(0), [idx(1, 2)]: bodyOf(0), [idx(0, 3)]: brainOf(1) });
  ok(
    "stack cannot jump over a piece",
    !legalMoves(s2).some((m) => m.kind === "stack" && m.to === idx(1, 3))
  );
}

// --- stack captures stack = instant win ------------------------------------
{
  const s = pos({ [idx(1, 1)]: stackOf(0), [idx(2, 2)]: stackOf(1) });
  const m = find(s, (x) => x.kind === "stack" && x.to === idx(2, 2));
  ok("stack may capture a stack", !!m);
  ok("capturing a stack wins", applyMove(s, m).winner === 0);

  const s2 = pos({ [idx(1, 1)]: stackOf(0), [idx(2, 2)]: stackOf(1) }, 0, {
    stackCapturesStack: false,
  });
  ok(
    "rule flag disables stack-takes-stack",
    !legalMoves(s2).some((x) => x.kind === "stack" && x.to === idx(2, 2))
  );
}

// --- invasion: only a lone BRAIN scores, and only after surviving a turn ---
{
  // BLUE lone BRAIN already on rank 4; RED to move and cannot reach it
  const s = pos({ [idx(0, 3)]: brainOf(0), [idx(3, 0)]: brainOf(1), [idx(3, 1)]: bodyOf(1) }, 1);
  const quiet = legalMoves(s).find((m) => (m.to ?? m.target) !== idx(0, 3));
  const n = applyMove(s, quiet);
  ok("invasion scores once BLUE's turn comes round", n.winner === 0 && n.reason === "invasion");

  // a mounted BRAIN on the goal rank does not score
  const s2 = pos({ [idx(0, 3)]: stackOf(0), [idx(3, 0)]: brainOf(1), [idx(3, 1)]: bodyOf(1) }, 1);
  const quiet2 = legalMoves(s2).find((m) => (m.to ?? m.target) !== idx(0, 3));
  ok("a stack on the goal rank does not score", applyMove(s2, quiet2).winner === null);

  // and RED can simply capture the intruder instead
  const s3 = pos({ [idx(0, 3)]: brainOf(0), [idx(1, 3)]: bodyOf(1), [idx(3, 0)]: brainOf(1) }, 1);
  const kill = find(s3, (m) => m.kind === "body" && m.to === idx(0, 3));
  ok("the defender can capture the invading BRAIN", !!kill);
  ok("capturing it wins outright", applyMove(s3, kill).winner === 1);
}

// --- judgement -------------------------------------------------------------
{
  // BLUE brain on rank 3 (depth 2), RED brain on rank 4 (depth 0)
  const s = pos({ [idx(0, 2)]: brainOf(0), [idx(3, 3)]: brainOf(1) });
  ok("judgement rewards the deeper BRAIN", judge(s).winner === 0);

  // equal depth: komi 0.5 hands it to RED
  const s2 = pos({ [idx(0, 0)]: brainOf(0), [idx(3, 3)]: brainOf(1) });
  ok("komi breaks an exact tie for RED", judge(s2).winner === 1);

  // equal depth with komi 0: BODY count decides
  const s3 = pos({ [idx(0, 0)]: brainOf(0), [idx(3, 3)]: brainOf(1), [idx(1, 1)]: bodyOf(0) }, 0, {
    komi: 0,
  });
  ok("BODY count is the second tiebreak", judge(s3).winner === 0);
}

// --- a full game always terminates ----------------------------------------
{
  let s = initialState(makeRules());
  let guard = 0;
  while (s.winner === null && guard++ < 500) {
    const ms = legalMoves(s);
    s = applyMove(s, ms.length ? ms[guard % ms.length] : { kind: "pass" });
  }
  ok("games terminate", s.winner !== null && guard < 500);
}

console.log(`${pass} passed, ${fails.length} failed`);
if (fails.length) {
  for (const f of fails) console.log("  FAIL: " + f);
  process.exit(1);
}
