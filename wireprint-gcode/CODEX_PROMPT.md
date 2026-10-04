あなたは私のローカルPCで作業するエージェントです。Bambu Lab A1 mini で「ワイヤープリント（空中プリント）」のテストをする準備を、**印刷開始の直前まで**自動で進めてください。

## 目的
GitHub の `takasesomatenen/ANY-TASK` リポジトリ、ブランチ `claude/wireprint-gcode` にある `wireprint-gcode/` を使って 3cm のトラス・キューブの G-code を作り、A1 mini に LAN 経由で送って、私が OK したら印刷を開始できる状態にする。

## 私が用意するもの（足りなければ作業前に質問してください）
- プリンタの IP アドレス、シリアル番号、アクセスコード（プリンタ画面の 設定 → ネットワーク / LAN Only に表示）
- プリンタ側で「LAN Only モード」と「開発者モード（Developer Mode）」を有効にしておく。新しいファームウェアでは、Bambu Studio 以外のツールから印刷を送るのに必要
- PLA をロード済み、ベッドは空
- 秘密情報は `.env` に `BAMBU_IP` / `BAMBU_SERIAL` / `BAMBU_ACCESS_CODE` として置く。コードに直書きしない

## 手順
1. リポジトリを clone して `claude/wireprint-gcode` を checkout。Python 3.10 以上を確認し、作業用 venv を作る。
2. G-code を生成:
   ```
   cd wireprint-gcode
   python3 wireprint.py --printer a1mini --shape grid --cols 4 --rows 4 --spacing 10 --levels 8 -o cube30.gcode
   ```
   出力に `collision check: OK` があることを確認。なければ止めて報告。
   （最初の動作確認用に `--cols 2 --rows 2 --levels 3 -o tiny.gcode` も作っておく）
3. G-code を検査するスクリプトを書いて実行し、結果を表示: 全 X/Y が 0〜180、Z が 180 以下、ノズル 220℃ / ベッド 60℃、ファンが `M106 P1` で指定されていること。
4. G-code を Bambu の印刷ジョブ形式 `.gcode.3mf` に詰める。
   - 中身は `[Content_Types].xml`、`_rels/.rels`、`3D/3dmodel.model`（中身が空のモデルで可）、`Metadata/plate_1.gcode`、`Metadata/plate_1.gcode.md5`（G-code の MD5、大文字16進）、`Metadata/model_settings.config`、`Metadata/slice_info.config`（A1 mini の printer_model_id は `N1`、ノズル 0.4）。
   - Bambu Studio がインストールされていれば、適当な STL をスライスして書き出した `.gcode.3mf` を展開し、構造をそれに合わせる。作った 3mf が Bambu Studio で開いてプレビューできることも確認する。
5. 送信スクリプト `send_to_a1mini.py` を作る（`paho-mqtt` などの既存ライブラリを使ってよい）。
   - **アップロード**: FTPS（暗黙 TLS、ポート 990、ユーザー `bblp`、パスワード = アクセスコード）で SD カード直下に `.gcode.3mf` を置く。プリンタの証明書は自己署名なので、このホストに限り検証を緩めてよい。
   - **状態取得**: MQTT over TLS（ポート 8883、ユーザー `bblp`、パスワード = アクセスコード）に接続し、`device/{SERIAL}/report` を購読。`device/{SERIAL}/request` に `{"pushing":{"sequence_id":"0","command":"pushall"}}` を送って、gcode_state・温度・SD カードの有無・AMS の状態を表示。
   - **印刷開始**（`--start` を付けたときだけ）: `device/{SERIAL}/request` に `command: "project_file"` を送る。`param` は `"Metadata/plate_1.gcode"`、`url` はアップロード先（例 `ftp:///cube30.gcode.3mf`）、`md5`、`subtask_name`、`timelapse:false`、`use_ams:false`（外部スプールの場合。AMS lite を使うなら私に聞く）など。フィールド名と値は推測せず、OpenBambuAPI（https://github.com/Doridian/OpenBambuAPI）の MQTT ドキュメントで確認すること。
   - **監視**: 開始後は gcode_state・進捗（mc_percent）・温度・エラー（print_error / hms）を表示し続ける。Ctrl+C では監視をやめるだけで、印刷は止めない。
   - `--pause` / `--resume` / `--stop` で、一時停止・再開・停止のコマンドを送れるようにする。
   - 送るファイルは `--file` で選べるようにする（tiny と cube30 を切り替えるため）。
6. **予行演習**: まず `--start` なしで、アップロードと状態取得まで実行して結果を見せる。
7. 印刷開始は、私が「ベッド空・フィラメント OK・開始して」と言ってから。最初は tiny、問題なければ cube30 の順。

## 安全ルール
- 印刷開始・停止・プリンタ設定の変更は、私が明示的に許可するまでしない。
- プリンタが印刷中（gcode_state が RUNNING / PAUSE）なら何も送らず報告する。
- アクセスコードをログ・出力・コミットに出さない。`.env` は `.gitignore` に入れる。
- リポジトリへの push はしない。作業はローカルで完結させる。
- うまくいかないときは推測で直し続けず、エラー内容と試したことを報告して止まる。

## 完了したら報告すること
- 作ったファイルの一覧
- G-code の検査結果
- 3mf を Bambu Studio で開けたかどうか
- 予行演習で取れたプリンタの状態
- 印刷を開始するときに打つコマンド
