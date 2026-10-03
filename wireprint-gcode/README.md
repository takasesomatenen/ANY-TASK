# wireprint-gcode

普通のスライサーでは作れない「空中プリント（ワイヤープリント）」の G-code を直接生成するスクリプト。

1. XY を止めて **Z だけ上げながら押し出して柱を立てる**
2. 押し出しながら斜めに降りて、隣の柱の根元へ（三角形の補強）
3. 全部の柱が立ったら、**頂点どうしを空中で水平に橋渡し**
4. その橋の高さを次の段の土台にして繰り返す

## 使い方

```bash
python3 wireprint.py --shape tower -o tower.gcode            # 花瓶型ラティス・タワー
python3 wireprint.py --shape tower --twist 6 -o twist.gcode   # ねじれ
python3 wireprint.py --shape grid -o grid.gcode               # 4x4 の柱グリッド（動画っぽいやつ）
python3 wireprint.py --shape grid --cols 5 --rows 5 --taper 0.6 --levels 12 -o pyramid.gcode
python3 build_preview.py   # preview.html（3Dツールパスビューア）を再生成
```

`examples/` に生成済みの G-code があります（ベッド 220×220、PLA 210℃/60℃、汎用 Marlin/Klipper 用）。

## プリンタに合わせて調整するもの

| オプション | 意味 | デフォルト |
|---|---|---|
| `--clearance` | ノズル先端〜ヒーターブロック下面の高さ | 5 mm |
| `--hotend-radius` | ヒーターブロック/ファンダクトの水平半径 | 12 mm |
| `--level-h` | 1段（柱1本）の高さ。clearance より低く | 4.5 mm |
| `--bed X Y` | ベッドサイズ（中央に配置） | 220 220 |
| `--retract` | リトラクト量（ボーデンなら 4 前後） | 0.8 |
| `--nozzle-temp` / `--bed-temp` | 温度 | 210 / 60 |

速度・停止時間・押出量は `wireprint.py` の `Settings` で変えられます。
生成時にヒーターブロックと既に作ったワイヤーの干渉を簡易チェックし、ぶつかりそうなら警告を出して終了コード 2 を返します。

## 注意

- スタート G-code は汎用 Marlin 用。Bambu Lab や Prusa 純正の場合は `start_gcode()` を自分の機種のものに差し替えてください。
- 最初はベッドの横で見守り、1〜2段目で垂れ具合を確認。垂れるなら `top_delay` を長く、温度を 5℃下げる、`up_speed` を下げる。
- 冷却ファンは強いほど成功率が上がります。
