"""Fines & Regs: which local benchmarking or performance laws cover the building."""

from __future__ import annotations

from importlib import resources

import yaml

from ..models import ConnectorStatus
from .base import Connector, ConnectorContext


def load_rules() -> list[dict]:
    return yaml.safe_load(resources.files("ddq_agent.data").joinpath("regulations.yaml").read_text())


def matching_rules(city: str | None, state: str | None, sqft: float | None, rules: list[dict]) -> list[dict]:
    city, state = (city or "").strip().lower(), (state or "").strip().lower()
    hits = []
    for rule in rules:
        m = rule.get("match", {})
        if m.get("state") and m["state"] != state:
            continue
        if m.get("city") and m["city"] != city:
            continue
        covered = sqft is None or sqft >= rule.get("applies_over_sqft", 0)
        hits.append({**rule, "covered": covered})
    return hits


class FinesRegs(Connector):
    name = "fines_regs"
    description = "Local energy benchmarking and building performance standards, with penalties."

    def fetch(self, ctx: ConnectorContext):
        p = ctx.profile
        sqft = p.gross_floor_area_sqft or p.rentable_area_sqft
        hits = matching_rules(p.city, p.state, sqft, load_rules())
        if not hits:
            return self.result(
                ConnectorStatus.NO_DATA,
                f"No rule in the local table for {p.city}, {p.state}. Confirm with web search.",
                source="ddq_agent/data/regulations.yaml",
            )
        lines = []
        for h in hits:
            scope = "covers this building" if h["covered"] else f"applies over {h['applies_over_sqft']:,} sf, likely not covered"
            lines.append(f"{h['name']} ({h['kind']}, {scope}): {h['summary']} Penalty: {h['penalty']} [{h['url']}]")
        return self.result(
            ConnectorStatus.OK,
            " | ".join(lines) + " Thresholds and deadlines must be confirmed against the current ordinance.",
            {"rules": hits},
            source="ddq_agent/data/regulations.yaml",
        )
