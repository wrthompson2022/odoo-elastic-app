#!/usr/bin/env python3
"""Build the four-page client brief from its editable Markdown source.

Requires reportlab. Embeds local Arial when available, with PDF standard
fonts as a portable fallback. All graphics are original vectors.
"""
from pathlib import Path
from datetime import date, timedelta
from runpy import run_path
from xml.sax.saxutils import escape

from reportlab.lib import colors
from reportlab.lib.styles import ParagraphStyle
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfgen import canvas
from reportlab.platypus import Paragraph
from reportlab.graphics.charts.lineplots import LinePlot
from reportlab.graphics.shapes import Drawing, Line, Rect, String
from reportlab.graphics import renderPDF

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / 'docs/elastic_connector_feature_brief.md'
OUTPUT = ROOT / 'output/pdf/elastic_odoo_connector_feature_brief.pdf'
W, H = 612, 792
INK, BODY, TEAL = '#152329', '#43545A', '#00776F'
MINT, CORAL, PAPER = '#85DDC7', '#EF927D', '#FAFAF6'
LINE, PALE, WHITE = '#D8E1DC', '#E9F2ED', '#FFFFFF'


def register_fonts():
    font_dir = Path('/System/Library/Fonts/Supplemental')
    if (font_dir / 'Arial.ttf').exists():
        pdfmetrics.registerFont(TTFont('Brief', str(font_dir / 'Arial.ttf')))
        pdfmetrics.registerFont(TTFont('BriefBold', str(font_dir / 'Arial Bold.ttf')))
        return 'Brief', 'BriefBold'
    return 'Helvetica', 'Helvetica-Bold'


REG, BOLD = register_fonts()


def read_copy():
    sections, key = {}, None
    for line in SOURCE.read_text(encoding='utf-8').splitlines():
        if line.startswith('## '):
            key = line[3:]
            sections[key] = []
        elif key and line.strip():
            sections[key].append(line.strip())
    return {key: ' '.join(lines) for key, lines in sections.items()}


COPY = read_copy()


def box(c, x, top, width, height, fill, radius=0):
    c.setFillColor(colors.HexColor(fill))
    if radius:
        c.roundRect(x, H-top-height, width, height, radius, fill=1, stroke=0)
    else:
        c.rect(x, H-top-height, width, height, fill=1, stroke=0)


def line(c, x1, y1, x2, y2, color=LINE, width=1):
    c.setStrokeColor(colors.HexColor(color))
    c.setLineWidth(width)
    c.line(x1, H-y1, x2, H-y2)


def label(c, text, x, top, size=8.5, color=TEAL, bold=True, spacing=1):
    c.saveState()
    c.setFillColor(colors.HexColor(color))
    t = c.beginText(x, H-top-size)
    t.setFont(BOLD if bold else REG, size)
    t.setCharSpace(spacing)
    t.textOut(text)
    c.drawText(t)
    c.restoreState()


def para(c, text, x, top, width, size=10.5, leading=15, color=BODY,
         bold=False, max_height=None):
    style = ParagraphStyle('copy', fontName=BOLD if bold else REG,
                           fontSize=size, leading=leading,
                           textColor=colors.HexColor(color))
    p = Paragraph(escape(text).replace('\n', '<br/>'), style)
    _, height = p.wrap(width, H)
    if max_height is not None and height > max_height + .1:
        raise ValueError(f'Copy overflows ({height} > {max_height}): {text[:70]}')
    if top + height > 740:
        raise ValueError(f'Copy crosses footer: {text[:70]}')
    p.drawOn(c, x, H-top-height)
    return height


def heading(c, text, x, top, width=524, size=30, leading=34):
    return para(c, text, x, top, width, size, leading, '#000000', True)


def base(c, page, section):
    box(c, 0, 0, W, H, PAPER)
    label(c, 'ELASTIC / ODOO', 44, 30, 9, INK, spacing=1.3)
    label(c, section, 354, 31, 8, BODY, spacing=1.1)
    line(c, 44, 747, 568, 747)
    label(c, 'P2 BUSINESS SOLUTIONS', 44, 759, 7, BODY, spacing=.8)
    label(c, 'ODOO 18.0  /  SEPTEMBER 2026', 237, 759, 7, BODY, False, .4)
    label(c, f'0{page} / 04', 530, 758, 8, TEAL, spacing=.3)


def arrow(c, x1, x2, top, color):
    line(c, x1, top, x2, top, color, 2)
    direction = 1 if x2 > x1 else -1
    line(c, x2-5*direction, top-4, x2, top, color, 2)
    line(c, x2-5*direction, top+4, x2, top, color, 2)


def source_link(c, text, url, x, top):
    """Small, clickable primary-source reference beside the supported content."""
    label(c, text, x, top, 7, TEAL, bold=False, spacing=0)
    width = pdfmetrics.stringWidth(text, REG, 7)
    c.linkURL(url, (x, H-top-10, x+width, H-top+1), relative=0)


def icon(c, kind, x, top, color=TEAL):
    """Consistent line icons with no external asset dependencies."""
    c.saveState()
    c.translate(x, H-top-26)
    c.setStrokeColor(colors.HexColor(color))
    c.setFillColor(colors.HexColor(color))
    c.setLineWidth(1.4)
    c.setLineCap(1)
    c.setLineJoin(1)
    if kind == 'product':
        p = c.beginPath()
        for i, (a,b) in enumerate([(2,19),(13,25),(24,19),(24,7),(13,1),(2,7),(2,19),(13,13),(24,19)]):
            (p.moveTo if i == 0 else p.lineTo)(a,b)
        c.drawPath(p)
        c.line(13,13,13,1)
        c.line(7,22,19,16)
    elif kind == 'catalog':
        for a in [2,15]:
            for b in [2,15]:
                c.roundRect(a,b,9,9,1.5,fill=0,stroke=1)
    elif kind == 'price':
        p = c.beginPath()
        p.moveTo(2,24)
        for a,b in [(13,24),(25,12),(13,0),(2,11),(2,24)]:
            p.lineTo(a,b)
        c.drawPath(p)
        c.circle(8,18,2,fill=0,stroke=1)
        c.line(12,8,18,14)
    elif kind == 'people':
        c.circle(9,19,4,fill=0,stroke=1)
        c.circle(21,17,3,fill=0,stroke=1)
        p = c.beginPath()
        p.moveTo(1,2)
        p.curveTo(1,15,17,15,17,2)
        c.drawPath(p)
        p=c.beginPath()
        p.moveTo(18,10)
        p.curveTo(25,12,26,6,25,2)
        c.drawPath(p)
    elif kind == 'inventory':
        c.line(2,2,2,24)
        c.line(2,2,25,2)
        p=c.beginPath()
        p.moveTo(5,7)
        for a,b in [(11,7),(11,14),(18,14),(18,22),(25,22)]:
            p.lineTo(a,b)
        c.drawPath(p)
    elif kind == 'control':
        for a,b in [(5,18),(13,8),(22,15)]:
            c.line(a,2,a,b-3)
            c.line(a,b+3,a,25)
            c.circle(a,b,3,fill=0,stroke=1)
    elif kind == 'whiteboard':
        c.roundRect(1,6,24,18,2,fill=0,stroke=1)
        c.line(8,1,13,6)
        c.line(18,1,13,6)
        c.rect(5,10,6,9,fill=0,stroke=1)
        c.rect(15,13,6,6,fill=0,stroke=1)
    elif kind == 'campaign':
        p=c.beginPath()
        p.moveTo(2,15)
        for a,b in [(9,15),(22,23),(22,3),(9,10),(2,10),(2,15)]:
            p.lineTo(a,b)
        c.drawPath(p)
        c.line(7,10,10,2)
        c.line(10,2,14,2)
    elif kind == 'metadata':
        c.roundRect(7,1,17,24,2,fill=0,stroke=1)
        c.line(12,19,20,19)
        c.line(12,14,20,14)
        c.line(12,9,20,9)
        c.line(0,13,9,13)
        c.line(5,17,9,13)
        c.line(5,9,9,13)
    c.restoreState()


def page_one(c):
    base(c, 1, 'CONNECTOR FEATURE BRIEF')
    heading(c, 'Elastic Odoo\nConnector', 44, 85, size=44, leading=47)
    para(c, COPY['Introduction'], 44, 199, 475, 11.5, 17, max_height=68)
    for x, title in [(44, 'Availability that reflects demand'), (320, 'Merchandising built for Elastic')]:
        heading(c, title, x, 289, 248, 13.7, 18)
        para(c, COPY[title], x, 318, 248, 10, 14, max_height=56)
    box(c, 44, 386, 524, 194, INK, 13)
    label(c, 'ONE CONNECTED WHOLESALE WORKFLOW', 64, 405, 8.2, MINT)
    box(c, 64, 444, 100, 76, '#293C40', 7)
    box(c, 448, 444, 100, 76, '#293C40', 7)
    para(c, 'Odoo', 79, 461, 78, 20, 24, WHITE, True)
    para(c, 'Operations', 79, 493, 78, 8.5, 11, '#CEDED9')
    para(c, 'Elastic Suite', 458, 462, 88, 13.4, 21, WHITE, True)
    para(c, 'Selling experience', 458, 493, 88, 8.1, 11, '#CEDED9')
    para(c, 'Commerce data and order history', 187, 435, 238, 9, 13, MINT)
    arrow(c, 183, 427, 459, MINT)
    para(c, 'Odoo connector / secure SFTP', 232, 474, 195, 9, 13, WHITE)
    arrow(c, 427, 183, 505, CORAL)
    para(c, 'Elastic orders', 273, 517, 130, 9, 13, CORAL)
    para(c, 'Scheduled file exchange with manual run controls in Odoo.',
         64, 551, 484, 8.4, 12, '#CEDED9')
    heading(c, 'A seasonal dealer order', 44, 605, size=17, leading=22)
    for i, title in enumerate(['Curate', 'Order', 'Fulfill']):
        x = 44 + i*181
        label(c, f'0{i+1}', x, 643, 10, TEAL, spacing=.2)
        heading(c, title, x+25, 640, 138, 12, 16)
        para(c, COPY[title], x, 666, 161, 9, 12.5, max_height=62.5)
    source_link(c, 'Elastic integration approach', 'https://www.elasticsuite.com/integrations/', 44, 733)
    c.showPage()


def ats_chart():
    """Chart the actual export calculation against its projected-stock balances."""
    drawing = Drawing(524, 220)
    chart = LinePlot()
    chart.x, chart.y, chart.width, chart.height = 38, 29, 470, 146
    calculate = run_path(str(ROOT / 'services/inventory_availability.py'))['availability_timeline']
    today = date(2026, 9, 10)
    values = calculate(20, {today + timedelta(days=d): q for d, q in
                           [(3, -30), (7, 40), (10, -12)]}, today)
    chart.data = []
    for column in (1, 2):
        points = [(0, values[0][column])]
        for event_date, *quantities in values[1:]:
            elapsed = (event_date - today).days
            points.extend([(elapsed, points[-1][1]), (elapsed, quantities[column - 1])])
        points.append((14, points[-1][1]))
        chart.data.append(points)
    chart.lines[0].strokeColor = colors.HexColor('#B55A46')
    chart.lines[0].strokeWidth = 1.6
    chart.lines[0].strokeDashArray = [4,3]
    chart.lines[1].strokeColor = colors.HexColor(TEAL)
    chart.lines[1].strokeWidth = 2.5
    for axis in (chart.xValueAxis, chart.yValueAxis):
        axis.labels.fontName = REG
        axis.labels.fontSize = 8
        axis.labels.fillColor = colors.HexColor(BODY)
        axis.strokeColor = colors.HexColor(LINE)
        axis.strokeWidth = .6
    chart.xValueAxis.valueMin, chart.xValueAxis.valueMax = 0, 14
    chart.xValueAxis.valueSteps = [0,3,7,10,14]
    chart.xValueAxis.labelTextFormat = lambda v: 'Today' if v == 0 else f'Day {v:g}'
    chart.xValueAxis.labels.dy = -4
    chart.yValueAxis.valueMin, chart.yValueAxis.valueMax = -20, 50
    chart.yValueAxis.valueSteps = [-20,-10,0,10,20,30,40,50]
    chart.yValueAxis.visibleGrid = True
    chart.yValueAxis.gridStrokeColor = colors.HexColor('#DEE6E1')
    chart.yValueAxis.gridStrokeWidth = .5
    chart.yValueAxis.labels.dx = -5
    px = lambda day: chart.x + day / 14 * chart.width
    py = lambda qty: chart.y + (qty+20) / 70 * chart.height
    drawing.add(Rect(chart.x,chart.y,chart.width,py(0)-chart.y,
                     fillColor=colors.HexColor('#F9EBE5'),strokeColor=None))
    drawing.add(chart)
    drawing.add(Line(chart.x,py(0),chart.x+chart.width,py(0),
                     strokeColor=colors.HexColor('#98AAA1'),strokeWidth=.6))
    # Distinguish projected stock from the smaller quantity safe to offer.
    for x, color, title, dashed in [
        (38,TEAL,'ATS published to Elastic',False),
        (258,'#B55A46','Projected stock balance',True),
    ]:
        drawing.add(Line(x,207,x+22,207,strokeColor=colors.HexColor(color),
                         strokeWidth=2,strokeDashArray=[4,3] if dashed else None))
        drawing.add(String(x+29,203,title,fontName=REG,fontSize=8.5,fillColor=colors.HexColor(BODY)))
    drawing.add(String(2,185,'Units',fontName=REG,fontSize=8,fillColor=colors.HexColor(BODY)))
    for day, title in [(3,'Demand 30'),(7,'Receipt 40'),(10,'Demand 12')]:
        drawing.add(String(px(day),185,title,textAnchor='middle',fontName=BOLD,fontSize=8,
                           fillColor=colors.HexColor(INK)))
    for day, qty, title in [(3.5,0,'0 ATS'),(9,18,'18 ATS')]:
        drawing.add(String(px(day),py(qty)+7,title,textAnchor='middle',fontName=BOLD,fontSize=9,
                           fillColor=colors.HexColor(TEAL)))
    for day, qty, title in [(1,20,'20 on hand'),(8.2,30,'30 projected')]:
        drawing.add(String(px(day),py(qty)+7,title,textAnchor='middle',fontName=REG,fontSize=8,
                           fillColor=colors.HexColor('#9C4E3C')))
    drawing.add(String(px(5),py(-10)-12,'10-unit shortage',textAnchor='middle',
                       fontName=REG,fontSize=8,fillColor=colors.HexColor('#9C4E3C')))
    return drawing


def availability_page(c):
    base(c, 2, 'AVAILABILITY INTELLIGENCE')
    heading(c, 'Availability designed\nfor wholesale selling', 44, 86, size=32, leading=38)
    para(c, COPY['Availability introduction'], 44, 180, 500, 11, 16, max_height=64)
    heading(c, 'Time-phased ATS', 44, 233, size=19, leading=24)
    para(c, COPY['Time-phased ATS'], 44, 267, 520, 10.5, 15, max_height=45)
    renderPDF.draw(ats_chart(), c, 44, H-320-220)
    para(c, COPY['ATS example explanation'], 44, 550, 524, 9.5, 13.5, max_height=27)
    heading(c, 'BOM-based availability', 44, 590, 250, 14, 19)
    para(c, COPY['BOM-based availability'], 44, 619, 246, 9.4, 13.3, max_height=87)
    heading(c, 'Fit your stock policy', 320, 590, 248, 14, 19)
    para(c, COPY['Inventory policy controls'], 320, 619, 248, 9.4, 13.3, max_height=80)
    para(c, COPY['Inventory scope'], 44, 716, 524, 7.9, 10.5, max_height=24)
    c.showPage()


def page_two(c):
    base(c, 3, 'MERCHANDISING CONTROLS')
    heading(c, 'Odoo customizations\nfor effective selling', 44, 86, size=33, leading=38)
    para(c, COPY['Commerce introduction'], 44, 180, 480, 11, 16, max_height=48)
    features = [
        ('Shopify product enrichment', 'metadata'),
        ('Merchandising by variant', 'product'),
        ('Catalogs that stay aligned', 'catalog'),
        ('Dealer pricing from Odoo', 'price'),
        ('Account and rep continuity', 'people'),
        ('Controlled publishing', 'control'),
    ]
    for i, (title, kind) in enumerate(features):
        x = 44 + (i % 2) * 276
        top = 238 + (i // 2) * 142
        icon(c, kind, x, top)
        heading(c, title, x+37, top+4, 212, 13.2, 17)
        h = para(c, COPY[title], x, top+38, 246, 10, 14, INK, max_height=42)
        para(c, COPY[title+' connection'], x, top+38+h+6, 246, 9.6, 13.5,
             max_height=140-38-h-6)
    box(c, 44, 681, 524, 43, PALE, 6)
    para(c, COPY['Content workflows'], 57, 689, 498, 8.6, 12, max_height=36)
    source_link(c, 'Elastic Platform', 'https://www.elasticsuite.com/platform/', 44, 733)
    source_link(c, 'Elastic Suite capabilities', 'https://www.elasticsuite.com/', 145, 733)
    source_link(c, 'Retailer ordering', 'https://www.elasticsuite.com/retailer-resources/', 292, 733)
    c.showPage()


def page_three(c):
    base(c, 4, 'ORDERS AND OPERATIONS')
    heading(c, 'Elastic orders\nconnected to Odoo', 44, 83, size=31, leading=36)
    for x, kicker, title, body, note, accent in [
        (44, 'ELASTIC TO ODOO', 'From buying to fulfillment', 'Order intake', 'Order recovery', TEAL),
        (320, 'ODOO TO ELASTIC', 'Order history and tracking', 'Order history', 'History validation', '#AD5945'),
    ]:
        label(c, kicker, x, 179, 7.4, accent, spacing=.8)
        heading(c, title, x, 202, 248, 14.1, 19)
        h = para(c, COPY[body], x, 234, 245, 10, 14, max_height=98)
        para(c, COPY[note], x, 234+h+11, 245, 9.5, 13.5, max_height=81)
    line(c, 44, 402, 568, 402)
    heading(c, 'Daily operation in Odoo', 44, 420, size=18, leading=23)
    heading(c, 'Secure connections', 44, 457, 247, 12, 16)
    para(c, COPY['Secure connections'], 44, 481, 245, 9.5, 13.5, max_height=68)
    heading(c, 'Scheduling and visibility', 320, 457, 248, 12, 16)
    para(c, COPY['Scheduling and visibility'], 320, 481, 248, 9.5, 13.5, max_height=68)
    heading(c, 'Plan your rollout', 44, 555, size=18, leading=23)
    for i, title in enumerate(['Align', 'Validate', 'Activate']):
        x = 44 + i*181
        label(c, f'0{i+1}', x, 590, 11, TEAL, spacing=.2)
        heading(c, title, x+25, 588, 138, 12, 16)
        para(c, COPY[title], x, 613, 161, 9.1, 13, max_height=52)
    para(c, COPY['Deployment scope'], 44, 678, 524, 8, 11.5, max_height=35)
    para(c, COPY['Next step'], 44, 720, 524, 9, 12, TEAL, True)
    source_link(c, 'Elastic Order Management', 'https://www.elasticsuite.com/platform/', 44, 735)
    c.showPage()


def build():
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    chart_output = ROOT / 'output/charts/elastic_ats_availability_chart.pdf'
    chart_output.parent.mkdir(parents=True, exist_ok=True)
    renderPDF.drawToFile(ats_chart(), str(chart_output),
                         title='Illustrative time-phased ATS', author='P2 Business Solutions')
    c = canvas.Canvas(str(OUTPUT), pagesize=(W,H), pageCompression=1)
    c.setTitle('Elastic Odoo Connector Feature Brief')
    c.setAuthor('P2 Business Solutions')
    c.setSubject('Odoo 18.0 integration with Elastic B2B')
    page_one(c)
    availability_page(c)
    page_two(c)
    page_three(c)
    c.save()
    print(OUTPUT)


if __name__ == '__main__':
    build()
