// BODY N BRAIN — browser UI. Inlined into index.html by build.mjs.
// Player 0 is BLACK (solid pieces, moves first), player 1 is WHITE (outlined).

const $ = (id) => document.getElementById(id);
const boardEl = $("board");
const logEl = $("log");
const modebarEl = $("modebar");
const barEl = $("bar");

const RULES = makeRules();
const SIZE = RULES.size;
const SQ = (i) => sqName(i, SIZE);
const AT = (x, y) => idx(x, y, SIZE);
const SIDE = ["黒", "白"];

let state, history, sel, mode, lastMove, repeats, busy;
let aiSide, swapPending, swapUsed;
let teach = null; // tutorial progress, or null during a real game

/** Only swap on a real advantage — never on evaluation noise. */
const SWAP_MARGIN = 20;

const vsAI = () => $("opponent").value === "ai" && !teach;
const aiToMove = () => vsAI() && state.turn === aiSide;
const humanSide = () => (vsAI() ? 1 - aiSide : 0);
const flipped = () => humanSide() === 1;

// ---------------------------------------------------------------------------
// Tutorial — the player is taught by making each move themselves.
// Every step hand-places a position and only accepts the move it is teaching.
// ---------------------------------------------------------------------------

const TUTORIAL = [
  {
    title: "BODY は縦横に1マス",
    text: "<b>BODY（■）</b>は縦横に1マスだけ動きます。鈍いけれど、単体の敵駒を取れるのはこの駒です。動かしてみましょう。",
    cells: () => ({ [AT(2, 1)]: bodyOf(0), [AT(4, 3)]: bodyOf(1) }),
    accept: (m) => m.kind === "body",
  },
  {
    title: "BRAIN は斜めに1マス、駒を取れない",
    text: "<b>BRAIN（●）</b>は斜めに1マス。そして<b>絶対に駒を取れません</b>。右上の白い駒には入れないことを確かめてください。",
    cells: () => ({ [AT(2, 1)]: brainOf(0), [AT(3, 2)]: bodyOf(1) }),
    accept: (m) => m.kind === "brain",
  },
  {
    title: "重ねると、別の駒になる",
    text: "BRAIN を味方 BODY のマスへ動かすと<b>合体</b>。これがこのゲームの核心です。d3 の BODY に乗せてください。",
    cells: () => ({ [AT(2, 1)]: brainOf(0), [AT(3, 2)]: bodyOf(0) }),
    accept: (m) => m.mount === true,
  },
  {
    title: "合体駒は8方向に2マス",
    text: "合体駒は<b>8方向に最大2マス</b>滑ります。BODY にも BRAIN にも無い、まったく別の動きです。2マス動かしてみましょう。",
    cells: () => ({ [AT(2, 2)]: stackOf(0), [AT(4, 4)]: bodyOf(1) }),
    accept: (m) => m.kind === "stack" && m.dist === 2,
  },
  {
    title: "合体駒はタックルで崩す",
    text: "合体駒は単体の駒では<b>取れません</b>。代わりに BODY で体当たり（<b>タックル</b>）すると、上の BRAIN だけが1マス弾き飛ばされます。突撃した駒は動きません。",
    cells: () => ({ [AT(1, 2)]: bodyOf(0), [AT(2, 2)]: stackOf(1), [AT(0, 0)]: brainOf(0) }),
    accept: (m) => m.kind === "tackle",
    pause: 1100,
  },
  {
    title: "壁際の合体駒は即死する",
    text: "弾き飛ばす先が<b>盤外</b>か他の駒なら、BRAIN は撃墜されて<b>その場で勝ち</b>。合体駒は最強ですが、縁に出ると一撃で終わります。",
    cells: () => ({
      [AT(SIZE - 2, 2)]: bodyOf(0),
      [AT(SIZE - 1, 2)]: stackOf(1),
      [AT(0, 0)]: brainOf(0),
    }),
    accept: (m) => m.kind === "tackle" && m.push < 0,
    pause: 1100,
  },
  {
    title: "もう一つの勝ち方：侵攻",
    text: `敵陣の最奥（${SIZE}段目）に <b>BRAIN を降ろして</b>立たせ、相手の1手を生き延びても勝ちです。合体駒のまま乗り込んでも無効 — 必ず<b>分離</b>が要ります。BRAIN を最奥段へ降ろしてください。`,
    cells: () => ({ [AT(2, SIZE - 2)]: stackOf(0), [AT(0, 0)]: brainOf(1) }),
    accept: (m) => m.kind === "brain" && m.split && yOf(m.to, SIZE) === goalRank(0, SIZE),
    pause: 900,
  },
];

function startTutorial() {
  teach = { i: 0 };
  aiSide = 1;
  swapUsed = true;
  swapPending = false;
  loadTutorialStep();
}

function loadTutorialStep() {
  const step = TUTORIAL[teach.i];
  teach.done = false; // the new step has not been solved yet
  state = initialState(RULES);
  state.cells.fill(EMPTY);
  for (const [i, v] of Object.entries(step.cells())) state.cells[i] = v;
  state.ply = 4; // past the opening tax
  state.turn = 0;
  history = [];
  repeats = new Map();
  sel = null;
  lastMove = null;
  busy = false;
  // auto-select when only one piece can make the move being taught
  const froms = new Set(allowedMoves().map((m) => m.from));
  if (froms.size === 1) sel = [...froms][0];
  mode = defaultMode(sel);
  render();
}

function tutorialAdvance() {
  teach.i += 1;
  if (teach.i >= TUTORIAL.length) {
    teach = null;
    rememberTutorialDone();
    showVeil("チュートリアル終了", "7つのルールはこれで全部です。実戦へどうぞ。", [
      ["対局を始める", () => (closeVeil(), newGame()), true],
    ]);
    return;
  }
  loadTutorialStep();
}

const TEACH_KEY = "bodynbrain.taught";
function tutorialWasDone() {
  try {
    return localStorage.getItem(TEACH_KEY) === "1";
  } catch {
    return false;
  }
}
function rememberTutorialDone() {
  try {
    localStorage.setItem(TEACH_KEY, "1");
  } catch {
    /* private mode — just replay the tutorial next time */
  }
}

// ---------------------------------------------------------------------------
// Game
// ---------------------------------------------------------------------------

function newGame() {
  teach = null;
  state = initialState(RULES);
  history = [];
  repeats = new Map();
  sel = null;
  mode = "stack";
  lastMove = null;
  busy = false;
  aiSide = 1;
  swapPending = false;
  swapUsed = false;
  logEl.innerHTML = "";
  closeVeil();
  render();
}

/** Legal moves, narrowed to what the current tutorial step is teaching. */
function allowedMoves() {
  const ms = legalMoves(state);
  return teach ? ms.filter(TUTORIAL[teach.i].accept) : ms;
}

const movesFrom = (i) => allowedMoves().filter((m) => m.from === i);

function defaultMode(i) {
  if (i === null || i === undefined) return "stack";
  const kinds = new Set(movesFrom(i).map((x) => x.kind));
  return kinds.has("stack") ? "stack" : kinds.has("brain") ? "brain" : "body";
}

const MODES = [
  { key: "stack", label: "合体駒で動く", has: (m) => m.kind === "stack" || m.kind === "tackle" },
  { key: "brain", label: "BRAIN だけ降りる", has: (m) => m.kind === "brain" },
  { key: "body", label: "BODY だけ出る", has: (m) => m.kind === "body" || m.kind === "tackle" },
];

function offered() {
  if (sel === null) return [];
  const all = movesFrom(sel);
  if (!isStack(state.cells[sel])) return all;
  return all.filter(MODES.find((m) => m.key === mode).has);
}

const targetOf = (m) => (m.kind === "tackle" ? m.target : m.to);

// ---------------------------------------------------------------------------
// Rendering
// ---------------------------------------------------------------------------

function pieceHTML(c) {
  const p = ownerOf(c);
  if (isBody(c)) return `<div class="piece p${p}"><div class="pbody"></div></div>`;
  if (isBrain(c)) return `<div class="piece p${p} lone"><div class="pbrain"></div></div>`;
  return `<div class="piece p${p} stacked"><div class="pbody"></div><div class="pbrain"></div></div>`;
}

const markClass = (m) =>
  m.kind === "tackle" ? "mk-tackle" : m.capture ? "mk-take" : m.mount ? "mk-mount" : "mk-move";

function render() {
  const marks = new Map();
  for (const m of offered()) marks.set(targetOf(m), m);
  const teachTargets = teach ? new Set(allowedMoves().map(targetOf)) : null;

  boardEl.style.gridTemplateColumns = `repeat(${SIZE},1fr)`;
  boardEl.innerHTML = "";
  const flip = flipped();
  for (let row = 0; row < SIZE; row++) {
    for (let col = 0; col < SIZE; col++) {
      // 180-degree rotation when the human plays WHITE, so their own back rank
      // is always the near one
      const y = flip ? row : SIZE - 1 - row;
      const x = flip ? SIZE - 1 - col : col;
      const i = AT(x, y);

      const cell = document.createElement("div");
      let cls = "cell" + ((x + y) % 2 ? " alt" : "");
      if (y === 0 || y === SIZE - 1) cls += " goal";
      if (i === sel) cls += " sel";
      if (lastMove && (lastMove.from === i || targetOf(lastMove) === i)) cls += " last";
      if (teachTargets && teachTargets.has(i) && marks.size === 0) cls += " teachtarget";
      cell.className = cls;

      let html = `<span class="coord">${SQ(i)}</span>`;
      const c = state.cells[i];
      if (c !== 0) html += pieceHTML(c);
      const m = marks.get(i);
      if (m) html += `<span class="mk ${markClass(m)}"><i></i></span>`;
      cell.innerHTML = html;
      cell.onclick = () => onCell(i);
      boardEl.appendChild(cell);
    }
  }

  renderBar();
  renderModebar();
  $("undo").disabled = !history.length || busy || swapPending || !!teach;
}

function renderBar() {
  if (teach) {
    const step = TUTORIAL[teach.i];
    barEl.className = "bar teach";
    barEl.innerHTML =
      `<span class="step">${teach.i + 1}/${TUTORIAL.length}</span>` +
      `<p><b>${step.title}</b><br>${step.text}</p>`;
    return;
  }
  barEl.className = "bar";
  if (swapPending) {
    barEl.innerHTML =
      `<span class="step">SWAP</span>` +
      `<p>先手の初手を見て、<b>盤ごと陣営を入れ替えられます</b>。</p>`;
    return;
  }
  const p = state.turn;
  const who = vsAI() ? (p === aiSide ? "AI" : "あなた") : p === 0 ? "先手" : "後手";
  barEl.innerHTML =
    `<span class="turnmark${p === 0 ? " solid" : ""}"></span>` +
    `<p><b>${SIDE[p]}の手番</b> — ${who}${busy ? "（思考中…）" : ""}</p>`;
}

function renderModebar() {
  modebarEl.innerHTML = "";
  const add = (label, fn, cls) => {
    const b = document.createElement("button");
    b.textContent = label;
    if (cls) b.className = cls;
    b.onclick = fn;
    modebarEl.appendChild(b);
    return b;
  };

  if (teach) {
    if (teach.done) add("次へ →", tutorialAdvance, "primary");
    else {
      const s = document.createElement("span");
      s.className = "hint";
      s.textContent = "印のついたマスをクリック";
      modebarEl.appendChild(s);
    }
    add("スキップ", () => {
      teach = null;
      rememberTutorialDone();
      newGame();
    });
    return;
  }

  if (swapPending) {
    add("入れ替える", () => resolveSwap(true), "primary");
    add("このまま", () => resolveSwap(false));
    return;
  }

  if (sel !== null && isStack(state.cells[sel])) {
    for (const md of MODES) {
      const b = add(md.label, () => {
        mode = md.key;
        render();
      });
      if (md.key === mode) b.className = "on";
      b.disabled = !movesFrom(sel).some(md.has);
    }
    return;
  }

  const s = document.createElement("span");
  s.className = "hint";
  s.textContent =
    state.ply === 0 && RULES.openingTax
      ? "先手の初手は BODY を1マス動かすだけ（先手のコミ）"
      : sel === null
      ? "駒をクリック → 行き先をクリック"
      : "行き先をクリック";
  modebarEl.appendChild(s);
}

function logMove(player, m) {
  const d = document.createElement("div");
  if (player === 0) d.className = "b";
  d.textContent = `${String(Math.floor(state.ply / 2) + 1).padStart(2, " ")}. ${
    SIDE[player]
  } ${moveText(m, SIZE)}`;
  logEl.appendChild(d);
  logEl.scrollTop = logEl.scrollHeight;
}

// ---------------------------------------------------------------------------
// Interaction
// ---------------------------------------------------------------------------

function onCell(i) {
  if (busy || swapPending || isOver(state) || (teach && teach.done)) return;
  const m = offered().find((mv) => targetOf(mv) === i);
  if (m) return void play(m);

  const c = state.cells[i];
  if (c !== 0 && ownerOf(c) === state.turn && movesFrom(i).length) {
    sel = i;
    mode = defaultMode(i);
  } else {
    sel = null;
  }
  render();
}

function play(m) {
  const player = state.turn;
  history.push(state);
  if (!teach) logMove(player, m);
  state = applyMove(state, m);
  lastMove = m;
  sel = null;

  if (teach) {
    teach.done = true;
    render();
    const wait = TUTORIAL[teach.i].pause || 550;
    busy = true;
    setTimeout(() => {
      busy = false;
      render();
    }, wait);
    return;
  }

  const h = hashState(state);
  const n = (repeats.get(h) || 0) + 1;
  repeats.set(h, n);
  if (n >= 3 && !isOver(state)) {
    state = { ...state, winner: judge(state).winner, reason: "repetition" };
  }

  render();
  if (isOver(state)) return void finish();

  // Swap (pie) rule: having seen BLACK's opening, the second player may take
  // the BLACK side instead. This is what neutralises the first-move advantage.
  if ($("swapRule").checked && !swapUsed && state.ply === 1) {
    if (vsAI() && state.turn === aiSide) return void aiSwapDecision();
    swapPending = true;
    return void render();
  }

  if (!legalMoves(state).length) return void setTimeout(() => play({ kind: "pass" }), 350);
  if (aiToMove()) aiTurn();
}

function aiSwapDecision() {
  busy = true;
  render();
  setTimeout(() => {
    const depth = Math.max(2, Number($("level").value) - 1);
    const take = search(state, depth, 1 - state.turn).score > SWAP_MARGIN;
    busy = false;
    resolveSwap(take);
  }, 260);
}

function resolveSwap(doSwap) {
  swapPending = false;
  swapUsed = true;
  if (doSwap) {
    aiSide = 1 - aiSide;
    const d = document.createElement("div");
    d.className = "meta";
    d.textContent = "— スワップ発動：陣営が入れ替わりました —";
    logEl.appendChild(d);
  }
  render();

  if (doSwap && vsAI()) {
    showVeil(
      "スワップ発動",
      `AI があなたの初手を見て陣営を入れ替えました。あなたは <b>${
        SIDE[humanSide()]
      }</b> です。盤はあなたの陣が手前に来るよう反転しています。`,
      [["対局を続ける", () => (closeVeil(), aiToMove() && aiTurn()), true]]
    );
    return;
  }
  if (aiToMove()) aiTurn();
}

function aiTurn() {
  busy = true;
  render();
  setTimeout(() => {
    const depth = Number($("level").value);
    const m = chooseMove(state, depth, Math.random, depth <= 2 ? 0.5 : 0.06);
    busy = false;
    play(m);
  }, 200);
}

const REASONS = {
  brain: "相手の BRAIN を捕獲しました。",
  invasion: "BRAIN が敵陣に降り立ち、生き延びました。",
  repetition: "千日手 — 判定で決着しました。",
  judgement: "手数切れ — 判定で決着しました。",
};

function finish() {
  const w = state.winner;
  const j = judge(state);
  const tail = vsAI() && w !== -1 ? `（${w === humanSide() ? "あなた" : "AI"}）` : "";
  const detail =
    state.reason === "repetition" || state.reason === "judgement"
      ? `　侵攻度 ${j.depth[0]} 対 ${j.depth[1]}＋コミ${j.komi}、BODY ${j.bodies[0]} 対 ${j.bodies[1]}`
      : "";
  showVeil(
    w === -1 ? "引き分け" : `${SIDE[w]}の勝ち${tail}`,
    (REASONS[state.reason] || "") + detail,
    [
      ["もう一局", () => (closeVeil(), newGame()), true],
      ["待った", () => (closeVeil(), undo())],
    ]
  );
}

function popOne() {
  state = history.pop();
  while (logEl.lastChild && logEl.lastChild.className === "meta") logEl.removeChild(logEl.lastChild);
  if (logEl.lastChild) logEl.removeChild(logEl.lastChild);
}

function undo() {
  if (!history.length || busy || swapPending || teach) return;
  popOne();
  if (state.ply <= 1 && swapUsed) {
    if (humanSide() === 1) aiSide = 1 - aiSide;
    swapUsed = false;
  }
  while (history.length && aiToMove()) popOne();
  sel = null;
  lastMove = null;
  closeVeil();
  render();
}

// ---------------------------------------------------------------------------
// Overlay
// ---------------------------------------------------------------------------

function showVeil(title, html, buttons) {
  $("veilTitle").textContent = title;
  $("veilText").innerHTML = html;
  const box = $("veilBtns");
  box.innerHTML = "";
  for (const [label, fn, primary] of buttons) {
    const b = document.createElement("button");
    b.textContent = label;
    if (primary) b.className = "primary";
    b.onclick = fn;
    box.appendChild(b);
  }
  $("veil").classList.add("show");
}
const closeVeil = () => $("veil").classList.remove("show");

// ---------------------------------------------------------------------------
// Static panels
// ---------------------------------------------------------------------------

$("tagline").textContent = `${SIZE} × ${SIZE} — STACK TO CHANGE WHAT A PIECE IS`;

$("legend").innerHTML = [
  [`<span class="mk mk-move"><i></i></span>`, "移動できる"],
  [`<span class="mk mk-take"><i></i></span>`, "取れる"],
  [`<span class="mk mk-mount"><i></i></span>`, "合体できる"],
  [`<span class="mk mk-tackle"><i></i></span>`, "タックルできる"],
  [`<span class="piece p0"><span class="pbody"></span></span>`, "黒 = 先手（塗り）"],
  [`<span class="piece p1"><span class="pbody"></span></span>`, "白 = 後手（枠）"],
  [`<span class="piece p0 stacked"><span class="pbody"></span><span class="pbrain"></span></span>`, "合体駒"],
]
  .map(([sw, t]) => `<span class="sw">${sw}</span><span>${t}</span>`)
  .join("");

$("rules").innerHTML = `<dl>
<dt>BODY ■ — 縦横に1マス</dt><dd>単体の敵駒を取れる。合体駒にはタックルできる。</dd>
<dt>BRAIN ● — 斜めに1マス</dt><dd>駒を取れない。取られたら負け。</dd>
<dt>合体駒 — 8方向に最大2マス</dt><dd>飛び越え不可。単体の駒では取れず、合体駒だけが取れる。</dd>
<dt>タックル</dt><dd>BODY が隣の敵合体駒へ突撃すると、上の BRAIN が1マス弾かれる。
  行き先が盤外・他の駒なら撃墜＝勝ち。突撃側は動かない。</dd>
<dt>勝ち方は2つ</dt><dd>相手の BRAIN を取る。または単体の BRAIN を敵陣最奥に立たせ、相手の1手を生き延びる。</dd>
<dt>判定</dt><dd>千日手・${RULES.maxPly}手で判定。BRAIN がより深い側の勝ち、同じなら BODY の多い側。後手にコミ ${RULES.komi}。</dd>
<dt>先後の調整</dt><dd>先手の初手は BODY 移動のみ。さらに後手は初手を見てから陣営を入れ替えられる（スワップ）。</dd>
</dl>`;

$("newGame").onclick = newGame;
$("undo").onclick = undo;
$("teach").onclick = startTutorial;
$("opponent").onchange = newGame;
$("swapRule").onchange = newGame;
$("veil").onclick = (e) => {
  if (e.target === $("veil")) closeVeil();
};

if (tutorialWasDone()) newGame();
else startTutorial();
