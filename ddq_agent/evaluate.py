"""Score a generated DDQ against one the team completed by hand for the same property."""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

import openpyxl

HEADER = "ESG Consideration"


def _norm(text) -> str:
    return re.sub(r"[^a-z0-9]+", " ", str(text or "").lower()).strip()


def read_answers(path: Path) -> dict[str, dict[str, str]]:
    """Map normalized question text to its Response and Priority, for either layout."""
    ws = openpyxl.load_workbook(path, data_only=True).active
    out: dict[str, dict[str, str]] = {}
    cols: dict[str, int] = {}
    for row in ws.iter_rows(values_only=True):
        first = str(row[0]).strip() if row and row[0] is not None else ""
        if first == HEADER:
            cols = {str(v).strip(): i for i, v in enumerate(row) if v is not None}
            continue
        if not cols or not first or row[cols["Response"]] is None:
            continue
        out[_norm(first)] = {
            "response": str(row[cols["Response"]]).strip().upper(),
            "priority": str(row[cols["Priority"]] or "").strip().upper() if "Priority" in cols else "",
        }
    return out


@dataclass
class Score:
    compared: int
    response_matches: int
    priority_matches: int
    mismatches: list[tuple[str, str, str]]

    @property
    def response_accuracy(self) -> float:
        return self.response_matches / self.compared if self.compared else 0.0

    @property
    def priority_accuracy(self) -> float:
        return self.priority_matches / self.compared if self.compared else 0.0


def score(generated: Path, expected: Path) -> Score:
    got, want = read_answers(generated), read_answers(expected)
    common = [q for q in want if q in got]
    mismatches = [(q, want[q]["response"], got[q]["response"]) for q in common if want[q]["response"] != got[q]["response"]]
    return Score(
        compared=len(common),
        response_matches=len(common) - len(mismatches),
        priority_matches=sum(1 for q in common if want[q]["priority"] == got[q]["priority"]),
        mismatches=mismatches,
    )
