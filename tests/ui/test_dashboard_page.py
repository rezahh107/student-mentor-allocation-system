from __future__ import annotations
import pytest

from tests.ui import _headless

_headless.require_ui()

pytestmark = [pytest.mark.ui]
if _headless.PYTEST_SKIP_MARK is not None:
    pytestmark.append(_headless.PYTEST_SKIP_MARK)

from pathlib import Path
import os


from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import QFileDialog

from src.ui.pages.dashboard_page import DashboardPage
from src.ui.pages.dashboard_presenter import DashboardPresenter
from src.services.analytics_service import DashboardData


class DummyAnalytics:
    async def load_dashboard_data(self, date_range=None, force_refresh=False):
        return DashboardData(
            total_students=100,
            active_students=90,
            pending_allocations=10,
            growth_rate="+5.0%",
            growth_trend="up",
            active_percentage=90.0,
            pending_percentage=10.0,
            gender_distribution={0: 30, 1: 70},
            monthly_registrations=[{"month": "1403/01", "count": 10}, {"month": "1403/02", "count": 12}],
            center_performance={1: 50, 2: 30, 3: 20},
            age_distribution=[18, 19, 20, 21],
            recent_activities=[{"time": "12:10", "message": "ط«ط¨طھâ€Œظ†ط§ظ… ط¬ط¯غŒط¯", "details": "ع©ط¯: 123"}],
            performance_metrics={"center_utilization": {1: {"capacity": 100, "registered": 50, "utilization": 50.0}}},
            last_updated=None,
        )


@pytest.mark.skipif(os.name == 'nt', reason='PDF export is unstable on Windows headless tests')
@pytest.mark.asyncio
async def test_dashboard_load_and_pdf_export(qtbot, tmp_path, monkeypatch):
    pres = DashboardPresenter()
    # Inject dummy analytics
    pres.analytics_service = DummyAnalytics()
    page = DashboardPage(presenter=pres)
    qtbot.addWidget(page)
    page.show()

    # Load data
    await pres.load_dashboard_data()
    # Cards updated
    assert page.cards["total"].value_label.text() != "0"

    # Export PDF: patch file dialog
    pdf_path = tmp_path / "dash.pdf"
    monkeypatch.setattr(QFileDialog, "getSaveFileName", lambda *a, **k: (str(pdf_path), "PDF Files (*.pdf)"))
    await page._export_pdf()
    assert pdf_path.exists() and pdf_path.stat().st_size > 0


