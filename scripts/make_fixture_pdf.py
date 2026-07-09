"""生成 fixture 储量报告 PDF（供单测与离线模式）。

两页两张表，覆盖两种单位体系：
- p1 锂矿（Pilgangoora 风格）：Tonnes (Mt) / Grade (% Li2O) / Contained Li2O (kt)
- p2 金矿：Tonnes (Mt) / Grade (g/t Au) / Contained Gold (koz)

数字为示意值（量级参考公开披露的 Pilgangoora 资源规模），页面上明确标注 FIXTURE。

用法：python scripts/make_fixture_pdf.py
"""

from __future__ import annotations

from pathlib import Path

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.platypus import PageBreak, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

OUT = Path(__file__).resolve().parents[1] / (
    "src/mineral_daily/servers/pdf/data/fixture_resource_report.pdf"
)

LITHIUM_TABLE = [
    ["Category", "Tonnes (Mt)", "Grade (% Li2O)", "Contained Li2O (kt)"],
    ["Measured", "58.1", "1.14", "662"],
    ["Indicated", "152.3", "1.09", "1,660"],
    ["Measured + Indicated", "210.4", "1.10", "2,322"],
    ["Inferred", "103.6", "1.02", "1,057"],
    ["Total", "314.0", "1.08", "3,379"],
]

GOLD_TABLE = [
    ["Category", "Tonnes (Mt)", "Grade (g/t Au)", "Contained Gold (koz)"],
    ["Indicated", "42.5", "1.35", "1,845"],
    ["Inferred", "18.2", "1.10", "644"],
]

STYLE = TableStyle(
    [
        ("GRID", (0, 0), (-1, -1), 0.6, colors.black),
        ("BACKGROUND", (0, 0), (-1, 0), colors.lightgrey),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTNAME", (0, 1), (-1, -1), "Helvetica"),
        ("FONTSIZE", (0, 0), (-1, -1), 9),
        ("ALIGN", (1, 0), (-1, -1), "RIGHT"),
    ]
)


def main() -> None:
    OUT.parent.mkdir(parents=True, exist_ok=True)
    styles = getSampleStyleSheet()
    doc = SimpleDocTemplate(str(OUT), pagesize=A4, title="Fixture Mineral Resource Report")
    story = [
        Paragraph("Pilgangoora Lithium Project — Technical Report [FIXTURE]", styles["Title"]),
        Paragraph(
            "This is a FIXTURE document for automated tests and offline mode. "
            "Numbers are illustrative (magnitudes reference public disclosures). "
            "The following Mineral Resource estimate is reported inclusive of "
            "Measured, Indicated and Inferred categories.",
            styles["Normal"],
        ),
        Spacer(1, 12),
        Paragraph("Table 1-1: Mineral Resource Estimate — Pilgangoora (fixture)", styles["h3"]),
        Table(LITHIUM_TABLE, hAlign="LEFT"),
        PageBreak(),
        Paragraph("Example Gold Project — Mineral Resource Estimate [FIXTURE]", styles["Title"]),
        Paragraph(
            "Fixture gold-style table covering the g/t + ounces unit family. "
            "Indicated and Inferred Mineral Resources are stated below.",
            styles["Normal"],
        ),
        Spacer(1, 12),
        Table(GOLD_TABLE, hAlign="LEFT"),
    ]
    for item in story:
        if isinstance(item, Table):
            item.setStyle(STYLE)
    doc.build(story)
    print(f"[ok] fixture PDF 已写入 {OUT} ({OUT.stat().st_size} bytes)")


if __name__ == "__main__":
    main()
