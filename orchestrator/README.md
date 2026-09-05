# orchestrator

Claude(監督者)が Gemini と GPT(ワーカー)に同じタスクを投げ、両者の出力を
レビュー・検証・統合して最終回答を作る CLI。

ワーカー2つは**並列**に実行され、片方が失敗しても実行は止まらない
(失敗内容がそのまま監督者への入力に含まれ、レポートにも残る)。

各モデルは 2 通りの呼び方ができ、役割ごとに混在させてよい。

| バックエンド | 呼び方 | 費用 |
|---|---|---|
| `api` (既定) | REST API を直接叩く | トークン従量課金。APIキーが必要 |
| `cli` | ローカルの CLI を `subprocess` で呼ぶ | 各 CLI のサブスク枠。APIキー不要 |

## セットアップ

```bash
pip install -r requirements.txt --break-system-packages
```

`cli` バックエンドだけを使うなら `requests` も API キーも不要
(ただし import はするのでインストールはしておく)。

## 環境変数

### API バックエンド

| 変数 | 必須 | 用途 |
|---|---|---|
| `ANTHROPIC_API_KEY` | 監督者を api で動かすなら必須 | Claude |
| `GOOGLE_API_KEY` | 任意 | Gemini。未設定ならスキップ |
| `OPENAI_API_KEY` | 任意 | GPT。未設定ならスキップ |
| `CLAUDE_MODEL` | 任意 | 既定 `claude-opus-5` |
| `GEMINI_MODEL` | 任意 | 既定 `gemini-2.5-pro` |
| `GPT_MODEL` | 任意 | 既定 `gpt-5` |

### CLI バックエンド

| 変数 | 既定 |
|---|---|
| `CLAUDE_CLI_CMD` | `claude -p {prompt}` |
| `GEMINI_CLI_CMD` | `gemini -p {prompt}` |
| `GPT_CLI_CMD` | `codex exec {prompt}` |
| `CLI_TIMEOUT` | `600` (秒) |
| `ORCHESTRATOR_BACKEND` | `api` |

`{prompt}` がプロンプトの差し込み位置。含まれていない場合は末尾に引数として
付く。テンプレートは `shlex` で分割され、**シェルは経由しない**ので、
プロンプトに `;` や `&&` が入っていてもコマンドとして解釈されることはない。

CLI 側のフラグが手元のバージョンと違う場合は、この環境変数で合わせる:

```bash
export GEMINI_CLI_CMD='gemini --prompt {prompt} --output-format text'
```

## 使い方

```bash
# 全部 API (既定)
python3 orchestrator.py "タスク内容をここに書く"

# 全部 CLI (サブスク枠で動かす)
python3 orchestrator.py "タスク" --backend cli

# 混在: ワーカーの Gemini だけ CLI、残りは API
python3 orchestrator.py "タスク" --gemini-backend cli

python3 orchestrator.py --file task.txt
python3 orchestrator.py "タスク" --out report.md --json result.json
```

- `--backend {api,cli}` … 全役割の既定
- `--gemini-backend` / `--gpt-backend` / `--claude-backend` … 役割ごとの上書き
- `--cli-timeout SEC` … CLI 1回あたりのタイムアウト
- `--out` … 人間向けの Markdown レポートを保存
- `--json` … 各モデルの生の出力を含む JSON を保存(後段処理向け)

終了コード: `0` 成功 / `1` 監督者の呼び出し失敗 / `2` 引数エラー。

## 挙動のポイント

- **並列実行** — Gemini と GPT は `ThreadPoolExecutor` で同時に呼ぶ。
  api / cli のどちらでも並列。
- **リトライ (api)** — 429 / 5xx / 通信エラーは指数バックオフで最大3回試行。
  `Retry-After` ヘッダがあればそれに従う。
- **部分的失敗の許容** — ワーカーの失敗は `[GPT呼び出し失敗] ...`
  `[Gemini CLI失敗] ...` のような文字列になり、監督者にはそれがエラーである
  ことを伝えたうえで残り片方で判断させる。監督者の失敗のみ致命的。
- **CLI のハング防止** — 子プロセスの stdin は `DEVNULL` に塞ぐので、対話モードに
  落ちた CLI が入力待ちで止まることはない。タイムアウトでも打ち切る。
- **切り詰めの検出** — Claude の `stop_reason=max_tokens`、GPT の
  `finish_reason=length`、Gemini の `finishReason != STOP` を検出して
  出力に警告を付ける。
- **拒否の扱い (api)** — Claude が `stop_reason=refusal` を返した場合はエラー終了。
  サーバサイドフォールバック(`fallbacks: "default"`)を有効にしてあるため、
  カテゴリによっては代替モデルが自動で応答する。
- **キーの露出防止** — Gemini API キーは URL クエリではなく
  `x-goog-api-key` ヘッダで送るので、例外メッセージやログに載らない。
- **レポートの安全な組み立て** — ワーカー出力に含まれる水平線(`---`)は
  エスケープしてレポートのセクション構造が壊れないようにする
  (コードフェンス内は原文のまま)。CLI の ANSI 色コードも除去する。

## CLI バックエンドの注意点

- **遅い** — 呼び出しごとにプロセス起動と認証が入るので、API 直叩きより遅い。
- **上限がある** — 各 CLI のサブスクには日次・週次の利用上限があり、
  自動実行で回数を稼ぐと途中で失敗する。従量課金のような逃げ道はない。
- **出力の整形** — CLI はエージェント的な前置きを付けることがある。
  素の回答だけが欲しい場合はプロンプト側で指示するか、各 CLI の
  出力フォーマット指定オプションを `*_CLI_CMD` に足す。

## テスト

`requests` と `subprocess` をモックするので、API キーもネットワークも
CLI のインストールも不要。

```bash
python3 -m unittest discover -s tests -v
```
