# Health Endpoints

Health/readiness endpoints are backed by the aggregated
`ResourceManager.health_payload(...)` contract from `orchid_commons`.

## `GET /health`

- Runs runtime checks with `include_optional_checks=True`.
- Always returns `200 OK` with the aggregated payload.
- Includes optional checks (for example observability backends) when enabled.

## `GET /health/ready`

- Runs runtime checks with `include_optional_checks=False`.
- Returns `200 OK` when `readiness=true`.
- Returns `503 Service Unavailable` when `readiness=false`.

## `GET /health/live`

- Minimal probe to verify the process is alive.
- Returns `{ "status": "ok" }`.

## Payload Contract (`/health` and `/health/ready`)

```json
{
  "status": "ok | degraded | down",
  "healthy": true,
  "readiness": true,
  "liveness": true,
  "latency_ms": 12.5,
  "summary": {
    "total": 3,
    "healthy": 3,
    "unhealthy": 0
  },
  "checks": {
    "mongodb": {
      "healthy": true,
      "latency_ms": 2.1,
      "message": "MongoDB is healthy",
      "details": {
        "provider": "mongodb"
      }
    }
  }
}
```

Fields:

- `status`: aggregated status (`ok`, `degraded`, `down`).
- `healthy`: legacy alias (same value as `readiness`).
- `readiness`: readiness for serving traffic.
- `liveness`: process liveness (normally `true`).
- `latency_ms`: total aggregate health latency.
- `summary.total|healthy|unhealthy`: aggregate counters.
- `checks.<name>.healthy`: per-check status.
- `checks.<name>.latency_ms`: per-check latency.
- `checks.<name>.message`: optional backend message.
- `checks.<name>.details`: optional metadata (`error_type`, `provider`, etc.).

## Fallback When Runtime Is Unavailable

If the runtime resource manager is not initialized (or health evaluation fails),
the service returns a `down` payload with a `runtime_manager` check.
