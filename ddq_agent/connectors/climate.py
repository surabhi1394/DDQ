"""Free climate and hazard services (FEMA National Risk Index, USGS), First Street, and
user-defined custom sources from the Settings page."""

from __future__ import annotations

import json
import os
from urllib.parse import quote

from .. import settings
from ..models import ConnectorResult, ConnectorStatus
from .base import Connector, ConnectorContext

# FEMA's ArcGIS Online feature service for the National Risk Index at census-tract level.
NRI_URL = os.environ.get(
    "NRI_URL",
    "https://services.arcgis.com/XG15cJAlne2vxtgt/arcgis/rest/services/National_Risk_Index_Census_Tracts/FeatureServer/0/query",
)
USGS_DESIGN_MAPS_URL = "https://earthquake.usgs.gov/ws/designmaps/asce7-22.json"
USGS_ELEVATION_URL = "https://epqs.nationalmap.gov/v1/json"
FIRST_STREET_URL = os.environ.get(
    "FIRST_STREET_URL", "https://api.firststreet.org/v1/location/summary/property?lat={lat}&lng={lon}"
)

NRI_HAZARDS = {
    "AVLN": "Avalanche", "CFLD": "Coastal flooding", "CWAV": "Cold wave", "DRGT": "Drought",
    "ERQK": "Earthquake", "HAIL": "Hail", "HWAV": "Heat wave", "HRCN": "Hurricane",
    "ISTM": "Ice storm", "LNDS": "Landslide", "LTNG": "Lightning", "RFLD": "Riverine flooding",
    "SWND": "Strong wind", "TRND": "Tornado", "TSUN": "Tsunami", "VLCN": "Volcanic activity",
    "WFIR": "Wildfire", "WNTW": "Winter weather",
}
ELEVATED = {"Relatively High", "Very High"}
MAX_RAW_CHARS = 20_000


def _needs_location(connector: Connector, ctx: ConnectorContext) -> ConnectorResult | None:
    if ctx.latitude is None or ctx.longitude is None:
        return connector.result(ConnectorStatus.NO_DATA, "No coordinates (geocode did not succeed).")
    return None


def summarize_nri(attrs: dict) -> tuple[str, dict]:
    hazards = {
        label: attrs.get(f"{code}_RISKR")
        for code, label in NRI_HAZARDS.items()
        if attrs.get(f"{code}_RISKR") not in (None, "", "Not Applicable", "Insufficient Data", "No Rating")
    }
    data = {
        "tract": attrs.get("TRACTFIPS"),
        "county": attrs.get("COUNTY"),
        "overall_risk": attrs.get("RISK_RATNG"),
        "risk_score": attrs.get("RISK_SCORE"),
        "expected_annual_loss": attrs.get("EAL_RATNG"),
        "social_vulnerability": attrs.get("SOVI_RATNG"),
        "community_resilience": attrs.get("RESL_RATNG"),
        "hazards": hazards,
    }
    elevated = [f"{h} ({r})" for h, r in hazards.items() if r in ELEVATED]
    summary = f"FEMA National Risk Index for census tract {data['tract']}: overall risk {data['overall_risk']}"
    summary += f"; elevated hazards: {', '.join(elevated)}." if elevated else "; no hazard rated relatively high or above."
    return summary, data


class FemaRiskIndex(Connector):
    name = "fema_nri"
    description = "FEMA National Risk Index: census-tract risk ratings for 18 natural hazards."

    def fetch(self, ctx: ConnectorContext):
        if (missing := _needs_location(self, ctx)) is not None:
            return missing
        resp = ctx.client().get(
            NRI_URL,
            params={
                "geometry": f"{ctx.longitude},{ctx.latitude}",
                "geometryType": "esriGeometryPoint",
                "inSR": "4326",
                "spatialRel": "esriSpatialRelIntersects",
                "outFields": "*",
                "returnGeometry": "false",
                "f": "json",
            },
        )
        resp.raise_for_status()
        features = resp.json().get("features", [])
        if not features:
            return self.result(ConnectorStatus.NO_DATA, "No National Risk Index tract at this location.", source="FEMA NRI")
        summary, data = summarize_nri(features[0]["attributes"])
        return self.result(ConnectorStatus.OK, summary, data, "FEMA National Risk Index (census tract)")


class UsgsSeismic(Connector):
    name = "usgs_seismic"
    description = "USGS seismic design values (ASCE 7-22) for the location."
    fields = ("pgam", "ss", "s1", "sms", "sm1", "sds", "sd1", "sdc")

    def fetch(self, ctx: ConnectorContext):
        if (missing := _needs_location(self, ctx)) is not None:
            return missing
        resp = ctx.client().get(
            USGS_DESIGN_MAPS_URL,
            params={"latitude": ctx.latitude, "longitude": ctx.longitude, "riskCategory": "II",
                    "siteClass": "Default", "title": "DDQ"},
        )
        resp.raise_for_status()
        raw = resp.json().get("response", {}).get("data", {})
        data = {k: raw[k] for k in self.fields if raw.get(k) is not None}
        if not data:
            return self.result(ConnectorStatus.NO_DATA, "USGS returned no design values.", source="USGS Design Maps")
        parts = [f"{k.upper()} {v}" for k, v in data.items()]
        return self.result(
            ConnectorStatus.OK,
            "USGS ASCE 7-22 seismic design values (Risk Category II, default site class): " + ", ".join(parts) + ".",
            data,
            "USGS Seismic Design Web Services (ASCE 7-22)",
        )


class UsgsElevation(Connector):
    name = "usgs_elevation"
    description = "USGS 3DEP ground elevation at the location (context for flood exposure)."

    def fetch(self, ctx: ConnectorContext):
        if (missing := _needs_location(self, ctx)) is not None:
            return missing
        resp = ctx.client().get(
            USGS_ELEVATION_URL,
            params={"x": ctx.longitude, "y": ctx.latitude, "wkid": 4326, "units": "Feet", "includeDate": "false"},
        )
        resp.raise_for_status()
        value = resp.json().get("value")
        try:
            feet = round(float(value), 1)
        except (TypeError, ValueError):
            return self.result(ConnectorStatus.NO_DATA, "USGS returned no elevation.", source="USGS EPQS")
        return self.result(
            ConnectorStatus.OK, f"Ground elevation about {feet} ft above sea level.", {"elevation_ft": feet},
            "USGS 3DEP Elevation Point Query Service",
        )


def fill_template(url: str, ctx: ConnectorContext) -> str:
    p = ctx.profile
    address = ", ".join(x for x in (p.street_address, p.city, p.state, p.postal_code) if x)
    values = {
        "lat": "" if ctx.latitude is None else f"{ctx.latitude:.6f}",
        "lon": "" if ctx.longitude is None else f"{ctx.longitude:.6f}",
        "address": address, "street": p.street_address or "", "city": p.city or "",
        "state": p.state or "", "zip": p.postal_code or "",
    }
    return url.format(**{k: quote(v, safe="") for k, v in values.items()})


def _raw_payload(resp) -> tuple[str, dict]:
    try:
        payload = resp.json()
        text = json.dumps(payload)
    except ValueError:
        text = resp.text
    clipped = text[:MAX_RAW_CHARS]
    return clipped, {"response": clipped, "truncated": len(text) > MAX_RAW_CHARS}


class FirstStreet(Connector):
    """First Street property-level climate risk (flood, fire, heat, wind, air).

    Needs a First Street API key. The lookup URL can be changed with FIRST_STREET_URL to match
    the endpoint in your First Street API account. Without a key, the research step still reads
    First Street's free Risk Factor pages through web search.
    """

    name = "first_street"
    description = "First Street: property-level flood, fire, heat, wind and air quality risk."
    required_env = ("FIRST_STREET_API_KEY",)

    def fetch(self, ctx: ConnectorContext):
        if (missing := _needs_location(self, ctx)) is not None:
            return missing
        resp = ctx.client().get(
            fill_template(FIRST_STREET_URL, ctx),
            headers={"Authorization": f"Bearer {settings.get('FIRST_STREET_API_KEY')}"},
        )
        resp.raise_for_status()
        text, data = _raw_payload(resp)
        return self.result(
            ConnectorStatus.OK, "First Street risk data returned (see raw response).", data, "First Street API"
        )


class CustomSource(Connector):
    """A JSON or text API the team added in Settings, called with the property's location."""

    description = "Custom source added in Settings."

    def __init__(self, source: dict):
        self.source = source
        self.name = f"custom:{source['id']}"
        self.description = source.get("notes") or f"Custom source: {source['name']}"

    def fetch(self, ctx: ConnectorContext):
        url = self.source["url"]
        if ("{lat}" in url or "{lon}" in url) and ctx.latitude is None:
            return self.result(ConnectorStatus.NO_DATA, "No coordinates (geocode did not succeed).")
        headers = {}
        if self.source.get("header_name") and self.source.get("header_value"):
            headers[self.source["header_name"]] = self.source["header_value"]
        resp = ctx.client().get(fill_template(url, ctx), headers=headers)
        resp.raise_for_status()
        text, data = _raw_payload(resp)
        return self.result(
            ConnectorStatus.OK, f"{self.source['name']} returned data (see raw response).", data, self.source["name"]
        )
