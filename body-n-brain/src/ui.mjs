// BODY N BRAIN — browser UI. Inlined into index.html by build.mjs.

const $ = (id) => document.getElementById(id);
const boardEl = $("board");
const logEl = $("log");
const modebarEl = $("modebar");

const RULES = makeRules();

let state, history, sel, mode, lastMove, repeats, busy;
// Seat the AI occupies. The swap (pie) rule can hand it the other colour.
let aiSide, swapPending, swapUsed;

const MODES = [
  { key: "stack", label: "合体駒で動く" },
  { key: "brain", label: "BRAIN だけ降りる" },
  { key: "body", label: "BODY だけ出る" },
];

function newGame() {
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
  $("banner").classList.remove("show");
  render();
}

const vsAI = () => $("opponent").value === "ai";
const aiToMove = () => vsAI() && state.turn === aiSide;
/** The colour the person at the keyboard is playing. */
const humanSide = () => (vsAI() ? 1 - aiSide : 0);
/** Keep the human's own back rank at the bottom, even after a swap. */
const flipped = () => humanSide() === 1;

/** Only swap on a real advantage — never on evaluation noise. */
const SWAP_MARGIN = 20;

function showBanner(title, colour, text, buttons) {
  $("bannerTitle").textContent = title;
  $("bannerTitle").style.color = colour;
  $("bannerText").textContent = text;
  const box = $("bannerBtns");
  box.innerHTML = "";
  for (const [label, fn] of buttons) {
    const b = document.createElement("button");
    b.textContent = label;
    b.onclick = fn;
    box.appendChild(b);
  }
  $("banner").classList.add("show");
}

const closeBanner = () => $("banner").classList.remove("show");

// --- move helpers ----------------------------------------------------------

function movesFrom(i) {
  return legalMoves(state).filter((m) => m.from === i);
}

/** Moves offered for the current selection, filtered by the active mode. */
function offered() {
  if (sel === null) return [];
  const all = movesFrom(sel);
  if (!isStack(state.cells[sel])) return all;
  if (mode === "stack") return all.filter((m) => m.kind === "stack" || m.kind === "tackle");
  if (mode === "brain") return all.filter((m) => m.kind === "brain");
  return all.filter((m) => m.kind === "body" || m.kind === "tackle");
}

const targetOf = (m) => (m.kind === "tackle" ? m.target : m.to);

// --- rendering -------------------------------------------------------------

function pieceHTML(c) {
  const p = ownerOf(c);
  const cls = `piece p${p}`;
  if (isBody(c)) return `<div class="${cls}"><div class="body"></div></div>`;
  if (isBrain(c)) return `<div class="${cls} lonebrain"><div class="brain"></div></div>`;
  return `<div class="${cls} stacked"><div class="body"></div><div class="brain"></div></div>`;
}

function render() {
  const marks = new Map();
  for (const m of offered()) marks.set(targetOf(m), m);

  boardEl.innerHTML = "";
  const flip = flipped();
  for (let row = 0; row < H; row++) {
    for (let col = 0; col < W; col++) {
      // 180-degree rotation when the human plays RED, so their own pieces are
      // always the ones nearest to them.
      const y = flip ? row : H - 1 - row;
      const x = flip ? W - 1 - col : col;
      const i = idx(x, y);
      const cell = document.createElement("div");
      cell.className = "cell" + ((x + y) % 2 ? " dark" : "");
      if (y === goalRank(0)) cell.className += " goal0";
      if (y === goalRank(1)) cell.className += " goal1";
      if (i === sel) cell.className += " sel";
      if (lastMove && (lastMove.from === i || targetOf(lastMove) === i)) cell.className += " lastto";

      let html = `<span class="coord">${sqName(i)}</span>`;
      const c = state.cells[i];
      if (c !== 0) html += pieceHTML(c);
      const m = marks.get(i);
      if (m) {
        const kind = m.kind === "tackle" ? "tack" : m.capture || m.mount ? "cap" : "";
        html += `<span class="marker ${kind}"><i></i></span>`;
      }
      cell.innerHTML = html;
      cell.onclick = () => onCell(i);
      boardEl.appendChild(cell);
    }
  }

  const p = state.turn;
  $("turnDot").style.background = p === 0 ? "var(--blue)" : "var(--red)";
  const who = vsAI() ? (p === aiSide ? "AI" : "あなた") : p === 0 ? "先手" : "後手";
  $("turnText").textContent = `${p === 0 ? "BLUE" : "RED"} の手番 — ${who}`;
  $("undo").disabled = history.length === 0 || busy || swapPending;
  renderModebar();
}

function renderModebar() {
  modebarEl.innerHTML = "";
  if (swapPending) {
    const hint = document.createElement("span");
    hint.className = "hint";
    hint.textContent = "スワップ権：先手の初手を見て、盤ごと入れ替われます　";
    modebarEl.appendChild(hint);
    for (const [label, doSwap] of [
      ["入れ替える", true],
      ["このまま", false],
    ]) {
      const b = document.createElement("button");
      b.textContent = label;
      b.onclick = () => resolveSwap(doSwap);
      modebarEl.appendChild(b);
    }
    return;
  }
  if (sel === null || !isStack(state.cells[sel])) {
    const s = document.createElement("span");
    s.className = "hint";
    s.textContent =
      state.ply === 0 && RULES.openingTax
        ? "先手の初手は BODY を1マス動かすだけ（先手のコミ）"
        : sel === null
        ? "駒をクリックして動かします"
        : "行き先をクリック（合体駒は動き方を選べます）";
    modebarEl.appendChild(s);
    return;
  }
  for (const md of MODES) {
    const b = document.createElement("button");
    b.textContent = md.label;
    if (md.key === mode) b.className = "on";
    const has = movesFrom(sel).some((m) =>
      md.key === "stack"
        ? m.kind === "stack" || m.kind === "tackle"
        : md.key === "brain"
        ? m.kind === "brain"
        : m.kind === "body" || m.kind === "tackle"
    );
    b.disabled = !has;
    b.onclick = () => {
      mode = md.key;
      render();
    };
    modebarEl.appendChild(b);
  }
}

function logMove(player, m) {
  const d = document.createElement("div");
  d.className = player === 0 ? "b" : "r";
  d.textContent = `${String(Math.floor(state.ply / 2) + 1).padStart(2, " ")}. ${
    player === 0 ? "B" : "R"
  }  ${moveText(m)}`;
  logEl.appendChild(d);
  logEl.scrollTop = logEl.scrollHeight;
}

// --- interaction -----------------------------------------------------------

function resolveSwap(doSwap) {
  swapPending = false;
  swapUsed = true;
  if (doSwap) {
    aiSide = 1 - aiSide;
    const d = document.createElement("div");
    d.className = "meta";
    d.textContent = "   — スワップ発動：両者の陣営が入れ替わりました —";
    logEl.appendChild(d);
  }
  render();

  // Losing your colour on move one is bewildering unless it is spelled out.
  if (doSwap && vsAI()) {
    const you = humanSide() === 0 ? "BLUE（先手）" : "RED（後手）";
    showBanner(
      "スワップ発動",
      "var(--gold)",
      `AI があなたの初手を見て陣営を入れ替えました。あなたは ${you} です。` +
        `盤はあなたの陣が手前に来るよう反転しています。`,
      [["対局を続ける", () => {
        closeBanner();
        if (aiToMove()) aiTurn();
      }]]
    );
    return;
  }
  if (aiToMove()) aiTurn();
}

function onCell(i) {
  if (busy || swapPending || isOver(state)) return;
  const m = offered().find((mv) => targetOf(mv) === i);
  if (m) return void play(m);

  const c = state.cells[i];
  if (c !== 0 && ownerOf(c) === state.turn) {
    sel = i;
    const kinds = new Set(movesFrom(i).map((x) => x.kind));
    mode = kinds.has("stack") ? "stack" : kinds.has("brain") ? "brain" : "body";
  } else {
    sel = null;
  }
  render();
}

function play(m) {
  const player = state.turn;
  history.push(state);
  logMove(player, m);
  state = applyMove(state, m);
  lastMove = m;
  sel = null;

  const h = hashState(state);
  const n = (repeats.get(h) || 0) + 1;
  repeats.set(h, n);
  if (n >= 3 && !isOver(state)) {
    state = { ...state, winner: judge(state).winner, reason: "repetition" };
  }

  render();
  if (isOver(state)) return void finish();

  // The swap (pie) rule: having seen BLUE's opening move, the second player may
  // take the BLUE side instead. This is what actually neutralises the
  // first-move advantage — see docs/BALANCE.md.
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
    // Take the swap only when the opening gave the first player a real edge.
    // A bare > 0 test swaps on evaluation noise, which reads to the player as
    // the game taking their colour away for no reason.
    const take = search(state, depth, 1 - state.turn).score > SWAP_MARGIN;
    busy = false;
    resolveSwap(take);
  }, 260);
}

function aiTurn() {
  busy = true;
  render();
  setTimeout(() => {
    const depth = Number($("level").value);
    const m = chooseMove(state, depth, Math.random, depth <= 2 ? 0.5 : 0.06);
    busy = false;
    play(m);
  }, 220);
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
  const side = w === 0 ? "BLUE" : "RED";
  const tail = vsAI() && w !== -1 ? `（${w === humanSide() ? "あなた" : "AI"}）` : "";
  const detail =
    state.reason === "repetition" || state.reason === "judgement"
      ? `（侵攻度 ${j.depth[0]} 対 ${j.depth[1]}＋コミ${j.komi}、BODY ${j.bodies[0]} 対 ${j.bodies[1]}）`
      : "";
  showBanner(
    w === -1 ? "引き分け" : `${side} の勝ち${tail}`,
    w === -1 ? "var(--gold)" : w === 0 ? "var(--blue)" : "var(--red)",
    (REASONS[state.reason] || "") + detail,
    [
      ["もう一局", newGame],
      ["待った", () => {
        closeBanner();
        undo();
      }],
    ]
  );
}

function popOne() {
  state = history.pop();
  while (logEl.lastChild && logEl.lastChild.className === "meta") logEl.removeChild(logEl.lastChild);
  if (logEl.lastChild) logEl.removeChild(logEl.lastChild);
}

function undo() {
  if (!history.length || busy || swapPending) return;
  popOne();
  // Rewinding past the swap decision must also give the colours back.
  if (state.ply <= 1 && swapUsed) {
    if (humanSide() === 1) aiSide = 1 - aiSide;
    swapUsed = false;
  }
  while (history.length && aiToMove()) popOne();
  sel = null;
  lastMove = null;
  closeBanner();
  render();
}

$("newGame").onclick = newGame;
$("undo").onclick = undo;
$("opponent").onchange = newGame;
$("swapRule").onchange = newGame;
$("banner").onclick = (e) => {
  if (e.target === $("banner")) closeBanner();
};

$("rules").innerHTML = `
<b>目的</b>
<ul>
  <li>相手の <b>BRAIN</b> を捕獲する</li>
  <li>または、単体の <b>BRAIN</b> を相手の最奥段に置き、相手の1手を生き延びる（<b>侵攻勝ち</b>）</li>
</ul>
<b>動き</b>
<ul>
  <li><b>BODY</b>（四角）… 縦横に1マス。単体の敵駒を取れる。</li>
  <li><b>BRAIN</b>（丸）… 斜めに1マス。<code>絶対に駒を取れない</code>。</li>
  <li><b>合体駒</b>（BRAIN が BODY に乗った状態）… 8方向に最大2マス滑る。飛び越え不可。</li>
</ul>
<b>合体と分離</b>
<ul>
  <li>BRAIN が味方 BODY のマスへ入る／BODY が味方 BRAIN のマスへ入ると <b>合体</b>。</li>
  <li>合体駒からは「BRAIN だけ降りる」「BODY だけ出る」も選べる（<b>分離</b>）。</li>
</ul>
<b>タックル</b>
<ul>
  <li>BODY は隣接する敵の合体駒へ突撃できる。合体駒は取れないが、
      上の BRAIN が突撃方向へ1マス <b>叩き落とされる</b>。
      その先が盤外か塞がっていれば BRAIN は <code>撃墜＝負け</code>。突撃側は動かない。</li>
</ul>
<b>判定</b>
<ul>
  <li>千日手・${RULES.maxPly}手到達は <b>判定</b>：BRAIN がより深く侵攻している側の勝ち。
      同じなら BODY の多い側。後手には <b>コミ ${RULES.komi}</b> が付く。</li>
</ul>
<b>先手・後手の調整</b>
<ul>
  <li><b>先手の初手</b>は BODY を1マス動かすだけ（合体・侵攻の禁止）。</li>
  <li><b>スワップ</b>：後手は先手の初手を見てから、盤ごと陣営を入れ替えられる。
      先手が有利な初手を指すほど、奪われる。真剣勝負ではこれを推奨。</li>
</ul>`;

newGame();
