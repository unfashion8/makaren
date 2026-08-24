# -*- coding: utf-8 -*-
"""OpenAI APIを用いたKOKOROEパーソナル鑑定の生成。"""
import os
import re
import time
from openai import OpenAI, APIConnectionError, APITimeoutError, RateLimitError, APIError
from dotenv import load_dotenv
from prompts import build_system_prompt, build_profile_user_prompt, build_relationship_user_prompt

load_dotenv()


_INTERNAL_LABEL_RENAMES = {
    "構成数の概要": "パーソナル構造の概要",
    "構成数": "内面的な構造",
    "誕生数Ⅰ": "生来の行動基盤",
    "誕生数Ⅱ": "社会との接点",
    "誕生数": "生来の行動基盤",
    "影数": "反応が強まりやすい場面",
    "社会数": "社会で表れやすい傾向",
    "魂数": "内面の動機",
    "外見数": "周囲から見えやすい印象",
    "使命数": "担いやすい役割",
    "家系数": "受け継いだ土台",
    "自我数": "自己決定の傾向",
    "演技数": "場面への適応傾向",
    "隠数": "見落としやすい反応",
    "核数": "価値判断の軸",
    "欠番": "補うと安定する視点",
}

_ART_SCORE_LABELS = (
    "抽象度", "コントラスト", "密度", "余白", "明度", "有機性", "ソリッド感", "躍動感",
)


def hide_internal_calculation_values(text: str) -> str:
    """モデルが誤って出した内部値・採点表を、利用者向け本文から除去する。"""
    cleaned = str(text or "")
    if not cleaned:
        return ""

    # スクリーンショットのような作品採点行は行ごと削除する。
    score_line = re.compile(
        rf"(?:{'|'.join(map(re.escape, _ART_SCORE_LABELS))}).*(?:\d{{1,3}}\s*/\s*100|\d{{1,3}}\s*%)"
    )
    lines = [line for line in cleaned.splitlines() if not score_line.search(line)]
    cleaned = "\n".join(lines)

    cleaned = re.sub(r"パーソナルイヤー\s*(?:は|[:：=])?\s*[1-9]", "その年の流れ", cleaned)
    for internal_label, public_label in _INTERNAL_LABEL_RENAMES.items():
        # ラベルに直結する値を先に捨て、ラベル自体も自然な公開表現へ変える。
        cleaned = re.sub(
            rf"{re.escape(internal_label)}\s*(?:[（(][^\n）)]{{0,24}}[）)])?\s*(?:[:：=]|は)?\s*(?:11|22|[0-9]+)(?:\s*/\s*[0-9]+)?",
            public_label,
            cleaned,
        )
        cleaned = cleaned.replace(internal_label, public_label)

    # 点数・割合の形式は、本文で数値評価を想起させないよう値を残さない。
    cleaned = re.sub(r"(?<!\d)\d{1,3}\s*/\s*100(?!\d)", "", cleaned)
    cleaned = re.sub(r"(?<!\d)\d{1,3}\s*%(?!\d)", "", cleaned)
    cleaned = re.sub(r"[ \t]{2,}", " ", cleaned)
    cleaned = re.sub(r"\n{3,}", "\n\n", cleaned)
    return cleaned.strip()


def get_client():
    key = os.getenv("OPENAI_API_KEY")
    if not key:
        raise ValueError("OPENAI_API_KEY が設定されていません。.env を確認してください。")
    return OpenAI(api_key=key)


def _create_chat_completion(client: OpenAI, system: str, user: str):
    """
    OpenAI API呼び出し（接続不安定時の簡易リトライ付き）。
    環境変数で調整可:
      - OPENAI_TIMEOUT_SECONDS (default: 120)
      - OPENAI_RETRY_COUNT (default: 3)
    """
    timeout_sec = float(os.getenv("OPENAI_TIMEOUT_SECONDS", "120"))
    retry_count = max(1, int(os.getenv("OPENAI_RETRY_COUNT", "3")))
    model = os.getenv("OPENAI_TEXT_MODEL", "gpt-4o").strip() or "gpt-4o"

    for attempt in range(1, retry_count + 1):
        try:
            return client.chat.completions.create(
                model=model,
                max_tokens=8192,
                timeout=timeout_sec,
                messages=[
                    {"role": "system", "content": system},
                    {"role": "user", "content": user},
                ],
            )
        except (APIConnectionError, APITimeoutError) as e:
            if attempt >= retry_count:
                raise RuntimeError(
                    "OpenAIへの接続に失敗しました。ネットワーク状態を確認して、少し時間をおいて再試行してください。"
                ) from e
            time.sleep(min(2 ** (attempt - 1), 4))
        except RateLimitError as e:
            raise RuntimeError(
                "APIの利用上限に達しました。少し待ってから再試行してください。"
            ) from e
        except APIError as e:
            raise RuntimeError(f"OpenAI APIエラー: {e}") from e


def revise_generated_text(
    existing_text: str,
    instruction: str,
    *,
    target_label: str,
    context: str = "",
) -> str:
    """Revise one generated document while preserving unaffected content."""
    if not (existing_text or "").strip():
        raise ValueError(f"修正対象の{target_label}がありません")
    if not (instruction or "").strip():
        raise ValueError("修正指示がありません")
    system = (
        "あなたはKOKOROE／ココロエのパーソナル鑑定を改訂する編集者です。"
        "利用者の指摘を事実として尊重し、指摘された箇所を具体的に修正してください。"
        "指摘と無関係な構成・内容・固有名詞は維持し、別人の鑑定書へ作り替えないでください。"
        "ラッキーアイテム、運命論、断定的な人格評価、恐怖を煽る表現は禁止です。"
        "内部計算の数字、点数、割合、数式、構成数名、周期番号は本文へ出してはいけません。"
        "出力は改訂後の本文だけにし、Markdown記法、前置き、変更履歴は付けないでください。"
    )
    user = f"""【修正対象】
{target_label}

【利用者の指摘】
{instruction.strip()}

【入力・計算の文脈】
{context.strip() or '（追加情報なし）'}

【現在の本文】
{existing_text.strip()}

現在の本文を土台として、利用者の指摘を反映した完成版全文を出力してください。"""
    response = _create_chat_completion(get_client(), system, user)
    revised = response.choices[0].message.content or ""
    if not revised.strip():
        raise RuntimeError("修正版の本文が生成されませんでした")
    return hide_internal_calculation_values(revised)


def generate_profile(
    last_name_roma: str,
    first_name_roma: str,
    birth_date: str,
    consultation: str,
    numbers: dict,
    nine_year_cycle: list[dict] | None = None,
    maiden_last_name: str | None = None,
    numbers_maiden: dict | None = None,
) -> str:
    """本人用鑑定を生成。計算値は推論専用で、公開本文には含めない。"""
    client = get_client()
    system = build_system_prompt()
    user = build_profile_user_prompt(
        last_name_roma,
        first_name_roma,
        birth_date,
        consultation,
        numbers,
        nine_year_cycle,
        maiden_last_name=maiden_last_name,
        numbers_maiden=numbers_maiden,
    )

    response = _create_chat_completion(client, system, user)
    return hide_internal_calculation_values(response.choices[0].message.content)


def generate_relationship_analysis(
    main_name: str, main_birth: str,
    main_numbers: dict,
    others: list[dict],
) -> str:
    """周囲10人との関係性分析を生成"""
    client = get_client()
    system = (
        "あなたはKOKOROE／ココロエの関係性鑑定の専門家です。"
        "ラッキーアイテム・運命論・恐怖を煽る表現は禁止。"
        "構造的・現実的・運用に活かせる形で、各人物との相性と関係性のヒントを書いてください。"
        "メインの本人用プロファイルは別途A4約4枚分で作成済みなので、ここでは省略せず、"
        "各人物との関係性に特化した内容を十分な分量で書いてください。"
        "1人あたりA4用紙の約半ページ分（日本語でおおよそ800〜1200文字、3〜5段落程度）を目安とし、"
        "人数が増えればそのぶん全体の分量も増えるようにしてください。"
        "名前については、与えられたローマ字表記（例: YAMADA, TANAKA など）をそのまま用い、"
        "漢字や別の表記への推測変換は一切行わないでください。"
        "内部計算の数字、点数、割合、数式、構成数名、周期番号は本文へ出してはいけません。"
    )
    user = build_relationship_user_prompt(
        main_name, main_birth, main_numbers, others
    )

    response = _create_chat_completion(client, system, user)
    return hide_internal_calculation_values(response.choices[0].message.content)
