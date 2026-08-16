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
  goalRank,
  EMPTY,
} from "./engine.mjs";

let pass = 0;
const fails = [];
function ok(name, cond) {
  if (cond) pass++;
  else fails.push(name);
}

const SIZE = makeRules().size;
const at = (x, y) => idx(x, y, SIZE);

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

// --- board setup -----------------------------------------------------------
{
  for (const size of [4, 5, 6, 7]) {
    const s = initialState(makeRules({ size }));
    const mine = [...s.cells].filter((c) => c === bodyOf(0) || c === brainOf(0));
    ok(`${size}x${size}: each player fields size pieces`, mine.length === size);
    ok(
      `${size}x${size}: exactly one BRAIN each`,
      [...s.cells].filter((c) => c === brainOf(0)).length === 1 &&
        [...s.cells].filter((c) => c === brainOf(1)).length === 1
    );
    // 180-degree rotational symmetry between the two setups
    const n = size * size;
    let symmetric = true;
    for (let i = 0; i < n; i++) {
      const a = s.cells[i];
      const b = s.cells[n - 1 - i];
      const kindA = a === 0 ? 0 : a === bodyOf(0) || a === bodyOf(1) ? 1 : 2;
      const kindB = b === 0 ? 0 : b === bodyOf(0) || b === bodyOf(1) ? 1 : 2;
      if (kindA !== kindB) symmetric = false;
    }
    ok(`${size}x${size}: setup is rotationally symmetric`, symmetric);
  }
}

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
  ok("opening tax: RED is unrestricted", new Set(legalMoves(after).map((m) => m.kind)).size > 1);
}

// --- mounting --------------------------------------------------------------
{
  const s = pos({ [at(1, 0)]: brainOf(0), [at(2, 1)]: bodyOf(0), [at(0, SIZE - 1)]: brainOf(1) });
  const m = find(s, (x) => x.kind === "brain" && x.mount);
  ok("BRAIN mounts a friendly BODY diagonally", !!m);
  ok("mount produces a stack", applyMove(s, m).cells[at(2, 1)] === stackOf(0));

  const s2 = pos({ [at(1, 0)]: bodyOf(0), [at(1, 1)]: brainOf(0), [at(0, SIZE - 1)]: brainOf(1) });
  const m2 = find(s2, (x) => x.kind === "body" && x.mount);
  ok("BODY slides under a friendly BRAIN", !!m2);
  ok("that also produces a stack", applyMove(s2, m2).cells[at(1, 1)] === stackOf(0));
}

// --- BRAIN may never capture ----------------------------------------------
{
  const s = pos({ [at(1, 1)]: brainOf(0), [at(2, 2)]: bodyOf(1), [at(0, SIZE - 1)]: brainOf(1) });
  ok(
    "lone BRAIN cannot capture",
    !legalMoves(s).some((m) => m.kind === "brain" && m.to === at(2, 2))
  );
}

// --- lone BODY cannot capture a stack, only tackle it ----------------------
{
  const s = pos({ [at(1, 1)]: bodyOf(0), [at(2, 1)]: stackOf(1), [at(0, 0)]: brainOf(0) });
  const toStack = legalMoves(s).filter((m) => (m.to ?? m.target) === at(2, 1));
  ok("BODY cannot capture a stack outright", !toStack.some((m) => m.kind === "body"));
  const t = toStack.find((m) => m.kind === "tackle");
  ok("BODY can tackle an adjacent stack", !!t);
  ok("tackle push square is one further along", t.push === at(3, 1));

  const n = applyMove(s, t);
  ok("tackler does not move", n.cells[at(1, 1)] === bodyOf(0));
  ok("tackled stack becomes a lone BODY", n.cells[at(2, 1)] === bodyOf(1));
  ok("knocked-off BRAIN lands behind", n.cells[at(3, 1)] === brainOf(1));
  ok("tackle alone does not end the game", n.winner === null);
}

// --- tackle into a wall destroys the BRAIN --------------------------------
{
  const e = SIZE - 1;
  const s = pos({ [at(e - 1, 1)]: bodyOf(0), [at(e, 1)]: stackOf(1), [at(0, 0)]: brainOf(0) });
  const t = find(s, (m) => m.kind === "tackle");
  ok("wall tackle is flagged as fatal", t && t.push === -1);
  const n = applyMove(s, t);
  ok("wall tackle wins the game", n.winner === 0 && n.reason === "brain");
}

// --- tackle into an occupied square also destroys the BRAIN ---------------
{
  const s = pos({
    [at(1, 1)]: bodyOf(0),
    [at(2, 1)]: stackOf(1),
    [at(3, 1)]: bodyOf(0),
    [at(0, 0)]: brainOf(0),
  });
  const t = find(s, (m) => m.kind === "tackle" && m.target === at(2, 1));
  ok("blocked tackle is fatal", t && t.push === -1);
  ok("blocked tackle wins", applyMove(s, t).winner === 0);
}

// --- stack movement --------------------------------------------------------
{
  const s = pos({ [at(1, 1)]: stackOf(0), [at(0, SIZE - 1)]: brainOf(1) });
  const dists = legalMoves(s)
    .filter((m) => m.kind === "stack")
    .map((m) => m.dist);
  ok("stack slides up to stackRange", Math.max(...dists) === makeRules().stackRange);

  const s2 = pos({ [at(1, 1)]: stackOf(0), [at(1, 2)]: bodyOf(0), [at(0, SIZE - 1)]: brainOf(1) });
  ok(
    "stack cannot jump over a piece",
    !legalMoves(s2).some((m) => m.kind === "stack" && m.to === at(1, 3))
  );
}

// --- stack captures stack = instant win ------------------------------------
{
  const s = pos({ [at(1, 1)]: stackOf(0), [at(2, 2)]: stackOf(1) });
  const m = find(s, (x) => x.kind === "stack" && x.to === at(2, 2));
  ok("stack may capture a stack", !!m);
  ok("capturing a stack wins", applyMove(s, m).winner === 0);

  const s2 = pos({ [at(1, 1)]: stackOf(0), [at(2, 2)]: stackOf(1) }, 0, {
    stackCapturesStack: false,
  });
  ok(
    "rule flag disables stack-takes-stack",
    !legalMoves(s2).some((x) => x.kind === "stack" && x.to === at(2, 2))
  );
}

// --- invasion: only a lone BRAIN scores, and only after surviving a turn ---
{
  const g0 = goalRank(0, SIZE); // BLUE's target rank
  // BLUE lone BRAIN already on the goal rank; RED to move and far away
  const s = pos({ [at(0, g0)]: brainOf(0), [at(SIZE - 1, 0)]: brainOf(1) }, 1);
  const quiet = legalMoves(s).find((m) => (m.to ?? m.target) !== at(0, g0));
  const n = applyMove(s, quiet);
  ok("invasion scores once BLUE's turn comes round", n.winner === 0 && n.reason === "invasion");

  // a mounted BRAIN on the goal rank does not score
  const s2 = pos({ [at(0, g0)]: stackOf(0), [at(SIZE - 1, 0)]: brainOf(1) }, 1);
  const quiet2 = legalMoves(s2).find((m) => (m.to ?? m.target) !== at(0, g0));
  ok("a stack on the goal rank does not score", applyMove(s2, quiet2).winner === null);

  // and the defender can simply capture the intruder instead
  const s3 = pos({ [at(0, g0)]: brainOf(0), [at(1, g0)]: bodyOf(1), [at(SIZE - 1, 0)]: brainOf(1) }, 1);
  const kill = find(s3, (m) => m.kind === "body" && m.to === at(0, g0));
  ok("the defender can capture the invading BRAIN", !!kill);
  ok("capturing it wins outright", applyMove(s3, kill).winner === 1);
}

// --- judgement -------------------------------------------------------------
{
  // BLUE brain one rank from its goal, RED brain still at home
  const s = pos({ [at(0, SIZE - 2)]: brainOf(0), [at(SIZE - 1, SIZE - 1)]: brainOf(1) });
  ok("judgement rewards the deeper BRAIN", judge(s).winner === 0);

  // equal depth: komi 0.5 hands it to RED
  const s2 = pos({ [at(0, 0)]: brainOf(0), [at(SIZE - 1, SIZE - 1)]: brainOf(1) });
  ok("komi breaks an exact tie for RED", judge(s2).winner === 1);

  // equal depth with komi 0: BODY count decides
  const s3 = pos(
    { [at(0, 0)]: brainOf(0), [at(SIZE - 1, SIZE - 1)]: brainOf(1), [at(1, 1)]: bodyOf(0) },
    0,
    { komi: 0 }
  );
  ok("BODY count is the second tiebreak", judge(s3).winner === 0);
}

// --- a full game always terminates at every size --------------------------
{
  for (const size of [4, 5, 6, 7]) {
    let s = initialState(makeRules({ size }));
    let guard = 0;
    while (s.winner === null && guard++ < 2000) {
      const ms = legalMoves(s);
      s = applyMove(s, ms.length ? ms[guard % ms.length] : { kind: "pass" });
    }
    ok(`${size}x${size}: games terminate`, s.winner !== null && guard < 2000);
  }
}

console.log(`${pass} passed, ${fails.length} failed`);
if (fails.length) {
  for (const f of fails) console.log("  FAIL: " + f);
  process.exit(1);
}
