# -*- coding: utf-8 -*-
"""KOKOROEの鑑定文とパーソナルアートをA4 PDFへまとめる。"""
import io
import os
import re

from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import Image, PageBreak, Paragraph, SimpleDocTemplate, Spacer


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


def _font_name():
    return FONT_NAME if _JP_FONT_OK else "Helvetica"


def _text_to_flowables(text: str, styles) -> list:
    """プレーンテキストの見出しと改行をFlowableへ変換する。"""
    flowables = []
    body_style = styles.get("KokoroeBodyText", styles["Normal"])
    heading_style = ParagraphStyle(
        "KokoroeHeading",
        parent=body_style,
        fontName=_font_name(),
        fontSize=12,
        spaceBefore=10,
        spaceAfter=6,
        textColor="#1b2540",
    )
    for block in str(text or "").split("\n\n"):
        block = block.strip()
        if not block:
            flowables.append(Spacer(1, 6))
            continue
        if block == "[[PAGEBREAK]]":
            flowables.append(PageBreak())
            continue
        for raw_line in block.splitlines():
            line = raw_line.strip()
            if not line:
                continue
            escaped = line.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
            is_heading = bool(re.match(r"^#+\s", line) or re.match(r"^\d+\.\s+.+", line))
            if is_heading:
                escaped = escaped.replace("#", "").strip()
                flowables.append(Paragraph(escaped, heading_style))
            else:
                flowables.append(Paragraph(escaped, body_style))
        flowables.append(Spacer(1, 6))
    return flowables


def build_pdf(
    content: str,
    title: str = "KOKOROE パーソナル鑑定書",
    numbers: dict | None = None,
    nine_year_cycle: list[dict] | None = None,
    artwork_bytes: bytes | None = None,
) -> bytes:
    """公開PDFを生成する。計算値は互換引数として受けるが、描画には使わない。"""
    _ = numbers, nine_year_cycle
    buffer = io.BytesIO()
    doc = SimpleDocTemplate(
        buffer,
        pagesize=A4,
        rightMargin=20 * mm,
        leftMargin=20 * mm,
        topMargin=20 * mm,
        bottomMargin=20 * mm,
    )
    styles = getSampleStyleSheet()
    styles["Normal"].fontName = _font_name()
    styles["Normal"].fontSize = 10
    styles["Normal"].leading = 14
    if "KokoroeBodyText" not in styles:
        styles.add(
            ParagraphStyle(
                name="KokoroeBodyText",
                parent=styles["Normal"],
                fontName=_font_name(),
                fontSize=10,
                leading=14,
            )
        )
    styles["Title"].fontName = _font_name()
    styles["Title"].fontSize = 16
    styles["Title"].spaceAfter = 12
    styles["Title"].textColor = "#1b2540"
    reference_style = ParagraphStyle(
        name="KokoroeReference",
        parent=styles["KokoroeBodyText"],
        fontSize=8.5,
        leading=12,
        textColor="#5d6370",
        spaceAfter=12,
    )

    page_width, page_height = map(float, A4)
    available_width = max(100, page_width - 40 * mm)
    available_height = max(100, page_height - 40 * mm)
    story = []

    if artwork_bytes:
        story.append(Paragraph("KOKOROE PERSONAL ART", styles["Title"]))
        story.append(Spacer(1, 8))
        try:
            story.append(
                Image(
                    io.BytesIO(artwork_bytes),
                    width=available_width,
                    height=available_height * 0.88,
                    kind="proportional",
                )
            )
            story.append(PageBreak())
        except Exception:
            story = []

    story.extend(
        [
            Paragraph(title, styles["Title"]),
            Paragraph(
                "KOKOROEは、カバラ数秘術ヤマカレンを参考にしながら、独自の鑑定設計と抽象画制作へ再構成したサービスです。内部の計算値・採点値は表示していません。",
                reference_style,
            ),
            Spacer(1, 6),
        ]
    )
    story.extend(_text_to_flowables(content, styles))
    doc.build(story)
    return buffer.getvalue()
