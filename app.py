# -*- coding: utf-8 -*-
"""
マカレン数秘術 プロファイル生成 Webアプリ
"""
import os
import re
import random
import unicodedata
import json
import smtplib
from email.message import EmailMessage
from pathlib import Path
from datetime import datetime, timezone
from datetime import date
from threading import Thread
from flask import Flask, request, jsonify, render_template, send_file
from dotenv import load_dotenv
import profile_generator as pg
import pdf_generator as pdfgen
import io

load_dotenv()

app = Flask(__name__, static_folder="static", template_folder="templates")

# 料金（円）
PRICE_PROFILE_ONLY = 1000
PRICE_RELATIONSHIP_3 = 3000   # 関係性 3名まで（追加料金）
PRICE_RELATIONSHIP_5 = 4000   # 関係性 5名まで（追加料金）
PRICE_RELATIONSHIP_10 = 6000  # 関係性 10名まで（追加料金）
DATA_DIR = Path(__file__).resolve().parent / "data"
SUBMISSIONS_FILE = DATA_DIR / "submissions.jsonl"
AMBASSADORS_FILE = DATA_DIR / "ambassadors.json"
AMBASSADOR_EARNINGS_FILE = DATA_DIR / "ambassador_earnings.jsonl"
AMBASSADOR_REWARD_RATE = 0.10

# 商品ごとの合計金額（プロファイル＋関係性追加料金）
def _order_amount(product: str) -> int:
    if product == "profile_only":
        return PRICE_PROFILE_ONLY
    if product == "relationship_3":
        return PRICE_PROFILE_ONLY + PRICE_RELATIONSHIP_3
    if product == "relationship_5":
        return PRICE_PROFILE_ONLY + PRICE_RELATIONSHIP_5
    if product == "relationship_10":
        return PRICE_PROFILE_ONLY + PRICE_RELATIONSHIP_10
    return PRICE_PROFILE_ONLY


@app.route("/")
def index():
    t3 = PRICE_PROFILE_ONLY + PRICE_RELATIONSHIP_3
    t5 = PRICE_PROFILE_ONLY + PRICE_RELATIONSHIP_5
    t10 = PRICE_PROFILE_ONLY + PRICE_RELATIONSHIP_10
    return render_template(
        "index.html",
        price_profile=PRICE_PROFILE_ONLY,
        price_r3=PRICE_RELATIONSHIP_3,
        price_r5=PRICE_RELATIONSHIP_5,
        price_r10=PRICE_RELATIONSHIP_10,
        total_r3=t3,
        total_r5=t5,
        total_r10=t10,
        price_profile_display=f"{PRICE_PROFILE_ONLY:,}",
        total_r3_display=f"{t3:,}",
        total_r5_display=f"{t5:,}",
        total_r10_display=f"{t10:,}",
    )


@app.route("/thanks")
def thanks():
    """送信完了後のサンキューページ。"""
    return render_template("thanks.html")


@app.route("/name-guide")
def name_guide():
    """名前をローマ字にする方法の説明ページ。"""
    return render_template("name_guide.html")


def _normalize_text(value: str) -> str:
    """全角/半角ゆれを吸収して前後空白を除去する。"""
    return unicodedata.normalize("NFKC", str(value or "")).strip()


def _normalize_name(value: str) -> str:
    """姓名入力を正規化（全角->半角、連続空白圧縮、大文字化）。"""
    normalized = _normalize_text(value)
    normalized = re.sub(r"\s+", " ", normalized)
    return normalized.upper()


def _normalize_birth_date(value: str) -> str:
    """生年月日入力を正規化（全角->半角、区切り統一）。"""
    normalized = _normalize_text(value)
    return normalized.replace(".", "/").replace("-", "/")


def _normalize_email(value: str) -> str:
    return _normalize_text(value).lower()


def _is_valid_email(value: str) -> bool:
    if not value:
        return False
    return bool(re.match(r"^[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}$", value))


def _strip_markdown(text: str) -> str:
    """モデル出力からMarkdown記号を取り除く。"""
    if not text:
        return ""
    cleaned = str(text)
    for pat in ("**", "##", "---"):
        cleaned = cleaned.replace(pat, "")
    return cleaned


def _guess_smtp_config(smtp_user: str) -> tuple[str, int, bool, bool] | None:
    """
    SMTP_HOST 未設定時に、メールアドレスのドメインから一般的な設定を補完する。
    返り値: (host, port, use_tls, use_ssl)
    """
    if not smtp_user or "@" not in smtp_user:
        return None
    domain = smtp_user.split("@", 1)[1].lower()
    if domain in ("gmail.com", "googlemail.com"):
        return ("smtp.gmail.com", 587, True, False)
    if domain in ("outlook.com", "hotmail.com", "live.com", "outlook.jp"):
        return ("smtp.office365.com", 587, True, False)
    if domain in ("icloud.com", "me.com", "mac.com"):
        return ("smtp.mail.me.com", 587, True, False)
    if domain == "yahoo.co.jp":
        return ("smtp.mail.yahoo.co.jp", 465, False, True)
    return None


def _append_submission(record: dict):
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    with SUBMISSIONS_FILE.open("a", encoding="utf-8") as f:
        f.write(json.dumps(record, ensure_ascii=False) + "\n")


def _read_submissions(limit: int = 200) -> list[dict]:
    if not SUBMISSIONS_FILE.exists():
        return []
    with SUBMISSIONS_FILE.open("r", encoding="utf-8") as f:
        lines = [ln.strip() for ln in f if ln.strip()]
    rows = []
    for ln in lines[-max(1, min(limit, 1000)):]:
        try:
            rows.append(json.loads(ln))
        except json.JSONDecodeError:
            continue
    rows.reverse()
    return rows


def _existing_referral_codes_and_owners() -> tuple[set[str], dict[str, str]]:
    """発行済み紹介コード一覧と、コード→紹介者メールの対応を返す。"""
    codes = set()
    code_to_email: dict[str, str] = {}
    if not SUBMISSIONS_FILE.exists():
        return codes, code_to_email
    with SUBMISSIONS_FILE.open("r", encoding="utf-8") as f:
        for ln in f:
            ln = ln.strip()
            if not ln:
                continue
            try:
                r = json.loads(ln)
                c = (r.get("referral_code_issued") or "").strip()
                if c and len(c) == 7 and c.isdigit():
                    codes.add(c)
                    code_to_email[c] = (r.get("email") or "").strip()
            except json.JSONDecodeError:
                continue
    return codes, code_to_email


def _generate_referral_code() -> str:
    """重複しないランダム7桁の紹介コードを発行する。"""
    existing, _ = _existing_referral_codes_and_owners()
    for _ in range(100):
        code = str(random.randint(1000000, 9999999))
        if code not in existing:
            return code
    return str(random.randint(1000000, 9999999))


def _referrer_email_by_code(code: str) -> str | None:
    """紹介コードから紹介者メールを取得。"""
    _, code_to_email = _existing_referral_codes_and_owners()
    return code_to_email.get((code or "").strip()) or None


def _read_ambassadors() -> list[str]:
    """承認済みアンバサダーのメール一覧（非公開）。"""
    if not AMBASSADORS_FILE.exists():
        return []
    try:
        with AMBASSADORS_FILE.open("r", encoding="utf-8") as f:
            data = json.load(f)
        emails = data.get("emails") if isinstance(data, dict) else (data if isinstance(data, list) else [])
        return [str(e).strip().lower() for e in emails if e and "@" in str(e)]
    except (json.JSONDecodeError, TypeError):
        return []


def _is_ambassador(email: str) -> bool:
    return _normalize_email(email) in _read_ambassadors()


def _append_ambassador_earning(ambassador_email: str, referee_email: str, order_amount: int):
    """アンバサダー報酬（売上10%）を1件記録。Stripe還元は別途。"""
    reward = int(order_amount * AMBASSADOR_REWARD_RATE)
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    record = {
        "at": datetime.now(timezone.utc).isoformat(),
        "ambassador_email": _normalize_email(ambassador_email),
        "referee_email": _normalize_email(referee_email),
        "order_amount": order_amount,
        "reward_amount": reward,
    }
    with AMBASSADOR_EARNINGS_FILE.open("a", encoding="utf-8") as f:
        f.write(json.dumps(record, ensure_ascii=False) + "\n")


def _admin_key_ok() -> bool:
    key = os.getenv("ADMIN_SECRET", "").strip()
    if not key:
        return False
    return request.args.get("key") == key or request.headers.get("X-Admin-Key") == key



def _resolve_smtp_settings() -> tuple[dict | None, str | None]:
    smtp_host = os.getenv("SMTP_HOST", "").strip()
    smtp_port = int(os.getenv("SMTP_PORT", "587"))
    smtp_user = os.getenv("SMTP_USER", "").strip()
    smtp_password = os.getenv("SMTP_PASSWORD", "").strip()
    smtp_from = os.getenv("SMTP_FROM", smtp_user).strip()
    smtp_use_tls = os.getenv("SMTP_USE_TLS", "true").strip().lower() == "true"
    smtp_use_ssl = os.getenv("SMTP_USE_SSL", "false").strip().lower() == "true"

    if not smtp_user or not smtp_password:
        return None, "SMTP設定が不足しています。.env に最低限 SMTP_USER / SMTP_PASSWORD を設定してください"

    if not smtp_host:
        guessed = _guess_smtp_config(smtp_user)
        if guessed:
            smtp_host, smtp_port, smtp_use_tls, smtp_use_ssl = guessed
        else:
            return None, "SMTP_HOST が未設定です。Gmail/Outlook/iCloud/Yahoo以外は SMTP_HOST と SMTP_PORT も設定してください"

    if not smtp_from:
        smtp_from = smtp_user

    return (
        {
            "smtp_host": smtp_host,
            "smtp_port": smtp_port,
            "smtp_user": smtp_user,
            "smtp_password": smtp_password,
            "smtp_from": smtp_from,
            "smtp_use_tls": smtp_use_tls,
            "smtp_use_ssl": smtp_use_ssl,
        },
        None,
    )


def _email_subject_and_body(product: str, name: str) -> tuple[str, str]:
    """プラン別のメール件名と本文を返す。"""
    if product == "relationship_3":
        subject = "3名相性鑑定の結果をお届けいたしました"
        body = (
            "このたびは、3名相性鑑定をご依頼いただきありがとうございます。\n"
            "結果をお送りいたしました。 それぞれの関係性について、何か感じるものがあれば幸いです。\n\n"
            "3名という範囲で見ると、ひとつひとつの関係の輪郭がはっきりします。 同時に、人間関係には「流れ」があることにも気づかれるかもしれません。\n"
            "ある人との関係が、別の関係に影響を与えている。 自分がどこに立っているかで、見える景色が変わる。\n"
            "もし「もう少し広く見てみたい」と思われたら、 5名相性鑑定という選択肢もございます。 視野を広げることで、ご自身の立ち位置がより明確になることがあります。\n\n"
            "もしご興味をお持ちの方がいらっしゃれば、 あなた専用の紹介コードをお伝えください。\n"
            "ご友人は10%OFFで鑑定をお受けいただけます。 このコードはご自身でもお使いいただけますので、 次回ご利用の際にもどうぞ。\n"
            "数秘術という共通の視点があると、会話が少し深まることがあります。\n\n"
            "――\n"
            "マカレン数秘術\n"
            "KIMURA KENJI\n"
        )
    elif product == "relationship_5":
        subject = "5名相性鑑定の結果をお届けいたしました"
        body = (
            "このたびは、5名相性鑑定をご依頼いただきありがとうございます。 じっくりと向き合ってくださったこと、嬉しく思います。\n"
            "鑑定結果をお送りいたしました。\n\n"
            "5名という人数になると、単なる相性を超えて、 ひとつのパターンが見えてくることがあります。\n"
            "あなたがどのような役割を担いやすいのか。 どういう人に惹かれ、どういう人との間に緊張が生まれやすいのか。\n"
            "それは良い悪いではなく、ただ「そういう傾向がある」ということ。 知っておくだけで、関係の捉え方が少し変わることがあります。\n"
            "人間関係は、ステージごとに更新されていくものです。 環境が変わったとき、新しい人が加わったとき、 またこの鑑定を見直していただければ、違う発見があるかもしれません。\n\n"
            "もしこの体験を誰かと共有されたい場合は、 あなた専用の紹介コードをお使いください。\n"
            "ご友人は10%OFFで鑑定をお受けいただけます。 このコードはご自身の次回鑑定にもお使いいただけます。\n"
            "互いの特性を知った上で関係を築く。 そんな会話のきっかけになれば幸いです。\n\n"
            "――\n"
            "マカレン数秘術\n"
            "KIMURA KENJI\n"
        )
    elif product == "relationship_10":
        subject = "10名相性鑑定の結果をお届けいたしました"
        body = (
            "このたびは、10名相性鑑定をご依頼いただきありがとうございます。 これだけの関係性に真剣に向き合おうとされる姿勢に、深く敬意を表します。\n"
            "鑑定結果をお送りいたしました。\n\n"
            "10名という人数を俯瞰すると、 人間関係がひとつの「地図」のように見えてくることがあります。\n"
            "誰と深く関わり、誰とは適度な距離を保つのか。 どの関係にエネルギーを注ぎ、どこで力を抜くのか。\n"
            "こうした判断が、静かに、しかし的確になっていく。 それがこの鑑定の意図するところです。\n"
            "新しい縁が現れたとき、環境が変化したときには、 その人を加えて再度分析されることをお勧めいたします。 地図は更新されることで、より有用なものになります。\n\n"
            "もしこの鑑定にご興味をお持ちの方がいらっしゃれば、 あなた専用の紹介コードをお伝えください。\n"
            "ご友人は10%OFFで鑑定をお受けいただけます。 このコードはご自身でもお使いいただけます。\n"
            "理解を共有できる人が増えることで、 あなた自身の判断もまた、より確かなものになっていきます。\n\n"
            "――\n"
            "マカレン数秘術\n"
            "KIMURA KENJI\n"
        )
    else:
        # profile_only
        subject = "鑑定結果をお届けいたしました"
        body = (
            "このたびは、マカレン数秘術をご利用いただきありがとうございます。\n"
            "鑑定結果をお送りいたしました。 どうぞお時間のあるときに、お読みいただければ幸いです。\n\n"
            "自分自身の数字を知ると、ふとしたときに気づくことがあります。 なぜこのタイミングで、あの人のことが気になったのか。 どうしてこの関係に、特別な何かを感じるのか。\n"
            "もし今、誰かの顔が浮かんでいるなら、 その人との相性には、何らかの意味があるのかもしれません。\n"
            "相性鑑定はいつでもお受けいただけます。 必要だと感じたときに、またお声がけください。\n\n"
            "もしマカレン数秘術を誰かにお伝えいただける場合は、 あなた専用の紹介コードをお使いください。\n"
            "ご友人は10%OFFで鑑定をお受けいただけます。 また、このコードはご自身でもお使いいただけます。\n"
            "同じ体験を共有することで、会話がひとつ深まることもあります。\n\n"
            "――\n"
            "マカレン数秘術\n"
            "KIMURA KENJI\n"
        )
    return subject, body


def _send_profile_email(
    profile: str,
    relationship: str,
    name: str,
    email_to: str,
    product: str,
    birth_date: str,
    consultation: str,
    numbers: dict | None,
    nine_year_cycle: list[dict] | None = None,
    referral_code_issued: str | None = None,
    referred_by: str | None = None,
) -> tuple[bool, str | None]:
    if not profile:
        return False, "送信するプロファイル本文がありません"
    if not _is_valid_email(email_to):
        return False, "メールアドレスの形式が正しくありません"

    smtp_settings, smtp_error = _resolve_smtp_settings()
    if smtp_error:
        return False, smtp_error

    full_content = profile
    if relationship:
        # 本文（1〜9のセクション）のあと、必ず新しいページから
        # 「10. 周囲の人物との関係性」が始まるようにページ分割マーカーを挿入する。
        full_content += "\n\n[[PAGEBREAK]]\n\n" + relationship
    title = f"マカレン数秘術 プロファイル — {name}"

    try:
        pdf_bytes = pdfgen.build_pdf(
            full_content,
            title=title,
            numbers=numbers or {},
            nine_year_cycle=nine_year_cycle or [],
        )
    except Exception as e:
        return False, f"PDFの作成に失敗しました: {e}"

    subject, body = _email_subject_and_body(product, name)
    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = smtp_settings["smtp_from"]
    msg["To"] = email_to
    msg.set_content(body)
    safe_name = re.sub(r"[^0-9A-Za-z_\-]+", "_", name) or "profile"
    msg.add_attachment(
        pdf_bytes,
        maintype="application",
        subtype="pdf",
        filename=f"makaren_profile_{safe_name}.pdf",
    )

    try:
        if smtp_settings["smtp_use_ssl"]:
            with smtplib.SMTP_SSL(
                smtp_settings["smtp_host"], smtp_settings["smtp_port"], timeout=30
            ) as server:
                server.login(smtp_settings["smtp_user"], smtp_settings["smtp_password"])
                server.send_message(msg)
        else:
            with smtplib.SMTP(
                smtp_settings["smtp_host"], smtp_settings["smtp_port"], timeout=30
            ) as server:
                if smtp_settings["smtp_use_tls"]:
                    server.starttls()
                server.login(smtp_settings["smtp_user"], smtp_settings["smtp_password"])
                server.send_message(msg)
    except Exception as e:
        return False, f"メール送信に失敗しました: {e}"

    record = {
        "sent_at": datetime.now(timezone.utc).isoformat(),
        "name": name,
        "email": email_to,
        "birth_date": birth_date,
        "product": product,
        "consultation": consultation,
        "has_relationship": bool(relationship),
    }
    if referral_code_issued:
        record["referral_code_issued"] = referral_code_issued
    if referred_by:
        record["referred_by"] = referred_by
    _append_submission(record)
    return True, None


def _parse_birth_date(birth_date: str):
    """
    YYYY/MM/DD または YYYY-MM-DD を (year, month, day) に変換。
    ・形式が違う
    ・存在しない日付
    ・1900〜2100年の範囲外
    はエラー扱いとして (None, None, None) を返す。
    """
    if not birth_date:
        return None, None, None
    m = re.match(r"^\s*(\d{4})[/-](\d{1,2})[/-](\d{1,2})\s*$", birth_date)
    if not m:
        return None, None, None
    y, month, day = map(int, m.groups())
    if y < 1900 or y > 2100:
        return None, None, None
    try:
        _ = date(y, month, day)
    except ValueError:
        return None, None, None
    return y, month, day


def _run_generate_job(
    last_name: str,
    first_name: str,
    maiden_last_name: str,
    birth_date: str,
    consultation: str,
    email_to: str,
    product: str,
    referred_by_code: str,
    others: list,
) -> None:
    """プロファイル生成〜PDF作成・メール送信までをバックグラウンドで実行するジョブ。

    HTTPレスポンスとは切り離して実行されるため、ユーザーがページ遷移しても処理は最後まで継続する。
    """
    try:
        import numerology as num

        y, m, d = _parse_birth_date(birth_date)
        if y is None or m is None or d is None:
            return

        numbers = num.compute_all(last_name, first_name, y, m, d)
        nine_year_cycle = num.compute_nine_year_cycle(y, m, d)
        numbers_maiden = None
        if maiden_last_name and maiden_last_name != last_name:
            numbers_maiden = num.compute_all(maiden_last_name, first_name, y, m, d)
        name_display = f"{last_name} {first_name}"

        # LLM に渡す相談内容。未入力の場合は、構成数から重要そうなテーマを選んで扱うよう指示する。
        if consultation:
            consultation_for_llm = consultation
        else:
            consultation_for_llm = (
                "本人から具体的な相談内容はないため、あなたが構成数の傾向から見て特に重要だと考えるテーマ"
                "（キャリア・人間関係・自己表現・お金・パートナーシップなどの中から1つ）を選び、"
                "そのテーマへのガイダンスも併せて含めてください。"
            )

        profile_text = pg.generate_profile(
            last_name,
            first_name,
            birth_date,
            consultation_for_llm,
            numbers,
            nine_year_cycle,
            maiden_last_name=maiden_last_name or None,
            numbers_maiden=numbers_maiden,
        )
        profile_text = _strip_markdown(profile_text)

        result: dict = {
            "ok": True,
            "profile": profile_text,
            "product": product,
            "numbers": numbers,
            "nine_year_cycle": nine_year_cycle,
            "name": name_display,
        }

        max_others = 0
        if product == "relationship_3":
            max_others = 3
        elif product == "relationship_5":
            max_others = 5
        elif product == "relationship_10":
            max_others = 10
        if max_others and others:
            cleaned_others = []
            for o in others:
                last = _normalize_name(o.get("last_name") or "")
                first = _normalize_name(o.get("first_name") or "")
                if not last and not first:
                    continue
                bd = _normalize_birth_date(o.get("birth_date") or "")
                entry = {
                    "last_name": last,
                    "first_name": first,
                    "birth_date": bd,
                    "name_display": f"{last} {first}".strip() or "（名前未入力）",
                }
                y2, m2, d2 = _parse_birth_date(bd)
                if y2 is not None and m2 is not None and d2 is not None:
                    entry["numbers"] = num.compute_all(last, first, y2, m2, d2)
                else:
                    entry["numbers"] = {}
                cleaned_others.append(entry)
            others = cleaned_others[:max_others]
            if others:
                relation_text = pg.generate_relationship_analysis(
                    name_display, birth_date, numbers, others
                )
                relation_text = _strip_markdown(relation_text)
                result["relationship"] = relation_text
            else:
                result["relationship"] = None
        else:
            result["relationship"] = None

        # 紹介コード発行（メール送信時のみ履歴に残す）
        referral_code_issued = ""
        referred_by = (
            referred_by_code
            if (referred_by_code and len(referred_by_code) == 7 and referred_by_code.isdigit())
            else None
        )
        if email_to:
            referral_code_issued = _generate_referral_code()
            order_amount = _order_amount(product)
            # 通常ユーザー: 紹介者への金銭報酬なし。アンバサダーのみ非公開で報酬を記録。
            if referred_by:
                referrer_email = _referrer_email_by_code(referred_by)
                if referrer_email and referrer_email != email_to and _is_ambassador(referrer_email):
                    _append_ambassador_earning(referrer_email, email_to, order_amount)
            _send_profile_email(
                profile=profile_text,
                relationship=result.get("relationship") or "",
                name=name_display,
                email_to=email_to,
                product=product,
                birth_date=birth_date,
                consultation=consultation,
                numbers=numbers,
                nine_year_cycle=nine_year_cycle,
                referral_code_issued=referral_code_issued,
                referred_by=referred_by,
            )
    except Exception:
        # バックグラウンドジョブなので、例外はログにだけ残す
        import traceback

        traceback.print_exc()


@app.route("/api/generate", methods=["POST"])
def generate():
    """プロファイル生成リクエストを受け取り、バックグラウンドジョブとして処理を実行する。

    フロントエンドからのHTTPレスポンスとは切り離されるため、
    ユーザーが /thanks ページやトップページに移動しても、
    PDF生成とメール送信はサーバー側で完了まで実行される。
    """
    data = request.get_json() or {}
    last_name = _normalize_name(data.get("last_name"))
    first_name = _normalize_name(data.get("first_name"))
    maiden_last_name = _normalize_name(data.get("maiden_last_name") or "")
    birth_date = _normalize_birth_date(data.get("birth_date"))
    consultation = _normalize_text(data.get("consultation"))
    email_to = _normalize_email(data.get("email"))
    product = data.get("product", "profile_only")
    referred_by_code = (data.get("referral_code") or "").strip()
    others = data.get("others", [])

    # サーバー側でも最低限のバリデーションだけ行い、問題なければ非同期ジョブを起動する
    if not last_name or not first_name:
        return jsonify({"ok": False, "error": "姓・名（ローマ字）は必須です"}), 400
    if not birth_date:
        return jsonify({"ok": False, "error": "生年月日は必須です"}), 400

    y, m, d = _parse_birth_date(birth_date)
    if y is None or m is None or d is None:
        return jsonify(
            {
                "ok": False,
                "error": "生年月日は YYYY/MM/DD 形式で、存在する日付（1900〜2100年）を入力してください",
            }
        ), 400

    # バックグラウンドでプロファイル生成〜メール送信まで実行
    Thread(
        target=_run_generate_job,
        args=(
            last_name,
            first_name,
            maiden_last_name,
            birth_date,
            consultation,
            email_to,
            product,
            referred_by_code,
            others,
        ),
        daemon=True,
    ).start()

    # フロント側は結果の詳細を使っていないため、即座に成功レスポンスだけ返す
    return jsonify({"ok": True})


@app.route("/api/download-pdf", methods=["POST"])
def download_pdf():
    data = request.get_json() or {}
    profile = data.get("profile", "")
    relationship = data.get("relationship")
    name = (data.get("name") or "プロファイル").strip()

    if not profile:
        return jsonify({"ok": False, "error": "プロファイルがありません"}), 400

    full_content = profile
    if relationship:
        full_content += "\n\n[[PAGEBREAK]]\n\n" + relationship

    title = f"マカレン数秘術 プロファイル — {name}"
    try:
        pdf_bytes = pdfgen.build_pdf(full_content, title=title)
    except Exception as e:
        return jsonify({"ok": False, "error": f"PDFの作成に失敗しました: {e}"}), 500

    return send_file(
        io.BytesIO(pdf_bytes),
        mimetype="application/pdf",
        as_attachment=True,
        download_name=f"makaren_profile_{name}.pdf",
    )


@app.route("/api/send-email", methods=["POST"])
def send_email():
    data = request.get_json() or {}
    profile = _normalize_text(data.get("profile"))
    relationship = _normalize_text(data.get("relationship"))
    name = _normalize_text(data.get("name") or "プロファイル")
    email_to = _normalize_email(data.get("email"))
    product = _normalize_text(data.get("product") or "profile_only")
    birth_date = _normalize_birth_date(data.get("birth_date"))
    consultation = _normalize_text(data.get("consultation"))

    # 可能ならここでも9年サイクルを再計算
    y, m, d = _parse_birth_date(birth_date)
    nine_year_cycle = []
    if y is not None and m is not None and d is not None:
        import numerology as num  # 局所インポート
        nine_year_cycle = num.compute_nine_year_cycle(y, m, d)

    sent_ok, sent_error = _send_profile_email(
        profile=profile,
        relationship=relationship,
        name=name,
        email_to=email_to,
        product=product,
        birth_date=birth_date,
        consultation=consultation,
        numbers=None,
        nine_year_cycle=nine_year_cycle,
    )
    if not sent_ok:
        status = 400
        if sent_error and (sent_error.startswith("PDFの作成") or sent_error.startswith("メール送信")):
            status = 500
        return jsonify({"ok": False, "error": sent_error or "メール送信に失敗しました"}), status
    return jsonify({"ok": True})


@app.route("/api/submissions", methods=["GET"])
def list_submissions():
    limit_raw = request.args.get("limit", "200")
    try:
        limit = int(limit_raw)
    except ValueError:
        limit = 200
    rows = _read_submissions(limit=limit)
    return jsonify({"ok": True, "items": rows, "count": len(rows)})


def _read_ambassador_earnings(limit: int = 5000) -> list[dict]:
    if not AMBASSADOR_EARNINGS_FILE.exists():
        return []
    rows = []
    with AMBASSADOR_EARNINGS_FILE.open("r", encoding="utf-8") as f:
        for ln in f:
            ln = ln.strip()
            if not ln:
                continue
            try:
                rows.append(json.loads(ln))
            except json.JSONDecodeError:
                continue
    rows.reverse()
    return rows[:limit]


def _ambassador_stats() -> tuple[list[dict], int, int]:
    """アンバサダーごとの紹介数・売上、全体の累計紹介数・累計売上。"""
    ambassadors = _read_ambassadors()
    earnings = _read_ambassador_earnings()
    by_email: dict[str, dict] = {}
    for e in ambassadors:
        by_email[e] = {"email": e, "referral_count": 0, "total_sales": 0, "total_reward": 0}
    total_referrals = 0
    total_sales = 0
    for r in earnings:
        em = (r.get("ambassador_email") or "").strip().lower()
        if not em:
            continue
        total_referrals += 1
        amt = r.get("order_amount") or 0
        rew = r.get("reward_amount") or 0
        total_sales += amt
        if em not in by_email:
            by_email[em] = {"email": em, "referral_count": 0, "total_sales": 0, "total_reward": 0}
        by_email[em]["referral_count"] += 1
        by_email[em]["total_sales"] += amt
        by_email[em]["total_reward"] += rew
    return list(by_email.values()), total_referrals, total_sales


@app.route("/admin")
def admin():
    """管理画面（ADMIN_SECRET 必須）。アンバサダー一覧・累計紹介数・累計売上。"""
    if not _admin_key_ok():
        return "Unauthorized", 401
    ambassadors_list, total_referrals, total_sales = _ambassador_stats()
    return render_template(
        "admin.html",
        ambassadors=ambassadors_list,
        total_referrals=total_referrals,
        total_sales=total_sales,
        admin_key=request.args.get("key", ""),
    )


@app.route("/admin/ambassadors", methods=["POST"])
def admin_add_ambassador():
    """アンバサダーを1件追加（招待制・非公開）。"""
    if not _admin_key_ok():
        return jsonify({"ok": False, "error": "Unauthorized"}), 401
    data = request.get_json() or request.form
    email = _normalize_email(data.get("email") or "")
    if not email or not _is_valid_email(email):
        return jsonify({"ok": False, "error": "有効なメールアドレスを入力してください"}), 400
    current = _read_ambassadors()
    if email in current:
        return jsonify({"ok": True, "message": "既に登録済みです"})
    current.append(email)
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    with AMBASSADORS_FILE.open("w", encoding="utf-8") as f:
        json.dump({"emails": current, "updated_at": datetime.now(timezone.utc).isoformat()}, f, ensure_ascii=False, indent=2)
    return jsonify({"ok": True, "message": "追加しました"})


@app.route("/admin/ambassadors/remove", methods=["POST"])
def admin_remove_ambassador():
    """アンバサダーを1件解除。"""
    if not _admin_key_ok():
        return jsonify({"ok": False, "error": "Unauthorized"}), 401
    data = request.get_json() or request.form
    email = _normalize_email(data.get("email") or "")
    if not email:
        return jsonify({"ok": False, "error": "メールアドレスを指定してください"}), 400
    current = _read_ambassadors()
    if email not in current:
        return jsonify({"ok": True, "message": "登録されていません"})
    current = [e for e in current if e != email]
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    with AMBASSADORS_FILE.open("w", encoding="utf-8") as f:
        json.dump({"emails": current, "updated_at": datetime.now(timezone.utc).isoformat()}, f, ensure_ascii=False, indent=2)
    return jsonify({"ok": True, "message": "解除しました"})


if __name__ == "__main__":
    # READMEの案内URLと合わせて、デフォルトは5001に統一
    port = int(os.getenv("FLASK_PORT", "5001"))
    app.run(host="0.0.0.0", port=port, debug=os.getenv("FLASK_ENV") == "development")
