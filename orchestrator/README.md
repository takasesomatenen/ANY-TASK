# orchestrator

Claude(監督者)が Gemini と GPT(ワーカー)に同じタスクを投げ、両者の出力を
レビュー・検証・統合して最終回答を作る CLI。

ワーカー2つは**並列**に実行され、片方が失敗しても実行は止まらない
(失敗内容がそのまま監督者への入力に含まれ、レポートにも残る)。

## セットアップ

```bash
pip install -r requirements.txt --break-system-packages
```

## 環境変数

| 変数 | 必須 | 用途 |
|---|---|---|
| `ANTHROPIC_API_KEY` | 必須 | 監督者(Claude) |
| `GOOGLE_API_KEY` | 任意 | ワーカー(Gemini)。未設定ならスキップ |
| `OPENAI_API_KEY` | 任意 | ワーカー(GPT)。未設定ならスキップ |
| `CLAUDE_MODEL` | 任意 | 既定 `claude-opus-5` |
| `GEMINI_MODEL` | 任意 | 既定 `gemini-2.5-pro` |
| `GPT_MODEL` | 任意 | 既定 `gpt-5` |

ワーカーは両方とも任意だが、少なくとも片方は設定しないと比較する対象がない。

## 使い方

```bash
python3 orchestrator.py "タスク内容をここに書く"
python3 orchestrator.py --file task.txt
python3 orchestrator.py "タスク" --out report.md --json result.json
```

- `--out` … 人間向けの Markdown レポートを保存
- `--json` … 各モデルの生の出力を含む JSON を保存(後段処理向け)

終了コード: `0` 成功 / `1` 監督者の呼び出し失敗 / `2` 引数エラー。

## 挙動のポイント

- **並列実行** — Gemini と GPT は `ThreadPoolExecutor` で同時に呼ぶ。
- **リトライ** — 429 / 5xx / 通信エラーは指数バックオフで最大3回試行。
  `Retry-After` ヘッダがあればそれに従う。
- **部分的失敗の許容** — ワーカーの失敗は `[GPT呼び出し失敗] ...` のような
  文字列になり、監督者にはそれがエラーであることを伝えたうえで残り片方で
  判断させる。監督者(Claude)の失敗のみ致命的。
- **切り詰めの検出** — Claude の `stop_reason=max_tokens`、GPT の
  `finish_reason=length`、Gemini の `finishReason != STOP` を検出して
  出力に警告を付ける。
- **拒否の扱い** — Claude が `stop_reason=refusal` を返した場合はエラー終了。
  サーバサイドフォールバック(`fallbacks: "default"`)を有効にしてあるため、
  カテゴリによっては代替モデルが自動で応答する。
- **キーの露出防止** — Gemini API キーは URL クエリではなく
  `x-goog-api-key` ヘッダで送るので、例外メッセージやログに載らない。
- **レポートの安全な組み立て** — ワーカー出力に含まれる水平線(`---`)は
  エスケープしてレポートのセクション構造が壊れないようにする
  (コードフェンス内は原文のまま)。

## テスト

`requests` をモックするので API キーもネットワークも不要。

```bash
python3 -m unittest discover -s tests -v
```
