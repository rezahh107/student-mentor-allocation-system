from __future__ import annotations

from io import BytesIO
from typing import Dict, List, Any
import logging

import jdatetime
import matplotlib.pyplot as plt
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import inch
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import Image, Paragraph, SimpleDocTemplate, Table, TableStyle, PageBreak
import os

from src.services.analytics_service import DashboardData


class DashboardReportGenerator:
    """تولید گزارش PDF از داده‌های داشبورد با پشتیبانی فارسی."""

    def __init__(self) -> None:
        # تلاش برای ثبت فونت فارسی در صورت وجود
        try:
            pdfmetrics.registerFont(TTFont("Vazir", "assets/fonts/Vazir.ttf"))
            self.font_name = "Vazir"
        except Exception as exc:  # noqa: BLE001
            logging.getLogger(__name__).warning("فونت Vazir در دسترس نبود؛ Helvetica استفاده شد", exc_info=exc)
            self.font_name = "Helvetica"
        self.dpi = 300

    async def generate_dashboard_pdf(self, dashboard_data: DashboardData, filepath: str) -> str:
        doc = SimpleDocTemplate(filepath, pagesize=A4, rightMargin=36, leftMargin=36, topMargin=36, bottomMargin=36)
        story = []

        styles = getSampleStyleSheet()
        persian = ParagraphStyle(
            "Persian",
            parent=styles["Normal"],
            fontName=self.font_name,
            fontSize=12,
            alignment=2,  # Right align
        )

        # Title
        title = Paragraph("گزارش داشبورد مدیریتی دانش‌آموزان", persian)
        story.append(title)

        # Date
        date_str = jdatetime.datetime.now().strftime("%Y/%m/%d - %H:%M")
        story.append(Paragraph(f"تاریخ گزارش: {date_str}", persian))

        story.append(Paragraph("\n", persian))

        # Summary table
        active_pct = f"{dashboard_data.active_percentage:.1f}%"
        pending_pct = f"{dashboard_data.pending_percentage:.1f}%"
        summary_data = [
            ["شاخص", "مقدار", "تغییرات"],
            ["کل دانش‌آموزان", f"{dashboard_data.total_students:,}", dashboard_data.growth_rate],
            ["ثبت‌نام فعال", f"{dashboard_data.active_students:,}", active_pct],
            ["در انتظار تخصیص", f"{dashboard_data.pending_allocations}", pending_pct],
            ["آخرین بروزرسانی", jdatetime.datetime.fromgregorian(datetime=dashboard_data.last_updated).strftime("%Y/%m/%d %H:%M"), ""],
        ]

        table = Table(summary_data)
        table.setStyle(
            TableStyle(
                [
                    ("BACKGROUND", (0, 0), (-1, 0), colors.grey),
                    ("TEXTCOLOR", (0, 0), (-1, 0), colors.whitesmoke),
                    ("ALIGN", (0, 0), (-1, -1), "RIGHT"),
                    ("FONTNAME", (0, 0), (-1, -1), self.font_name),
                    ("FONTSIZE", (0, 0), (-1, 0), 12),
                    ("BOTTOMPADDING", (0, 0), (-1, 0), 12),
                    ("BACKGROUND", (0, 1), (-1, -1), colors.beige),
                    ("GRID", (0, 0), (-1, -1), 1, colors.black),
                ]
            )
        )
        story.append(table)

        story.append(Paragraph("\n", persian))

        # Charts
        story.append(self._gender_chart(dashboard_data.gender_distribution))
        story.append(self._trend_chart(dashboard_data.monthly_registrations))

        doc.build(story)
        return filepath

    def _gender_chart(self, gender_data: Dict[int, int]) -> Image:
        plt.figure(figsize=(3.5, 2.6))
        plt.rcParams["font.family"] = ["Vazir", "Tahoma"]
        labels = ["زن", "مرد"]
        sizes = [gender_data.get(0, 0), gender_data.get(1, 0)]
        colors = ["#E91E63", "#2196F3"]
        plt.pie(sizes, labels=labels, colors=colors, autopct="%1.1f%%")
        plt.title("توزیع جنسیتی دانش‌آموزان")
        buf = BytesIO()
        plt.savefig(buf, format="png", bbox_inches="tight", dpi=150)
        buf.seek(0)
        plt.close()
        return Image(buf, width=3.2 * inch, height=2.2 * inch)

    def _trend_chart(self, monthly: List[Dict[str, Any]]) -> Image:  # type: ignore[name-defined]
        plt.figure(figsize=(5, 2.6))
        plt.rcParams["font.family"] = ["Vazir", "Tahoma"]
        months = [m.get("month", "") for m in monthly]
        counts = [int(m.get("count", 0)) for m in monthly]
        plt.plot(months, counts, "o-", color="#2196F3")
        plt.fill_between(range(len(months)), counts, alpha=0.2, color="#2196F3")
        plt.xticks(rotation=45, ha="right")
        plt.grid(True, alpha=0.3)
        plt.title("روند ثبت‌نام")
        buf = BytesIO()
        plt.savefig(buf, format="png", bbox_inches="tight", dpi=150)
        buf.seek(0)
        plt.close()
        return Image(buf, width=5.5 * inch, height=2.2 * inch)

    async def generate_advanced_report(
        self,
        dashboard_data: DashboardData,
        filepath: str,
        *,
        include_detailed_tables: bool = True,
        include_trend_analysis: bool = True,
        custom_logo_path: str | None = None,
    ) -> str:
        """تولید گزارش پیشرفته با بخش‌های بیشتر و هدر سفارشی."""
        doc = SimpleDocTemplate(filepath, pagesize=A4, rightMargin=50, leftMargin=50, topMargin=80, bottomMargin=40)
        story = []

        styles = getSampleStyleSheet()
        persian = ParagraphStyle("Persian", parent=styles["Normal"], fontName=self.font_name, fontSize=12, alignment=2)

        # Logo header
        if custom_logo_path and os.path.exists(custom_logo_path):
            try:
                story.append(Image(custom_logo_path, width=120, height=50))
            except Exception as exc:  # noqa: BLE001
                logging.getLogger(__name__).warning("بارگذاری لوگوی سفارشی در گزارش ناموفق بود", exc_info=exc)
        story.append(Paragraph("گزارش داشبورد مدیریتی دانش‌آموزان", persian))
        story.append(Paragraph(jdatetime.datetime.now().strftime("%Y/%m/%d - %H:%M"), persian))

        # Executive summary
        summary = [
            ["شاخص", "مقدار"],
            ["کل دانش‌آموزان", f"{dashboard_data.total_students:,}"],
            ["ثبت‌نام فعال", f"{dashboard_data.active_students:,}"],
            ["در انتظار تخصیص", f"{dashboard_data.pending_allocations}"],
            ["نرخ رشد", dashboard_data.growth_rate],
        ]
        table = Table(summary)
        table.setStyle(TableStyle([("FONTNAME", (0, 0), (-1, -1), self.font_name), ("GRID", (0, 0), (-1, -1), 1, colors.black)]))
        story.append(table)

        # Charts page
        story.append(PageBreak())
        story.append(self._gender_chart(dashboard_data.gender_distribution))
        story.append(self._trend_chart(dashboard_data.monthly_registrations))

        # Details
        if include_detailed_tables:
            story.append(PageBreak())
            # Center performance
            centers = dashboard_data.performance_metrics.get("center_utilization", {})
            rows = [["مرکز", "ظرفیت", "ثبت‌شده", "نرخ"]]
            names = {1: "مرکز", 2: "گلستان", 3: "صدرا"}
            for cid, row in centers.items():
                rows.append([names.get(cid, str(cid)), row.get("capacity", 0), row.get("registered", 0), f"{row.get('utilization', 0):.1f}%"])
            t = Table(rows)
            t.setStyle(TableStyle([("FONTNAME", (0, 0), (-1, -1), self.font_name), ("GRID", (0, 0), (-1, -1), 1, colors.grey)]))
            story.append(t)

        if include_trend_analysis:
            # Simple paragraph placeholder
            story.append(Paragraph("تحلیل روند: در این بازه زمانی، تغییرات ثبت‌نام مطابق نمودار روند بوده است.", persian))

        doc.build(story)
        return filepath
