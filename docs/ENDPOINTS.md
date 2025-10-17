# API Endpoints

این مستند از OpenAPI تولید شده است و نمونه‌ها قابل اجرا هستند.
## `POST /__lint`
 Lint Echo
```
curl -X POST http://localhost:8000/__lint -H 'Authorization: Bearer cli-admin-token-1234567890' -H 'Content-Type: application/json' -d '{"نمونه": "نمونه"}'
```
**Request Example**
```json
{
  "نمونه": "نمونه"
}
```
**Response Example (200)**
```json
{
  "نمونه": "نمونه"
}
```

## `GET /api/exports/csv`
Exporter Stub
```
curl -X GET http://localhost:8000/api/exports/csv -H 'Authorization: Bearer cli-admin-token-1234567890'
```
**Response Example (200)**
```json
{
  "نمونه": "نمونه"
}
```

## `GET /api/jobs`
List Jobs
```
curl -X GET http://localhost:8000/api/jobs -H 'Authorization: Bearer cli-admin-token-1234567890'
```
**Response Example (200)**
```json
"نمونه"
```

## `POST /api/jobs`
Create Job
```
curl -X POST http://localhost:8000/api/jobs -H 'Authorization: Bearer cli-admin-token-1234567890' -H 'Content-Type: application/json' -d '{"نمونه": "نمونه"}'
```
**Request Example**
```json
{
  "نمونه": "نمونه"
}
```
**Response Example (200)**
```json
"نمونه"
```

## `GET /download`
Download Endpoint
```
curl -X GET http://localhost:8000/download -H 'Authorization: Bearer cli-admin-token-1234567890'
```
**Response Example (200)**
```json
"نمونه"
```

## `GET /download/{token}`
Download Artifact
```
curl -X GET http://localhost:8000/download/{token} -H 'Authorization: Bearer cli-admin-token-1234567890'
```
**Response Example (200)**
```json
"نمونه"
```

## `GET /healthz`
Healthz
```
curl -X GET http://localhost:8000/healthz -H 'Authorization: Bearer cli-admin-token-1234567890'
```
**Response Example (200)**
```json
"نمونه"
```

## `GET /metrics`
Metrics Endpoint
```
curl -X GET http://localhost:8000/metrics -H 'Authorization: Bearer cli-admin-token-1234567890' -H 'X-Metrics-Token: cli-metrics-token-1234567890'
```
**Response Example (200)**
```json
"نمونه"
```

## `GET /readyz`
Readyz
```
curl -X GET http://localhost:8000/readyz -H 'Authorization: Bearer cli-admin-token-1234567890'
```
**Response Example (200)**
```json
"نمونه"
```

## `GET /ui/exports`
Ui Exports
```
curl -X GET http://localhost:8000/ui/exports -H 'Authorization: Bearer cli-admin-token-1234567890'
```

## `GET /ui/exports/new`
Ui Exports New
```
curl -X GET http://localhost:8000/ui/exports/new -H 'Authorization: Bearer cli-admin-token-1234567890'
```

## `GET /ui/health`
Ui Health
```
curl -X GET http://localhost:8000/ui/health -H 'Authorization: Bearer cli-admin-token-1234567890'
```

## `GET /ui/jobs/{job_id}`
Ui Job
```
curl -X GET http://localhost:8000/ui/jobs/{job_id} -H 'Authorization: Bearer cli-admin-token-1234567890'
```

## `GET /ui/uploads`
Ui Uploads
```
curl -X GET http://localhost:8000/ui/uploads -H 'Authorization: Bearer cli-admin-token-1234567890'
```
