# KOKOROE／ココロエ パーソナル鑑定・絵画販売

生年月日・名前・相談内容を非公開の内部分析へ変換し、**A4約4枚** のパーソナル鑑定とオリジナル抽象画を生成するWebアプリです。利用者は専用ページで指摘・再生成・承認を行い、承認版PDFの受け取りと額装希望の申込ができます。計算値・採点・数式は利用者向け画面とPDFへ表示しません。

KOKOROEは、カバラ数秘術ヤマカレンを参考にしながら、独自の鑑定設計と抽象画制作へ再構成したサービスです。作品は鑑定確認用の高精細画像を生成し、承認後に同一構図の額装用プリントマスターを別途制作します。

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

レビュー・修正・生成物保存を有効にする場合は、既存のSupabase基盤に対して次も設定します。`SUPABASE_SERVICE_ROLE_KEY` はサーバー専用で、HTMLやフロントエンドJavaScriptへ渡してはいけません。

```
SUPABASE_URL=https://your-project-ref.supabase.co
SUPABASE_SERVICE_ROLE_KEY=your-server-only-key
KOKOROE_STORAGE_BUCKET=makaren-deliverables
PUBLIC_BASE_URL=https://your-app.example.com
OPENAI_IMAGE_MODEL=gpt-image-2
KOKOROE_REVIEW_IMAGE_SIZE=1536x2304
KOKOROE_REVIEW_IMAGE_QUALITY=high
KOKOROE_PRINT_IMAGE_SIZE=2304x3456
KOKOROE_PRINT_IMAGE_QUALITY=high
```

Supabaseの2項目が両方未設定の場合は、従来の「生成後すぐPDFメール送信」へ安全にフォールバックします。片方だけ設定された状態は設定ミスとして受付を止めます。

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

生成後は、メールで届く専用URLから初稿を確認します。修正は上書きではなく新しい版として保存され、承認後に最終PDFがメール送信されます。額装希望は承認後に専用ページから登録できます。

## レビュー・再生成フロー

1. 初回の鑑定文・関係性分析・パーソナルアート・PDFを生成
2. 非公開Storageと版管理テーブルへVersion 1を保存
3. SHA-256ハッシュだけをDBへ保存した専用確認URLをメール送信
4. 利用者の指摘を受け付け、対象に応じて鑑定文・関係性・作品を再生成
5. 新しいVersionを作成し、旧版は履歴として保持
6. 承認後に同一構図の額装用プリントマスターを生成し、最終PDFを送付
7. 額装画面で高精細マスターを拡大確認し、必要なら額装希望を保存

同じ版への二重修正と二重承認は、状態と版番号を条件にした更新で拒否します。

## 送信履歴の管理

メール送信が成功すると、送信履歴を `data/submissions.jsonl` に1行1件で保存します。  
管理用の一覧は `GET /api/submissions` で取得できます（例: `/api/submissions?limit=100`）。

## PDFの日本語表示について

PDF内で日本語を正しく表示するには、日本語対応フォントが必要です。  
`pdf_generator.py` の `FONT_PATHS` に、環境にあるフォントパスを追加してください（例: Noto Sans CJK など）。

## プロジェクト構成

- `app.py` — Flask ルート・API
- `profile_generator.py` — OpenAI (ChatGPT) API 呼び出し
- `prompts.py` — KOKOROE鑑定文用プロンプト
- `pdf_generator.py` — A4 PDF 生成
- `makaren_workflow.py` — Supabase REST/Storage接続、レビュートークン、作品生成
- `art_direction.py` — 抽象画の構成・物質性・空間設計
- `ART_DIRECTION.md` — 美術史リサーチと制作基準
- `engine_config.json` — エンジン仕様（設計思想・禁止出力など）
- `templates/index.html` — 入力フォーム・結果表示
- `templates/review.html` — 修正・承認・額装希望の専用ページ
