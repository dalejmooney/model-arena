"""The web view.

Read only, and on purpose. The terminal runs comparisons, this reads what they
produced. Adding a "run it now" button means holding four streams open across a
request, which is a different problem from displaying a result and would be the
tail wagging the dog at this stage.

Everything is priced at request time from stored tokens rather than served from a
figure recorded on the day, so a page reflects today's prices and moves when they
do. That is the whole reason the database has no cost column.
"""

from datetime import date
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import HTMLResponse

from model_arena import render, storage
from model_arena.arena import price

app = FastAPI(title="Model Arena", docs_url=None, redoc_url=None)

# Overridable so tests can point at a temporary database instead of the real one.
DB: Path = storage.DEFAULT_DB


@app.get("/", response_class=HTMLResponse)
def index() -> HTMLResponse:
    today = date.today()
    rows = []
    for summary in storage.recent(limit=50, path=DB):
        run = storage.load(summary.id, path=DB)
        if run is None:  # pragma: no cover - deleted between the two queries
            continue
        _, total, unpriced = price(run.results, today)
        rows.append((run, len(run.results), total, len(unpriced)))
    return HTMLResponse(render.runs_page(rows))


@app.get("/runs/{run_id}", response_class=HTMLResponse)
def run(run_id: int) -> HTMLResponse:
    run = storage.load(run_id, path=DB)
    if run is None:
        return HTMLResponse(
            render.page("not found", render.header(f"no run {run_id}")), status_code=404
        )
    today = date.today()
    rows, total, unpriced = price(run.results, today)
    return HTMLResponse(render.run_page(run, rows, total, unpriced, today))


def serve(host: str = "127.0.0.1", port: int = 8000) -> None:
    """Run the viewer. Bound to localhost, because this is somebody's own history."""
    import uvicorn

    uvicorn.run(app, host=host, port=port, log_level="warning")
