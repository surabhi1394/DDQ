"""DDQ web tool: start a review from an address or an OM, follow its progress, read the dashboard,
download the Excel. Run with `ddq serve`."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from importlib import resources
from pathlib import Path
from typing import Callable, Optional

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, Response

from .pipeline import Review, run_review
from .report import write_report
from .store import Store, review_to_dict, summarize

MAX_OM_BYTES = 30 * 1024 * 1024  # the API's request limit is 32 MB


def _page(name: str) -> HTMLResponse:
    return HTMLResponse(resources.files("ddq_agent.web").joinpath(name).read_text())


def create_app(
    store: Store | None = None,
    runner: Callable[..., Review] = run_review,
    workers: int = 2,
) -> FastAPI:
    store = store or Store()
    pool = ThreadPoolExecutor(max_workers=workers, thread_name_prefix="ddq")
    app = FastAPI(title="DDQ review")

    def execute(review_id: str) -> None:
        meta = store.meta(review_id)
        store.update(review_id, status="running")
        try:
            review = runner(
                om_path=Path(meta["om_path"]) if meta["om_path"] else None,
                address=meta["address"] or None,
                on_step=lambda msg: store.update(review_id, step=msg),
            )
            store.save_review(review_id, review)
            write_report(review, store.report_path(review_id))
            title = review.profile.name or meta["title"]
            store.update(review_id, status="done", summary=summarize(review), title=title)
        except Exception as exc:  # surface the failure on the dashboard instead of losing it
            store.update(review_id, status="failed", error=f"{type(exc).__name__}: {exc}")

    @app.get("/static/style.css")
    def stylesheet():
        css = resources.files("ddq_agent.web").joinpath("style.css").read_text()
        return Response(css, media_type="text/css")

    @app.get("/", response_class=HTMLResponse)
    def home():
        return _page("index.html")

    @app.get("/reviews/{review_id}", response_class=HTMLResponse)
    def review_page(review_id: str):
        _meta_or_404(review_id)
        return _page("review.html")

    @app.get("/api/reviews")
    def list_reviews():
        return store.list()

    @app.post("/api/reviews", status_code=201)
    async def create_review(address: str = Form(""), om: Optional[UploadFile] = File(None)):
        address = address.strip()
        om_bytes = await om.read() if om is not None and om.filename else None
        if not address and not om_bytes:
            raise HTTPException(400, "Enter an address or upload an Offering Memorandum.")
        if om_bytes:
            if not om_bytes.startswith(b"%PDF"):
                raise HTTPException(400, "The Offering Memorandum must be a PDF.")
            if len(om_bytes) > MAX_OM_BYTES:
                raise HTTPException(400, "The PDF is larger than 30 MB.")
        meta = store.create(address or None, om.filename if om_bytes else None, om_bytes)
        pool.submit(execute, meta["id"])
        return meta

    @app.get("/api/reviews/{review_id}")
    def get_review(review_id: str):
        meta = _meta_or_404(review_id)
        review = store.load_review(review_id) if meta["status"] == "done" else None
        return {"meta": meta, "review": review_to_dict(review) if review else None}

    @app.get("/api/reviews/{review_id}/report.xlsx")
    def download(review_id: str):
        meta = _meta_or_404(review_id)
        path = store.report_path(review_id)
        if not path.exists():
            raise HTTPException(404, "The report is not ready yet.")
        safe = "".join(ch if ch.isalnum() or ch in " -_" else "_" for ch in meta["title"])[:60].strip() or "review"
        return FileResponse(
            path,
            filename=f"{safe} ESG DDQ.xlsx",
            media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        )

    def _meta_or_404(review_id: str) -> dict:
        try:
            return store.meta(review_id)
        except KeyError:
            raise HTTPException(404, "Review not found.") from None

    app.state.store = store
    app.state.pool = pool
    return app
