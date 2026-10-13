"""DDQ web tool: start a review from an address or an OM, follow its progress, read the dashboard,
download the Excel. Run with `ddq serve`."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from importlib import resources
from pathlib import Path
from typing import Callable

from fastapi import Body, FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, Response

from .pipeline import Review, run_review
from .report import write_report
from .store import Store, review_to_dict, summarize

from . import settings
from .llm import SUPPORTED_SUFFIXES

# Documents are sent base64-encoded with each model request, which has a 32 MB limit.
MAX_UPLOAD_BYTES = 22 * 1024 * 1024
DOCUMENT_LABELS = [
    "Offering Memorandum", "Property Condition Assessment", "Phase I ESA", "Energy audit",
    "Utility data", "ENERGY STAR / benchmarking report", "Lease", "Certification", "Other",
]


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
                address=meta["address"] or None,
                documents=[(Path(d["path"]), f"{d['label']}: {d['name']}") for d in meta["documents"]],
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
    async def create_review(
        address: str = Form(""),
        files: list[UploadFile] = File(default=[]),
        labels: list[str] = Form(default=[]),
    ):
        address = address.strip()
        documents = []
        for n, upload in enumerate(f for f in files if f.filename):
            content = await upload.read()
            suffix = Path(upload.filename).suffix.lower()
            if suffix not in SUPPORTED_SUFFIXES:
                raise HTTPException(400, f"{upload.filename}: use PDF, image, Excel, CSV or text files.")
            if suffix == ".pdf" and not content.startswith(b"%PDF"):
                raise HTTPException(400, f"{upload.filename} is not a valid PDF.")
            label = labels[n] if n < len(labels) and labels[n] in DOCUMENT_LABELS else "Other"
            documents.append((upload.filename, label, content))
        if not address and not documents:
            raise HTTPException(400, "Enter an address or upload at least one document.")
        if sum(len(d[2]) for d in documents) > MAX_UPLOAD_BYTES:
            raise HTTPException(400, "Documents total more than 22 MB. Remove some or upload smaller files.")
        meta = store.create(address or None, documents)
        pool.submit(execute, meta["id"])
        return meta

    @app.get("/api/document-labels")
    def document_labels():
        return DOCUMENT_LABELS

    @app.get("/settings", response_class=HTMLResponse)
    def settings_page():
        return _page("settings.html")

    @app.get("/api/settings")
    def get_settings():
        return settings.describe()

    @app.post("/api/settings")
    def save_settings(body: dict = Body(...)):
        values = body.get("values", {})
        try:
            settings.set_values({k: (None if v is None else str(v)) for k, v in values.items()})
        except KeyError as exc:
            raise HTTPException(400, f"Unknown setting {exc}") from None
        return settings.describe()

    @app.post("/api/settings/file")
    async def save_settings_file(key: str = Form(...), file: UploadFile = File(...)):
        field = next((f for f in settings.FIELDS if f.key == key and f.kind == "file"), None)
        if field is None:
            raise HTTPException(400, "That setting does not take a file.")
        path = settings.data_file_path(key, file.filename or "data.csv")
        path.write_bytes(await file.read())
        settings.set_values({key: str(path.resolve())})
        return settings.describe()

    @app.post("/api/settings/sources", status_code=201)
    def add_source(body: dict = Body(...)):
        try:
            settings.add_custom_source(
                body.get("name", ""), body.get("url", ""), body.get("header_name", ""),
                body.get("header_value", ""), body.get("notes", ""),
            )
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from None
        return settings.describe()

    @app.delete("/api/settings/sources/{source_id}")
    def remove_source(source_id: str):
        settings.remove_custom_source(source_id)
        return settings.describe()

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
