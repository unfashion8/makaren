# -*- coding: utf-8 -*-
"""KOKOROE／ココロエ パーソナル鑑定・絵画販売Webアプリ。"""
import os
import re
import random
import unicodedata
import json
import smtplib
import logging
from email.message import EmailMessage
from pathlib import Path
from datetime import datetime, timezone
from datetime import date
from threading import Thread
from flask import Flask, request, jsonify, render_template, send_file, make_response
from dotenv import load_dotenv
import profile_generator as pg
import pdf_generator as pdfgen
from makaren_workflow import (
    WorkflowStoreError,
    generate_artwork,
    generate_print_master,
    generate_review_token,
    get_workflow_store,
    hash_review_token,
    workflow_config_error,
    workflow_enabled,
)
import io

load_dotenv()

logging.basicConfig(
    level=os.getenv("LOG_LEVEL", "INFO").upper(),
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("kokoroe.mail")

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


@app.route("/health")
def health():
    """稼働監視用。起動確認だけしてすぐ 200 を返す。"""
    return "", 200


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


@app.route("/lp")
def lp():
    """KOKOROEのランディングページ。"""
    return render_template("lp.html")


# UNFASHION オークション商品一覧（unfashion8.com 用）
UNFASHION_PRODUCTS_FILE = DATA_DIR / "unfashion_products.json"
SELLER_URL = "https://auctions.yahoo.co.jp/seller/4XQdPCTXHMTSxfGS6kcu2ab1B3GFN"


def _read_unfashion_products() -> tuple[list[dict], int, str]:
    """unfashion_products.json を読み、商品リスト・総数・出品者URLを返す。"""
    if not UNFASHION_PRODUCTS_FILE.exists():
        return [], 0, SELLER_URL
    try:
        with UNFASHION_PRODUCTS_FILE.open("r", encoding="utf-8") as f:
            data = json.load(f)
        items = data.get("items") if isinstance(data, dict) else []
        total = data.get("total", len(items)) if isinstance(data, dict) else len(items)
        seller_url = (data.get("seller_url") or SELLER_URL) if isinstance(data, dict) else SELLER_URL
        if not isinstance(items, list):
            items = []
        return items, total, seller_url
    except (json.JSONDecodeError, TypeError):
        return [], 0, SELLER_URL


@app.route("/shop")
def shop():
    """UNFASHION 商品一覧ページ（Yahoo!オークション出品を自社サイトで表示）。"""
    items, total, seller_url = _read_unfashion_products()
    return render_template(
        "shop.html",
        items=items,
        total=total,
        seller_url=seller_url,
    )


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
            "KOKOROEという共通の視点があると、会話が少し深まることがあります。\n\n"
            "――\n"
            "KOKOROE／ココロエ\n"
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
            "KOKOROE／ココロエ\n"
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
            "KOKOROE／ココロエ\n"
            "KIMURA KENJI\n"
        )
    else:
        # profile_only
        subject = "鑑定結果をお届けいたしました"
        body = (
            "このたびは、KOKOROE／ココロエをご利用いただきありがとうございます。\n"
            "鑑定結果をお送りいたしました。 どうぞお時間のあるときに、お読みいただければ幸いです。\n\n"
            "自分自身の内面の傾向を知ると、ふとしたときに気づくことがあります。 なぜこのタイミングで、あの人のことが気になったのか。 どうしてこの関係に、特別な何かを感じるのか。\n"
            "もし今、誰かの顔が浮かんでいるなら、 その人との相性には、何らかの意味があるのかもしれません。\n"
            "相性鑑定はいつでもお受けいただけます。 必要だと感じたときに、またお声がけください。\n\n"
            "もしKOKOROEを誰かにお伝えいただける場合は、 あなた専用の紹介コードをお使いください。\n"
            "ご友人は10%OFFで鑑定をお受けいただけます。 また、このコードはご自身でもお使いいただけます。\n"
            "同じ体験を共有することで、会話がひとつ深まることもあります。\n\n"
            "――\n"
            "KOKOROE／ココロエ\n"
            "KIMURA KENJI\n"
        )
    return subject, body


def _send_plain_email(email_to: str, subject: str, body: str) -> tuple[bool, str | None]:
    """Send a small notification email without attachments."""
    if not _is_valid_email(email_to):
        return False, "メールアドレスの形式が正しくありません"
    smtp_settings, smtp_error = _resolve_smtp_settings()
    if smtp_error:
        return False, smtp_error
    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = smtp_settings["smtp_from"]
    msg["To"] = email_to
    msg.set_content(body)
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
        return True, None
    except Exception as exc:
        logger.exception("[workflow_email] notification failed email=%s", email_to)
        return False, f"メール送信に失敗しました: {exc}"


def _send_review_email(
    email_to: str,
    name: str,
    review_url: str,
    *,
    revised: bool = False,
) -> tuple[bool, str | None]:
    subject = "修正版の確認をお願いします — KOKOROE" if revised else "鑑定と作品の確認をお願いします — KOKOROE"
    opening = "ご指摘を反映した修正版が完成しました。" if revised else "鑑定書とパーソナルアートの初稿が完成しました。"
    body = (
        f"{name} 様\n\n"
        f"{opening}\n"
        "下記の専用ページで内容をご確認ください。\n\n"
        f"{review_url}\n\n"
        "修正したい点がある場合は、ページ内から具体的にお知らせください。\n"
        "内容に問題がなければ承認してください。承認後、最終PDFをメールでお送りします。\n\n"
        "このURLはご本人専用です。第三者へ転送しないでください。\n\n"
        "――\nKOKOROE／ココロエ\nKIMURA KENJI\n"
    )
    return _send_plain_email(email_to, subject, body)


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
    others_list: list[dict] | None = None,
    artwork_bytes: bytes | None = None,
    pdf_bytes_override: bytes | None = None,
) -> tuple[bool, str | None]:
    profile = pg.hide_internal_calculation_values(profile)
    relationship = pg.hide_internal_calculation_values(relationship)
    if not profile:
        logger.error("[send_email] プロファイル本文が空のため送信できません email=%s product=%s", email_to, product)
        return False, "送信するプロファイル本文がありません"
    if not _is_valid_email(email_to):
        logger.error("[send_email] メールアドレス形式が不正です email=%s", email_to)
        return False, "メールアドレスの形式が正しくありません"

    smtp_settings, smtp_error = _resolve_smtp_settings()
    if smtp_error:
        logger.error("[send_email] SMTP設定エラー email=%s error=%s", email_to, smtp_error)
        return False, smtp_error

    full_content = profile
    if relationship:
        # 本文（1〜9のセクション）のあと、必ず新しいページから
        # 「10. 周囲の人物との関係性」が始まるようにページ分割マーカーを挿入する。
        full_content += "\n\n[[PAGEBREAK]]\n\n" + relationship
    title = f"KOKOROE パーソナル鑑定書 — {name}"

    pdf_bytes = pdf_bytes_override
    if pdf_bytes is None:
        try:
            pdf_bytes = pdfgen.build_pdf(
                full_content,
                title=title,
                numbers=numbers or {},
                nine_year_cycle=nine_year_cycle or [],
                artwork_bytes=artwork_bytes,
            )
        except Exception as e:
            logger.exception("[send_email] PDF作成エラー email=%s product=%s", email_to, product)
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
        filename=f"kokoroe_reading_{safe_name}.pdf",
    )

    try:
        logger.info(
            "[send_email] 送信開始 email=%s from=%s host=%s port=%s product=%s",
            email_to,
            smtp_settings["smtp_from"],
            smtp_settings["smtp_host"],
            smtp_settings["smtp_port"],
            product,
        )
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
        logger.info("[send_email] 送信完了 email=%s product=%s", email_to, product)
    except Exception as e:
        logger.exception("[send_email] メール送信エラー email=%s product=%s", email_to, product)
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
    if others_list:
        record["others"] = [{"name_display": o.get("name_display") or "", "birth_date": o.get("birth_date") or ""} for o in others_list]
    try:
        _append_submission(record)
        logger.info("[send_email] 送信記録を保存しました email=%s product=%s", email_to, product)
    except Exception:
        # SMTP送信後のローカル記録失敗を「未送信」と扱うと再送が重複するため、
        # 納品自体は成功として扱い、記録エラーだけをログに残す。
        logger.exception("[send_email] 送信記録の保存に失敗しました email=%s", email_to)
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


def _generate_analysis(
    last_name: str,
    first_name: str,
    maiden_last_name: str,
    birth_date: str,
    consultation: str,
    product: str,
    others: list,
) -> dict:
    """Generate the shared profile/relationship payload used by both delivery modes."""
    import numerology as num

    y, m, d = _parse_birth_date(birth_date)
    if y is None or m is None or d is None:
        raise ValueError("生年月日が不正です")
    numbers = num.compute_all(last_name, first_name, y, m, d)
    nine_year_cycle = num.compute_nine_year_cycle(y, m, d)
    numbers_maiden = None
    if maiden_last_name and maiden_last_name != last_name:
        numbers_maiden = num.compute_all(maiden_last_name, first_name, y, m, d)
    name_display = f"{last_name} {first_name}"
    consultation_for_llm = consultation or (
        "本人から具体的な相談内容はないため、あなたが内部分析から見て特に重要だと考えるテーマ"
        "（キャリア・人間関係・自己表現・お金・パートナーシップなどの中から1つ）を選び、"
        "そのテーマへのガイダンスも併せて含めてください。"
    )
    profile_text = _strip_markdown(
        pg.generate_profile(
            last_name,
            first_name,
            birth_date,
            consultation_for_llm,
            numbers,
            nine_year_cycle,
            maiden_last_name=maiden_last_name or None,
            numbers_maiden=numbers_maiden,
        )
    )
    result: dict = {
        "ok": True,
        "profile": profile_text,
        "relationship": None,
        "product": product,
        "numbers": numbers,
        "numbers_maiden": numbers_maiden,
        "nine_year_cycle": nine_year_cycle,
        "name": name_display,
        "others": [],
    }
    max_others = {
        "relationship_3": 3,
        "relationship_5": 5,
        "relationship_10": 10,
    }.get(product, 0)
    if max_others and others:
        cleaned_others = []
        for other in others:
            last = _normalize_name(other.get("last_name") or "")
            first = _normalize_name(other.get("first_name") or "")
            if not last and not first:
                continue
            other_birth = _normalize_birth_date(other.get("birth_date") or "")
            entry = {
                "last_name": last,
                "first_name": first,
                "birth_date": other_birth,
                "name_display": f"{last} {first}".strip() or "（名前未入力）",
                "numbers": {},
            }
            y2, m2, d2 = _parse_birth_date(other_birth)
            if y2 is not None and m2 is not None and d2 is not None:
                entry["numbers"] = num.compute_all(last, first, y2, m2, d2)
            cleaned_others.append(entry)
        result["others"] = cleaned_others[:max_others]
        if result["others"]:
            result["relationship"] = _strip_markdown(
                pg.generate_relationship_analysis(
                    name_display, birth_date, numbers, result["others"]
                )
            )
    return result


def _result_pdf_bytes(result: dict, artwork_bytes: bytes | None) -> bytes:
    full_content = pg.hide_internal_calculation_values(result["profile"])
    if result.get("relationship"):
        full_content += "\n\n[[PAGEBREAK]]\n\n" + pg.hide_internal_calculation_values(result["relationship"])
    return pdfgen.build_pdf(
        full_content,
        title=f"KOKOROE パーソナル鑑定書 — {result['name']}",
        numbers=result.get("numbers") or {},
        nine_year_cycle=result.get("nine_year_cycle") or [],
        artwork_bytes=artwork_bytes,
    )


def _record_workflow_event(store, workflow_id: str, event_type: str, payload: dict | None = None) -> None:
    try:
        store.insert(
            "makaren_workflow_events",
            {"workflow_id": workflow_id, "event_type": event_type, "payload": payload or {}},
        )
    except Exception:
        logger.exception("[workflow] event recording failed workflow_id=%s event=%s", workflow_id, event_type)


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
    """Legacy direct-delivery job, kept as a safe fallback until Supabase is configured."""
    logger.info("[generate_job] legacy start email=%s product=%s", email_to, product)
    try:
        result = _generate_analysis(
            last_name, first_name, maiden_last_name, birth_date, consultation, product, others
        )
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
            sent_ok, sent_err = _send_profile_email(
                profile=result["profile"],
                relationship=result.get("relationship") or "",
                name=result["name"],
                email_to=email_to,
                product=product,
                birth_date=birth_date,
                consultation=consultation,
                numbers=result["numbers"],
                nine_year_cycle=result["nine_year_cycle"],
                referral_code_issued=referral_code_issued,
                referred_by=referred_by,
                others_list=result["others"],
            )
            if sent_ok:
                logger.info(
                    "[generate_job] メール送信成功 email=%s product=%s referral=%s",
                    email_to,
                    product,
                    referral_code_issued or "",
                )
            else:
                logger.error(
                    "[generate_job] メール送信失敗 email=%s product=%s error=%s",
                    email_to,
                    product,
                    sent_err or "",
                )
    except Exception:
        logger.exception(
            "[generate_job] 予期しないエラー last_name=%s first_name=%s email=%s product=%s",
            last_name,
            first_name,
            email_to,
            product,
        )


def _run_workflow_generate_job(
    last_name: str,
    first_name: str,
    maiden_last_name: str,
    birth_date: str,
    consultation: str,
    email_to: str,
    product: str,
    referred_by_code: str,
    others: list,
    public_base_url: str,
) -> None:
    """Generate version 1, store it privately, then email the review link."""
    store = get_workflow_store()
    review_token = generate_review_token()
    referral_code_issued = _generate_referral_code()
    referred_by = (
        referred_by_code
        if referred_by_code and len(referred_by_code) == 7 and referred_by_code.isdigit()
        else None
    )
    workflow = store.insert(
        "makaren_workflows",
        {
            "customer_name": f"{last_name} {first_name}",
            "email": email_to,
            "birth_date": birth_date,
            "product": product,
            "consultation": consultation or None,
            "review_token_hash": hash_review_token(review_token),
            "referral_code_used": referred_by,
            "referral_code_issued": referral_code_issued,
            "status": "generating",
        },
    )
    workflow_id = workflow["id"]
    _record_workflow_event(store, workflow_id, "generation_started")
    try:
        result = _generate_analysis(
            last_name, first_name, maiden_last_name, birth_date, consultation, product, others
        )
        numbers_full = {
            "numbers": result["numbers"],
            "numbers_maiden": result.get("numbers_maiden"),
            "nine_year_cycle": result["nine_year_cycle"],
        }
        reading = store.insert(
            "makaren_readings",
            {
                "name": result["name"],
                "birth_date": birth_date,
                "email": email_to,
                "product": product,
                "numbers_full": numbers_full,
                "referral_code_used": referred_by,
                "others": result["others"],
            },
        )
        store.update(
            "makaren_workflows",
            {
                "reading_id": reading["id"],
                "numbers_full": numbers_full,
                "others": result["others"],
            },
            filters={"id": f"eq.{workflow_id}"},
        )
        art_bytes, art_prompt, art_mime, image_model = generate_artwork(
            result["profile"], result["numbers"]
        )
        pdf_bytes = _result_pdf_bytes(result, art_bytes)
        art_path = f"workflows/{workflow_id}/v1/art.png"
        pdf_path = f"workflows/{workflow_id}/v1/report.pdf"
        store.upload(art_path, art_bytes, art_mime)
        store.upload(pdf_path, pdf_bytes, "application/pdf")
        version = store.insert(
            "makaren_workflow_versions",
            {
                "workflow_id": workflow_id,
                "version_no": 1,
                "profile_text": result["profile"],
                "relationship_text": result.get("relationship"),
                "art_prompt": art_prompt,
                "art_storage_path": art_path,
                "art_mime_type": art_mime,
                "pdf_storage_path": pdf_path,
                "text_model": os.getenv("OPENAI_TEXT_MODEL", "gpt-4o"),
                "image_model": image_model,
                "change_summary": "初回生成",
                "status": "ready",
            },
        )
        store.update(
            "makaren_workflows",
            {"status": "awaiting_review", "current_version": 1, "last_error": None},
            filters={"id": f"eq.{workflow_id}", "status": "eq.generating"},
        )
        _record_workflow_event(
            store, workflow_id, "version_ready", {"version_no": 1, "version_id": version["id"]}
        )
        review_url = f"{public_base_url.rstrip('/')}/review/{review_token}"
        sent_ok, sent_error = _send_review_email(email_to, result["name"], review_url)
        if not sent_ok:
            store.update(
                "makaren_workflows",
                {"last_error": sent_error},
                filters={"id": f"eq.{workflow_id}"},
            )
            _record_workflow_event(store, workflow_id, "review_email_failed")
        else:
            _record_workflow_event(store, workflow_id, "review_email_sent")
    except Exception as exc:
        logger.exception("[workflow] initial generation failed workflow_id=%s", workflow_id)
        store.update(
            "makaren_workflows",
            {"status": "failed", "last_error": str(exc)[:1000]},
            filters={"id": f"eq.{workflow_id}"},
        )
        _record_workflow_event(store, workflow_id, "generation_failed")


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
    if not email_to:
        email_to = "unfashion8@gmail.com"
    product = data.get("product", "profile_only")
    referred_by_code = (data.get("referral_code") or "").strip()
    others = data.get("others", [])

    # サーバー側でも最低限のバリデーションだけ行い、問題なければ非同期ジョブを起動する
    if not last_name or not first_name:
        return jsonify({"ok": False, "error": "姓・名（ローマ字）は必須です"}), 400
    if not birth_date:
        return jsonify({"ok": False, "error": "生年月日は必須です"}), 400
    if not _is_valid_email(email_to):
        return jsonify({"ok": False, "error": "メールアドレスの形式が正しくありません"}), 400
    if product not in {"profile_only", "relationship_3", "relationship_5", "relationship_10"}:
        return jsonify({"ok": False, "error": "プランが正しくありません"}), 400

    y, m, d = _parse_birth_date(birth_date)
    if y is None or m is None or d is None:
        return jsonify(
            {
                "ok": False,
                "error": "生年月日は YYYY/MM/DD 形式で、存在する日付（1900〜2100年）を入力してください",
            }
        ), 400

    # SMTP設定の事前チェック（本番環境でメールが送れない問題を早期に検知する）
    _, smtp_error = _resolve_smtp_settings()
    if smtp_error:
        return jsonify({"ok": False, "error": smtp_error}), 500

    has_any_workflow_setting = bool(
        os.getenv("SUPABASE_URL", "").strip()
        or os.getenv("SUPABASE_SERVICE_ROLE_KEY", "").strip()
    )
    if has_any_workflow_setting and not workflow_enabled():
        return jsonify({"ok": False, "error": workflow_config_error()}), 500

    # Supabase設定済みならレビュー・版管理フロー、未設定なら従来の直接納品を使う。
    target = _run_generate_job
    job_args = (
        last_name,
        first_name,
        maiden_last_name,
        birth_date,
        consultation,
        email_to,
        product,
        referred_by_code,
        others,
    )
    if workflow_enabled():
        public_base_url = (
            os.getenv("PUBLIC_BASE_URL", "").strip().rstrip("/")
            or request.url_root.rstrip("/")
        )
        target = _run_workflow_generate_job
        job_args = job_args + (public_base_url,)

    Thread(
        target=target,
        args=job_args,
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

    full_content = pg.hide_internal_calculation_values(profile)
    if relationship:
        full_content += "\n\n[[PAGEBREAK]]\n\n" + pg.hide_internal_calculation_values(relationship)

    title = f"KOKOROE パーソナル鑑定書 — {name}"
    try:
        pdf_bytes = pdfgen.build_pdf(full_content, title=title)
    except Exception as e:
        return jsonify({"ok": False, "error": f"PDFの作成に失敗しました: {e}"}), 500

    return send_file(
        io.BytesIO(pdf_bytes),
        mimetype="application/pdf",
        as_attachment=True,
        download_name=f"kokoroe_reading_{name}.pdf",
    )


@app.route("/api/send-email", methods=["POST"])
def send_email():
    data = request.get_json() or {}
    profile = _normalize_text(data.get("profile"))
    relationship = _normalize_text(data.get("relationship"))
    name = _normalize_text(data.get("name") or "プロファイル")
    email_to = _normalize_email(data.get("email"))
    if not email_to:
        email_to = "unfashion8@gmail.com"
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


def _parse_iso_datetime(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None


def _load_review_state(token: str):
    store = get_workflow_store()
    workflow = store.select_one(
        "makaren_workflows",
        filters={"review_token_hash": f"eq.{hash_review_token(token)}"},
    )
    if not workflow:
        return store, None, None, None
    version = None
    if int(workflow.get("current_version") or 0) > 0:
        version = store.select_one(
            "makaren_workflow_versions",
            filters={
                "workflow_id": f"eq.{workflow['id']}",
                "version_no": f"eq.{workflow['current_version']}",
            },
        )
    delivery = store.select_one(
        "makaren_deliveries",
        filters={"workflow_id": f"eq.{workflow['id']}"},
    )
    return store, workflow, version, delivery


def _workflow_expired(workflow: dict) -> bool:
    expires_at = _parse_iso_datetime(workflow.get("expires_at"))
    return bool(expires_at and expires_at <= datetime.now(timezone.utc))


def _revision_context(workflow: dict) -> tuple[dict, list, str]:
    numbers_full = workflow.get("numbers_full") or {}
    numbers = numbers_full.get("numbers") if isinstance(numbers_full, dict) else {}
    nine_year_cycle = (
        numbers_full.get("nine_year_cycle") if isinstance(numbers_full, dict) else []
    )
    context = json.dumps(
        {
            "name": workflow.get("customer_name"),
            "birth_date": workflow.get("birth_date"),
            "consultation": workflow.get("consultation"),
            "numbers": numbers or {},
            "others": workflow.get("others") or [],
        },
        ensure_ascii=False,
    )
    return numbers or {}, nine_year_cycle or [], context


def _run_revision_job(
    workflow_id: str,
    feedback_id: str,
    review_url: str,
) -> None:
    store = get_workflow_store()
    try:
        workflow = store.select_one(
            "makaren_workflows", filters={"id": f"eq.{workflow_id}"}
        )
        feedback = store.select_one(
            "makaren_feedback", filters={"id": f"eq.{feedback_id}"}
        )
        if not workflow or not feedback:
            raise RuntimeError("ワークフローまたは修正依頼が見つかりません")
        base_no = int(feedback["base_version_no"])
        if int(workflow.get("current_version") or 0) != base_no:
            store.update(
                "makaren_feedback",
                {"status": "cancelled", "error_message": "新しい版が既に存在します"},
                filters={"id": f"eq.{feedback_id}"},
            )
            return
        locked = store.update(
            "makaren_workflows",
            {"status": "regenerating", "last_error": None},
            filters={
                "id": f"eq.{workflow_id}",
                "status": "eq.revision_requested",
                "current_version": f"eq.{base_no}",
            },
        )
        if not locked:
            raise RuntimeError("修正処理を開始できませんでした")
        store.update(
            "makaren_feedback",
            {"status": "processing"},
            filters={"id": f"eq.{feedback_id}", "status": "eq.queued"},
        )
        base_version = store.select_one(
            "makaren_workflow_versions",
            filters={
                "workflow_id": f"eq.{workflow_id}",
                "version_no": f"eq.{base_no}",
            },
        )
        if not base_version:
            raise RuntimeError("修正元の版が見つかりません")

        target = feedback["target"]
        instruction = feedback["instruction"]
        numbers, nine_year_cycle, context = _revision_context(workflow)
        profile_text = base_version["profile_text"]
        relationship_text = base_version.get("relationship_text")
        if target in {"profile", "all"}:
            profile_text = _strip_markdown(
                pg.revise_generated_text(
                    profile_text,
                    instruction,
                    target_label="本人用プロファイル",
                    context=context,
                )
            )
        if target in {"relationship", "all"} and relationship_text:
            relationship_text = _strip_markdown(
                pg.revise_generated_text(
                    relationship_text,
                    instruction,
                    target_label="関係性分析",
                    context=context,
                )
            )

        regenerate_art = target in {"profile", "art", "all"}
        if regenerate_art:
            art_bytes, art_prompt, art_mime, image_model = generate_artwork(
                profile_text,
                numbers,
                previous_prompt=base_version.get("art_prompt"),
                revision_instruction=instruction,
            )
        else:
            art_prompt = base_version.get("art_prompt")
            art_mime = base_version.get("art_mime_type") or "image/png"
            image_model = base_version.get("image_model")
            art_bytes = store.download(base_version["art_storage_path"])

        new_no = base_no + 1
        result = {
            "profile": profile_text,
            "relationship": relationship_text,
            "name": workflow["customer_name"],
            "numbers": numbers,
            "nine_year_cycle": nine_year_cycle,
        }
        pdf_bytes = _result_pdf_bytes(result, art_bytes)
        art_path = base_version.get("art_storage_path")
        if regenerate_art:
            art_path = f"workflows/{workflow_id}/v{new_no}/art.png"
            store.upload(art_path, art_bytes, art_mime)
        pdf_path = f"workflows/{workflow_id}/v{new_no}/report.pdf"
        store.upload(pdf_path, pdf_bytes, "application/pdf")
        version = store.insert(
            "makaren_workflow_versions",
            {
                "workflow_id": workflow_id,
                "version_no": new_no,
                "parent_version_id": base_version["id"],
                "source_feedback_id": feedback_id,
                "profile_text": profile_text,
                "relationship_text": relationship_text,
                "art_prompt": art_prompt,
                "art_storage_path": art_path,
                "art_mime_type": art_mime,
                "pdf_storage_path": pdf_path,
                "text_model": os.getenv("OPENAI_TEXT_MODEL", "gpt-4o"),
                "image_model": image_model,
                "change_summary": instruction[:1000],
                "status": "ready",
            },
        )
        advanced = store.update(
            "makaren_workflows",
            {
                "status": "awaiting_review",
                "current_version": new_no,
                "revision_count": int(workflow.get("revision_count") or 0) + 1,
                "last_error": None,
            },
            filters={
                "id": f"eq.{workflow_id}",
                "status": "eq.regenerating",
                "current_version": f"eq.{base_no}",
            },
        )
        if not advanced:
            raise RuntimeError("新しい版を現在版に切り替えられませんでした")
        store.update(
            "makaren_workflow_versions",
            {"status": "superseded"},
            filters={"id": f"eq.{base_version['id']}", "status": "eq.ready"},
        )
        store.update(
            "makaren_feedback",
            {
                "status": "completed",
                "processed_at": datetime.now(timezone.utc).isoformat(),
                "error_message": None,
            },
            filters={"id": f"eq.{feedback_id}"},
        )
        _record_workflow_event(
            store,
            workflow_id,
            "revision_ready",
            {"version_no": new_no, "version_id": version["id"], "target": target},
        )
        sent, error = _send_review_email(
            workflow["email"], workflow["customer_name"], review_url, revised=True
        )
        if not sent:
            store.update(
                "makaren_workflows",
                {"last_error": error},
                filters={"id": f"eq.{workflow_id}"},
            )
    except Exception as exc:
        logger.exception("[workflow] revision failed workflow_id=%s", workflow_id)
        try:
            store.update(
                "makaren_feedback",
                {
                    "status": "failed",
                    "error_message": str(exc)[:1000],
                    "processed_at": datetime.now(timezone.utc).isoformat(),
                },
                filters={"id": f"eq.{feedback_id}"},
            )
            store.update(
                "makaren_workflows",
                {"status": "awaiting_review", "last_error": str(exc)[:1000]},
                filters={"id": f"eq.{workflow_id}", "status": "eq.regenerating"},
            )
            _record_workflow_event(store, workflow_id, "revision_failed")
        except Exception:
            logger.exception("[workflow] failed to persist revision error workflow_id=%s", workflow_id)


def _deliver_approved_workflow(workflow_id: str) -> None:
    store = get_workflow_store()
    try:
        workflow = store.select_one(
            "makaren_workflows", filters={"id": f"eq.{workflow_id}"}
        )
        if not workflow or workflow.get("status") != "approved":
            return
        claimed = store.update(
            "makaren_workflows",
            {"status": "finalizing", "last_error": None},
            filters={"id": f"eq.{workflow_id}", "status": "eq.approved"},
        )
        if not claimed:
            return
        delivery = store.select_one(
            "makaren_deliveries", filters={"workflow_id": f"eq.{workflow_id}"}
        )
        if not delivery:
            raise RuntimeError("納品レコードが見つかりません")
        if delivery.get("fulfillment_type") == "digital" and delivery.get("status") == "delivered":
            store.update(
                "makaren_workflows",
                {
                    "status": "delivered",
                    "delivered_at": datetime.now(timezone.utc).isoformat(),
                    "last_error": None,
                },
                filters={"id": f"eq.{workflow_id}", "status": "eq.finalizing"},
            )
            return
        version = store.select_one(
            "makaren_workflow_versions",
            filters={
                "workflow_id": f"eq.{workflow_id}",
                "version_no": f"eq.{workflow['current_version']}",
            },
        )
        if not version or not version.get("pdf_storage_path"):
            raise RuntimeError("承認版PDFが見つかりません")
        artwork_bytes = None
        if version.get("art_storage_path"):
            artwork_bytes = store.download(version["art_storage_path"])
        print_spec = dict(delivery.get("print_spec") or {})
        print_master_path = f"workflows/{workflow_id}/v{workflow['current_version']}/art-print.png"
        if artwork_bytes and not print_spec.get("master_path"):
            print_master_ready = False
            try:
                store.download(print_master_path)
                print_master_ready = True
            except WorkflowStoreError:
                try:
                    print_bytes, print_mime, _print_model = generate_print_master(artwork_bytes)
                    store.upload(print_master_path, print_bytes, print_mime)
                    print_master_ready = True
                except Exception as exc:
                    logger.exception(
                        "[workflow] print master generation failed workflow_id=%s",
                        workflow_id,
                    )
                    _record_workflow_event(
                        store,
                        workflow_id,
                        "print_master_failed",
                        {"error": str(exc)[:500]},
                    )
            if print_master_ready:
                print_spec["master_path"] = print_master_path
                delivery["print_spec"] = print_spec
                store.update(
                    "makaren_deliveries",
                    {"print_spec": print_spec},
                    filters={"id": f"eq.{delivery['id']}"},
                )
                _record_workflow_event(store, workflow_id, "print_master_ready")
        numbers_full = workflow.get("numbers_full") or {}
        numbers = numbers_full.get("numbers") if isinstance(numbers_full, dict) else {}
        cycle = numbers_full.get("nine_year_cycle") if isinstance(numbers_full, dict) else []
        referred_by = workflow.get("referral_code_used")
        pdf_bytes = _result_pdf_bytes(
            {
                "profile": version["profile_text"],
                "relationship": version.get("relationship_text"),
                "name": workflow["customer_name"],
                "numbers": numbers or {},
                "nine_year_cycle": cycle or [],
            },
            artwork_bytes,
        )
        sent, error = _send_profile_email(
            profile=version["profile_text"],
            relationship=version.get("relationship_text") or "",
            name=workflow["customer_name"],
            email_to=workflow["email"],
            product=workflow["product"],
            birth_date=workflow.get("birth_date") or "",
            consultation=workflow.get("consultation") or "",
            numbers=numbers or {},
            nine_year_cycle=cycle or [],
            referral_code_issued=workflow.get("referral_code_issued"),
            referred_by=referred_by,
            others_list=workflow.get("others") or [],
            pdf_bytes_override=pdf_bytes,
        )
        if not sent:
            raise RuntimeError(error or "最終メールを送信できませんでした")
        now = datetime.now(timezone.utc).isoformat()
        delivered = store.update(
            "makaren_workflows",
            {"status": "delivered", "delivered_at": now, "last_error": None},
            filters={"id": f"eq.{workflow_id}", "status": "eq.finalizing"},
        )
        if not delivered:
            raise RuntimeError("納品状態を確定できませんでした")
        if delivery and delivery.get("fulfillment_type") == "digital":
            store.update(
                "makaren_deliveries",
                {"status": "delivered", "last_error": None},
                filters={"id": f"eq.{delivery['id']}"},
            )
        if referred_by:
            try:
                referrer_email = _referrer_email_by_code(referred_by)
                if (
                    referrer_email
                    and referrer_email != workflow["email"]
                    and _is_ambassador(referrer_email)
                ):
                    _append_ambassador_earning(
                        referrer_email, workflow["email"], _order_amount(workflow["product"])
                    )
            except Exception:
                logger.exception("[workflow] referral bookkeeping failed workflow_id=%s", workflow_id)
        _record_workflow_event(store, workflow_id, "digital_delivery_sent")
    except Exception as exc:
        logger.exception("[workflow] delivery failed workflow_id=%s", workflow_id)
        store.update(
            "makaren_workflows",
            {"status": "approved", "last_error": str(exc)[:1000]},
            filters={"id": f"eq.{workflow_id}", "status": "eq.finalizing"},
        )
        delivery = store.select_one(
            "makaren_deliveries", filters={"workflow_id": f"eq.{workflow_id}"}
        )
        if delivery and delivery.get("fulfillment_type") == "digital" and delivery.get("status") != "delivered":
            store.update(
                "makaren_deliveries",
                {"status": "failed", "last_error": str(exc)[:1000]},
                filters={"id": f"eq.{delivery['id']}"},
            )
        _record_workflow_event(store, workflow_id, "digital_delivery_failed")


@app.route("/review/<token>", methods=["GET"])
def review_workflow(token: str):
    if not workflow_enabled():
        return "Review workflow is not configured", 503
    try:
        store, workflow, version, delivery = _load_review_state(token)
        if not workflow:
            return "確認ページが見つかりません", 404
        if _workflow_expired(workflow):
            return "確認ページの有効期限が切れています", 410
        art_url = None
        print_art_url = None
        pdf_url = None
        if version and version.get("art_storage_path"):
            art_url = store.signed_url(version["art_storage_path"], 600)
        if version:
            version = dict(version)
            version["profile_text"] = pg.hide_internal_calculation_values(version.get("profile_text") or "")
            version["relationship_text"] = pg.hide_internal_calculation_values(version.get("relationship_text") or "")
            pdf_url = f"/review/{token}/pdf"
        print_spec = delivery.get("print_spec") if delivery else None
        if workflow.get("status") == "delivered" and isinstance(print_spec, dict):
            print_path = print_spec.get("master_path")
            if print_path:
                print_art_url = store.signed_url(print_path, 600)
        response = make_response(
            render_template(
                "review.html",
                token=token,
                workflow=workflow,
                version=version,
                delivery=delivery,
                art_url=art_url,
                print_art_url=print_art_url,
                pdf_url=pdf_url,
            )
        )
        response.headers["Cache-Control"] = "no-store, max-age=0"
        response.headers["Pragma"] = "no-cache"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; img-src 'self' https://*.supabase.co data:; "
            "style-src 'self' 'unsafe-inline'; script-src 'self' 'unsafe-inline'; "
            "form-action 'self'; base-uri 'none'; frame-ancestors 'none'"
        )
        return response
    except WorkflowStoreError:
        logger.exception("[workflow] review page failed")
        return "確認ページを読み込めませんでした", 503


@app.route("/review/<token>/pdf", methods=["GET"])
def review_workflow_pdf(token: str):
    """既存版も含め、内部値を除去したPDFを都度生成して返す。"""
    if not workflow_enabled():
        return "Review workflow is not configured", 503
    try:
        store, workflow, version, _delivery = _load_review_state(token)
        if not workflow or not version:
            return "確認ページが見つかりません", 404
        if _workflow_expired(workflow):
            return "確認ページの有効期限が切れています", 410
        artwork_bytes = None
        if version.get("art_storage_path"):
            artwork_bytes = store.download(version["art_storage_path"])
        pdf_bytes = _result_pdf_bytes(
            {
                "profile": version.get("profile_text") or "",
                "relationship": version.get("relationship_text"),
                "name": workflow.get("customer_name") or "",
                "numbers": {},
                "nine_year_cycle": [],
            },
            artwork_bytes,
        )
        response = send_file(
            io.BytesIO(pdf_bytes),
            mimetype="application/pdf",
            as_attachment=False,
            download_name="kokoroe_reading.pdf",
        )
        response.headers["Cache-Control"] = "no-store, max-age=0"
        response.headers["Referrer-Policy"] = "no-referrer"
        return response
    except WorkflowStoreError:
        logger.exception("[workflow] safe PDF preview failed")
        return "PDFを読み込めませんでした", 503


@app.route("/api/review/<token>/feedback", methods=["POST"])
def submit_workflow_feedback(token: str):
    if not workflow_enabled():
        return jsonify({"ok": False, "error": "レビュー機能が未設定です"}), 503
    data = request.get_json() or {}
    target = _normalize_text(data.get("target") or "all")
    instruction = _normalize_text(data.get("instruction"))
    try:
        base_version = int(data.get("base_version"))
    except (TypeError, ValueError):
        return jsonify({"ok": False, "error": "版番号が正しくありません"}), 400
    if target not in {"profile", "relationship", "art", "all"}:
        return jsonify({"ok": False, "error": "修正対象が正しくありません"}), 400
    if not instruction or len(instruction) > 4000:
        return jsonify({"ok": False, "error": "修正内容は1〜4000文字で入力してください"}), 400
    try:
        store, workflow, version, _ = _load_review_state(token)
        if not workflow or not version:
            return jsonify({"ok": False, "error": "確認対象が見つかりません"}), 404
        if _workflow_expired(workflow):
            return jsonify({"ok": False, "error": "確認期限が切れています"}), 410
        if workflow.get("status") != "awaiting_review":
            return jsonify({"ok": False, "error": "現在は修正を受け付けられません"}), 409
        if int(workflow.get("revision_count") or 0) >= int(workflow.get("max_revisions") or 0):
            return jsonify({"ok": False, "error": "修正回数の上限に達しました"}), 409
        if base_version != int(workflow.get("current_version") or 0):
            return jsonify({"ok": False, "error": "新しい版があるため、ページを再読み込みしてください"}), 409
        if target == "relationship" and not version.get("relationship_text"):
            return jsonify({"ok": False, "error": "関係性分析がないプランです"}), 400
        reserved = store.update(
            "makaren_workflows",
            {"status": "revision_requested", "last_error": None},
            filters={
                "id": f"eq.{workflow['id']}",
                "status": "eq.awaiting_review",
                "current_version": f"eq.{base_version}",
            },
        )
        if not reserved:
            return jsonify({"ok": False, "error": "別の処理が進行中です"}), 409
        try:
            feedback = store.insert(
                "makaren_feedback",
                {
                    "workflow_id": workflow["id"],
                    "base_version_no": base_version,
                    "target": target,
                    "instruction": instruction,
                    "status": "queued",
                },
            )
        except Exception:
            store.update(
                "makaren_workflows",
                {"status": "awaiting_review"},
                filters={"id": f"eq.{workflow['id']}", "status": "eq.revision_requested"},
            )
            raise
        public_base_url = (
            os.getenv("PUBLIC_BASE_URL", "").strip().rstrip("/")
            or request.url_root.rstrip("/")
        )
        review_url = f"{public_base_url}/review/{token}"
        Thread(
            target=_run_revision_job,
            args=(workflow["id"], feedback["id"], review_url),
            daemon=True,
        ).start()
        _record_workflow_event(
            store, workflow["id"], "revision_requested", {"target": target, "base_version": base_version}
        )
        return jsonify({"ok": True, "message": "修正を受け付けました"}), 202
    except WorkflowStoreError:
        logger.exception("[workflow] feedback submission failed")
        return jsonify({"ok": False, "error": "修正依頼を保存できませんでした"}), 503


@app.route("/api/review/<token>/approve", methods=["POST"])
def approve_workflow(token: str):
    if not workflow_enabled():
        return jsonify({"ok": False, "error": "レビュー機能が未設定です"}), 503
    data = request.get_json() or {}
    try:
        version_no = int(data.get("version"))
    except (TypeError, ValueError):
        return jsonify({"ok": False, "error": "版番号が正しくありません"}), 400
    try:
        store, workflow, version, delivery = _load_review_state(token)
        if not workflow or not version:
            return jsonify({"ok": False, "error": "確認対象が見つかりません"}), 404
        if _workflow_expired(workflow):
            return jsonify({"ok": False, "error": "確認期限が切れています"}), 410
        if workflow.get("status") == "delivered":
            return jsonify({"ok": True, "message": "すでに承認・納品済みです"})
        if workflow.get("status") == "finalizing":
            return jsonify({"ok": True, "message": "承認済みです。最終PDFを送信しています"})
        if workflow.get("status") == "approved":
            if not delivery:
                delivery = store.insert(
                    "makaren_deliveries",
                    {
                        "workflow_id": workflow["id"],
                        "version_id": version["id"],
                        "fulfillment_type": "digital",
                        "status": "data_ready",
                    },
                )
            elif delivery.get("fulfillment_type") == "digital" and delivery.get("status") == "failed":
                store.update(
                    "makaren_deliveries",
                    {"status": "data_ready", "last_error": None},
                    filters={"id": f"eq.{delivery['id']}"},
                )
            Thread(target=_deliver_approved_workflow, args=(workflow["id"],), daemon=True).start()
            return jsonify({"ok": True, "message": "承認済みです。最終PDFの送信を再開しました"})
        if workflow.get("status") != "awaiting_review" or version_no != int(workflow["current_version"]):
            return jsonify({"ok": False, "error": "現在の版を承認できません"}), 409
        now = datetime.now(timezone.utc).isoformat()
        approved = store.update(
            "makaren_workflows",
            {"status": "approved", "approved_at": now, "last_error": None},
            filters={
                "id": f"eq.{workflow['id']}",
                "status": "eq.awaiting_review",
                "current_version": f"eq.{version_no}",
            },
        )
        if not approved:
            return jsonify({"ok": False, "error": "別の処理が進行中です"}), 409
        store.update(
            "makaren_workflow_versions",
            {"status": "approved"},
            filters={"id": f"eq.{version['id']}"},
        )
        try:
            if delivery:
                store.update(
                    "makaren_deliveries",
                    {"version_id": version["id"], "status": "data_ready", "last_error": None},
                    filters={"id": f"eq.{delivery['id']}"},
                )
            else:
                store.insert(
                    "makaren_deliveries",
                    {
                        "workflow_id": workflow["id"],
                        "version_id": version["id"],
                        "fulfillment_type": "digital",
                        "status": "data_ready",
                    },
                )
        except Exception:
            store.update(
                "makaren_workflows",
                {"status": "awaiting_review", "approved_at": None},
                filters={"id": f"eq.{workflow['id']}", "status": "eq.approved"},
            )
            store.update(
                "makaren_workflow_versions",
                {"status": "ready"},
                filters={"id": f"eq.{version['id']}", "status": "eq.approved"},
            )
            raise
        _record_workflow_event(store, workflow["id"], "approved", {"version_no": version_no})
        Thread(target=_deliver_approved_workflow, args=(workflow["id"],), daemon=True).start()
        return jsonify({"ok": True, "message": "承認しました。最終PDFをメールでお送りします"})
    except WorkflowStoreError:
        logger.exception("[workflow] approval failed")
        return jsonify({"ok": False, "error": "承認を保存できませんでした"}), 503


@app.route("/api/review/<token>/framing", methods=["POST"])
def request_framing(token: str):
    if not workflow_enabled():
        return jsonify({"ok": False, "error": "レビュー機能が未設定です"}), 503
    data = request.get_json() or {}
    try:
        store, workflow, version, delivery = _load_review_state(token)
        if not workflow or not version:
            return jsonify({"ok": False, "error": "確認対象が見つかりません"}), 404
        if workflow.get("status") != "delivered":
            return jsonify({"ok": False, "error": "最終PDFの納品後にお申し込みください"}), 409
        existing_print_spec = delivery.get("print_spec") if delivery else None
        print_spec = {
            "size": _normalize_text(data.get("size"))[:100],
            "paper": _normalize_text(data.get("paper"))[:100],
            "notes": _normalize_text(data.get("print_notes"))[:1000],
        }
        if isinstance(existing_print_spec, dict) and existing_print_spec.get("master_path"):
            print_spec["master_path"] = existing_print_spec["master_path"]
        frame_spec = {
            "style": _normalize_text(data.get("frame_style"))[:100],
            "color": _normalize_text(data.get("frame_color"))[:100],
            "notes": _normalize_text(data.get("frame_notes"))[:1000],
        }
        shipping_address = {
            "name": _normalize_text(data.get("shipping_name"))[:200],
            "postal_code": _normalize_text(data.get("postal_code"))[:20],
            "address": _normalize_text(data.get("address"))[:500],
            "phone": _normalize_text(data.get("phone"))[:40],
        }
        if not print_spec["size"] or not frame_spec["style"]:
            return jsonify({"ok": False, "error": "希望サイズと額装スタイルを入力してください"}), 400
        values = {
            "version_id": version["id"],
            "fulfillment_type": "framed_print",
            "print_spec": print_spec,
            "frame_spec": frame_spec,
            "shipping_address": shipping_address,
            "status": "pending",
            "last_error": None,
        }
        if delivery:
            store.update(
                "makaren_deliveries", values, filters={"id": f"eq.{delivery['id']}"}
            )
        else:
            store.insert(
                "makaren_deliveries", {"workflow_id": workflow["id"], **values}
            )
        _record_workflow_event(store, workflow["id"], "framing_requested")
        return jsonify({"ok": True, "message": "額装のご希望を受け付けました"})
    except WorkflowStoreError:
        logger.exception("[workflow] framing request failed")
        return jsonify({"ok": False, "error": "額装申込を保存できませんでした"}), 503


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


def _product_label(product: str) -> str:
    """プラン名を日本語で返す。"""
    labels = {
        "profile_only": "プロファイルのみ",
        "relationship_3": "3名相性",
        "relationship_5": "5名相性",
        "relationship_10": "10名相性",
    }
    return labels.get(product, product or "—")


@app.route("/admin")
def admin():
    """管理画面（ADMIN_SECRET 必須）。アンバサダー一覧・鑑定申込一覧・累計紹介数・累計売上。"""
    if not _admin_key_ok():
        return "Unauthorized", 401
    ambassadors_list, total_referrals, total_sales = _ambassador_stats()
    submissions = _read_submissions(limit=500)
    for row in submissions:
        row["product_label"] = _product_label(row.get("product") or "")
        sent = row.get("sent_at") or ""
        if sent:
            try:
                dt = datetime.fromisoformat(sent.replace("Z", "+00:00"))
                row["sent_at_ja"] = dt.strftime("%Y年%m月%d日 %H:%M")
            except Exception:
                row["sent_at_ja"] = sent
        else:
            row["sent_at_ja"] = "—"
    workflows = []
    workflow_error = None
    if workflow_enabled():
        try:
            workflows = get_workflow_store().select(
                "makaren_workflows", order="created_at.desc", limit=100
            )
            status_labels = {
                "generating": "初回生成中",
                "awaiting_review": "確認待ち",
                "revision_requested": "修正受付",
                "regenerating": "再生成中",
                "approved": "承認・送信中",
                "finalizing": "最終PDF送信中",
                "delivered": "納品済み",
                "failed": "失敗",
                "cancelled": "取消",
            }
            for workflow in workflows:
                workflow["status_label"] = status_labels.get(
                    workflow.get("status"), workflow.get("status") or "—"
                )
                created = workflow.get("created_at") or ""
                parsed = _parse_iso_datetime(created)
                workflow["created_at_ja"] = (
                    parsed.strftime("%Y年%m月%d日 %H:%M") if parsed else created
                )
        except Exception as exc:
            logger.exception("[admin] workflow list failed")
            workflow_error = str(exc)
    return render_template(
        "admin.html",
        ambassadors=ambassadors_list,
        total_referrals=total_referrals,
        total_sales=total_sales,
        submissions=submissions,
        workflows=workflows,
        workflow_error=workflow_error,
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
