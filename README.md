# Valorant 試合 → Discord 通知

GitHub Actions で 10 分おきに最新の試合をチェックし、新しい試合があれば Discord に通知します。
データは HenrikDev API（非公式 Valorant API）から取得します。

## ファイル構成

```
valorant_notify.py                    通知スクリプト（標準ライブラリのみ）
.github/workflows/valorant-notify.yml 定期実行の設定
state/last_match.json                 最後に通知した試合 ID（自動で作成・更新）
```

## セットアップ

### 1. HenrikDev API キーを取得
1. https://docs.henrikdev.xyz から HenrikDev の Discord サーバーに参加
2. サーバー内の案内に従って API キーを発行（Basic キーで十分）

### 2. Discord Webhook を作成
通知したいチャンネルの「チャンネルの編集」→「連携サービス」→「ウェブフック」→「新しいウェブフック」→「ウェブフック URL をコピー」

### 3. GitHub リポジトリを作成してファイルを置く
- **公開（Public）リポジトリを推奨**：Actions が無料・無制限で使えます。
  API キーと Webhook URL は Secrets に入れるので公開されません。
- 非公開（Private）にする場合は無料枠（月 2,000 分）を超えないよう、
  ワークフローの cron を `"*/30 * * * *"`（30 分おき）に変えてください。

このフォルダの中身をそのまま push します。

### 4. Secrets を登録
リポジトリの Settings → Secrets and variables → Actions → New repository secret

| 名前 | 値 |
|---|---|
| `HENRIK_API_KEY` | 手順 1 の API キー |
| `DISCORD_WEBHOOK_URL` | 手順 2 の Webhook URL |

### 5. 初回実行
Actions タブ →「Valorant 試合通知」→「Run workflow」。
初回は最新の試合 ID を記録するだけで通知は送りません。次の試合から通知されます。

## 通知内容
勝敗・マップ・モード・エージェント・ラウンドスコア・K/D/A・ACS・HS%・ランク（RR 変動）。
タイトルをクリックすると tracker.gg の試合ページが開きます。

## テスト送信
Actions タブ →「Valorant 試合通知」→「Run workflow」で「テスト送信」にチェックを入れて実行すると、
最新の 1 試合を必ず Discord に通知します（記録している試合 ID は変わりません）。

## 設定の変更
- 監視するプレイヤー：ワークフローの `VAL_NAME` / `VAL_TAG`
- リージョン：`VAL_REGION`（日本は `ap`）
- 実行間隔：`cron`（最短 5 分。GitHub 側の都合で遅れることがあります）

## ローカルで試す（Discord に送らず内容だけ表示）
PowerShell:
```
$env:HENRIK_API_KEY="キー"; $env:VAL_NAME="年上お姉さんに依存されたい"; $env:VAL_TAG="blitz"; $env:DRY_RUN="1"; $env:STATE_FILE="test_state.json"
python valorant_notify.py
```
初回は記録だけなので、`test_state.json` の `last_match_id` を適当な値（例: `"x"`）に書き換えて再実行すると、直近 5 試合分の通知内容が表示されます。

## 注意
- 非公式 API のため、仕様変更や一時停止で動かなくなることがあります。
- リポジトリに 60 日間コミットがないと定期実行が自動停止されます（試合のたびに状態ファイルがコミットされるので、普段プレイしていれば止まりません）。
