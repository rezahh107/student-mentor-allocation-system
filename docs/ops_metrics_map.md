# نگاشت هشدارها به داشبورد عملیات

| هشدار | داشبورد | پنل | متریک |
|-------|---------|------|--------|
| SLO آمادگی | ops/dashboards/slo.json | "واکنش آماده‌سازی" | `export_duration_seconds_bucket{phase="ready"}` |
| SLO سلامت | ops/dashboards/slo.json | "پایش سلامت" | `export_duration_seconds_bucket{phase="healthz"}` |
| حافظهٔ سامانه | ops/dashboards/slo.json | "مصرف حافظه" | `node_memory_MemAvailable_bytes` |
| خطای آپلود | ops/dashboards/errors.json | "نرخ خطا" | `upload_errors_total{type="fatal"}` |
| خطای نرم | ops/dashboards/errors.json | "هشدار خطای نرم" | `upload_errors_total{type="soft"}` |
| حجم برون‌سپاری | ops/dashboards/exports.json | "حجم فایل" | `export_file_bytes_total{kind="zip"}` |
| میانگین ردیف | ops/dashboards/exports.json | "میانگین ردیف" | `export_rows_total{type="sabt"}` |
| کارهای معوق | ops/dashboards/uploads.json | "صف بارگذاری" | `export_jobs_total{status="queued"}` |
| سرعت آپلود | ops/dashboards/uploads.json | "سرعت بارگذاری" | `export_duration_seconds_count{phase="upload"}` |

تمام مسیرها به فایل‌های JSON موجود در مخزن اشاره می‌کنند و برای آگاهی تیم عملیات آماده‌اند.
