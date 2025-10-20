from __future__ import annotations

"""Streamlit dashboard for continuous testing insights.

داشبورد استریملیت برای تحلیل کیفیت و تست‌ها به صورت پیوسته.
"""

import asyncio
import json
from collections import defaultdict
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Awaitable, Dict, Iterable, List, Optional

import sys

_PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from sma.core.logging_config import setup_logging

setup_logging()

import arabic_reshaper
import matplotlib.font_manager as fm
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import streamlit as st
from streamlit.errors import StreamlitAPIException
from bidi.algorithm import get_display


try:
    from scripts.adaptive_testing import AdaptiveTester, TestingMode
except Exception:  # noqa: BLE001
    AdaptiveTester = None  # type: ignore[assignment]
    TestingMode = None  # type: ignore[assignment]


def configure_page() -> None:
    """Set the Streamlit page configuration before any UI commands."""
    try:
        st.set_page_config(page_title="SmartAlloc Continuous Quality", layout="wide")
    except StreamlitAPIException:
        # When running outside Streamlit or after configuration, ignore the warning.
        pass


configure_page()


ROOT = Path(__file__).resolve().parents[1]
LOGS_DIR = ROOT / "logs"
FONT_PATH = ROOT / "assets" / "fonts" / "Vazir.ttf"

plt.rcParams["axes.unicode_minus"] = False


def configure_fonts() -> Optional[fm.FontProperties]:
    """Configure Matplotlib to use Vazir font when available.

    تنظیم فونت مت‌پلات‌لیب برای استفاده از فونت وزیر در صورت دسترس بودن.
    """

    if FONT_PATH.exists():
        try:
            fm.fontManager.addfont(str(FONT_PATH))
            font = fm.FontProperties(fname=str(FONT_PATH))
            plt.rcParams["font.family"] = font.get_name()
            plt.rcParams.setdefault("font.sans-serif", [font.get_name(), "DejaVu Sans", "Arial"])
            return font
        except Exception as exc:  # noqa: BLE001
            print(f"[dashboard] failed to load Vazir font: {exc}")
    else:
        print(f"[dashboard] Vazir font not found at {FONT_PATH}")
    return None


def reshape_rtl(text: str) -> str:
    """Prepare Persian strings for RTL rendering in Streamlit.

    آماده3ازی متن فارسی برای نمایش راست به چپ در استریملیت.
    """

    if not text:
        return ""
    reshaped = arabic_reshaper.reshape(text)
    return get_display(reshaped)


def bilingual(en: str, fa: str) -> str:
    """Compose bilingual UI strings with RTL Persian content.

    ترکیب متن دو زبانه برای نمایش همزمان انگلیسی و فارسی.
    """

    return f"{en} | {reshape_rtl(fa)}"


class MeaningfulMetrics:
    """محاسبه معیارهای کیفی و کمی معنادار.

    Computes meaningful quality metrics and exposes ML-driven forecasting when available.
    """

    def __init__(self) -> None:
        self._tester = self._lazy_tester()
        self.ml_enabled = self._check_ml_availability()

    def _lazy_tester(self) -> Optional[AdaptiveTester]:
        if AdaptiveTester is None:
            return None
        try:
            return AdaptiveTester()
        except Exception as exc:  # noqa: BLE001
            print(f"[dashboard] failed to initialise AdaptiveTester: {exc}")
            return None

    def _check_ml_availability(self) -> bool:
        try:
            import prophet  # noqa: F401
            import sklearn  # noqa: F401
            return True
        except Exception:  # noqa: BLE001
            return False

    def _run_async(self, coro: Awaitable[Any]) -> Any:
        try:
            return asyncio.run(coro)
        except RuntimeError:
            loop = asyncio.new_event_loop()
            try:
                return loop.run_until_complete(coro)
            finally:
                loop.close()

    async def calculate_test_meaningfulness_score(self, test_data: List[Dict[str, Any]]) -> Dict[str, Any]:
        if not test_data:
            return {"score": 0.0, "factors": {}}

        latest = test_data[-1]
        total_tests = max(1, int(latest.get("total_tests", 0)))
        total_assertions = int(latest.get("total_assertions", 0))
        test_names = latest.get("test_names", []) or []

        def bounded(value: float, limit: float) -> float:
            return min(max(value, 0.0), limit)

        denominator = max(total_tests * 3, 1)
        factors = {
            "assertion_density": bounded(total_assertions / denominator * 100, 100.0),
            "edge_case_coverage": 0.0,
            "error_handling": 0.0,
            "integration_depth": 0.0,
            "performance_checks": 0.0,
        }

        keywords_edge = ("edge", "boundary", "limit", "خاص", "مرزی")
        edge_tests = sum(1 for name in test_names if any(key in name.lower() for key in keywords_edge))
        factors["edge_case_coverage"] = bounded(edge_tests / total_tests * 100, 100.0)

        keywords_error = ("error", "exception", "raise", "خطا", "استثنا")
        error_tests = sum(1 for name in test_names if any(key in name.lower() for key in keywords_error))
        factors["error_handling"] = bounded(error_tests / total_tests * 100, 100.0)

        fixtures_used = int(latest.get("fixtures_count", 0))
        factors["integration_depth"] = bounded((fixtures_used / total_tests) * 100, 100.0)

        perf_tests = int(latest.get("performance_tests_count", 0))
        factors["performance_checks"] = bounded((perf_tests / total_tests) * 100, 100.0)

        weights = {
            "assertion_density": 0.25,
            "edge_case_coverage": 0.25,
            "error_handling": 0.2,
            "integration_depth": 0.2,
            "performance_checks": 0.1,
        }

        score = sum(factors[key] * weights[key] for key in factors)
        return {
            "score": round(score, 2),
            "factors": {name: round(value, 2) for name, value in factors.items()},
        }

    def predict_failure_trend(self, historical_data: List[Dict[str, Any]]) -> Dict[str, Any]:
        usable = [entry for entry in historical_data if entry.get("date")]
        if len(usable) < 7:
            return {"prediction": bilingual("Insufficient data", "داده کافی نیست"), "confidence": 0}

        frame = pd.DataFrame([
            {
                "ds": pd.to_datetime(row.get("date")),
                "y": float(row.get("failed_tests_count", 0)) / max(float(row.get("total_tests", 1)), 1.0),
            }
            for row in usable[-30:]
        ])

        if self.ml_enabled and len(frame) >= 14:
            try:
                from prophet import Prophet

                model = Prophet(daily_seasonality=False, weekly_seasonality=True, yearly_seasonality=False)
                model.fit(frame)
                future = model.make_future_dataframe(periods=7)
                prediction = model.predict(future)
                last_actual = frame["y"].iloc[-1]
                next_week = prediction["yhat"].iloc[-7:]
                next_avg = max(0.0, next_week.mean())
                trend = self._classify_trend(last_actual, next_avg)
                confidence = min(95, 50 + len(frame) * 1.5)
                return {
                    "prediction": trend,
                    "next_week_failure_rate": round(next_avg * 100, 2),
                    "confidence": round(confidence, 0),
                    "method": "Prophet ML",
                }
            except Exception as exc:  # noqa: BLE001
                print(f"[dashboard] Prophet forecasting failed: {exc}")

        recent = frame.tail(7)
        next_avg = max(0.0, recent["y"].mean())
        first_half = max(0.0, recent.head(3)["y"].mean())
        second_half = max(0.0, recent.tail(3)["y"].mean())
        trend = self._classify_trend(first_half, second_half)
        return {
            "prediction": trend,
            "next_week_failure_rate": round(next_avg * 100, 2),
            "confidence": 60,
            "method": "Moving Average",
        }

    def render_advanced_metrics_tab(self, historical_data: List[Dict[str, Any]]) -> None:
        st.header("📊 معیارهای عمیق و معنادار / Deep Meaningful Metrics")

        if TestingMode is None:
            st.info(bilingual("Adaptive tester unavailable", "ماژول تست تطبیقی در دسترس نیست."))
            return

        col1, col2 = st.columns([1, 3])
        with col1:
            selected_mode = st.selectbox(
                bilingual("Test Mode", "حالت تست"),
                options=[mode.value for mode in TestingMode],
                index=1,
            )

        with col2:
            if st.button("🚀 اجرای تست تطبیقی / Run Adaptive Tests", use_container_width=True):
                if self._tester is None:
                    st.warning(bilingual("Adaptive tester unavailable", "نمی‌توان تست‌ها را اجرا کرد."))
                else:
                    with st.spinner(bilingual("Running adaptive suite...", "در حال اجرای تست تطبیقی...")):
                        results = self._run_async(self._tester.run_adaptive_tests())
                    st.success(bilingual("Adaptive run completed", "اجرای تطبیقی کامل شد."))
                    st.json(results)

        if not historical_data:
            historical_data = self.load_historical_data()

        if not historical_data:
            st.warning(bilingual("No historical metrics to display", "داده‌ای برای نمایش وجود ندارد."))
            return

        col_a, col_b, col_c, col_d = st.columns(4)
        latest = historical_data[-1]
        coverage_pct = latest.get("coverage_percent")
        if coverage_pct is None:
            coverage_pct = latest.get("coverage", {}).get("percent", 0)
        with col_a:
            st.metric(
                "پوشش کد / Coverage",
                f"{coverage_pct}%",
                help="درصد خطوطی که تحت پوشش تست قرار گرفته‌اند",
            )

        meaningfulness = self._run_async(self.calculate_test_meaningfulness_score(historical_data))
        with col_b:
            st.metric(
                "امتیاز معناداری / Meaningfulness",
                f"{meaningfulness['score']}%",
                help="ارزیابی کیفیت و عمق تست‌ها",
            )

        security_score = latest.get("security_score") or 0
        with col_c:
            st.metric(
                "امتیاز امنیت / Security",
                f"{security_score}%",
                help="شاخص ترکیبی وضعیت امنیتی",
            )

        prediction = self.predict_failure_trend(historical_data)
        with col_d:
            st.metric(
                "پیش‌بینی هفته آینده / Next Week",
                f"{prediction.get('next_week_failure_rate', 0)}% شکست",
                delta=prediction.get("prediction", "-"),
                help=f"اطمینان: {prediction.get('confidence', 0)}% - روش: {prediction.get('method', 'N/A')}",
            )

        factors = meaningfulness.get("factors", {})
        with st.expander("🔍 فاکتورهای معناداری / Meaningfulness Factors", expanded=False):
            if factors:
                df = pd.DataFrame([
                    {"Factor": name, "Score": value} for name, value in factors.items()
                ])
                st.dataframe(df, use_container_width=True)
                if st.checkbox(bilingual("Show radar chart", "نمایش نمودار راداری")):
                    self._render_radar_chart(factors)
            else:
                st.info(bilingual("No factor data available", "داده‌ای برای فاکتورهای معناداری وجود ندارد."))

    def _render_radar_chart(self, factors: Dict[str, float]) -> None:
        if not factors:
            return
        labels = list(factors.keys())
        values = list(factors.values())
        values.append(values[0])
        angles = np.linspace(0, 2 * np.pi, len(labels), endpoint=False).tolist()
        angles.append(angles[0])
        fig, ax = plt.subplots(subplot_kw={"polar": True})
        ax.plot(angles, values, "o-", linewidth=2)
        ax.fill(angles, values, alpha=0.25)
        ax.set_thetagrids(np.degrees(angles[:-1]), labels)
        ax.set_ylim(0, 100)
        st.pyplot(fig, clear_figure=True)

    def load_historical_data(self) -> List[Dict[str, Any]]:
        now = datetime.now()
        return [
            {
                "date": (now - timedelta(days=idx)).strftime("%Y-%m-%d"),
                "total_tests": 120 + idx,
                "failed_tests_count": (idx % 5),
                "coverage_percent": 80 + (idx % 10),
                "security_score": 88 + (idx % 5),
                "execution_time": 45 + idx,
                "tests_per_second": 3.0 + (idx % 4) / 4,
                "total_assertions": 300 + idx * 5,
                "test_names": [f"test_sample_{i}" for i in range(150)],
                "fixtures_count": 20 + (idx % 5),
                "performance_tests_count": 5 + (idx % 3),
            }
            for idx in range(14, 0, -1)
        ]

    def _classify_trend(self, baseline: float, comparison: float) -> str:
        if baseline == 0:
            ratio = comparison
        else:
            ratio = comparison / max(baseline, 1e-6)
        if ratio > 1.1:
            return "روند افزایشی"
        if ratio < 0.9:
            return "روند کاهشی"
        return "روند ثابت"

def parse_summary_date(value: Any) -> Optional[datetime]:
    """Convert stored summary dates into datetime objects.

    تبدیل تاریخ ذخیره3ده به شیء تاریخ-زمان پایتون.
    """

    if isinstance(value, datetime):
        return value
    if isinstance(value, str):
        for fmt in ("%Y-%m-%dT%H:%M:%S.%fZ", "%Y-%m-%dT%H:%M:%S%z", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d"):
            try:
                parsed = datetime.strptime(value, fmt)
                if parsed.tzinfo is not None:
                    return parsed.astimezone().replace(tzinfo=None)
                return parsed
            except ValueError:
                continue
        try:
            parsed = datetime.fromisoformat(value.replace("Z", ""))
            return parsed
        except ValueError:
            return None
    return None


class DashboardApp:
    """Streamlit presenter for Codex quality analytics.

    ارائه3دهنده استریملیت برای تحلیل3 کیفیت کدکس.
    """

    def __init__(self, logs_dir: Path | None = None) -> None:
        self.logs_dir = logs_dir or LOGS_DIR
        self.font_prop = configure_fonts()
        self.meaningful_metrics = MeaningfulMetrics()

    def load_historical(self) -> List[Dict[str, Any]]:
        """Load historical summaries from logs directory.

        بارگذاری خلاصه3 تاریخی نتایج تست از مسیر لاگ.
        """

        summaries: List[Dict[str, Any]] = []
        if not self.logs_dir.exists():
            return summaries
        for path in sorted(self.logs_dir.glob("summary_*.json")):
            try:
                payload = json.loads(path.read_text(encoding="utf-8"))
            except Exception as exc:  # noqa: BLE001
                st.warning(bilingual(f"Failed to load {path.name}", f"بارگذاری {path.name} ناموفق بود: {exc}"))
                continue
            if isinstance(payload, dict):
                payload.setdefault("_source", path.name)
                summaries.append(payload)
        return summaries

    def analyze_recurring_issues(self, data: List[Dict[str, Any]], days: int = 7) -> pd.DataFrame:
        """Aggregate recurring failures within a time window.

        تجمیع شکست3 تکرارشونده در بازه زمانی مشخص.
        """

        cutoff_date = datetime.now().date() - timedelta(days=days - 1)
        sorted_data = sorted(
            data,
            key=lambda item: parse_summary_date(item.get("date")) or datetime.min,
        )
        counter: Dict[str, Dict[str, Any]] = defaultdict(lambda: {
            "test": "",
            "message": "",
            "count": 0,
            "last_seen": datetime.min,
            "first_seen": datetime.max,
            "sources": set(),
        })
        trend_tracker: Dict[str, List[float]] = defaultdict(list)

        total_snapshots = len(sorted_data)
        for idx, summary in enumerate(sorted_data):
            recorded_at = parse_summary_date(summary.get("date"))
            if recorded_at and recorded_at.date() < cutoff_date:
                continue
            failed_tests: Iterable[Dict[str, Any]] = summary.get("failed_tests", [])
            window_position = (idx + 1) / max(1, total_snapshots)
            for failure in failed_tests:
                nodeid = failure.get("nodeid") or failure.get("test") or "unknown"
                entry = counter[nodeid]
                entry["test"] = nodeid
                entry["message"] = failure.get("message") or failure.get("error") or ""
                entry["count"] += 1
                entry["sources"].add(summary.get("_source", "unknown"))
                if recorded_at:
                    entry["last_seen"] = max(entry["last_seen"], recorded_at)
                    entry["first_seen"] = min(entry["first_seen"], recorded_at)
                trend_tracker[nodeid].append(window_position)

        records: List[Dict[str, Any]] = []
        for nodeid, info in counter.items():
            if info["count"] == 0:
                continue
            span_days = max((info["last_seen"] - info["first_seen"]).days, 0)
            avg_position = sum(trend_tracker[nodeid]) / max(1, len(trend_tracker[nodeid]))
            if avg_position > 0.66:
                trend = "increasing"
            elif avg_position < 0.33:
                trend = "decreasing"
            else:
                trend = "stable"
            risk_score = min(1.0, (info["count"] / max(1, days)) * (1.2 if trend == "increasing" else 1.0))
            records.append(
                {
                    "test": nodeid,
                    "message": info["message"],
                    "occurrences": info["count"],
                    "last_seen": info["last_seen"].strftime("%Y-%m-%d %H:%M") if info["last_seen"] != datetime.min else "-",
                    "span_days": span_days,
                    "risk_score": round(risk_score, 3),
                    "trend": trend,
                    "sources": ", ".join(sorted(info["sources"])),
                }
            )

        if not records:
            return pd.DataFrame(columns=[
                "test",
                "message",
                "occurrences",
                "last_seen",
                "span_days",
                "risk_score",
                "trend",
                "sources",
            ])

        df = pd.DataFrame(records)
        df.sort_values(by=["occurrences", "risk_score"], ascending=False, inplace=True)
        return df

    def plot_top_failures(self, df: pd.DataFrame) -> None:
        """Visualize top failures with Vazir font applied.

        نمایش نموداری شکست3 برتر با استفاده از فونت وزیر.
        """

        if df.empty:
            return
        top_df = df.head(10)
        fig, ax = plt.subplots(figsize=(8, max(4, len(top_df) * 0.5)))
        ax.barh(top_df["test"], top_df["occurrences"], color="#ff6b6b")
        ax.invert_yaxis()
        title = bilingual("Top Recurring Failures", "شکست3 پرتکرار")
        if self.font_prop:
            ax.set_title(title, fontproperties=self.font_prop)
        else:
            ax.set_title(title)
        ax.set_xlabel(bilingual("Occurrences", "تکرار"))
        ax.set_ylabel(bilingual("Test", "تست"))
        if self.font_prop:
            for label in ax.get_xticklabels() + ax.get_yticklabels():
                label.set_fontproperties(self.font_prop)
        st.pyplot(fig, clear_figure=True)

    def render_recurring_issues(self, historical_data: List[Dict[str, Any]]) -> None:
        """Render recurring issue analysis with user controls.

        نمایش تحلیل شکست3 تکرارشونده به همراه کنترل3 کاربر.
        """

        st.subheader(bilingual("Recurring Failures", "شکست3 تکرارشونده"))
        days = st.slider(
            bilingual("Filter to last X days", "فیلتر براساس تعداد روز"),
            min_value=1,
            max_value=30,
            value=7,
            help=bilingual(
                "Adjust window for recurring failure analysis.",
                "بازه3 زمانی تحلیل شکست3 تکراری را تنظیم کنید.",
            ),
        )

        recurring_df = self.analyze_recurring_issues(historical_data, days)
        if recurring_df.empty:
            st.success(bilingual("No recurring failures detected.", "هیچ شکست تکرارشوندهای یافت نشد."))
            return

        st.dataframe(recurring_df)
        csv_bytes = recurring_df.to_csv(index=False).encode("utf-8")
        st.download_button(
            label=bilingual("Download CSV", "دانلود فایل CSV"),
            data=csv_bytes,
            file_name="recurring_issues.csv",
            mime="text/csv",
        )
        self.plot_top_failures(recurring_df)

    def render_summary(self, historical_data: List[Dict[str, Any]]) -> None:
        """Render summary cards including light predictive signals.

        نمایش خلاصه3 وضعیت به همراه شاخص3 پیش3بینی ساده.
        """

        total_runs = len(historical_data)
        total_failures = sum(len(item.get("failed_tests", [])) for item in historical_data)
        coverage_trend = [item.get("coverage", {}).get("percent") for item in historical_data if item.get("coverage")]
        avg_coverage = round(sum(coverage_trend) / len(coverage_trend), 2) if coverage_trend else 0.0

        col1, col2, col3 = st.columns(3)
        col1.metric(bilingual("Test Runs", "اجرای تست"), total_runs)
        col2.metric(bilingual("Total Failures", "تعداد شکست"), total_failures)
        col3.metric(bilingual("Avg Coverage", "میانگین پوشش"), f"{avg_coverage}%")

    def run(self) -> None:
        """Entry point: render dashboard components.

        نقطه ورود برای نمایش اجزای داشبورد.
        """

        st.title(bilingual("Continuous Quality Dashboard", "داشبورد کیفیت پیوسته"))

        historical_data = self.load_historical()
        if not historical_data:
            st.warning(bilingual("No historical data found.", "داده تاریخی یافت نشد."))
            return

        self.render_summary(historical_data)
        st.divider()
        self.meaningful_metrics.render_advanced_metrics_tab(historical_data)
        st.divider()
        self.render_recurring_issues(historical_data)


def main() -> None:
    """Run dashboard when executed as a script.

    اجرای داشبورد هنگام اجرای مستقیم اسکریپت.
    """

    app = DashboardApp()
    app.run()


if __name__ == "__main__":
    main()
