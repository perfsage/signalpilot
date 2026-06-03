"""FastAPI application exposing the SignalPilot REST API and dashboard.

Full implementation will expose:
- ``GET  /api/analyses``              – list recent analyses
- ``POST /api/analyses``              – trigger a new analysis
- ``GET  /api/analyses/{id}``         – fetch a specific analysis (JSON)
- ``GET  /api/analyses/{id}/report``  – fetch the HTML report
- ``GET  /healthz``                   – liveness probe
"""

from __future__ import annotations

from fastapi import FastAPI

app = FastAPI(
    title="SignalPilot",
    description="Kubernetes RCA copilot REST API",
    version="0.1.0",
)


@app.get("/healthz", tags=["ops"])
async def healthz() -> dict[str, str]:
    """Liveness probe."""
    raise NotImplementedError


@app.get("/api/analyses", tags=["analyses"])
async def list_analyses() -> list[dict]:
    """Return metadata for all saved analyses."""
    raise NotImplementedError


@app.post("/api/analyses", tags=["analyses"], status_code=202)
async def trigger_analysis(namespace: str) -> dict:
    """Enqueue a new RCA analysis for *namespace*."""
    raise NotImplementedError


@app.get("/api/analyses/{analysis_id}", tags=["analyses"])
async def get_analysis(analysis_id: str) -> dict:
    """Return the full Analysis JSON for *analysis_id*."""
    raise NotImplementedError
