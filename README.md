# マカレン数秘術 プロファイル作成

生年月日・名前・相談内容から、マカレン数秘術エンジン（v2.0）に基づく **A4約4枚** のプロファイルを生成するWebアプリです。OpenAI API で文章を生成し、PDFをメール送信できます。

## 料金プラン（商品）

| 商品 | 料金 |
|------|------|
| 自分の占いプロファイル | ¥1,000 |
| プロファイル ＋ 周囲10人との関係性 | ¥6,000 |

※ 実際の決済は本リポジトリには含まれていません。フォームでプラン選択のみ対応しています。

## 必要な環境

- Python 3.10+
- OpenAI API キー（ChatGPT）

## セットアップ

```bash
cd makaren_profile
python -m venv venv
source venv/bin/activate   # Windows: venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env
```

`.env` に API キーを設定してください。

```
OPENAI_API_KEY=sk-proj-...
```

メール送信を使う場合は SMTP 設定も追加してください。

```
SMTP_USER=your_user
SMTP_PASSWORD=your_password
SMTP_FROM=your_user@example.com

# 必要に応じて
SMTP_HOST=smtp.example.com
SMTP_PORT=587
SMTP_USE_TLS=true
SMTP_USE_SSL=false
```

最低限は `SMTP_USER` と `SMTP_PASSWORD` です。  
Gmail / Outlook / iCloud / Yahoo.co.jp は `SMTP_HOST` 未設定でも自動補完されます。

管理画面（アンバサダー一覧・累計紹介数・累計売上）を使う場合は `.env` に `ADMIN_SECRET` を設定し、`/admin?key=あなたのシークレット` でアクセスしてください。アンバサダー制度はサイト上では説明せず、完全招待制です。

## 起動

```bash
python app.py
```

ブラウザで http://localhost:5001 を開き、フォームから名前・生年月日・相談内容を入力して「プロファイルを生成」を押してください。  
別ポートを使いたい場合は `.env` に `FLASK_PORT=xxxx` を設定してください。

生成後は「PDFをメールで受け取る」で送信できます。

## 送信履歴の管理

メール送信が成功すると、送信履歴を `data/submissions.jsonl` に1行1件で保存します。  
管理用の一覧は `GET /api/submissions` で取得できます（例: `/api/submissions?limit=100`）。

## PDFの日本語表示について

PDF内で日本語を正しく表示するには、日本語対応フォントが必要です。  
`pdf_generator.py` の `FONT_PATHS` に、環境にあるフォントパスを追加してください（例: Noto Sans CJK など）。

## プロジェクト構成

- `app.py` — Flask ルート・API
- `profile_generator.py` — OpenAI (ChatGPT) API 呼び出し
- `prompts.py` — マカレン数秘術エンジン用プロンプト
- `pdf_generator.py` — A4 PDF 生成
- `engine_config.json` — エンジン仕様（設計思想・禁止出力など）
- `templates/index.html` — 入力フォーム・結果表示
