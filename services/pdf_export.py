"""PDF export service — produces a beautifully designed financial report."""

import io
import logging
import re
from collections import defaultdict

_logger = logging.getLogger(__name__)
from datetime import date, datetime

from reportlab.graphics.charts.barcharts import VerticalBarChart
from reportlab.graphics.charts.piecharts import Pie
from reportlab.graphics.shapes import Drawing, String, Line, Rect, Circle
from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_LEFT, TA_RIGHT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import cm, mm
from reportlab.platypus import (
    BaseDocTemplate, Frame, KeepTogether, NextPageTemplate, PageBreak,
    PageTemplate, Paragraph, Spacer, Table, TableStyle,
)
from sqlalchemy import func
from sqlmodel import Session, select

from i18n import _
from models.movement import Movement, MovementTag
from models.recurring import RecurringItem
from models.saving import Saving, SavingTag
from models.source import Source
from models.tag import Tag
from models.whim import Whim

# ---------------------------------------------------------------------------
# Colour palette
# ---------------------------------------------------------------------------
_PRIMARY = colors.HexColor("#696CFF")
_PRIMARY_LIGHT = colors.HexColor("#E7E7FF")
_PRIMARY_DARK = colors.HexColor("#5A5EE6")
_SUCCESS = colors.HexColor("#71DD37")
_SUCCESS_DARK = colors.HexColor("#28A745")
_SUCCESS_LIGHT = colors.HexColor("#E8FBE0")
_DANGER = colors.HexColor("#FF3E1D")
_DANGER_LIGHT = colors.HexColor("#FFE0DA")
_WARNING = colors.HexColor("#FFAB00")
_WARNING_LIGHT = colors.HexColor("#FFF3D6")
_INFO = colors.HexColor("#03C3EC")
_GRAY_50 = colors.HexColor("#F5F5F9")
_GRAY_100 = colors.HexColor("#ECEEF1")
_GRAY_200 = colors.HexColor("#D9DEE3")
_GRAY_500 = colors.HexColor("#A1ACB8")
_GRAY_700 = colors.HexColor("#4B465C")
_DARK = colors.HexColor("#2B2C40")
_WHITE = colors.white

PAGE_W, PAGE_H = A4
MARGIN = 1.8 * cm
CONTENT_W = PAGE_W - 2 * MARGIN

# Section accent colours (used for table headers and TOC dots)
_SECTION_COLORS = {
    "sources": _INFO,
    "movements": _SUCCESS_DARK,
    "tags": _WARNING,
    "recurring": _DANGER,
    "savings": colors.HexColor("#4CAF50"),
    "whims": _WARNING,
}

# Reportlab chart colour palette for pie slices, etc.
_CHART_COLORS = [
    _PRIMARY, _SUCCESS, _DANGER, _WARNING, _INFO,
    colors.HexColor("#8B5CF6"), colors.HexColor("#F97316"),
    colors.HexColor("#06B6D4"), _GRAY_500,
]

_styles = getSampleStyleSheet()


# ---------------------------------------------------------------------------
# Styles (created once per call via closure to avoid name collisions)
# ---------------------------------------------------------------------------

def _make_styles():
    return {
        "title": ParagraphStyle(
            "PDFTitle", parent=_styles["Title"],
            fontSize=32, leading=38, textColor=_PRIMARY,
            fontName="Helvetica-Bold", spaceAfter=2,
        ),
        "subtitle": ParagraphStyle(
            "PDFSubtitle", parent=_styles["Normal"],
            fontSize=12, leading=16, textColor=_GRAY_500,
            fontName="Helvetica", spaceAfter=16,
        ),
        "section": ParagraphStyle(
            "PDFSection", parent=_styles["Heading2"],
            fontSize=18, leading=22, textColor=_DARK,
            fontName="Helvetica-Bold", spaceBefore=0, spaceAfter=8,
        ),
        "subsection": ParagraphStyle(
            "PDFSubsection", parent=_styles["Heading3"],
            fontSize=12, leading=15, textColor=_GRAY_700,
            fontName="Helvetica-Bold", spaceBefore=10, spaceAfter=6,
        ),
        "body": ParagraphStyle(
            "PDFBody", parent=_styles["Normal"],
            fontSize=9, leading=12, textColor=_GRAY_700,
            fontName="Helvetica",
        ),
        "body_small": ParagraphStyle(
            "PDFBodySmall", parent=_styles["Normal"],
            fontSize=8, leading=10, textColor=_GRAY_500,
            fontName="Helvetica",
        ),
        "kpi_value": ParagraphStyle(
            "KPIValue", parent=_styles["Normal"],
            fontSize=20, leading=24, textColor=_DARK,
            fontName="Helvetica-Bold", alignment=TA_CENTER,
        ),
        "kpi_label": ParagraphStyle(
            "KPILabel", parent=_styles["Normal"],
            fontSize=7, leading=9, textColor=_GRAY_500,
            fontName="Helvetica", alignment=TA_CENTER,
        ),
        "th": ParagraphStyle(
            "TH", parent=_styles["Normal"],
            fontSize=8, leading=10, textColor=_WHITE,
            fontName="Helvetica-Bold",
        ),
        "td": ParagraphStyle(
            "TD", parent=_styles["Normal"],
            fontSize=8, leading=10, textColor=_GRAY_700,
            fontName="Helvetica",
        ),
        "td_right": ParagraphStyle(
            "TDR", parent=_styles["Normal"],
            fontSize=8, leading=10, textColor=_GRAY_700,
            fontName="Helvetica", alignment=TA_RIGHT,
        ),
        "td_income": ParagraphStyle(
            "TDInc", parent=_styles["Normal"],
            fontSize=8, leading=10, textColor=_SUCCESS_DARK,
            fontName="Helvetica-Bold", alignment=TA_RIGHT,
        ),
        "td_expense": ParagraphStyle(
            "TDExp", parent=_styles["Normal"],
            fontSize=8, leading=10, textColor=_DANGER,
            fontName="Helvetica-Bold", alignment=TA_RIGHT,
        ),
        "month_header": ParagraphStyle(
            "MonthH", parent=_styles["Normal"],
            fontSize=9, leading=12, textColor=_PRIMARY,
            fontName="Helvetica-Bold",
        ),
    }


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _fmt(value: float, currency: str = "") -> str:
    formatted = f"{value:,.2f}"
    return f"{formatted} {currency}" if currency else formatted


_EMOJI_RE = re.compile(
    "["
    "\U0001F1E0-\U0001F1FF"  # flags
    "\U0001F300-\U0001F5FF"  # symbols & pictographs
    "\U0001F600-\U0001F64F"  # emoticons
    "\U0001F680-\U0001F6FF"  # transport & map
    "\U0001F700-\U0001F77F"  # alchemical
    "\U0001F780-\U0001F7FF"  # geometric shapes ext
    "\U0001F800-\U0001F8FF"  # supplemental arrows
    "\U0001F900-\U0001F9FF"  # supplemental symbols
    "\U0001FA00-\U0001FA6F"  # chess symbols
    "\U0001FA70-\U0001FAFF"  # symbols ext-A
    "\U00002702-\U000027B0"  # dingbats
    "\U0000FE00-\U0000FE0F"  # variation selectors
    "\U0000200D"              # zero width joiner
    "\U000020BF"              # bitcoin sign
    "\U000020A0-\U000020CF"  # currency symbols
    "\U00002600-\U000026FF"  # misc symbols
    "\U00002300-\U000023FF"  # misc technical
    "\U0000FE0F"              # variation selector-16
    "]+", re.UNICODE)


def _strip_emoji(text: str) -> str:
    """Remove emoji characters that ReportLab can't render."""
    return _EMOJI_RE.sub("", text).strip()


def _p(text: str, style) -> Paragraph:
    # Strip emoji and sanitize for reportlab XML parser
    t = _strip_emoji(str(text))
    t = t.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    return Paragraph(t, style)


def _color_dot(hex_color: str, size: float = 6) -> Drawing:
    """Draw a small coloured circle."""
    d = Drawing(size + 2, size + 2)
    c = hex_color.lstrip("#") if hex_color else "A1ACB8"
    try:
        fill = colors.HexColor(f"#{c}")
    except Exception:
        _logger.debug("Invalid hex color %r, using fallback", hex_color)
        fill = _GRAY_500
    d.add(Circle(size / 2 + 1, size / 2 + 1, size / 2,
                 fillColor=fill, strokeColor=fill))
    return d


# ---------------------------------------------------------------------------
# KPI cards
# ---------------------------------------------------------------------------

def _kpi_card(label: str, value: str, accent=None) -> Table:
    s = _make_styles()
    vs = ParagraphStyle("_kv", parent=s["kpi_value"], textColor=accent or _DARK)
    t = Table(
        [[_p(value, vs)], [_p(label, s["kpi_label"])]],
        colWidths=[CONTENT_W / 4 - 4 * mm],
    )
    t.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), _GRAY_50),
        ("BOX", (0, 0), (-1, -1), 0.5, _GRAY_200),
        ("ROUNDEDCORNERS", [6, 6, 6, 6]),
        ("TOPPADDING", (0, 0), (-1, 0), 10),
        ("BOTTOMPADDING", (0, -1), (-1, -1), 8),
        ("LEFTPADDING", (0, 0), (-1, -1), 4),
        ("RIGHTPADDING", (0, 0), (-1, -1), 4),
        ("ALIGN", (0, 0), (-1, -1), "CENTER"),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
    ]))
    return t


def _kpi_row(kpis: list[tuple[str, str, colors.Color | None]]) -> Table:
    cards = [_kpi_card(l, v, c) for l, v, c in kpis]
    while len(cards) < 4:
        cards.append("")
    t = Table([cards[:4]], colWidths=[CONTENT_W / 4] * 4)
    t.setStyle(TableStyle([
        ("ALIGN", (0, 0), (-1, -1), "CENTER"),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("LEFTPADDING", (0, 0), (-1, -1), 2),
        ("RIGHTPADDING", (0, 0), (-1, -1), 2),
    ]))
    return t


# ---------------------------------------------------------------------------
# Dividers
# ---------------------------------------------------------------------------

def _divider():
    d = Drawing(CONTENT_W, 8)
    d.add(Line(0, 4, CONTENT_W, 4, strokeColor=_GRAY_200, strokeWidth=0.5))
    return d


def _accent_bar(color=_PRIMARY, height=3):
    d = Drawing(CONTENT_W, height + 2)
    d.add(Rect(0, 1, CONTENT_W, height, fillColor=color, strokeColor=color))
    return d


# ---------------------------------------------------------------------------
# Styled table
# ---------------------------------------------------------------------------

def _styled_table(headers, rows, col_widths, accent=_PRIMARY):
    s = _make_styles()
    header_row = [_p(h, s["th"]) for h in headers]
    all_rows = [header_row] + rows

    t = Table(all_rows, colWidths=col_widths, repeatRows=1)

    cmds = [
        ("BACKGROUND", (0, 0), (-1, 0), accent),
        ("TEXTCOLOR", (0, 0), (-1, 0), _WHITE),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, 0), 8),
        ("BOTTOMPADDING", (0, 0), (-1, 0), 8),
        ("TOPPADDING", (0, 0), (-1, 0), 8),
        ("FONTNAME", (0, 1), (-1, -1), "Helvetica"),
        ("FONTSIZE", (0, 1), (-1, -1), 8),
        ("TOPPADDING", (0, 1), (-1, -1), 5),
        ("BOTTOMPADDING", (0, 1), (-1, -1), 5),
        ("LEFTPADDING", (0, 0), (-1, -1), 6),
        ("RIGHTPADDING", (0, 0), (-1, -1), 6),
        ("LINEBELOW", (0, 0), (-1, 0), 1, accent),
        ("LINEBELOW", (0, 1), (-1, -2), 0.3, _GRAY_200),
        ("LINEBELOW", (0, -1), (-1, -1), 0.5, _GRAY_200),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
    ]
    for i in range(1, len(all_rows)):
        if i % 2 == 0:
            cmds.append(("BACKGROUND", (0, i), (-1, i), _GRAY_50))
    t.setStyle(TableStyle(cmds))
    return t


# ---------------------------------------------------------------------------
# Charts
# ---------------------------------------------------------------------------

def _monthly_bar_chart(session: Session) -> Drawing | None:
    today = date.today()
    data_in, data_out, labels = [], [], []

    for i in range(11, -1, -1):
        m, y = today.month - i, today.year
        while m <= 0:
            m += 12; y -= 1
        ms = date(y, m, 1)
        me = date(y + 1, 1, 1) if m == 12 else date(y, m + 1, 1)

        inc = float(session.exec(select(func.coalesce(func.sum(Movement.amount), 0)).where(
            Movement.date >= ms, Movement.date < me, Movement.direction == "in")).one())
        exp = float(session.exec(select(func.coalesce(func.sum(Movement.amount), 0)).where(
            Movement.date >= ms, Movement.date < me, Movement.direction == "out")).one())
        labels.append(ms.strftime("%b"))
        data_in.append(inc)
        data_out.append(exp)

    if not any(data_in) and not any(data_out):
        return None

    dw = Drawing(CONTENT_W, 190)
    ch = VerticalBarChart()
    ch.x, ch.y, ch.width, ch.height = 40, 15, CONTENT_W - 60, 150
    ch.data = [data_in, data_out]
    ch.categoryAxis.categoryNames = labels
    ch.categoryAxis.labels.fontSize = 7
    ch.categoryAxis.labels.fontName = "Helvetica"
    ch.categoryAxis.strokeColor = _GRAY_200
    ch.categoryAxis.labels.fillColor = _GRAY_700
    ch.valueAxis.labels.fontSize = 7
    ch.valueAxis.labels.fontName = "Helvetica"
    ch.valueAxis.strokeColor = _GRAY_200
    ch.valueAxis.labels.fillColor = _GRAY_700
    ch.valueAxis.gridStrokeColor = _GRAY_100
    ch.valueAxis.gridStrokeWidth = 0.3
    ch.bars[0].fillColor = _SUCCESS
    ch.bars[0].strokeColor = _SUCCESS
    ch.bars[1].fillColor = _DANGER
    ch.bars[1].strokeColor = _DANGER
    ch.barSpacing, ch.groupSpacing = 1, 6
    dw.add(ch)
    # Legend
    ly = ch.y + ch.height + 6
    dw.add(Rect(ch.x, ly, 8, 8, fillColor=_SUCCESS, strokeColor=_SUCCESS))
    dw.add(String(ch.x + 12, ly + 1, _("income"), fontSize=7, fontName="Helvetica", fillColor=_GRAY_700))
    dw.add(Rect(ch.x + 70, ly, 8, 8, fillColor=_DANGER, strokeColor=_DANGER))
    dw.add(String(ch.x + 82, ly + 1, _("expense"), fontSize=7, fontName="Helvetica", fillColor=_GRAY_700))
    return dw


def _tag_pie_chart(session: Session) -> Drawing | None:
    tags = session.exec(select(Tag)).all()
    if not tags:
        return None

    counts, names = [], []
    for tag in tags:
        c = session.exec(select(func.count(MovementTag.movement_id)).where(
            MovementTag.tag_id == tag.id)).one()
        if c > 0:
            counts.append(c)
            names.append(_strip_emoji(tag.name))

    if not counts:
        return None

    # Top 8 + Other
    if len(counts) > 8:
        combined = sorted(zip(counts, names), reverse=True)
        top = combined[:7]
        rest = sum(c for c, _n in combined[7:])
        counts = [c for c, _n in top] + [rest]
        names = [n for _c, n in top] + [_("all")]

    dw = Drawing(CONTENT_W * 0.55, 180)
    pie = Pie()
    pie.x, pie.y, pie.width, pie.height = 20, 10, 130, 130
    pie.data = counts
    pie.labels = [f"{n} ({c})" for n, c in zip(names, counts)]
    for i in range(len(counts)):
        pie.slices[i].fillColor = _CHART_COLORS[i % len(_CHART_COLORS)]
        pie.slices[i].strokeColor = _WHITE
        pie.slices[i].strokeWidth = 1.5
    pie.sideLabels = True
    pie.simpleLabels = False
    pie.slices.fontSize = 7
    pie.slices.fontName = "Helvetica"
    pie.slices.labelRadius = 1.3
    dw.add(pie)
    return dw


def _savings_bar_chart(session: Session) -> Drawing | None:
    today = date.today()
    data, labels = [], []
    for i in range(11, -1, -1):
        m, y = today.month - i, today.year
        while m <= 0:
            m += 12; y -= 1
        ms = date(y, m, 1)
        me = date(y + 1, 1, 1) if m == 12 else date(y, m + 1, 1)
        t = float(session.exec(select(func.coalesce(func.sum(Saving.amount), 0)).where(
            Saving.date >= ms, Saving.date < me)).one())
        labels.append(ms.strftime("%b"))
        data.append(t)

    if not any(data):
        return None

    dw = Drawing(CONTENT_W, 155)
    ch = VerticalBarChart()
    ch.x, ch.y, ch.width, ch.height = 40, 12, CONTENT_W - 60, 125
    ch.data = [data]
    ch.categoryAxis.categoryNames = labels
    ch.categoryAxis.labels.fontSize = 7
    ch.categoryAxis.labels.fontName = "Helvetica"
    ch.categoryAxis.strokeColor = _GRAY_200
    ch.categoryAxis.labels.fillColor = _GRAY_700
    ch.valueAxis.labels.fontSize = 7
    ch.valueAxis.labels.fontName = "Helvetica"
    ch.valueAxis.strokeColor = _GRAY_200
    ch.valueAxis.labels.fillColor = _GRAY_700
    ch.valueAxis.gridStrokeColor = _GRAY_100
    ch.valueAxis.gridStrokeWidth = 0.3
    ch.bars[0].fillColor = colors.HexColor("#4CAF50")
    ch.bars[0].strokeColor = colors.HexColor("#4CAF50")
    dw.add(ch)
    return dw


# ---------------------------------------------------------------------------
# Page decorators
# ---------------------------------------------------------------------------

def _cover_page(canvas, doc):
    canvas.saveState()
    # Full-width top accent bar
    canvas.setFillColor(_PRIMARY)
    canvas.rect(0, PAGE_H - 8, PAGE_W, 8, fill=1, stroke=0)
    # Subtle left accent stripe
    canvas.setFillColor(_PRIMARY_LIGHT)
    canvas.rect(0, 0, 6, PAGE_H - 8, fill=1, stroke=0)
    # Bottom bar
    canvas.setFillColor(_PRIMARY)
    canvas.rect(0, 0, PAGE_W, 3, fill=1, stroke=0)
    # Footer
    canvas.setFont("Helvetica", 7)
    canvas.setFillColor(_GRAY_500)
    canvas.drawCentredString(PAGE_W / 2, 10,
                             f"Yfine — {_('export_pdf_generated')} {date.today().isoformat()}")
    canvas.restoreState()


def _content_page(canvas, doc):
    canvas.saveState()
    # Top accent line
    canvas.setStrokeColor(_PRIMARY)
    canvas.setLineWidth(2)
    canvas.line(MARGIN, PAGE_H - 14, PAGE_W - MARGIN, PAGE_H - 14)
    # Header
    canvas.setFont("Helvetica-Bold", 8)
    canvas.setFillColor(_PRIMARY)
    canvas.drawString(MARGIN, PAGE_H - 12, "Yfine")
    canvas.setFont("Helvetica", 7)
    canvas.setFillColor(_GRAY_500)
    canvas.drawRightString(PAGE_W - MARGIN, PAGE_H - 12, date.today().isoformat())
    # Bottom
    canvas.setStrokeColor(_GRAY_200)
    canvas.setLineWidth(0.5)
    canvas.line(MARGIN, 26, PAGE_W - MARGIN, 26)
    canvas.setFont("Helvetica", 7)
    canvas.setFillColor(_GRAY_500)
    canvas.drawCentredString(PAGE_W / 2, 14, str(doc.page))
    canvas.restoreState()


# ---------------------------------------------------------------------------
# Cover page & TOC
# ---------------------------------------------------------------------------

def _build_cover(session: Session, sections: list[str]) -> list:
    s = _make_styles()
    el = []

    el.append(Spacer(1, 60))

    # Big title
    el.append(_p("Yfine", s["title"]))
    el.append(_p(_("export_pdf_title"), ParagraphStyle(
        "CoverLine2", parent=s["subtitle"], fontSize=16, spaceAfter=4,
        textColor=_GRAY_700, fontName="Helvetica")))
    el.append(_p(
        _("export_pdf_date_range").replace("{date}", date.today().isoformat()),
        s["subtitle"]))
    el.append(Spacer(1, 4))
    el.append(_accent_bar(_PRIMARY, 3))
    el.append(Spacer(1, 24))

    # KPIs
    sources = session.exec(select(Source)).all()
    net_by_cur: dict[str, float] = {}
    for src in sources:
        i_s = float(session.exec(select(func.coalesce(func.sum(Movement.amount), 0)).where(
            Movement.source_id == src.id, Movement.direction == "in")).one())
        o_s = float(session.exec(select(func.coalesce(func.sum(Movement.amount), 0)).where(
            Movement.source_id == src.id, Movement.direction == "out")).one())
        net_by_cur.setdefault(src.currency, 0.0)
        net_by_cur[src.currency] += src.starting_balance + i_s - o_s

    mov_count = session.exec(select(func.count(Movement.id))).one()
    kpis = []
    for cur, total in sorted(net_by_cur.items()):
        kpis.append((f"{_('net_worth')} ({cur})", _fmt(total),
                      _SUCCESS_DARK if total >= 0 else _DANGER))
    kpis.append((_("total_sources"), str(len(sources)), _PRIMARY))
    kpis.append((_("movements"), str(mov_count), _INFO))
    for i in range(0, len(kpis), 4):
        el.append(_kpi_row(kpis[i:i + 4]))
        el.append(Spacer(1, 8))

    el.append(Spacer(1, 24))

    # --- Table of Contents ---
    el.append(_p(_("export_pdf_contents"), ParagraphStyle(
        "TocTitle", parent=s["section"], fontSize=14, spaceAfter=12)))

    # Build a nice styled TOC table
    toc_rows = []
    section_icons = {
        "sources": _("sources"),
        "movements": _("movements"),
        "tags": _("tags"),
        "recurring": _("recurring"),
        "savings": _("savings"),
        "whims": _("whims"),
    }
    toc_descriptions = {
        "sources": _("export_pdf_toc_sources"),
        "movements": _("export_pdf_toc_movements"),
        "tags": _("export_pdf_toc_tags"),
        "recurring": _("export_pdf_toc_recurring"),
        "savings": _("export_pdf_toc_savings"),
        "whims": _("export_pdf_toc_whims"),
    }

    for sec in sections:
        color = _SECTION_COLORS.get(sec, _PRIMARY)
        # Colored dot drawing
        dot = Drawing(10, 10)
        dot.add(Circle(5, 5, 4, fillColor=color, strokeColor=color))

        name_style = ParagraphStyle("TocName", parent=s["body"],
                                     fontSize=10, fontName="Helvetica-Bold",
                                     textColor=_DARK)
        desc_style = ParagraphStyle("TocDesc", parent=s["body_small"],
                                     fontSize=8, textColor=_GRAY_500)

        toc_rows.append([
            dot,
            _p(section_icons.get(sec, sec), name_style),
            _p(toc_descriptions.get(sec, ""), desc_style),
        ])

    toc_table = Table(toc_rows,
                      colWidths=[16, CONTENT_W * 0.25, CONTENT_W * 0.65])
    toc_table.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("TOPPADDING", (0, 0), (-1, -1), 6),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
        ("LEFTPADDING", (0, 0), (0, -1), 0),
        ("LINEBELOW", (0, 0), (-1, -2), 0.3, _GRAY_100),
    ]))
    el.append(toc_table)

    el.append(PageBreak())
    return el


# ---------------------------------------------------------------------------
# Section header helper
# ---------------------------------------------------------------------------

def _section_header(title: str, color=_PRIMARY):
    """Section title with accent bar — used at start of every section page."""
    s = _make_styles()
    return [
        _accent_bar(color, 3),
        Spacer(1, 8),
        _p(title, s["section"]),
        Spacer(1, 4),
    ]


# ---------------------------------------------------------------------------
# SOURCES
# ---------------------------------------------------------------------------

def _build_sources(session: Session) -> list:
    s = _make_styles()
    el = _section_header(_("sources"), _INFO)

    sources = session.exec(select(Source)).all()
    if not sources:
        el.append(_p(_("no_sources"), s["body"]))
        return el

    rows = []
    for src in sources:
        i_s = float(session.exec(select(func.coalesce(func.sum(Movement.amount), 0)).where(
            Movement.source_id == src.id, Movement.direction == "in")).one())
        o_s = float(session.exec(select(func.coalesce(func.sum(Movement.amount), 0)).where(
            Movement.source_id == src.id, Movement.direction == "out")).one())
        bal = src.starting_balance + i_s - o_s
        bal_s = s["td_income"] if bal >= 0 else s["td_expense"]
        rows.append([
            _p(src.name, s["td"]),
            _p(src.currency, s["td"]),
            _p(_fmt(src.starting_balance), s["td_right"]),
            _p(_fmt(bal), bal_s),
        ])

    headers = [_("name"), _("currency"), _("starting_balance"), _("current_balance")]
    cw = [CONTENT_W * w for w in (0.35, 0.15, 0.25, 0.25)]
    el.append(_styled_table(headers, rows, cw, _INFO))
    el.append(Spacer(1, 12))
    return el


# ---------------------------------------------------------------------------
# MOVEMENTS — grouped by month
# ---------------------------------------------------------------------------

def _build_movements(session: Session) -> list:
    s = _make_styles()
    el = _section_header(_("movements"), _SUCCESS_DARK)

    # Totals
    total_in = float(session.exec(select(func.coalesce(func.sum(Movement.amount), 0)).where(
        Movement.direction == "in")).one())
    total_out = float(session.exec(select(func.coalesce(func.sum(Movement.amount), 0)).where(
        Movement.direction == "out")).one())
    net = total_in - total_out
    mov_count = session.exec(select(func.count(Movement.id))).one()

    kpis = [
        (_("income"), _fmt(total_in), _SUCCESS_DARK),
        (_("expense"), _fmt(total_out), _DANGER),
        ("Net", _fmt(net), _DARK),
        (_("movements"), str(mov_count), _PRIMARY),
    ]
    el.append(_kpi_row(kpis))
    el.append(Spacer(1, 14))

    # Chart
    chart = _monthly_bar_chart(session)
    if chart:
        el.append(_p(_("export_pdf_monthly_overview"), s["subsection"]))
        el.append(Spacer(1, 4))
        el.append(chart)
        el.append(Spacer(1, 14))

    # Lookups
    sources_map = {src.id: src.name for src in session.exec(select(Source)).all()}
    tags_map = {t.id: t.name for t in session.exec(select(Tag)).all()}
    mov_tags: dict[int, list[str]] = {}
    for mt in session.exec(select(MovementTag)).all():
        mov_tags.setdefault(mt.movement_id, []).append(tags_map.get(mt.tag_id, ""))

    movements = session.exec(select(Movement).order_by(Movement.date.desc())).all()

    if not movements:
        el.append(_p(_("no_movements"), s["body"]))
        return el

    # Group by month
    months: dict[str, list[Movement]] = {}
    for mov in movements:
        key = mov.date.strftime("%Y-%m")
        months.setdefault(key, []).append(mov)

    headers = [_("date"), _("source"), _("direction"), _("amount"), _("note"), _("tags")]
    cw = [CONTENT_W * w for w in (0.12, 0.15, 0.11, 0.14, 0.26, 0.22)]

    for month_key, month_movs in months.items():
        # Month header
        month_label = month_movs[0].date.strftime("%B %Y").capitalize()
        month_in = sum(m.amount for m in month_movs if m.direction == "in")
        month_out = sum(m.amount for m in month_movs if m.direction == "out")

        month_header_text = (
            f"{month_label}"
            f'&nbsp;&nbsp;&nbsp;<font color="#28A745">+{_fmt(month_in)}</font>'
            f'&nbsp;&nbsp;<font color="#FF3E1D">-{_fmt(month_out)}</font>'
        )

        rows = []
        for mov in month_movs:
            source_name = sources_map.get(mov.source_id, _("external"))
            ds = s["td_income"] if mov.direction == "in" else s["td_expense"]
            dl = _("income") if mov.direction == "in" else _("expense")
            tag_str = ", ".join(mov_tags.get(mov.id, []))

            rows.append([
                _p(str(mov.date.day), s["td"]),
                _p(source_name, s["td"]),
                _p(dl, ds),
                _p(_fmt(mov.amount), ds),
                _p(mov.note or "", s["td"]),
                _p(tag_str, s["body_small"]),
            ])

        # Build month block: header + table, keep header with first rows
        month_el = []
        month_el.append(Spacer(1, 6))
        month_el.append(Paragraph(month_header_text, ParagraphStyle(
            "MH", parent=s["month_header"], fontSize=10, spaceBefore=4, spaceAfter=4)))
        month_el.append(_styled_table(headers, rows, cw, _SUCCESS_DARK))
        month_el.append(Spacer(1, 4))

        # KeepTogether for small months, otherwise just flow
        if len(month_movs) <= 8:
            el.append(KeepTogether(month_el))
        else:
            el.extend(month_el)

    if mov_count > len(movements):
        el.append(Spacer(1, 4))
        el.append(_p(
            _("export_pdf_showing_of").replace("{n}", str(len(movements))).replace(
                "{total}", str(mov_count)),
            s["body_small"]))

    el.append(Spacer(1, 12))
    return el


# ---------------------------------------------------------------------------
# TAGS
# ---------------------------------------------------------------------------

def _build_tags(session: Session) -> list:
    s = _make_styles()
    el = _section_header(_("tags"), _WARNING)

    tags = session.exec(select(Tag)).all()
    if not tags:
        el.append(_p(_("no_tags"), s["body"]))
        return el

    rows = []
    for tag in tags:
        mc = session.exec(select(func.count(MovementTag.movement_id)).where(
            MovementTag.tag_id == tag.id)).one()
        sc = session.exec(select(func.count(SavingTag.saving_id)).where(
            SavingTag.tag_id == tag.id)).one()

        # Color dot + name
        if tag.color:
            dot = _color_dot(tag.color, 6)
            name_cell = Table([[dot, _p(tag.name, s["td"])]],
                              colWidths=[12, CONTENT_W * 0.46])
            name_cell.setStyle(TableStyle([
                ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                ("LEFTPADDING", (0, 0), (-1, -1), 0),
                ("RIGHTPADDING", (0, 0), (-1, -1), 0),
                ("TOPPADDING", (0, 0), (-1, -1), 0),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 0),
            ]))
        else:
            name_cell = _p(tag.name, s["td"])

        rows.append([name_cell, _p(str(mc), s["td_right"]), _p(str(sc), s["td_right"])])

    headers = [_("name"), _("export_excel_usage_movements"), _("export_excel_usage_savings")]
    cw = [CONTENT_W * 0.50, CONTENT_W * 0.25, CONTENT_W * 0.25]
    el.append(_styled_table(headers, rows, cw, _WARNING))
    el.append(Spacer(1, 14))

    # Pie chart
    pie = _tag_pie_chart(session)
    if pie:
        el.append(_p(_("export_excel_tag_distribution"), s["subsection"]))
        el.append(Spacer(1, 4))
        el.append(pie)

    el.append(Spacer(1, 12))
    return el


# ---------------------------------------------------------------------------
# RECURRING
# ---------------------------------------------------------------------------

def _build_recurring(session: Session) -> list:
    s = _make_styles()
    el = _section_header(_("recurring"), _DANGER)

    sources_map = {src.id: src.name for src in session.exec(select(Source)).all()}
    items = session.exec(select(RecurringItem).order_by(RecurringItem.next_due_date)).all()

    if not items:
        el.append(_p(_("no_recurring"), s["body"]))
        return el

    ff = {"daily": 30, "weekly": 4.33, "monthly": 1, "yearly": 1 / 12}
    m_in = sum(it.amount * ff.get(it.frequency, 1) for it in items if it.direction == "in")
    m_out = sum(it.amount * ff.get(it.frequency, 1) for it in items if it.direction == "out")

    kpis = [
        (f"{_('export_excel_monthly_equiv')} ({_('income')})", _fmt(m_in), _SUCCESS_DARK),
        (f"{_('export_excel_monthly_equiv')} ({_('expense')})", _fmt(m_out), _DANGER),
        (f"Net / {_('monthly')}", _fmt(m_in - m_out), _DARK),
        (_("recurring"), str(len(items)), _PRIMARY),
    ]
    el.append(_kpi_row(kpis))
    el.append(Spacer(1, 12))

    rows = []
    for it in items:
        ds = s["td_income"] if it.direction == "in" else s["td_expense"]
        dl = _("income") if it.direction == "in" else _("expense")
        rows.append([
            _p(it.name, s["td"]),
            _p(_fmt(it.amount), ds),
            _p(dl, ds),
            _p(_(it.frequency), s["td"]),
            _p(sources_map.get(it.source_id, "—"), s["td"]),
            _p(str(it.next_due_date), s["td"]),
        ])

    headers = [_("name"), _("amount"), _("direction"), _("frequency"),
               _("source"), _("next_due_date")]
    cw = [CONTENT_W * w for w in (0.24, 0.14, 0.12, 0.14, 0.20, 0.16)]
    el.append(_styled_table(headers, rows, cw, _DANGER))
    el.append(Spacer(1, 12))
    return el


# ---------------------------------------------------------------------------
# SAVINGS
# ---------------------------------------------------------------------------

def _build_savings(session: Session) -> list:
    s = _make_styles()
    el = _section_header(_("savings"), colors.HexColor("#4CAF50"))

    savings = session.exec(select(Saving).order_by(Saving.date.desc())).all()
    total = sum(sv.amount for sv in savings)

    if not savings:
        el.append(_p(_("no_savings"), s["body"]))
        return el

    kpis = [
        (_("savings_total"), _fmt(total), _SUCCESS_DARK),
        (_("savings"), str(len(savings)), _PRIMARY),
    ]
    el.append(_kpi_row(kpis))
    el.append(Spacer(1, 12))

    chart = _savings_bar_chart(session)
    if chart:
        el.append(_p(_("savings_trend"), s["subsection"]))
        el.append(Spacer(1, 4))
        el.append(chart)
        el.append(Spacer(1, 12))

    tags_map = {t.id: t.name for t in session.exec(select(Tag)).all()}
    sav_tags: dict[int, list[str]] = {}
    for st in session.exec(select(SavingTag)).all():
        sav_tags.setdefault(st.saving_id, []).append(tags_map.get(st.tag_id, ""))

    display = savings[:30]
    rows = []
    for sv in display:
        tag_str = ", ".join(sav_tags.get(sv.id, []))
        rows.append([
            _p(str(sv.date), s["td"]),
            _p(_fmt(sv.amount), s["td_income"]),
            _p(sv.currency, s["td"]),
            _p(sv.description or "", s["td"]),
            _p(tag_str, s["body_small"]),
        ])

    headers = [_("date"), _("amount"), _("currency"), _("saving_description"), _("tags")]
    cw = [CONTENT_W * w for w in (0.15, 0.18, 0.12, 0.30, 0.25)]
    el.append(_styled_table(headers, rows, cw, colors.HexColor("#4CAF50")))

    if len(savings) > 30:
        el.append(Spacer(1, 4))
        el.append(_p(_("export_pdf_showing_of").replace("{n}", "30").replace(
            "{total}", str(len(savings))), s["body_small"]))

    el.append(Spacer(1, 12))
    return el


# ---------------------------------------------------------------------------
# WHIMS
# ---------------------------------------------------------------------------

def _build_whims(session: Session) -> list:
    s = _make_styles()
    el = _section_header(_("whims"), _WARNING)

    sources_map = {src.id: src.name for src in session.exec(select(Source)).all()}
    whims = session.exec(select(Whim).order_by(Whim.status, Whim.priority.desc())).all()

    if not whims:
        el.append(_p(_("no_whims"), s["body"]))
        return el

    pend_t = sum(w.amount for w in whims if w.status == "pending")
    purch_t = sum(w.amount for w in whims if w.status == "purchased")
    pend_c = sum(1 for w in whims if w.status == "pending")
    purch_c = sum(1 for w in whims if w.status == "purchased")

    kpis = [
        (f"{_('whim_pending')} ({pend_c})", _fmt(pend_t), _WARNING),
        (f"{_('whim_purchased')} ({purch_c})", _fmt(purch_t), _SUCCESS_DARK),
        (_("whims"), str(len(whims)), _PRIMARY),
    ]
    el.append(_kpi_row(kpis))
    el.append(Spacer(1, 12))

    sl = {"pending": _("whim_pending"), "purchased": _("whim_purchased"),
          "dismissed": _("whim_dismissed")}
    pl = {"low": _("priority_low"), "medium": _("priority_medium"),
          "high": _("priority_high")}

    rows = []
    for w in whims:
        if w.status == "purchased":
            as_ = s["td_income"]
            ss_ = s["td_income"]
        elif w.status == "pending":
            as_ = s["td_expense"]
            ss_ = ParagraphStyle("_ws", parent=s["td"], textColor=_WARNING,
                                 fontName="Helvetica-Bold")
        else:
            as_ = s["td_right"]
            ss_ = s["td"]

        rows.append([
            _p(w.name, s["td"]),
            _p(_fmt(w.amount, w.currency), as_),
            _p(pl.get(w.priority, w.priority), s["td"]),
            _p(sources_map.get(w.source_id, "—"), s["td"]),
            _p(sl.get(w.status, w.status), ss_),
        ])

    headers = [_("name"), _("amount"), _("whim_priority"), _("source"), _("export_excel_status")]
    cw = [CONTENT_W * w for w in (0.28, 0.20, 0.14, 0.20, 0.18)]
    el.append(_styled_table(headers, rows, cw, _WARNING))
    el.append(Spacer(1, 12))
    return el


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------

EXPORTABLE_SECTIONS = ["sources", "movements", "tags", "recurring", "savings", "whims"]

_BUILDERS = {
    "sources": _build_sources,
    "movements": _build_movements,
    "tags": _build_tags,
    "recurring": _build_recurring,
    "savings": _build_savings,
    "whims": _build_whims,
}


def export_pdf(session: Session, sections: list[str]) -> bytes:
    valid = [s for s in sections if s in _BUILDERS]
    if not valid:
        valid = list(_BUILDERS.keys())

    buf = io.BytesIO()

    doc = BaseDocTemplate(
        buf, pagesize=A4,
        leftMargin=MARGIN, rightMargin=MARGIN,
        topMargin=MARGIN + 8, bottomMargin=MARGIN,
        title="Yfine Financial Report", author="Yfine",
    )

    cover_frame = Frame(MARGIN, MARGIN, CONTENT_W, PAGE_H - 2 * MARGIN, id="cover")
    normal_frame = Frame(MARGIN, MARGIN + 8, CONTENT_W, PAGE_H - 2 * MARGIN - 16, id="normal")

    doc.addPageTemplates([
        PageTemplate(id="cover", frames=[cover_frame], onPage=_cover_page),
        PageTemplate(id="normal", frames=[normal_frame], onPage=_content_page),
    ])

    elements = []
    elements.extend(_build_cover(session, valid))
    elements.append(NextPageTemplate("normal"))

    # Each section starts on its own page
    for i, section in enumerate(valid):
        if i > 0:
            elements.append(PageBreak())
        elements.extend(_BUILDERS[section](session))

    doc.build(elements)
    return buf.getvalue()
