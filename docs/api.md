# EDA Agent API Documentation

## Overview

The EDA Agent provides a RESTful API for LLM-driven EDA parameter tuning. It accepts natural language queries, reasons about timing/congestion/power metrics, and triggers ORFS/OpenROAD runs.

**Base URL**: `http://localhost:8000`

**Authentication**: JWT Bearer token (see [Auth Endpoints](#auth-endpoints))

---

## Table of Contents

- [Health](#health)
- [Auth Endpoints](#auth-endpoints)
- [Chat Endpoints](#chat-endpoints)
- [Metrics Endpoints](#metrics-endpoints)
- [Runs Endpoints](#runs-endpoints)
- [Models](#models)

---

## Health

### GET /health

Health check endpoint.

**Response**:
```json
{
  "status": "ok",
  "version": "0.1.0"
}
```

---

## Auth Endpoints

### POST /auth/register

Register a new user.

**Request Body**:
```json
{
  "username": "string",
  "email": "user@example.com",
  "password": "string"
}
```

**Response** (201):
```json
{
  "id": 1,
  "username": "string",
  "email": "user@example.com"
}
```

### POST /auth/token

Authenticate and receive access token.

**Request Body**:
```json
{
  "username": "string",
  "password": "string"
}
```

**Response**:
```json
{
  "access_token": "eyJhbGc...",
  "token_type": "bearer"
}
```

**Usage**: Include in subsequent requests:
```
Authorization: Bearer <access_token>
```

---

## Chat Endpoints

### POST /agent/chat

Send a natural language query to the LLM agent.

**Headers**: `Authorization: Bearer <token>`

**Request Body**:
```json
{
  "message": "Improve timing for aes on sky130hd",
  "session_id": "optional-session-uuid"  // optional
}
```

**Response**:
```json
{
  "reply": "I recommend reducing PLACE_DENSITY to 0.60...",
  "session_id": "uuid-if-created",
  "tool_calls": [
    {
      "name": "infer_root_cause",
      "arguments": {...}
    }
  ]
}
```

### DELETE /agent/chat/{session_id}

Clear a chat session.

**Headers**: `Authorization: Bearer <token>`

**Response** (204): No content.

---

## Metrics Endpoints

All metrics endpoints require `Authorization: Bearer <token>`.

### GET /metrics/timing

Query timing metrics for a run.

**Query Parameters**:
| Param | Type | Description |
|-------|------|------------|
| `design_name` | string | Design name (e.g., `aes`) |
| `run_id` | int | Specific run ID |
| `stage` | string | Stage: `synth`, `floorplan`, `place`, `cts`, `route`, `finish` |
| `limit` | int | Max rows (default 10) |

**Example**: `GET /metrics/timing?design_name=aes&stage=route&limit=5`

**Response**:
```json
{
  "run_id": 42,
  "design_name": "aes",
  "stage": "route",
  "summary": [
    {
      "wns_ns": -0.352,
      "tns_ns": -2.816,
      "setup_violations": 8,
      "hold_violations": 0,
      "fmax_mhz": 144.93,
      "clock_skew_ns": 0.045
    }
  ]
}
```

### GET /metrics/congestion

Query congestion metrics.

**Query Parameters**: `design_name`, `run_id`, `stage`, `limit`

**Response**:
```json
{
  "run_id": 42,
  "design_name": "aes",
  "stage": "route",
  "summary": [
    {
      "hotspot_count": 5,
      "max_overflow": 4,
      "total_overflow": 7,
      "worst_layer": "metal3"
    }
  ]
}
```

### GET /metrics/utilization

Query utilization metrics.

**Query Parameters**: `design_name`, `run_id`, `stage`, `limit`

**Response**:
```json
{
  "run_id": 42,
  "design_name": "aes",
  "stage": "finish",
  "summary": [
    {
      "utilization_pct": 68.0,
      "num_cells": 12847,
      "area_um2": 123456.78
    }
  ]
}
```

### GET /metrics/power

Query power metrics.

**Query Parameters**: `design_name`, `run_id`, `stage`, `limit`

**Response**:
```json
{
  "run_id": 42,
  "design_name": "aes",
  "stage": "finish",
  "summary": [
    {
      "total_power_mw": 0.654,
      "dynamic_power_mw": 0.58,
      "leakage_power_mw": 0.074
    }
  ]
}
```

### GET /metrics/compare

Compare two runs.

**Query Parameters**:
| Param | Type | Description |
|-------|------|------------|
| `design_name` | string | Design name |
| `run_a` | int | First run ID |
| `run_b` | int | Second run ID |
| `metric` | string | `wns`, `tns`, `setup`, `hold`, `power`, `util` |

**Response**:
```json
{
  "design_name": "aes",
  "run_a": 40,
  "run_b": 42,
  "metric": "wns",
  "value_a": -0.192,
  "value_b": -0.352,
  "delta": 0.160,
  "improved": true
}
```

---

## Runs Endpoints

### POST /runs/

Trigger a new EDA run.

**Headers**: `Authorization: Bearer <token>`

**Request Body**:
```json
{
  "backend": "orfs",
  "stage": "finish",
  "design_name": "aes",
  "design_config": "/path/to/config.mk",
  "pdk": "sky130hd",
  "params": {
    "PLACE_DENSITY": "0.60"
  }
}
```

**Response** (202):
```json
{
  "status": "accepted",
  "run_id": 43,
  "message": "Run queued"
}
```

**Available Backends**: `orfs`

**Available Stages**: `synth`, `floorplan`, `place`, `cts`, `route`, `finish`

### GET /runs/

List runs with filters.

**Query Parameters**: `design_name`, `stage`, `backend`, `status`, `limit`

**Response**:
```json
{
  "runs": [
    {
      "run_id": 42,
      "backend": "orfs",
      "stage": "route",
      "design_name": "aes",
      "status": "success",
      "started_at": "2026-05-03T10:00:00Z",
      "finished_at": "2026-05-03T10:05:00Z"
    }
  ]
}
```

### GET /runs/{run_id}

Get run details.

**Response**:
```json
{
  "run_id": 42,
  "backend": "orfs",
  "stage": "route",
  "design_name": "aes",
  "status": "success",
  "started_at": "2026-05-03T10:00:00Z",
  "finished_at": "2026-05-03T10:05:00Z",
  "log_path": "/path/to/flow/logs/.../42.log",
  "report_dir": "/path/to/reports/sky130hd/aes/base"
}
```

---

## Models

### ChatRequest
```python
class ChatRequest(BaseModel):
    message: str
    session_id: str | None = None
```

### ChatResponse
```python
class ChatResponse(BaseModel):
    reply: str
    session_id: str
    tool_calls: list[dict] | None = None
```

### RegisterRequest
```python
class RegisterRequest(BaseModel):
    username: str
    email: EmailStr
    password: str
```

### TokenResponse
```python
class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
```

### RunStageRequest
```python
class RunStageRequest(BaseModel):
    backend: str  # "orfs"
    stage: str    # "finish"
    design_name: str
    design_config: str
    pdk: str
    params: dict = {}
```

---

## Error Responses

| Status | Description |
|--------|-------------|
| 400 | Bad Request – invalid parameters |
| 401 | Unauthorized – missing/invalid token |
| 403 | Forbidden – insufficient permissions |
| 404 | Not Found – run_id not found |
| 422 | Validation Error – request body invalid |
| 500 | Internal Server Error |

Example error:
```json
{
  "detail": "Run not found"
}
```

---

## Quick Start

1. Start server:
   ```bash
   uvicorn eda_agent.api.main:app --reload
   ```

2. Register user:
   ```bash
   curl -X POST http://localhost:8000/auth/register \
     -H "Content-Type: application/json" \
     -d '{"username":"alice","email":"alice@example.com","password":"secret"}'
   ```

3. Login:
   ```bash
   curl -X POST http://localhost:8000/auth/token \
     -H "Content-Type: application/json" \
     -d '{"username":"alice","password":"secret"}'
   # → {"access_token": "...", "token_type": "bearer"}
   ```

4. Chat:
   ```bash
   curl -X POST http://localhost:8000/agent/chat \
     -H "Authorization: Bearer <token>" \
     -H "Content-Type: application/json" \
     -d '{"message":"Improve timing for aes on sky130hd"}'
   ```

5. Query metrics:
   ```bash
   curl "http://localhost:8000/metrics/timing?design_name=aes&stage=route" \
     -H "Authorization: Bearer <token>"
   ```

---

## Swagger UI

Interactive docs available at: `http://localhost:8000/docs`

ReDoc available at: `http://localhost:8000/redoc`