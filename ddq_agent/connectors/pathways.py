"""File-based decarbonization datasets: CRREM pathways and NREL Cambium emission factors.

Both datasets are downloaded by you (CRREM is licensed; Cambium is a free NREL download)
and converted to small CSVs, so no data is bundled here.

CRREM_PATHWAYS_CSV columns:
    country, property_type, year, energy_kwh_m2, carbon_kgco2e_m2
CAMBIUM_CSV columns:
    state, year, scenario, lrmer_kg_per_mwh
"""

from __future__ import annotations

import csv
import os
from pathlib import Path

from ..models import ConnectorStatus
from .base import Connector, ConnectorContext

KBTU_PER_SQFT_TO_KWH_PER_M2 = 3.15459
SQFT_PER_M2 = 10.7639


def _read_csv(path: str) -> list[dict[str, str]]:
    with Path(path).open(newline="") as f:
        return list(csv.DictReader(f))


def stranding_year(intensity: float, pathway: dict[int, float]) -> int | None:
    """First year the pathway limit drops below the building's (flat) intensity."""
    for year in sorted(pathway):
        if pathway[year] < intensity:
            return year
    return None


def building_eui(ctx: ConnectorContext) -> tuple[float | None, str]:
    es = ctx.results.get("energy_star")
    if es and es.status == ConnectorStatus.OK:
        for key in ("siteIntensityWN", "siteIntensity"):
            if es.data.get(key):
                return float(es.data[key]), "ENERGY STAR Portfolio Manager"
    if ctx.profile.site_eui_kbtu_sqft:
        return ctx.profile.site_eui_kbtu_sqft, "Offering Memorandum"
    return None, ""


def building_carbon_kg_m2(ctx: ConnectorContext) -> float | None:
    es = ctx.results.get("energy_star")
    gfa = ctx.profile.gross_floor_area_sqft or ctx.profile.rentable_area_sqft
    if es and es.status == ConnectorStatus.OK and es.data.get("totalLocationBasedGHGEmissions") and gfa:
        tonnes = float(es.data["totalLocationBasedGHGEmissions"])  # metric tons CO2e per year
        return tonnes * 1000 / (gfa / SQFT_PER_M2)
    return None


class Crrem(Connector):
    name = "crrem"
    description = "CRREM pathways: the year the building's energy and carbon intensity strand against 1.5C targets."
    required_env = ("CRREM_PATHWAYS_CSV",)

    def fetch(self, ctx: ConnectorContext):
        eui, eui_source = building_eui(ctx)
        if eui is None:
            return self.result(ConnectorStatus.NO_DATA, "No site EUI from ENERGY STAR or the OM to compare.")
        ptype = (ctx.profile.property_type or "office").lower()
        country = (ctx.profile.country or "US").upper()
        rows = [
            r for r in _read_csv(os.environ["CRREM_PATHWAYS_CSV"])
            if r["country"].upper() == country and r["property_type"].lower() == ptype
        ]
        if not rows:
            return self.result(ConnectorStatus.NO_DATA, f"No CRREM pathway rows for {country} / {ptype}.")
        energy_path = {int(r["year"]): float(r["energy_kwh_m2"]) for r in rows if r.get("energy_kwh_m2")}
        carbon_path = {int(r["year"]): float(r["carbon_kgco2e_m2"]) for r in rows if r.get("carbon_kgco2e_m2")}
        eui_kwh_m2 = eui * KBTU_PER_SQFT_TO_KWH_PER_M2
        data = {
            "site_eui_kbtu_sqft": eui,
            "site_eui_kwh_m2": round(eui_kwh_m2, 1),
            "eui_source": eui_source,
            "energy_stranding_year": stranding_year(eui_kwh_m2, energy_path),
        }
        carbon = building_carbon_kg_m2(ctx)
        if carbon is not None and carbon_path:
            data["carbon_kgco2e_m2"] = round(carbon, 1)
            data["carbon_stranding_year"] = stranding_year(carbon, carbon_path)
        parts = [f"Site EUI {eui} kBtu/sf ({data['site_eui_kwh_m2']} kWh/m2, from {eui_source})"]
        parts.append(
            f"energy pathway strands in {data['energy_stranding_year']}"
            if data["energy_stranding_year"] else "within the energy pathway through its last year"
        )
        if "carbon_stranding_year" in data:
            parts.append(
                f"carbon {data['carbon_kgco2e_m2']} kgCO2e/m2 strands in {data['carbon_stranding_year']}"
                if data["carbon_stranding_year"] else "within the carbon pathway"
            )
        return self.result(ConnectorStatus.OK, "; ".join(parts) + ".", data, f"CRREM pathways ({country}, {ptype})")


class Cambium(Connector):
    name = "cambium"
    description = "NREL Cambium: projected long-run marginal grid emission factors for the property's state."
    required_env = ("CAMBIUM_CSV",)

    def fetch(self, ctx: ConnectorContext):
        state = (ctx.profile.state or "").upper()
        if not state:
            return self.result(ConnectorStatus.NO_DATA, "No state in the OM.")
        rows = [r for r in _read_csv(os.environ["CAMBIUM_CSV"]) if r["state"].upper() == state]
        if not rows:
            return self.result(ConnectorStatus.NO_DATA, f"No Cambium rows for {state}.")
        factors = {f"{r['scenario']}:{r['year']}": float(r["lrmer_kg_per_mwh"]) for r in rows}
        shown = ", ".join(f"{k} {v:.0f} kg/MWh" for k, v in sorted(factors.items()))
        return self.result(
            ConnectorStatus.OK,
            f"Long-run marginal grid emissions for {state}: {shown}.",
            {"state": state, "lrmer_kg_per_mwh": factors},
            "NREL Cambium",
        )
