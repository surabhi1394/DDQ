"""Free public location services: US Census geocoder and FEMA flood zones (NFHL)."""

from __future__ import annotations

from ..models import ConnectorStatus
from .base import Connector, ConnectorContext

CENSUS_URL = "https://geocoding.geo.census.gov/geocoder/locations/onelineaddress"
# National Flood Hazard Layer, layer 28 = Flood Hazard Zones.
NFHL_URL = "https://hazards.fema.gov/arcgis/rest/services/public/NFHL/MapServer/28/query"


class Geocode(Connector):
    name = "geocode"
    description = "US Census geocoder: address to latitude/longitude (needed by location-based connectors)."

    def fetch(self, ctx: ConnectorContext):
        p = ctx.profile
        parts = [p.street_address, p.city, p.state, p.postal_code]
        if not p.street_address or not (p.city or p.postal_code):
            return self.result(ConnectorStatus.NO_DATA, "OM did not give a full street address.")
        address = ", ".join(x for x in parts if x)
        resp = ctx.client().get(
            CENSUS_URL, params={"address": address, "benchmark": "Public_AR_Current", "format": "json"}
        )
        resp.raise_for_status()
        matches = resp.json().get("result", {}).get("addressMatches", [])
        if not matches:
            return self.result(ConnectorStatus.NO_DATA, f"No geocoder match for '{address}'.", source=CENSUS_URL)
        coords = matches[0]["coordinates"]
        ctx.latitude, ctx.longitude = coords["y"], coords["x"]
        return self.result(
            ConnectorStatus.OK,
            f"Matched '{matches[0].get('matchedAddress', address)}' at {ctx.latitude:.5f}, {ctx.longitude:.5f}.",
            {"latitude": ctx.latitude, "longitude": ctx.longitude, "matched_address": matches[0].get("matchedAddress")},
            source="US Census Geocoder",
        )


class FemaFlood(Connector):
    name = "fema_flood"
    description = "FEMA National Flood Hazard Layer: flood zone at the property's location."

    def fetch(self, ctx: ConnectorContext):
        if ctx.latitude is None or ctx.longitude is None:
            return self.result(ConnectorStatus.NO_DATA, "No coordinates (geocode did not succeed).")
        resp = ctx.client().get(
            NFHL_URL,
            params={
                "geometry": f"{ctx.longitude},{ctx.latitude}",
                "geometryType": "esriGeometryPoint",
                "inSR": "4326",
                "spatialRel": "esriSpatialRelIntersects",
                "outFields": "FLD_ZONE,ZONE_SUBTY,SFHA_TF",
                "returnGeometry": "false",
                "f": "json",
            },
        )
        resp.raise_for_status()
        features = resp.json().get("features", [])
        if not features:
            return self.result(
                ConnectorStatus.NO_DATA, "Location is not inside a mapped NFHL flood zone polygon.", source="FEMA NFHL"
            )
        attrs = features[0]["attributes"]
        sfha = attrs.get("SFHA_TF") == "T"
        zone = attrs.get("FLD_ZONE")
        subtype = attrs.get("ZONE_SUBTY") or ""
        summary = f"FEMA flood zone {zone}{' (' + subtype + ')' if subtype else ''}; " + (
            "inside the Special Flood Hazard Area (1% annual chance)." if sfha else "outside the Special Flood Hazard Area."
        )
        return self.result(ConnectorStatus.OK, summary, {"zone": zone, "subtype": subtype, "sfha": sfha}, "FEMA NFHL")
