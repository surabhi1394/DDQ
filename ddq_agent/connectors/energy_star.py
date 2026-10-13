"""ENERGY STAR Portfolio Manager web services.

Needs a Portfolio Manager account the property is shared with:
ESPM_USERNAME, ESPM_PASSWORD, and a property id (from the OM, or ESPM_PROPERTY_ID).
Metric names can be changed with ESPM_METRICS (comma separated, Portfolio Manager names).
"""

from __future__ import annotations

import datetime as dt
import os
import xml.etree.ElementTree as ET

from ..models import ConnectorStatus
from .base import Connector, ConnectorContext

ESPM_BASE = os.environ.get("ESPM_BASE_URL", "https://portfoliomanager.energystar.gov/ws")
DEFAULT_METRICS = "score,siteIntensityWN,sourceIntensityWN,totalLocationBasedGHGEmissions"


def parse_metrics(xml_text: str) -> dict[str, str]:
    root = ET.fromstring(xml_text)
    out = {}
    for metric in root.iter("metric"):
        value = metric.findtext("value")
        if value not in (None, ""):
            out[metric.get("name")] = value
    return out


class EnergyStar(Connector):
    name = "energy_star"
    description = "ENERGY STAR Portfolio Manager: score, weather-normalized EUI and GHG emissions."
    required_env = ("ESPM_USERNAME", "ESPM_PASSWORD")

    def fetch(self, ctx: ConnectorContext):
        prop_id = ctx.profile.espm_property_id or os.environ.get("ESPM_PROPERTY_ID")
        if not prop_id:
            return self.result(ConnectorStatus.NO_DATA, "No Portfolio Manager property id in the OM or ESPM_PROPERTY_ID.")
        year = dt.date.today().year - 1
        resp = ctx.client().get(
            f"{ESPM_BASE}/property/{prop_id}/metrics",
            params={"year": year, "month": 12, "measurementSystem": "EPA"},
            headers={"PM-Metrics": os.environ.get("ESPM_METRICS", DEFAULT_METRICS)},
            auth=(os.environ["ESPM_USERNAME"], os.environ["ESPM_PASSWORD"]),
        )
        resp.raise_for_status()
        metrics = parse_metrics(resp.text)
        if not metrics:
            return self.result(ConnectorStatus.NO_DATA, f"Portfolio Manager returned no metrics for {year}.")
        summary = ", ".join(f"{k}={v}" for k, v in metrics.items())
        return self.result(
            ConnectorStatus.OK,
            f"Portfolio Manager property {prop_id}, period ending Dec {year}: {summary}.",
            {"property_id": prop_id, "year": year, **metrics},
            source=f"ENERGY STAR Portfolio Manager property {prop_id}",
        )
