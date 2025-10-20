#!/bin/bash
# run_full_tests.sh

set -e

echo "🚀 شروع اجرای تست‌های کامل SmartAllocPY"
echo "================================================"

TIMESTAMP=$(date '+%Y%m%d_%H%M%S')
LOG_DIR="test_logs"
REPORT_FILE="$LOG_DIR/test_report_$TIMESTAMP.html"

mkdir -p "$LOG_DIR"

echo "📋 مرحله 1: بررسی محیط"
echo "------------------------"
python --version
pytest --version
echo ""

echo "🧪 مرحله 2: تست‌های واحد"
echo "------------------------"
pytest tests/core/ tests/models/ tests/services/ \
    -v --tb=short \
    --html=$LOG_DIR/unit_tests_$TIMESTAMP.html \
    --self-contained-html || true

echo ""

echo "🖥️  مرحله 3: تست‌های UI"
echo "------------------------"
if command -v xvfb-run &> /dev/null; then
    xvfb-run -a pytest tests/ui/ \
        -v --tb=short \
        --html=$LOG_DIR/ui_tests_$TIMESTAMP.html \
        --self-contained-html || true
else
    pytest tests/ui/ \
        -v --tb=short --disable-warnings \
        --html=$LOG_DIR/ui_tests_$TIMESTAMP.html \
        --self-contained-html || true
fi

echo ""

echo "🔗 مرحله 4: تست‌های یکپارچگی"
echo "-----------------------------"
pytest tests/integration/ \
    -v --tb=short \
    --html=$LOG_DIR/integration_tests_$TIMESTAMP.html \
    --self-contained-html || true

echo ""

echo "⚡ مرحله 5: تست‌های عملکرد"
echo "---------------------------"
pytest tests/performance/ \
    -v --tb=short \
    --html=$LOG_DIR/performance_tests_$TIMESTAMP.html \
    --self-contained-html || true

echo ""

echo "📊 مرحله 6: گزارش پوشش کامل"
echo "-----------------------------"
pytest --cov=sma \
    --cov-report=html:$LOG_DIR/coverage_$TIMESTAMP \
    --cov-report=term \
    --cov-report=xml:$LOG_DIR/coverage_$TIMESTAMP.xml \
    --html=$REPORT_FILE \
    --self-contained-html \
    -v || true

echo ""
echo "✅ تست‌های کامل پایان یافت"
echo "📁 گزارش‌ها در: $LOG_DIR"
echo "🌐 گزارش اصلی: $REPORT_FILE"
echo "📊 گزارش پوشش: $LOG_DIR/coverage_$TIMESTAMP/index.html"
