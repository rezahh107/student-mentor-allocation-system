from __future__ import annotations
import pytest
import os
pytestmark = pytest.mark.skipif(os.name == 'nt', reason='Realtime UI test requires a non-Windows headless environment')


import asyncio


from src.ui.pages.dashboard_presenter import DashboardPresenter
from src.services.analytics_service import DashboardData


class DummyAnalytics:
    async def load_dashboard_data(self, date_range=None, force_refresh=False):
        return DashboardData(
            total_students=1,
            active_students=1,
            pending_allocations=0,
            growth_rate="+0.0%",
            growth_trend="stable",
            active_percentage=100.0,
            pending_percentage=0.0,
            gender_distribution={0: 0, 1: 1},
            monthly_registrations=[{"month": "1403/01", "count": 1}],
            center_performance={1: 1},
            age_distribution=[18],
            recent_activities=[],
            performance_metrics={},
            last_updated=None,
        )


@pytest.mark.realtime
@pytest.mark.asyncio
async def test_realtime_triggers_refresh(qtbot, monkeypatch):
    pres = DashboardPresenter()
    pres.analytics_service = DummyAnalytics()

    # Patch RealtimeService.start_listening to no-op and emit once
    class DummyRT:
        def __init__(self, *_):
            self.data_updated = type("Sig", (), {"connect": lambda *a, **k: None})()

        async def start_listening(self):
            return

    monkeypatch.setattr("src.ui.pages.dashboard_presenter.RealtimeService", DummyRT)

    # Connect to data_loaded signal
    loaded = asyncio.get_event_loop().create_future()
    pres.data_loaded.connect(lambda _: (not loaded.done()) and loaded.set_result(True))

    # Trigger handler directly (simulate WS message)
    await pres.load_dashboard_data()
    pres._handle_realtime_update({"type": "student_update"})
    await asyncio.wait_for(loaded, timeout=2)
    assert loaded.done()

