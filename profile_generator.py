# -*- coding: utf-8 -*-
"""
OpenAI (ChatGPT) API を用いたマカレン数秘術プロファイル生成
"""
import os
import time
from openai import OpenAI, APIConnectionError, APITimeoutError, RateLimitError, APIError
from dotenv import load_dotenv
from prompts import build_system_prompt, build_profile_user_prompt, build_relationship_user_prompt

load_dotenv()


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
        "あなたはマカレン数秘術の鑑定書を改訂する編集者です。"
        "利用者の指摘を事実として尊重し、指摘された箇所を具体的に修正してください。"
        "指摘と無関係な構成・内容・固有名詞は維持し、別人の鑑定書へ作り替えないでください。"
        "ラッキーアイテム、運命論、断定的な人格評価、恐怖を煽る表現は禁止です。"
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
    return revised.strip()


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
    """本人用プロファイル（A4約4枚分）を生成。構成数は事前計算済みの辞書を渡す。旧姓あり時は numbers_maiden で考察を追加。"""
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
    return response.choices[0].message.content


def generate_relationship_analysis(
    main_name: str, main_birth: str,
    main_numbers: dict,
    others: list[dict],
) -> str:
    """周囲10人との関係性分析を生成"""
    client = get_client()
    system = (
        "あなたはマカレン数秘術に基づく関係性分析の専門家です。"
        "ラッキーアイテム・運命論・恐怖を煽る表現は禁止。"
        "構造的・現実的・運用に活かせる形で、各人物との相性と関係性のヒントを書いてください。"
        "メインの本人用プロファイルは別途A4約4枚分で作成済みなので、ここでは省略せず、"
        "各人物との関係性に特化した内容を十分な分量で書いてください。"
        "1人あたりA4用紙の約半ページ分（日本語でおおよそ800〜1200文字、3〜5段落程度）を目安とし、"
        "人数が増えればそのぶん全体の分量も増えるようにしてください。"
        "名前については、与えられたローマ字表記（例: YAMADA, TANAKA など）をそのまま用い、"
        "漢字や別の表記への推測変換は一切行わないでください。"
    )
    user = build_relationship_user_prompt(
        main_name, main_birth, main_numbers, others
    )

    response = _create_chat_completion(client, system, user)
    return response.choices[0].message.content
