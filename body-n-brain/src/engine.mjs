// BODY N BRAIN — rules engine
//
// 4x4 board (16 squares). Two players: 0 = BLUE (先手), 1 = RED (後手).
//
// Cell codes:
//   0 empty
//   1 BODY  of P0     2 BODY  of P1
//   3 BRAIN of P0     4 BRAIN of P1
//   5 STACK of P0     6 STACK of P1   (a BODY carrying its own BRAIN)
//
// Every rule that affects balance is exposed through a `rules` object so the
// balance harness (src/sweep.mjs) can measure variants instead of guessing.

export const W = 4;
export const H = 4;
export const N = W * H;

export const EMPTY = 0;
export const bodyOf = (p) => 1 + p;
export const brainOf = (p) => 3 + p;
export const stackOf = (p) => 5 + p;

export const ownerOf = (c) => (c === 0 ? -1 : (c - 1) & 1);
export const isBody = (c) => c === 1 || c === 2;
export const isBrain = (c) => c === 3 || c === 4;
export const isStack = (c) => c === 5 || c === 6;

export const ORTHO = [
  [1, 0],
  [-1, 0],
  [0, 1],
  [0, -1],
];
export const DIAG = [
  [1, 1],
  [1, -1],
  [-1, 1],
  [-1, -1],
];
export const ALL8 = [...ORTHO, ...DIAG];

export const xOf = (i) => i % W;
export const yOf = (i) => (i / W) | 0;
export const idx = (x, y) => y * W + x;
export const onBoard = (x, y) => x >= 0 && x < W && y >= 0 && y < H;

export const FILES = "abcd";
export const sqName = (i) => FILES[xOf(i)] + (yOf(i) + 1);

function step(i, dx, dy) {
  const x = xOf(i) + dx;
  const y = yOf(i) + dy;
  return onBoard(x, y) ? idx(x, y) : -1;
}

// ---------------------------------------------------------------------------
// Rules
// ---------------------------------------------------------------------------

// Tuned by self-play sweep (see docs/BALANCE.md). Measured at depth 4 over 180
// low-noise games: first player 53.3%, draws 0%, ~21 plies, with all three win
// mechanics (capture / invasion / judgement) firing regularly.
export const DEFAULT_RULES = {
  bodies: 3, // BODY pieces per player (plus exactly one BRAIN)
  stackRange: 2, // how far a whole stack may slide
  stackCapturesStack: true, // a stack may capture another stack outright
  tackle: true, // a BODY may charge a stack and knock the BRAIN off
  invasion: "lone", // 'none' | 'lone' | 'any' — only a dismounted BRAIN scores
  komi: 0.5, // judgement bonus for RED, compensating BLUE's first move
  openingTax: true, // BLUE's first move must be a plain BODY step (no mount)
  redPreMounted: false, // RED starts already combined, BLUE does not
  maxPly: 60,
};

export function makeRules(over = {}) {
  return { ...DEFAULT_RULES, ...over };
}

/** Back-rank setup for P0; P1 mirrors it through a 180-degree rotation. */
function backRank(bodies) {
  // index 0..3 == a1..d1
  if (bodies <= 2) return ["B", "R", "B", null];
  if (bodies === 3) return ["B", "R", "B", "B"];
  return ["B", "R", "B", "B"]; // 4 bodies do not fit alongside the brain
}

export const goalRank = (p) => (p === 0 ? H - 1 : 0);

// ---------------------------------------------------------------------------
// State
// ---------------------------------------------------------------------------

export function initialState(rules = DEFAULT_RULES) {
  const cells = new Int8Array(N);
  const pat = backRank(rules.bodies);
  for (let x = 0; x < W; x++) {
    const p = pat[x];
    if (!p) continue;
    cells[x] = p === "B" ? bodyOf(0) : brainOf(0);
    cells[N - 1 - x] = p === "B" ? bodyOf(1) : brainOf(1);
  }
  if (rules.redPreMounted) {
    // RED's BRAIN begins the game already riding one of its BODY pieces, and
    // RED fields one fewer piece on the board as a result. This is the
    // compensation for moving second.
    for (let i = 0; i < N; i++) if (cells[i] === brainOf(1)) cells[i] = stackOf(1);
    for (let i = N - 1; i >= 0; i--) {
      if (cells[i] === bodyOf(1)) {
        cells[i] = EMPTY;
        break;
      }
    }
  }
  return { cells, turn: 0, ply: 0, passes: 0, winner: null, reason: null, rules };
}

export function cloneState(s) {
  return {
    cells: Int8Array.from(s.cells),
    turn: s.turn,
    ply: s.ply,
    passes: s.passes,
    winner: s.winner,
    reason: s.reason,
    rules: s.rules,
  };
}

export function hashState(s) {
  let h = "";
  for (let i = 0; i < N; i++) h += s.cells[i];
  return h + "|" + s.turn;
}

export function hasBrainOnBoard(s, p) {
  const b = brainOf(p);
  const st = stackOf(p);
  for (let i = 0; i < N; i++) if (s.cells[i] === b || s.cells[i] === st) return true;
  return false;
}

/** Is `p`'s BRAIN standing on the enemy home rank in a way that scores? */
export function brainOnGoal(s, p) {
  const mode = s.rules.invasion;
  if (mode === "none") return false;
  const y = goalRank(p);
  const lone = brainOf(p);
  const st = stackOf(p);
  for (let x = 0; x < W; x++) {
    const c = s.cells[idx(x, y)];
    if (c === lone) return true;
    if (mode === "any" && c === st) return true;
  }
  return false;
}

/**
 * Positional judgement used when the game stops making progress (3-fold
 * repetition or the ply limit). Shuffling is therefore never a safe way to
 * hold a draw: the player who has pushed their BRAIN deeper — and failing
 * that, the player with more BODY pieces — takes the point.
 *
 * Returns { winner: 0 | 1 | -1, depth: [d0, d1], bodies: [b0, b1] }.
 */
export function judge(s) {
  const depth = [0, 0];
  const bodies = [0, 0];
  for (let i = 0; i < N; i++) {
    const c = s.cells[i];
    if (c === 0) continue;
    const o = ownerOf(c);
    if (isBody(c) || isStack(c)) bodies[o] += 1;
    if (isBrain(c) || isStack(c)) depth[o] = H - 1 - Math.abs(yOf(i) - goalRank(o));
  }
  const komi = s.rules.komi || 0;
  let winner = -1;
  if (depth[0] !== depth[1] + komi) winner = depth[0] > depth[1] + komi ? 0 : 1;
  else if (bodies[0] !== bodies[1]) winner = bodies[0] > bodies[1] ? 0 : 1;
  return { winner, depth, bodies, komi };
}

// ---------------------------------------------------------------------------
// Move generation
//
//   'body'    a lone BODY — or the BODY stepping out from under its BRAIN —
//             walks one orthogonal step; captures a lone enemy piece by
//             displacement; sliding onto a friendly lone BRAIN mounts it.
//   'tackle'  a BODY charges an adjacent enemy STACK. The stack is not
//             captured, but its BRAIN is knocked one square further along the
//             charge line. If that square is off the board or occupied, the
//             BRAIN is destroyed. The charging piece never moves.
//   'brain'   a lone BRAIN — or the BRAIN dismounting — slides one diagonal
//             step. It can never capture. Landing on a friendly lone BODY
//             mounts it.
//   'stack'   a whole stack slides up to `stackRange` squares in any of the 8
//             directions without jumping, capturing a lone enemy piece.
// ---------------------------------------------------------------------------

export function legalMoves(s, player = s.turn) {
  const c = s.cells;
  const r = s.rules;
  const moves = [];
  const me = player;
  const opp = 1 - player;

  for (let i = 0; i < N; i++) {
    const cell = c[i];
    if (cell === 0 || ownerOf(cell) !== me) continue;
    const stack = isStack(cell);

    if (isBody(cell) || stack) {
      for (const [dx, dy] of ORTHO) {
        const t = step(i, dx, dy);
        if (t < 0) continue;
        const tc = c[t];
        if (tc === 0) {
          moves.push({ kind: "body", from: i, to: t, split: stack });
        } else if (ownerOf(tc) === opp) {
          if (isStack(tc)) {
            if (!r.tackle) continue;
            const push = step(t, dx, dy);
            const blocked = push < 0 || c[push] !== 0;
            moves.push({ kind: "tackle", from: i, target: t, push: blocked ? -1 : push });
          } else {
            moves.push({ kind: "body", from: i, to: t, capture: tc, split: stack });
          }
        } else if (!stack && isBrain(tc)) {
          moves.push({ kind: "body", from: i, to: t, mount: true });
        }
      }
    }

    if (isBrain(cell) || stack) {
      for (const [dx, dy] of DIAG) {
        const t = step(i, dx, dy);
        if (t < 0) continue;
        const tc = c[t];
        if (tc === 0) moves.push({ kind: "brain", from: i, to: t, split: stack });
        else if (ownerOf(tc) === me && isBody(tc))
          moves.push({ kind: "brain", from: i, to: t, mount: true, split: stack });
      }
    }

    if (stack) {
      for (const [dx, dy] of ALL8) {
        let t = i;
        for (let n = 1; n <= r.stackRange; n++) {
          t = step(t, dx, dy);
          if (t < 0) break;
          const tc = c[t];
          if (tc === 0) {
            moves.push({ kind: "stack", from: i, to: t, dist: n });
            continue;
          }
          if (ownerOf(tc) === opp && (!isStack(tc) || r.stackCapturesStack)) {
            moves.push({ kind: "stack", from: i, to: t, dist: n, capture: tc });
          }
          break;
        }
      }
    }
  }

  if (r.openingTax && s.ply === 0 && me === 0) {
    // BLUE pays for the initiative: its opening move must be a plain BODY step
    const taxed = moves.filter((m) => m.kind === "body" && !m.mount);
    if (taxed.length) return taxed;
  }
  return moves;
}

// ---------------------------------------------------------------------------
// Applying moves
// ---------------------------------------------------------------------------

export function applyMove(s, m) {
  const n = cloneState(s);
  const c = n.cells;
  const me = s.turn;
  const opp = 1 - me;

  switch (m.kind) {
    case "body":
      c[m.from] = m.split ? brainOf(me) : EMPTY;
      c[m.to] = m.mount ? stackOf(me) : bodyOf(me);
      break;
    case "brain":
      c[m.from] = m.split ? bodyOf(me) : EMPTY;
      c[m.to] = m.mount ? stackOf(me) : brainOf(me);
      break;
    case "stack":
      c[m.from] = EMPTY;
      c[m.to] = stackOf(me);
      break;
    case "tackle":
      // the charging piece never leaves its square
      c[m.target] = bodyOf(opp);
      if (m.push >= 0) c[m.push] = brainOf(opp);
      break;
    case "pass":
      break;
    default:
      throw new Error("unknown move kind: " + m.kind);
  }

  n.ply = s.ply + 1;
  n.passes = m.kind === "pass" ? s.passes + 1 : 0;
  n.turn = opp;

  if (!hasBrainOnBoard(n, opp)) {
    n.winner = me;
    n.reason = "brain";
  } else if (brainOnGoal(n, opp)) {
    // the opponent planted a BRAIN on our home rank and it survived our reply,
    // so they win as their turn begins
    n.winner = opp;
    n.reason = "invasion";
  } else if (n.passes >= 2 || n.ply >= n.rules.maxPly) {
    n.winner = judge(n).winner;
    n.reason = "judgement";
  }
  return n;
}

export function movesOrPass(s) {
  const ms = legalMoves(s);
  return ms.length ? ms : [{ kind: "pass" }];
}

export const isOver = (s) => s.winner !== null;

export function moveText(m) {
  switch (m.kind) {
    case "body":
      return `BODY ${sqName(m.from)}→${sqName(m.to)}${m.mount ? " 合体" : ""}${
        m.capture ? " ×" : ""
      }${m.split ? " 分離" : ""}`;
    case "brain":
      return `BRAIN ${sqName(m.from)}→${sqName(m.to)}${m.mount ? " 合体" : ""}${
        m.split ? " 分離" : ""
      }`;
    case "stack":
      return `MECH ${sqName(m.from)}→${sqName(m.to)}${m.capture ? " ×" : ""}`;
    case "tackle":
      return `TACKLE ${sqName(m.from)}→${sqName(m.target)}${
        m.push < 0 ? " 撃墜!!" : ` (BRAIN→${sqName(m.push)})`
      }`;
    case "pass":
      return "パス";
  }
  return "?";
}
