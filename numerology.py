# -*- coding: utf-8 -*-
"""
マカレン数秘：構成数計算（スプレッドシート用ロジックと同一）
姓・名はローマ字（A-Z）で与える想定。
"""
import re
import unicodedata


def _letter_to_num(ch: str) -> int:
    c = ord(ch.upper()) if ch else 0
    if c < 65 or c > 90:
        return 0
    return ((c - 65) % 9) + 1


def _normalize(s: str) -> str:
    if s is None:
        return ""
    s = unicodedata.normalize("NFKC", str(s)).upper().strip()
    s = re.sub(r"[^A-Z ]", "", s)
    return s.strip()


def _reduce_keep(n) -> int | str:
    """桁和縮約。11/22 は保持。"""
    if n == "" or n is None:
        return ""
    cleaned = re.sub(r"[^0-9]", "", str(n))
    if not cleaned:
        return ""
    x = int(cleaned)
    if x == 11 or x == 22:
        return x
    for _ in range(10):
        if x < 10:
            return x
        x = sum(int(d) for d in str(x))
        if x == 11 or x == 22:
            return x
    return x


def _sum_alpha(s: str) -> int:
    s = _normalize(s).replace(" ", "")
    return sum(_letter_to_num(ch) for ch in s)


def _sum_vowel(s: str) -> int:
    s = _normalize(s).replace(" ", "")
    return sum(_letter_to_num(ch) for ch in s if ch in "AEIOU")


def _sum_cons(s: str) -> int:
    s = _normalize(s).replace(" ", "")
    return sum(_letter_to_num(ch) for ch in s if ch.isalpha() and ch not in "AEIOU")


# ===== 数秘関数（スプレッドシートの NUM_* と対応） =====

def num_birth_i(y: int, m: int, d: int) -> int | str:
    s = sum(int(x) for x in (str(y) + str(m) + str(d)))
    return _reduce_keep(s)


def num_birth_ii(d: int) -> int | str:
    return _reduce_keep(d)


def num_kage(b_i, b_ii):
    b_i, b_ii = int(b_i) if b_i not in ("", None) else 0, int(b_ii) if b_ii not in ("", None) else 0
    if b_i == 9 and b_ii not in (2, 22):
        return ""
    if b_ii == 9 and b_i not in (2, 22):
        return ""
    if (b_i == 9 and b_ii in (2, 22)) or (b_ii == 9 and b_i in (2, 22)):
        return 2
    return _reduce_keep(b_i + b_ii)


def num_last_total(last: str) -> int | str:
    return _reduce_keep(_sum_alpha(last))


def num_first_total(first: str) -> int | str:
    return _reduce_keep(_sum_alpha(first))


def num_social_from_parts(kakei, jiga) -> int | str:
    return _reduce_keep(int(kakei or 0) + int(jiga or 0))


def num_soul_full(last: str, first: str) -> int | str:
    return _reduce_keep(_sum_vowel(last) + _sum_vowel(first))


def num_look_full(last: str, first: str) -> int | str:
    return _reduce_keep(_sum_cons(last) + _sum_cons(first))


def num_mission(b_i, shakai) -> int | str:
    return _reduce_keep(int(b_i or 0) + int(shakai or 0))


def num_stage(gaiken, month) -> int | str:
    m = 11 if int(month or 0) == 11 else _reduce_keep(month or 0)
    if m == "":
        m = 0
    return _reduce_keep(int(gaiken or 0) + int(m))


def num_insu(last: str, first: str) -> int | str:
    ln, fn = _normalize(last).replace(" ", ""), _normalize(first).replace(" ", "")
    l = _letter_to_num(ln[0]) if ln else 0
    f = _letter_to_num(fn[0]) if fn else 0
    return _reduce_keep(l + f)


def num_core(b_i, tamashi) -> int | str:
    return _reduce_keep(int(b_i or 0) + int(tamashi or 0))


# ラベル（プロンプト・表示用）
LABELS = [
    "誕生数Ⅰ", "誕生数Ⅱ", "影数", "家系数", "自我数", "社会数",
    "使命数", "魂数", "外見数", "演技数", "隠数", "核数",
]


def compute_all(last_name_roma: str, first_name_roma: str, year: int, month: int, day: int) -> dict:
    """
    姓・名（ローマ字）、生年月日から全12構成数を計算する。
    返り値: ラベル名をキー、値を数（または空文字）とする辞書。
    """
    last = last_name_roma or ""
    first = first_name_roma or ""
    y, m, d = int(year or 0), int(month or 0), int(day or 0)

    b11 = num_birth_i(y, m, d)
    b12 = num_birth_ii(d)
    b14 = num_last_total(last)
    b15 = num_first_total(first)
    b16 = num_social_from_parts(b14, b15)
    b17 = num_mission(b11, b16)
    b18 = num_soul_full(last, first)
    b19 = num_look_full(last, first)
    b20 = num_stage(b19, m)
    b21 = num_insu(last, first)
    b22 = num_core(b11, b18)
    b13 = num_kage(b11, b12)

    return {
        "誕生数Ⅰ": _fmt(b11),
        "誕生数Ⅱ": _fmt(b12),
        "影数": _fmt(b13),
        "家系数": _fmt(b14),
        "自我数": _fmt(b15),
        "社会数": _fmt(b16),
        "使命数": _fmt(b17),
        "魂数": _fmt(b18),
        "外見数": _fmt(b19),
        "演技数": _fmt(b20),
        "隠数": _fmt(b21),
        "核数": _fmt(b22),
    }


def _fmt(v) -> str:
    if v == "" or v is None:
        return ""
    return str(v)


# 9年サイクル用: 合計を1桁に還元（11→2, 22→4）。マカレン数秘術のルール。
def _reduce_to_one_digit_for_cycle(n: int) -> int:
    if n <= 0:
        return 1
    for _ in range(20):
        if n <= 9:
            return n
        if n == 11:
            return 2
        if n == 22:
            return 4
        n = sum(int(d) for d in str(n))
    return n if 1 <= n <= 9 else 1


# 西暦の桁和（11・22はまとめて1つとして扱う）。例: 2011→2+0+11=13→4, 2022→2+0+22=24→6
def _year_digit_sum_for_cycle(year: int) -> int:
    s = str(year)
    parts: list[int] = []
    i = 0
    while i < len(s):
        if i + 2 <= len(s):
            two = s[i : i + 2]
            if two == "11" or two == "22":
                parts.append(int(two))
                i += 2
                continue
        parts.append(int(s[i]))
        i += 1
    total = sum(parts)
    return _reduce_to_one_digit_for_cycle(total)


# 誕生数Ⅰを9年サイクル用に1桁に還元（11→2, 22→4）
def _birth_i_for_cycle(birth_i) -> int:
    if birth_i in ("", None):
        return 1
    x = int(str(birth_i).strip()) if str(birth_i).strip().isdigit() else 0
    if x == 11:
        return 2
    if x == 22:
        return 4
    return _reduce_to_one_digit_for_cycle(x)


# 各パーソナルイヤーの意味（マカレン数秘術 第6章に準拠）
NINE_YEAR_MEANINGS = {
    1: "はじまり",
    2: "バランス",
    3: "行動",
    4: "安定",
    5: "変化",
    6: "調和",
    7: "思考",
    8: "成果",
    9: "総括",
}


def compute_nine_year_cycle(year: int, month: int, day: int, length: int = 9, start_year: int | None = None) -> list[dict]:
    """
    9年サイクル（パーソナルイヤー）を計算する。
    ルール: 調べたい年（西暦）の各桁の和（11・22はまとめて足す）＋ 誕生数Ⅰ を1桁に還元。
    核数は使わず、誕生数Ⅰのみ使用。還元時は11→2, 22→4。
    """
    try:
        y = int(year)
        m = int(month)
        d = int(day)
    except (TypeError, ValueError):
        return []

    birth_i_raw = num_birth_i(y, m, d)
    birth_i = _birth_i_for_cycle(birth_i_raw)

    from datetime import date
    if start_year is None:
        # サーバーの現在日付を基準に、現在の年を中心に前後3年（計7年）で分析（例: 2026年なら2023〜2029）
        start_year = date.today().year - 3
        effective_length = 7
    else:
        effective_length = length

    cycles: list[dict] = []
    for offset in range(effective_length):
        target_year = start_year + offset
        year_sum = _year_digit_sum_for_cycle(target_year)
        personal_num = _reduce_to_one_digit_for_cycle(year_sum + birth_i)
        meaning = NINE_YEAR_MEANINGS.get(personal_num, "")
        cycles.append({
            "year": target_year,
            "personal_year": str(personal_num),
            "meaning": meaning,
        })
    return cycles
