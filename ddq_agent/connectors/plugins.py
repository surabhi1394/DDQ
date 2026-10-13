"""Connectors that need access you don't have yet. Each one is wired into the pipeline and
reports NOT_CONFIGURED until its credentials are set; fill in fetch() when access arrives.
"""

from __future__ import annotations

import os

from ..models import ConnectorStatus
from .base import Connector, ConnectorContext


class Audette(Connector):
    """Audette decarbonization and retrofit modelling.

    To plug in: set AUDETTE_API_KEY (and AUDETTE_BASE_URL if Audette gives you one), then
    replace the body of fetch() with the calls from Audette's API docs. Return the
    building's modelled measures (name, capex, energy and carbon savings, timing) in
    `data["measures"]`; the Retrofit Specialist already reads that key and will prefer
    Audette's numbers over its own estimates.
    """

    name = "audette"
    description = "Audette: modelled retrofit measures, capex and carbon savings."
    required_env = ("AUDETTE_API_KEY",)

    def fetch(self, ctx: ConnectorContext):
        return self.result(
            ConnectorStatus.NOT_CONFIGURED,
            "AUDETTE_API_KEY is set but the Audette client is not implemented yet (see connectors/plugins.py).",
        )


class Physrisk(Connector):
    """OS-Climate physrisk hazard indicators (flood, heat, wind, drought) under climate scenarios.

    physrisk is open source but runs as your own service. Point PHYSRISK_API_URL at a
    deployment of physrisk-api; the request below follows its hazard-data endpoint and
    may need adjusting to the version you deploy.
    """

    name = "physrisk"
    description = "OS-Climate physrisk: physical climate hazard indicators for the location."
    required_env = ("PHYSRISK_API_URL",)
    hazards = (
        ("RiverineInundation", "flood_depth"),
        ("CoastalInundation", "flood_depth"),
        ("ChronicHeat", "days_tas_above_35c"),
        ("Wind", "max_speed"),
    )

    def fetch(self, ctx: ConnectorContext):
        if ctx.latitude is None:
            return self.result(ConnectorStatus.NO_DATA, "No coordinates (geocode did not succeed).")
        scenario = os.environ.get("PHYSRISK_SCENARIO", "ssp585")
        year = int(os.environ.get("PHYSRISK_YEAR", "2050"))
        body = {
            "items": [
                {
                    "request_item_id": hazard,
                    "hazard_type": hazard,
                    "indicator_id": indicator,
                    "longitudes": [ctx.longitude],
                    "latitudes": [ctx.latitude],
                    "scenario": scenario,
                    "year": year,
                }
                for hazard, indicator in self.hazards
            ]
        }
        resp = ctx.client().post(os.environ["PHYSRISK_API_URL"].rstrip("/") + "/api/get_hazard_data", json=body)
        resp.raise_for_status()
        payload = resp.json()
        return self.result(
            ConnectorStatus.OK,
            f"physrisk hazard indicators for {scenario} {year} returned for {len(self.hazards)} hazards.",
            {"scenario": scenario, "year": year, "response": payload},
            source=f"OS-Climate physrisk ({scenario}, {year})",
        )


class Bpd(Connector):
    """LBNL Building Performance Database peer benchmarks.

    Needs a BPD API key (BPD_API_KEY). Implement fetch() against the BPD API to return
    the peer EUI distribution for the property's type and climate zone in data["peers"].
    """

    name = "bpd"
    description = "LBNL Building Performance Database: peer EUI distribution for similar buildings."
    required_env = ("BPD_API_KEY",)

    def fetch(self, ctx: ConnectorContext):
        return self.result(
            ConnectorStatus.NOT_CONFIGURED,
            "BPD_API_KEY is set but the BPD client is not implemented yet (see connectors/plugins.py).",
        )
