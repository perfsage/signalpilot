"""
FastAPI web dashboard for PerfSage SignalPilot.

Provides:
- GET /          → HTML dashboard (list of analyses)
- GET /analyze   → Run analysis and return HTML report
- GET /api/analyses  → JSON list of saved analyses
- GET /api/analyses/{id}  → JSON details for a specific analysis
- GET /health    → Health check
"""
from __future__ import annotations

from datetime import datetime
from typing import Optional

from fastapi import FastAPI
from fastapi.responses import HTMLResponse, JSONResponse


def create_app() -> FastAPI:
    """Construct and return the FastAPI application."""
    web_app = FastAPI(title="SignalPilot Dashboard", version="0.1.0")

    @web_app.get("/health")
    def health() -> dict:
        return {"status": "ok", "ts": datetime.utcnow().isoformat()}

    @web_app.get("/", response_class=HTMLResponse)
    def dashboard() -> str:
        return """
<!DOCTYPE html>
<html><head><title>SignalPilot Dashboard</title>
<meta charset="UTF-8">
<style>
body{background:#0f172a;color:#f1f5f9;font-family:system-ui,sans-serif;margin:0;padding:2rem}
h1{color:#38bdf8}
.form{background:#1e293b;border:1px solid #334155;border-radius:8px;padding:1.5rem;max-width:500px;margin:2rem 0}
input,button{padding:0.5rem 1rem;border-radius:4px;border:1px solid #334155;margin:0.3rem}
input{background:#0f172a;color:#f1f5f9;width:300px}
button{background:#2563eb;color:white;border:none;cursor:pointer}
button:hover{background:#1d4ed8}
</style></head>
<body>
<h1>&#9889; SignalPilot Dashboard</h1>
<div class="form">
<h3>Run Analysis</h3>
<form action="/analyze" method="get">
  <input name="namespace" placeholder="Namespace (e.g. default)" required>
  <input name="deployment" placeholder="Deployment (optional)">
  <button type="submit">Analyze</button>
</form>
</div>
</body></html>
"""

    @web_app.get("/analyze", response_class=HTMLResponse)
    def analyze_get(namespace: str, deployment: Optional[str] = None) -> HTMLResponse:
        """Run analysis and return HTML report."""
        try:
            from signalpilot.cli import _run_analysis
            from signalpilot.report.html import generate_html_report

            analysis = _run_analysis(namespace, deployment, None, False, None, True)
            html = generate_html_report(analysis)
            return HTMLResponse(content=html)
        except Exception as e:
            return HTMLResponse(
                content=(
                    "<html><body style='background:#0f172a;color:#f87171;"
                    "font-family:monospace;padding:2rem'>"
                    f"<h2>Analysis Error</h2><pre>{str(e)}</pre></body></html>"
                ),
                status_code=500,
            )

    @web_app.get("/api/analyses")
    def list_analyses() -> list[str]:
        """Return all saved analysis IDs."""
        try:
            from signalpilot.verification.store import VerificationStore

            store = VerificationStore()
            return store.list_analyses()
        except Exception:
            return []

    @web_app.get("/api/analyses/{analysis_id}")
    def get_analysis(analysis_id: str) -> JSONResponse:
        """Return the full Analysis JSON for analysis_id."""
        from fastapi import HTTPException

        from signalpilot.verification.store import VerificationStore

        store = VerificationStore()
        analysis = store.load(analysis_id)
        if analysis is None:
            raise HTTPException(status_code=404, detail=f"Analysis '{analysis_id}' not found")
        return JSONResponse(content=analysis.model_dump(mode="json"))

    return web_app
