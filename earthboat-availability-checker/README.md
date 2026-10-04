# Earthboat 空室確認スクリプト

Earthboat（アースボート）各拠点の空室状況を、指定した宿泊条件でまとめてチェックする CLI ツール。
JS(SPA) で描画される予約カレンダーを Playwright でヘッドレスブラウザ操作して読み取る。

## ⚠️ 重要な制約（このツールを書いた環境について）

このツールを作成したサンドボックス環境からは、組織のegressポリシーにより
`en.earthboat.jp` / `earthboat.jp` への外部通信がブロックされていました
（`curl`・Playwright(Chromium) 経由・Anthropic の WebFetch 経由、いずれも
到達不可 / 403 / `net::ERR_TUNNEL_CONNECTION_FAILED` を確認済み）。

そのため：

- **実サイトの予約カレンダーAPIエンドポイントを、開発者ツールで実際に確認できていません。**
- **`selectors.json` に入っているCSSセレクタは未検証（best-effort）です。** 実際のDOM構造に
  合わせて調整が必要な可能性があります。
- **このREADMEに実際の空室結果は記載していません。** 空室情報を捏造しないため、本番の
  空室確認は必ずインターネットに到達できる環境（あなたのPCなど）で実行してください。

上記の理由で、まず `--mode inspect` を一度実行し、実際のネットワークリクエスト／DOM構造を
確認してから `selectors.json` / `api_endpoints.json` を必要に応じて調整することを推奨します。

## セットアップ

```bash
cd earthboat-availability-checker
pip install -r requirements.txt
playwright install chromium
```

## 使い方

### 1. まず `--mode inspect` で実サイトの構造を確認（初回必須）

```bash
python check_availability.py --mode inspect --checkin 2026-08-09 --checkout 2026-08-10 --guests 2
```

各拠点ページを一度開き、以下を `results/inspect/` 以下に保存する：

- `<slug>.html` — ページの完全なHTML（レンダリング後）
- `<slug>_network.json` — ページ読み込み中に発生した XHR/fetch のうち JSON を返すものの一覧
  （ここに予約カレンダーの内部APIが見つかることが多い）
- `<slug>_candidates.json` — 日付入力・人数選択・カレンダーらしき要素の候補（outerHTML）
- `results/screenshots/<slug>_inspect.png` — 目視確認用スクリーンショット

ここで見つかった実際のAPIエンドポイントを `api_endpoints.json` に、実際のセレクタを
`selectors.json` に反映してから、以下のモードで本チェックを行う。

### 2. 内部APIが見つかった場合 → `--mode api`（推奨・高速・安定）

`api_endpoints.json` の該当拠点に URL・クエリパラメータ・レスポンス内の空室/料金フィールドの
パスを記入してから：

```bash
python check_availability.py --mode api --checkin 2026-08-09 --checkout 2026-08-10 --guests 2
```

### 3. APIが見つからない/不明な場合 → `--mode browser`（デフォルト、フルブラウザ操作）

```bash
python check_availability.py --mode browser --checkin 2026-08-09 --checkout 2026-08-10 --guests 2
```

各拠点ページを開き、`selectors.json` の候補セレクタでチェックイン/チェックアウト日・人数を
入力し、検索を実行、結果テキスト・予約ボタンの活性状態・料金表示を読み取る。
拠点ごとにスクリーンショットを `results/screenshots/<slug>.png` に保存するので、
自動判定が不安な場合は必ず目視で確認すること。

### 主なオプション

| オプション | 説明 | デフォルト |
|---|---|---|
| `--checkin` / `--checkout` | 宿泊日 (YYYY-MM-DD) | 2026-08-09 / 2026-08-10 |
| `--guests` | 人数 | 2 |
| `--locations` | チェック対象スラッグを絞り込み（例: `--locations ueda_onsen hakuba`） | 全拠点（優先順） |
| `--mode` | `inspect` / `browser` / `api` | `browser` |
| `--headed` | ブラウザを表示して実行（デバッグ用） | headless |
| `--executable-path` | 事前インストール済みChromiumのパスを直接指定したい場合 | Playwright標準 |
| `--delay` | 拠点間の待機秒数（サイトへの配慮） | 2.0 |

## 出力

- `results/availability.md` — Markdownテーブル（下記フォーマット）
- `results/availability.json` — 生データ（全拠点分の詳細・スクリーンショットパス等）
- `results/screenshots/` — 拠点ごとのスクリーンショット

```
| 拠点 | 空室 | 料金（2名） | 備考 |
|---|---|---|---|
| Ueda Onsen | ○/×/? | ¥xx,xxx | |
```

`?` は自動判定できなかった場合（要目視確認、対応するスクリーンショットを確認すること）。
備考欄にはキャンセル待ちの有無なども記載される。

## クロスチェック（一休.com）

一休.com にも Togakushi / Hakuba / Kitakaruizawa / Kurohime などが掲載されている場合がある。
Ueda Onsen（2026-07-31開業）は掲載されていない可能性が高いため、公式サイトでの確認が必須。
本ツールは公式サイト専用（一休.com対応は未実装）。

## 利用にあたっての注意

- 対象サイトの利用規約を確認し、過度な高頻度アクセスは避けること。
- 本ツールは1回の実行で全拠点をチェックする設計。ポーリングループは意図的に実装していない
  （再チェックしたい場合は都度手動で再実行すること）。
- 直前まで空室状況が変動しうるため、実際の予約前には必ず公式サイトで最終確認すること。
