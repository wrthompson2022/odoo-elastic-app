#!/usr/bin/env python3
"""Generate the client-facing Elastic Odoo connector feature brief PDF."""

from __future__ import annotations

from pathlib import Path
from textwrap import shorten
from xml.sax.saxutils import escape

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_LEFT
from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import inch
from reportlab.platypus import (
    Flowable,
    KeepTogether,
    PageBreak,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)


ROOT = Path(__file__).resolve().parents[1]
SOURCE_MD = ROOT / "docs" / "elastic_connector_feature_brief.md"
OUTPUT_PDF = ROOT / "output" / "pdf" / "elastic_odoo_connector_feature_brief.pdf"
ICON = ROOT / "static" / "description" / "icon.png"

PAGE_WIDTH, PAGE_HEIGHT = letter
MARGIN_X = 0.58 * inch
MARGIN_TOP = 0.54 * inch
MARGIN_BOTTOM = 0.48 * inch
CONTENT_WIDTH = PAGE_WIDTH - (MARGIN_X * 2)

INK = colors.HexColor("#18212F")
SLATE = colors.HexColor("#4B5565")
MIST = colors.HexColor("#F3F6F8")
LINE = colors.HexColor("#D9E0E7")
TEAL = colors.HexColor("#007D8F")
TEAL_DARK = colors.HexColor("#045D6B")
CORAL = colors.HexColor("#E15D4F")
GOLD = colors.HexColor("#F5AE2E")
GREEN = colors.HexColor("#3F8F5C")
VIOLET = colors.HexColor("#6D5BD0")
BLUE = colors.HexColor("#2E79B9")


def parse_markdown(path: Path) -> dict[str, list[str]]:
    sections: dict[str, list[str]] = {}
    current = "Title"
    sections[current] = []
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line:
            continue
        if line.startswith("# "):
            sections["Title"] = [line[2:].strip()]
            current = "Title"
        elif line.startswith("## "):
            current = line[3:].strip()
            sections[current] = []
        else:
            sections.setdefault(current, []).append(line)
    return sections


def make_styles() -> dict[str, ParagraphStyle]:
    base = getSampleStyleSheet()
    return {
        "cover_title": ParagraphStyle(
            "cover_title",
            parent=base["Title"],
            fontName="Helvetica-Bold",
            fontSize=31,
            leading=36,
            textColor=colors.white,
            alignment=TA_LEFT,
            spaceAfter=12,
        ),
        "cover_subtitle": ParagraphStyle(
            "cover_subtitle",
            parent=base["BodyText"],
            fontName="Helvetica",
            fontSize=12.5,
            leading=18,
            textColor=colors.HexColor("#E9F7F8"),
        ),
        "h1": ParagraphStyle(
            "h1",
            parent=base["Heading1"],
            fontName="Helvetica-Bold",
            fontSize=20,
            leading=24,
            textColor=INK,
            spaceAfter=10,
        ),
        "h2": ParagraphStyle(
            "h2",
            parent=base["Heading2"],
            fontName="Helvetica-Bold",
            fontSize=13,
            leading=16,
            textColor=INK,
            spaceBefore=8,
            spaceAfter=6,
        ),
        "body": ParagraphStyle(
            "body",
            parent=base["BodyText"],
            fontName="Helvetica",
            fontSize=9.4,
            leading=13.2,
            textColor=SLATE,
            spaceAfter=6,
        ),
        "small": ParagraphStyle(
            "small",
            parent=base["BodyText"],
            fontName="Helvetica",
            fontSize=8.2,
            leading=11,
            textColor=SLATE,
        ),
        "label": ParagraphStyle(
            "label",
            parent=base["BodyText"],
            fontName="Helvetica-Bold",
            fontSize=8.2,
            leading=10,
            textColor=TEAL_DARK,
            alignment=TA_CENTER,
        ),
        "cover_label": ParagraphStyle(
            "cover_label",
            parent=base["BodyText"],
            fontName="Helvetica-Bold",
            fontSize=8.2,
            leading=10,
            textColor=colors.white,
            alignment=TA_CENTER,
        ),
        "tile_title": ParagraphStyle(
            "tile_title",
            parent=base["BodyText"],
            fontName="Helvetica-Bold",
            fontSize=10,
            leading=12,
            textColor=INK,
        ),
        "tile_body": ParagraphStyle(
            "tile_body",
            parent=base["BodyText"],
            fontName="Helvetica",
            fontSize=8.1,
            leading=10.6,
            textColor=SLATE,
        ),
        "table_head": ParagraphStyle(
            "table_head",
            parent=base["BodyText"],
            fontName="Helvetica-Bold",
            fontSize=7.8,
            leading=9.4,
            textColor=colors.white,
            alignment=TA_LEFT,
        ),
        "table_cell": ParagraphStyle(
            "table_cell",
            parent=base["BodyText"],
            fontName="Helvetica",
            fontSize=7.5,
            leading=9.2,
            textColor=INK,
        ),
    }


STYLES = make_styles()


def p(text: str, style: str = "body", trusted: bool = False) -> Paragraph:
    return Paragraph(text if trusted else escape(text), STYLES[style])


def bullets(items: list[str], style: str = "body") -> list[Paragraph]:
    paragraphs = []
    for item in items:
        clean = item[2:] if item.startswith("- ") else item
        paragraphs.append(p(f"&#8226; {escape(clean)}", style, trusted=True))
    return paragraphs


class SectionBand(Flowable):
    def __init__(self, title: str, kicker: str, accent: colors.Color = TEAL):
        super().__init__()
        self.title = title
        self.kicker = kicker
        self.accent = accent
        self.width = CONTENT_WIDTH
        self.height = 0.52 * inch

    def draw(self) -> None:
        c = self.canv
        c.saveState()
        c.setFillColor(self.accent)
        c.roundRect(0, 0, self.width, self.height, 8, fill=1, stroke=0)
        c.setFillColor(colors.white)
        c.setFont("Helvetica-Bold", 13)
        c.drawString(0.22 * inch, 0.29 * inch, self.title)
        c.setFont("Helvetica", 8.2)
        c.drawString(0.22 * inch, 0.13 * inch, self.kicker)
        c.setFillColor(colors.Color(1, 1, 1, alpha=0.18))
        for idx in range(5):
            x = self.width - 1.2 * inch + idx * 0.24 * inch
            c.circle(x, 0.26 * inch, 0.08 * inch + idx * 0.01 * inch, fill=1, stroke=0)
        c.restoreState()


class ConnectorFlow(Flowable):
    def __init__(self):
        super().__init__()
        self.width = CONTENT_WIDTH
        self.height = 1.55 * inch

    def draw(self) -> None:
        c = self.canv
        c.saveState()
        y = 0.45 * inch
        box_w = 1.25 * inch
        box_h = 0.58 * inch
        gap = (self.width - box_w * 5) / 4
        labels = [
            ("Odoo", "system of record"),
            ("Connector", "map and stage"),
            ("SFTP", "secure exchange"),
            ("Elastic B2B", "commerce portal"),
            ("Orders", "return to Odoo"),
        ]
        fills = [TEAL, BLUE, GOLD, VIOLET, GREEN]
        for idx, (title, sub) in enumerate(labels):
            x = idx * (box_w + gap)
            c.setFillColor(fills[idx])
            c.roundRect(x, y, box_w, box_h, 8, fill=1, stroke=0)
            c.setFillColor(colors.white)
            c.setFont("Helvetica-Bold", 9)
            c.drawCentredString(x + box_w / 2, y + 0.35 * inch, title)
            c.setFont("Helvetica", 6.8)
            c.drawCentredString(x + box_w / 2, y + 0.2 * inch, sub)
            if idx < len(labels) - 1:
                x1 = x + box_w + 0.04 * inch
                x2 = x + box_w + gap - 0.04 * inch
                c.setStrokeColor(LINE)
                c.setLineWidth(2)
                c.line(x1, y + box_h / 2, x2, y + box_h / 2)
                c.setFillColor(LINE)
                c.line(x2 - 5, y + box_h / 2 + 4, x2, y + box_h / 2)
                c.line(x2 - 5, y + box_h / 2 - 4, x2, y + box_h / 2)
        c.setFillColor(INK)
        c.setFont("Helvetica-Bold", 10)
        c.drawString(0, 1.25 * inch, "How data moves")
        c.setFont("Helvetica", 8)
        c.setFillColor(SLATE)
        c.drawString(0, 1.1 * inch, "Outbound feeds keep Elastic aligned; inbound orders are staged, validated, and created in Odoo.")
        c.restoreState()


class MetricsStrip(Flowable):
    def __init__(self):
        super().__init__()
        self.width = CONTENT_WIDTH
        self.height = 0.9 * inch

    def draw(self) -> None:
        c = self.canv
        c.saveState()
        stats = [
            ("12", "outbound feed types", TEAL),
            ("2", "environment profiles", BLUE),
            ("1", "inbound order pipeline", GREEN),
            ("0", "blind imports", CORAL),
        ]
        col_w = self.width / 4
        for idx, (num, label, accent) in enumerate(stats):
            x = idx * col_w
            c.setFillColor(MIST)
            c.roundRect(x, 0.05 * inch, col_w - 0.08 * inch, 0.72 * inch, 8, fill=1, stroke=0)
            c.setFillColor(accent)
            c.setFont("Helvetica-Bold", 21)
            c.drawCentredString(x + (col_w - 0.08 * inch) / 2, 0.43 * inch, num)
            c.setFillColor(SLATE)
            c.setFont("Helvetica", 7.4)
            c.drawCentredString(x + (col_w - 0.08 * inch) / 2, 0.22 * inch, label)
        c.restoreState()


class CardGrid(Flowable):
    def __init__(self, cards: list[tuple[str, str, colors.Color]], columns: int = 2):
        super().__init__()
        self.cards = cards
        self.columns = columns
        self.width = CONTENT_WIDTH
        self.card_h = 0.74 * inch
        self.row_gap = 0.11 * inch
        self.height = ((len(cards) + columns - 1) // columns) * (self.card_h + self.row_gap)

    def draw(self) -> None:
        c = self.canv
        c.saveState()
        gap = 0.12 * inch
        card_w = (self.width - gap * (self.columns - 1)) / self.columns
        for idx, (title, body, accent) in enumerate(self.cards):
            row = idx // self.columns
            col = idx % self.columns
            x = col * (card_w + gap)
            y = self.height - (row + 1) * (self.card_h + self.row_gap) + self.row_gap
            c.setFillColor(colors.white)
            c.setStrokeColor(LINE)
            c.roundRect(x, y, card_w, self.card_h, 7, fill=1, stroke=1)
            c.setFillColor(accent)
            c.roundRect(x, y, 0.09 * inch, self.card_h, 7, fill=1, stroke=0)
            title_p = p(title, "tile_title")
            body_p = p(body, "tile_body")
            title_p.wrapOn(c, card_w - 0.28 * inch, 0.2 * inch)
            title_p.drawOn(c, x + 0.18 * inch, y + self.card_h - 0.27 * inch)
            body_p.wrapOn(c, card_w - 0.28 * inch, 0.35 * inch)
            body_p.drawOn(c, x + 0.18 * inch, y + 0.14 * inch)
        c.restoreState()


class CoverArt(Flowable):
    def __init__(self):
        super().__init__()
        self.width = PAGE_WIDTH
        self.height = PAGE_HEIGHT

    def wrap(self, availWidth, availHeight):
        return 0, 0

    def draw(self) -> None:
        pass


def draw_page_background(canvas, doc) -> None:
    page = canvas.getPageNumber()
    canvas.saveState()
    if page == 1:
        canvas.setFillColor(INK)
        canvas.rect(0, 0, PAGE_WIDTH, PAGE_HEIGHT, fill=1, stroke=0)
        bands = [(TEAL, 6.95), (BLUE, 6.52), (GREEN, 6.09), (GOLD, 5.66), (CORAL, 5.23)]
        for color, y in bands:
            canvas.setFillColor(color)
            canvas.rect(0, y * inch, PAGE_WIDTH, 0.23 * inch, fill=1, stroke=0)
        canvas.setFillColor(colors.Color(1, 1, 1, alpha=0.07))
        for idx in range(12):
            canvas.circle(5.3 * inch + idx * 0.2 * inch, 1.3 * inch + idx * 0.27 * inch, 0.38 * inch, fill=1, stroke=0)
    else:
        canvas.setFillColor(colors.white)
        canvas.rect(0, 0, PAGE_WIDTH, PAGE_HEIGHT, fill=1, stroke=0)
        canvas.setFillColor(MIST)
        canvas.rect(0, PAGE_HEIGHT - 0.27 * inch, PAGE_WIDTH, 0.27 * inch, fill=1, stroke=0)
        canvas.setFillColor(TEAL)
        canvas.rect(0, PAGE_HEIGHT - 0.27 * inch, 1.75 * inch, 0.27 * inch, fill=1, stroke=0)
        canvas.setFont("Helvetica-Bold", 7.2)
        canvas.setFillColor(colors.white)
        canvas.drawString(0.28 * inch, PAGE_HEIGHT - 0.18 * inch, "Elastic Odoo Connector")
        canvas.setFillColor(SLATE)
        canvas.setFont("Helvetica", 7.2)
        canvas.drawRightString(PAGE_WIDTH - 0.46 * inch, 0.28 * inch, f"Page {page}")
        canvas.setStrokeColor(LINE)
        canvas.line(MARGIN_X, 0.42 * inch, PAGE_WIDTH - MARGIN_X, 0.42 * inch)
    canvas.restoreState()


def cover_story(sections: dict[str, list[str]]) -> list:
    positioning = " ".join(sections.get("Positioning", []))
    subtitle = shorten(positioning, width=289, placeholder="").rstrip(".") + "."
    return [
        Spacer(1, 4.05 * inch),
        p("Elastic Odoo Connector", "cover_title"),
        Paragraph(
            subtitle,
            STYLES["cover_subtitle"],
        ),
        Spacer(1, 0.24 * inch),
        Table(
            [[p("Secure SFTP", "cover_label"), p("B2B Data Feeds", "cover_label"), p("Order Import", "cover_label")]],
            colWidths=[1.18 * inch, 1.32 * inch, 1.18 * inch],
            style=TableStyle(
                [
                    ("BACKGROUND", (0, 0), (-1, -1), colors.Color(1, 1, 1, alpha=0.14)),
                    ("BOX", (0, 0), (-1, -1), 0.5, colors.Color(1, 1, 1, alpha=0.28)),
                    ("INNERGRID", (0, 0), (-1, -1), 0.5, colors.Color(1, 1, 1, alpha=0.18)),
                    ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                    ("LEFTPADDING", (0, 0), (-1, -1), 9),
                    ("RIGHTPADDING", (0, 0), (-1, -1), 9),
                    ("TOPPADDING", (0, 0), (-1, -1), 8),
                    ("BOTTOMPADDING", (0, 0), (-1, -1), 8),
                ]
            ),
        ),
    ]


def feed_table() -> Table:
    rows = [
        ["Feed", "File", "Business purpose"],
        ["Products", "products.csv", "Item, SKU, UPC, color, size, permission, availability"],
        ["Customers", "customers.csv", "Sold-To accounts, catalog groups, price level, address"],
        ["Pricing", "prices.csv", "Pricelist-driven price groups and retail/list fallback"],
        ["Inventory", "inventory.csv", "Warehouse ATP and future availability snapshots"],
        ["Catalogs", "catalogs.csv", "Catalog definitions, dates, permissions, brand, season"],
        ["Mappings", "catalog_mapping.csv", "Catalog item/color placement rows"],
        ["Features", "features.csv", "Governed product feature and technology values"],
        ["Tags", "product_tags.csv", "Merchandising tags from Odoo sources"],
        ["Reps", "reps.csv / rep_mappings.csv", "Sales reps and customer-rep assignments"],
        ["Locations", "locations.csv", "Warehouse/location availability targets"],
    ]
    table_data = [[p(cell, "table_head" if idx == 0 else "table_cell") for cell in row] for idx, row in enumerate(rows)]
    table = Table(table_data, colWidths=[1.12 * inch, 1.42 * inch, CONTENT_WIDTH - 2.54 * inch])
    table.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, 0), TEAL_DARK),
                ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
                ("BACKGROUND", (0, 1), (-1, -1), colors.white),
                ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#F8FAFB")]),
                ("GRID", (0, 0), (-1, -1), 0.35, LINE),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("LEFTPADDING", (0, 0), (-1, -1), 6),
                ("RIGHTPADDING", (0, 0), (-1, -1), 6),
                ("TOPPADDING", (0, 0), (-1, -1), 5),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
            ]
        )
    )
    return table


def build_story(sections: dict[str, list[str]]) -> list:
    story: list = []
    story.extend(cover_story(sections))
    story.append(PageBreak())

    core_value = [item for item in sections.get("Core Value", []) if item.startswith("- ")]
    story.append(SectionBand("Connector Overview", "A client-safe summary of what the Odoo connector handles.", TEAL))
    story.append(Spacer(1, 0.16 * inch))
    story.append(p("The connector keeps Elastic B2B aligned with Odoo while preserving operational control inside Odoo.", "h1"))
    story.extend(bullets(core_value[:5], "body"))
    story.append(Spacer(1, 0.08 * inch))
    story.append(MetricsStrip())
    story.append(Spacer(1, 0.08 * inch))
    story.append(ConnectorFlow())
    story.append(PageBreak())

    cards = [
        ("Product and catalog data", "Products, variants, colors, sizes, catalog definitions, catalog mappings, and merchandising tags.", TEAL),
        ("Customer access", "Sold-To/Ship-To IDs, legacy account support, customer catalogs, price levels, and cross-reference matching.", BLUE),
        ("Pricing", "Variant-aware pricelist exports with Elastic price-group codes and list-price fallback.", GOLD),
        ("Inventory ATP", "Time-phased availability by warehouse with optional quotation demand and BOM component fallback.", GREEN),
        ("Order import", "SFTP polling, row grouping, staging, duplicate detection, sale-order creation, and retry.", CORAL),
        ("Operator controls", "Manual feed buttons, inactive cron hooks, logs, environment switching, and host-key verification.", VIOLET),
    ]
    story.append(SectionBand("Feature Highlights", "The capabilities Elastic can describe to prospective clients.", BLUE))
    story.append(Spacer(1, 0.16 * inch))
    story.append(CardGrid(cards, columns=2))
    story.append(Spacer(1, 0.16 * inch))
    story.append(p("Outbound feeds", "h2"))
    story.append(feed_table())
    story.append(PageBreak())

    story.append(SectionBand("Operational Model", "How teams run, observe, and troubleshoot the connector.", GREEN))
    story.append(Spacer(1, 0.16 * inch))
    ops_cards = [
        ("Beta and Production", "Separate SFTP profiles allow test validation before production cutover.", TEAL),
        ("Secure exchange", "Password or SSH key auth with stored host-key verification and fingerprint capture.", BLUE),
        ("Configurable files", "Delimiter, encoding, header row behavior, date formats, and per-feed toggles.", GOLD),
        ("Traceable runs", "Export and import logs capture state, filename, record counts, and error messages.", GREEN),
        ("Staged imports", "Incoming orders are captured as staged records before sale-order creation.", CORAL),
        ("Retry workflow", "Failed staged orders can be reviewed and retried after data correction.", VIOLET),
    ]
    story.append(CardGrid(ops_cards, columns=2))
    story.append(Spacer(1, 0.16 * inch))
    story.append(p("Implementation checkpoints", "h2"))
    notes = [item for item in sections.get("Implementation Notes", []) if item.startswith("- ")]
    story.extend(bullets(notes[:7], "body"))
    story.append(PageBreak())

    story.append(SectionBand("Technical Appendix", "Concise implementation facts for technical reviewers.", CORAL))
    story.append(Spacer(1, 0.16 * inch))
    appendix_rows = [
        ["Area", "Included behavior"],
        ["Platform", "Odoo 18.0 addon maintained by P2 Business Solutions."],
        ["Transport", "SFTP flat-file exchange with Beta/Sandbox and Production connection profiles."],
        ["Security", "Password or SSH key authentication; stored host-key verification available."],
        ["Exports", "Products, tags, features, customers, custom fields, locations, prices, inventory, catalogs, mappings, reps."],
        ["Imports", "Elastic order files staged by order/shipment, validated, deduplicated, and converted to Odoo sale orders."],
        ["Governance", "Product IDs, StockItemKey, colors, sizes, features, catalogs, price groups, and customer xrefs."],
        ["Automation", "Manual actions plus inactive scheduled actions for import orders and export all enabled."],
        ["Observability", "Export/import logs plus order staging states for processed, duplicate, and error records."],
    ]
    table_data = [[p(cell, "table_head" if row_idx == 0 else "table_cell") for cell in row] for row_idx, row in enumerate(appendix_rows)]
    table = Table(table_data, colWidths=[1.32 * inch, CONTENT_WIDTH - 1.32 * inch])
    table.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, 0), INK),
                ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#F8FAFB")]),
                ("GRID", (0, 0), (-1, -1), 0.35, LINE),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("LEFTPADDING", (0, 0), (-1, -1), 7),
                ("RIGHTPADDING", (0, 0), (-1, -1), 7),
                ("TOPPADDING", (0, 0), (-1, -1), 6),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
            ]
        )
    )
    story.append(table)
    story.append(Spacer(1, 0.2 * inch))
    story.append(
        KeepTogether(
            [
                p("Recommended client validation", "h2"),
                p(
                    "Before production use, confirm identifiers, customer matching, price groups, warehouse codes, "
                    "catalog permissions, taxonomies, order matching rules, and auto-confirmation policy.",
                    "body",
                ),
            ]
        )
    )
    return story


def main() -> None:
    if not SOURCE_MD.exists():
        raise SystemExit(f"Missing source file: {SOURCE_MD}")
    OUTPUT_PDF.parent.mkdir(parents=True, exist_ok=True)
    sections = parse_markdown(SOURCE_MD)
    doc = SimpleDocTemplate(
        str(OUTPUT_PDF),
        pagesize=letter,
        rightMargin=MARGIN_X,
        leftMargin=MARGIN_X,
        topMargin=MARGIN_TOP,
        bottomMargin=MARGIN_BOTTOM,
        title="Elastic Odoo Connector Feature Brief",
        author="P2 Business Solutions",
    )
    doc.build(build_story(sections), onFirstPage=draw_page_background, onLaterPages=draw_page_background)
    print(OUTPUT_PDF)


if __name__ == "__main__":
    main()
