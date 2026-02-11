# -*- coding: utf-8 -*-
"""
A4用紙・約4枚分のプロファイルをPDF化
"""
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import mm
from reportlab.lib import colors
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, PageBreak, Preformatted, Image, Table, TableStyle
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
import io
import re
import os

# 日本語フォント（環境に合わせてパスを変更可能）
FONT_PATHS = [
    "/System/Library/Fonts/Supplemental/Arial Unicode.ttf",
    "/System/Library/Fonts/Hiragino Sans GB.ttc",
    "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
]
FONT_NAME = "JPFont"
_JP_FONT_OK = False


def _register_japanese_font():
    global _JP_FONT_OK
    for path in FONT_PATHS:
        if os.path.isfile(path):
            try:
                pdfmetrics.registerFont(TTFont(FONT_NAME, path))
                _JP_FONT_OK = True
                return
            except Exception:
                continue
    _JP_FONT_OK = False


_register_japanese_font()
BASE_DIR = os.path.dirname(__file__)
IMAGES_DIR = os.path.join(BASE_DIR, "static", "images")
RELATION_DIAGRAM_PATH = os.path.join(IMAGES_DIR, "diagram_relations.png")


def _font_name():
    return FONT_NAME if _JP_FONT_OK else "Helvetica"


def _text_to_flowables(
    text: str,
    styles,
    core_image_path: str | None = None,
    core_image_width: float | None = None,
    core_image_max_height: float | None = None,
) -> list:
    """Markdown風の見出し・改行をFlowableに変換"""
    flowables = []
    fn = _font_name()
    body_style = styles.get("MakarenBodyText", styles["Normal"])
    heading_style = ParagraphStyle(
        "Heading",
        parent=body_style,
        fontName=fn,
        fontSize=12,
        spaceBefore=10,
        spaceAfter=6,
        textColor="navy",
    )
    inserted_core_image = False
    # 見出しっぽい行（## や 1. など）を検出
    for block in text.split("\n\n"):
        block = block.strip()
        if not block:
            flowables.append(Spacer(1, 6))
            continue
        # 特別なページ分割マーカー（[[PAGEBREAK]]）があれば強制改ページ
        if block == "[[PAGEBREAK]]":
            flowables.append(PageBreak())
            continue
        lines = block.split("\n")
        for line in lines:
            line = line.strip()
            # 「7. ９年サイクルの読み解き」のように、
            # 行頭が「数字. 」で始まる見出しはすべてHeadingスタイルに統一する
            is_heading = bool(
                re.match(r"^#+\s", line) or re.match(r"^\d+\.\s+.+", line)
            )
            if is_heading:
                flowables.append(Paragraph(line.replace("#", "").strip(), heading_style))
                # 「1. 核となる自己」の直後に核数イメージを挿入（あれば）
                if (
                    (not inserted_core_image)
                    and core_image_path
                    and "核となる自己" in line
                    and line.startswith("1.")
                ):
                    try:
                        w = core_image_width if core_image_width is not None else 250
                        h = core_image_max_height if core_image_max_height is not None else 300
                        img = Image(
                            core_image_path,
                            width=w,
                            height=h,
                            kind="proportional",
                        )
                        flowables.append(Spacer(1, 6))
                        flowables.append(img)
                        flowables.append(Spacer(1, 6))
                        inserted_core_image = True
                    except Exception:
                        # 画像読み込みに失敗しても本文生成は続行
                        pass
            else:
                # 改行を<br/>に
                line = line.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
                flowables.append(Paragraph(line, body_style))
        flowables.append(Spacer(1, 6))
    return flowables


def _core_image_path(core_value: str | None) -> str | None:
    """
    核数ごとのイメージ画像パスを返す。
    static/images/core_1.png のようなファイルが存在する場合のみ使用。
    """
    if not core_value:
        return None
    core_str = str(core_value).strip()
    filename = f"core_{core_str}.png"
    path = os.path.join(IMAGES_DIR, filename)
    return path if os.path.isfile(path) else None


def build_pdf(
    content: str,
    title: str = "マカレン数秘術 プロファイル",
    numbers: dict | None = None,
    nine_year_cycle: list[dict] | None = None,
) -> bytes:
    buffer = io.BytesIO()
    doc = SimpleDocTemplate(
        buffer,
        pagesize=A4,
        rightMargin=20 * mm,
        leftMargin=20 * mm,
        topMargin=20 * mm,
        bottomMargin=20 * mm,
    )
    fn = _font_name()
    styles = getSampleStyleSheet()
    styles["Normal"].fontName = fn
    styles["Normal"].fontSize = 10
    styles["Normal"].leading = 14
    if "MakarenBodyText" not in styles:
        styles.add(
            ParagraphStyle(
                name="MakarenBodyText",
                parent=styles["Normal"],
                fontName=fn,
                fontSize=10,
                leading=14,
            )
        )
    styles["Title"].fontName = fn
    styles["Title"].fontSize = 16
    styles["Title"].spaceAfter = 12
    styles["Title"].textColor = "navy"

    section_style = ParagraphStyle(
        name="SectionTitle",
        parent=styles["Title"],
        fontSize=12,
        spaceBefore=8,
        spaceAfter=4,
    )
    body_style = styles.get("MakarenBodyText", styles["Normal"])

    page_width, page_height = float(A4[0]), float(A4[1])
    margin_h = 20 * mm
    margin_v = 20 * mm
    available_width = max(100, page_width - margin_h * 2)
    available_height = max(100, page_height - margin_v * 2)

    story = [Paragraph(title, styles["Title"]), Spacer(1, 12)]

    core_value = None
    if numbers and "核数" in numbers:
        v = str(numbers.get("核数") or "").strip()
        core_value = v or None

    # 1ページ目: 構成数（表形式・画像参考の2行×5列）+ 関係図
    if numbers:
        story.append(Paragraph("構成数", section_style))
        # 画像参考: 1行目 誕生数(I・影数・II), 社会数, 魂数, 外見数, 使命数 / 2行目 家系数, 自我数, 演技数, 隠数, 核数
        def _v(k):
            return str(numbers.get(k) or "").strip() or "—"
        # 誕生数(I・影数・II)の間は全角スペースで区切る
        birth_cell = "　".join([_v("誕生数Ⅰ"), _v("影数"), _v("誕生数Ⅱ")]).strip() or "—"
        row1_labels = ["誕生数(I・影数・II)", "社会数", "魂数", "外見数", "使命数"]
        row1_vals = [birth_cell, _v("社会数"), _v("魂数"), _v("外見数"), _v("使命数")]
        row2_labels = ["家系数", "自我数", "演技数", "隠数", "核数"]
        row2_vals = [_v("家系数"), _v("自我数"), _v("演技数"), _v("隠数"), _v("核数")]
        table_data = [row1_labels, row1_vals, row2_labels, row2_vals]
        t = Table(table_data, colWidths=[available_width / 5.0] * 5)
        t.setStyle(TableStyle([
            ("FONTNAME", (0, 0), (-1, -1), _font_name()),
            ("FONTSIZE", (0, 0), (-1, -1), 9),
            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#e8e8e8")),
            ("BACKGROUND", (0, 2), (-1, 2), colors.HexColor("#e8e8e8")),
            ("GRID", (0, 0), (-1, -1), 0.5, colors.grey),
            ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
            ("ALIGN", (0, 0), (-1, -1), "CENTER"),
        ]))
        story.append(t)
        story.append(Spacer(1, 8))

        story.append(Paragraph("構成数の関係性", section_style))
        if os.path.isfile(RELATION_DIAGRAM_PATH):
            # 1ページ目に確実に収まるよう、図の高さを少し抑える（縦横比は保持）
            diagram_max_height = available_height * 0.45
            story.append(
                Image(
                    RELATION_DIAGRAM_PATH,
                    width=float(available_width),
                    height=float(diagram_max_height),
                    kind="proportional",
                )
            )
        else:
            # 画像がない場合はテキストベースの図解
            diagram_lines = [
                "外面的な構成数：誕生数Ⅰ・社会数・外見数・家系数",
                "内面的な構成数：演技数・魂数・自我数・核数・隠数",
                "使命数（役割）はこれら全体を束ねる中心の数としてイメージする。",
                "隠数は、内面的な構成数から影響を受ける「裏側の動き・弱点」として扱う。",
            ]
            diagram_text = "\n".join(diagram_lines)
            story.append(Preformatted(diagram_text, body_style))

        # 図の下に、画像内の説明テキストをそのまま挿入
        relation_text = (
            "10の構成数は、外面的なものと内面的なものに分けることができる。\n"
            "誕生数、社会数、家系数、外見数は外面的なものを観る構成数で、その影響を受けるのが使命数。\n"
            "核数、自我数、魂数、演技数は内面的なものを観る構成数で、その影響を受けるのが隠数。\n"
            "使命数、隠数を除いた８つの構成数は、この２つで分けたとき、対の関係になっている。\n"
            "そのため、\n\n"
            "・外面的な構成数と内面的な構成数の数字の傾向が同じ向きならば、裏表があまりない。\n"
            "・外面的な構成数と内面的な構成数の数字の傾向の向きが大きく違う場合は、自己矛盾、葛藤を抱えている。\n\n"
            "といったことが読み取れる。\n"
            "１つひとつの数字を単体で観るのではなく、このように組み合わせて観ていくことが大切。"
        )
        story.append(Spacer(1, 6))
        story.append(Preformatted(relation_text, body_style))
        story.append(Spacer(1, 8))

    # 2ページ目以降に９年サイクルと本文
    story.append(PageBreak())

    if nine_year_cycle:
        rows = []
        for row in nine_year_cycle:
            y = row.get("year")
            p = row.get("personal_year")
            m = row.get("meaning", "")
            if y is None or p in ("", None):
                continue
            year_label = f"{y}年"
            py_label = str(p)
            meaning_text = str(m or "")
            rows.append([year_label, py_label, meaning_text])
        if rows:
            story.append(Paragraph("９年サイクル（パーソナルイヤー）", section_style))
            table_data = [["年", "数", "テーマ / キーワード"]] + rows
            cycle_table = Table(
                table_data,
                colWidths=[available_width * 0.15, available_width * 0.15, available_width * 0.7],
            )
            cycle_table.setStyle(
                TableStyle(
                    [
                        ("FONTNAME", (0, 0), (-1, -1), _font_name()),
                        ("FONTSIZE", (0, 0), (-1, -1), 9),
                        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#e8e8e8")),
                        ("GRID", (0, 0), (-1, -1), 0.5, colors.grey),
                        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                        ("ALIGN", (0, 0), (1, -1), "CENTER"),
                        ("ALIGN", (2, 0), (2, -1), "LEFT"),
                    ]
                )
            )
            story.append(cycle_table)
            story.append(Spacer(1, 12))

    # 本文（LLM 生成テキスト）
    core_image_path = _core_image_path(core_value)
    max_core_inline_height = available_height * 0.4
    story.extend(
        _text_to_flowables(
            content,
            styles,
            core_image_path=core_image_path,
            core_image_width=available_width * 0.5 if core_image_path else 250,
            core_image_max_height=max_core_inline_height,
        )
    )

    doc.build(story)
    return buffer.getvalue()
