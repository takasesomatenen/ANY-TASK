# 先行ゲーム調査 —「コマにコマを乗せると性質が変わる」

結論から言うと、**「駒を積む」ボードゲームは山ほどあります**。ただし大半は
**「積んだ高さ＝移動距離」** か **「一番上の駒の持ち主が塔を操る」** のどちらかで、
BODY N BRAIN が狙う **「種類の違う駒が合体して、第三の動き方になる」** をやっている
ゲームは、実はかなり少数です。

---

## 1. 一番上の駒が塔を支配するタイプ

### Lasca（ラスカ / 1911・Emanuel Lasker）
チェス世界王者ラスカーが作ったチェッカー変種。取った駒を盤外に出さず、
**取った駒の「下」に敷いて塔（column）を作る**。塔は一番上の駒の持ち主のもので、
一番上の駒の動き（man か king か）で動く。塔が取られると、**一番上の1枚だけ**が
相手に奪われ、下の駒が解放されて復活する。

> 「A column is under the control of the player whose piece is on top, and has the
> move and jump capabilities of that piece.」

**BODY N BRAIN との関係**: 「上の駒が性質を決める」という発想の元祖に近い。
ただしラスカでは駒の種類は man / king の2種だけで、**乗る駒は敵の捕虜**。
自分の駒を意図的に合体させる操作はない。

### Bashni（バシニ / ロシアの「塔」）
ラスカの直接の祖先。ルールはほぼ同じで、Lasca はこれと English draughts の
掛け合わせ。

### Tak (2016)
石を積み上げ、塔は最上段の駒の持ち主が動かす。ただし動きは駒種ではなく
「持ち上げた枚数」で決まる。

---

## 2. 高さが移動力になるタイプ

| ゲーム | 年 | 積んだ結果 |
|---|---|---|
| **Focus**（Sid Sackson） | 1963 | 塔の高さ（1〜5）と同じマス数だけ動ける |
| **DVONN**（Kris Burm, GIPF Project） | 2001 | 高さ＝移動距離。DVONN 駒と繋がりを失った塔は盤から除去 |
| **Accasta** | – | 六角盤。高い塔ほど機動力が高い |
| **Quantum** | 2013 | 塔が 2/3/4/5 の高さなら 2/3/4/5 マス動ける |

いずれも **「高さという1次元のパラメータ」** に還元されていて、
「動き方の質が変わる」わけではありません。

---

## 3. ★ 一番近い先行例：Gounki（グンキ / 2005・Christophe Malavasi）

これが本命です。Gounki には **丸駒**と**四角駒**という
**動き方の違う2種類**があり、**自分の駒同士を積める**。そして

> 「if a combined piece comprises X rounds and Y squares, it may move up to
>  X steps like a round, or up to Y steps like a square.」

つまり **合体すると「丸の動き」と「四角の動き」の両方を選べる**。
さらに積んだ駒は再び分散（disperse）できる。

**「種類の違う駒を乗せると動き方が変わる」というアイデアは Gounki が既にやっています。**
正直に言って、BODY N BRAIN のコアメカニクスの直接の先祖です。

---

## 4. チェス変種の「運搬駒」

Chess Variant Pages 系には、他の駒を **積んで運ぶ** 駒がいくつか存在します。
たとえば *Taxi: The Nuclear C.a.B. Chess Game* の **Taxi** は最大3枚の駒を載せ、
**載っている駒の内容によって動きが変わる**。ただしこれらは大型変種の
一パーツで、ゲーム全体のコアメカニクスにはなっていません。

---

## 5. では BODY N BRAIN のどこが新しいのか

先行例と突き合わせた結果、**「乗せると性質が変わる」自体は新規性がありません**
（Gounki が先行）。BODY N BRAIN が固有に持っているのは次の3点です。

1. **合体が「足し算」ではなく「別モード」になる**
   BODY は縦横、BRAIN は斜め。Gounki のように「両方できる」のではなく、
   合体すると **8方向2マス滑走** という、どちらの単体にも無い動きに変わる。
   つまり 1+1 が 3 になる。

2. **★ タックル — 攻撃で塔を「崩せる」**
   先行例では、塔は **取られる** か **自分から降りる** かでしか解体されません。
   BODY N BRAIN では、単体の BODY が敵の合体駒に体当たりして
   **上の BRAIN だけを叩き落とせる**（合体駒自体は取れない）。
   落ちた先が盤外・他の駒なら BRAIN は撃墜されて即負け。
   → 「頭でっかちは足元をすくわれる」が、盤上の物理として成立する。

3. **勝利条件と強化パーツが同一の駒**
   BRAIN は「乗せると強くなるパーツ」であると同時に「取られたら負ける王」であり、
   さらに「敵陣に送り込めば勝てる侵攻ユニット」でもある。
   強くなろうとするほど、負け筋と勝ち筋の両方が同じ駒に集中する。

---

## 出典

- [Lasca — Wikipedia](https://en.wikipedia.org/wiki/Lasca)
- [Bashni — Wikipedia](https://en.wikipedia.org/wiki/Bashni)
- [Column Checkers variants — MindSports](https://mindsports.nl/index.php/on-the-evolution-of-draughts-variants/116-column-checkers)
- [Gounki — Wikipedia](https://en.wikipedia.org/wiki/Gounki)
- [Focus (board game) — Wikipedia](https://en.wikipedia.org/wiki/Focus_(board_game))
- [DVONN — Wikipedia](https://en.wikipedia.org/wiki/DVONN)
- [Accasta — Wikipedia](https://en.wikipedia.org/wiki/Accasta)
- [Quantum (board game) — Wikipedia](https://en.wikipedia.org/wiki/Quantum_(board_game))
- [Abstract Strategy games with Variable Movement rules — BoardGameGeek](https://boardgamegeek.com/geeklist/207643/abstract-strategy-games-with-variable-movement-rul)
- [Index T to Man and Beast — The Chess Variant Pages](https://www.chessvariants.com/ideas/index-t-to-man-and-beast)
