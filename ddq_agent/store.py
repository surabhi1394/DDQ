"""Reviews on disk: one folder per review with its input, status, results and Excel report."""

from __future__ import annotations

import datetime as dt
import json
import os
import re
import secrets
import threading
from pathlib import Path

from .models import ConnectorResult, PropertyProfile, ReportRow
from .pipeline import Review

_lock = threading.Lock()


def data_dir() -> Path:
    path = Path(os.environ.get("DDQ_DATA_DIR", "ddq_data"))
    path.mkdir(parents=True, exist_ok=True)
    return path


def review_to_dict(review: Review) -> dict:
    return {
        "profile": review.profile.model_dump(mode="json"),
        "connectors": [c.model_dump(mode="json") for c in review.connectors],
        "research_notes": review.research_notes,
        "rows": [r.model_dump(mode="json") for r in review.rows],
        "rounds": review.rounds,
        "log": review.log,
    }


def review_from_dict(data: dict) -> Review:
    return Review(
        profile=PropertyProfile(**data["profile"]),
        connectors=[ConnectorResult(**c) for c in data["connectors"]],
        research_notes=data["research_notes"],
        rows=[ReportRow(**r) for r in data["rows"]],
        rounds=data.get("rounds", 0),
        log=data.get("log", []),
    )


class Store:
    def __init__(self, root: Path | None = None):
        self.root = Path(root) if root else data_dir()
        self.root.mkdir(parents=True, exist_ok=True)

    def folder(self, review_id: str) -> Path:
        if not re.fullmatch(r"[0-9a-z-]+", review_id):
            raise KeyError(review_id)
        path = self.root / review_id
        if not path.is_dir():
            raise KeyError(review_id)
        return path

    def create(self, address: str | None, om_name: str | None, om_bytes: bytes | None) -> dict:
        review_id = dt.datetime.now().strftime("%Y%m%d-%H%M%S") + "-" + secrets.token_hex(3)
        folder = self.root / review_id
        folder.mkdir()
        om_path = None
        if om_bytes:
            om_path = folder / "om.pdf"
            om_path.write_bytes(om_bytes)
        meta = {
            "id": review_id,
            "address": address or "",
            "om_name": om_name or "",
            "om_path": str(om_path) if om_path else "",
            "title": address or om_name or review_id,
            "created_at": dt.datetime.now().isoformat(timespec="seconds"),
            "status": "queued",
            "steps": [],
            "error": "",
            "summary": {},
        }
        self._write_meta(folder, meta)
        return meta

    def meta(self, review_id: str) -> dict:
        return json.loads((self.folder(review_id) / "meta.json").read_text())

    def update(self, review_id: str, **changes) -> dict:
        with _lock:
            meta = self.meta(review_id)
            if "step" in changes:
                meta["steps"].append(changes.pop("step"))
            meta.update(changes)
            self._write_meta(self.folder(review_id), meta)
            return meta

    def save_review(self, review_id: str, review: Review) -> None:
        (self.folder(review_id) / "review.json").write_text(json.dumps(review_to_dict(review), indent=1))

    def load_review(self, review_id: str) -> Review | None:
        path = self.folder(review_id) / "review.json"
        return review_from_dict(json.loads(path.read_text())) if path.exists() else None

    def report_path(self, review_id: str) -> Path:
        return self.folder(review_id) / "report.xlsx"

    def list(self) -> list[dict]:
        metas = []
        for meta_file in self.root.glob("*/meta.json"):
            try:
                metas.append(json.loads(meta_file.read_text()))
            except (OSError, json.JSONDecodeError):
                continue
        return sorted(metas, key=lambda m: m["created_at"], reverse=True)

    @staticmethod
    def _write_meta(folder: Path, meta: dict) -> None:
        tmp = folder / "meta.json.tmp"
        tmp.write_text(json.dumps(meta, indent=1))
        tmp.replace(folder / "meta.json")


RANK = {"LOW": 1, "MODERATE": 2, "HIGH": 3}


def level(answer) -> str:
    """The higher of an answer's priority and risk; what the dashboard and summary count by."""
    return max((answer.priority, answer.risk), key=RANK.__getitem__)


def summarize(review: Review) -> dict:
    rows = review.rows
    count = lambda pred: sum(1 for r in rows if pred(r))  # noqa: E731
    return {
        "questions": len(rows),
        "verified": count(lambda r: r.verified),
        "needs_review": count(lambda r: not r.verified),
        "confirm_on_site": count(lambda r: r.answer.confirm_on_site),
        "high_risk": count(lambda r: level(r.answer) == "HIGH"),
        "moderate_risk": count(lambda r: level(r.answer) == "MODERATE"),
        "with_cost": count(lambda r: bool(r.answer.cost_estimate.strip())),
        "connectors_ok": sum(1 for c in review.connectors if c.status.value == "ok"),
        "connectors_total": len(review.connectors),
    }
