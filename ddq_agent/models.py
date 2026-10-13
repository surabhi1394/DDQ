"""Data shapes shared across the pipeline."""

from __future__ import annotations

from enum import Enum
from typing import Any, Literal, Optional

from pydantic import BaseModel, Field


class PropertyProfile(BaseModel):
    """Facts pulled from the Offering Memorandum. Unknown fields stay null."""

    name: Optional[str] = None
    street_address: Optional[str] = None
    city: Optional[str] = None
    state: Optional[str] = None
    postal_code: Optional[str] = None
    country: str = "US"
    property_type: Optional[str] = Field(None, description="e.g. Office, Multifamily, Industrial, Retail")
    year_built: Optional[int] = None
    gross_floor_area_sqft: Optional[float] = None
    rentable_area_sqft: Optional[float] = None
    floors: Optional[int] = None
    site_acres: Optional[float] = None
    parcel_numbers: list[str] = []
    zoning: Optional[str] = None
    certifications: list[str] = Field([], description="e.g. LEED Gold O+M, ENERGY STAR")
    energy_star_score: Optional[int] = None
    site_eui_kbtu_sqft: Optional[float] = None
    espm_property_id: Optional[str] = Field(None, description="ENERGY STAR Portfolio Manager property id, if stated")
    heating_fuel: Optional[str] = None
    hvac_summary: Optional[str] = None
    lighting_summary: Optional[str] = None
    water_fixtures_summary: Optional[str] = None
    backup_power_summary: Optional[str] = None
    ev_chargers: Optional[str] = None
    utilities: Optional[str] = None
    waste_summary: Optional[str] = None
    facade_and_glazing: Optional[str] = None
    roofing: Optional[str] = None
    known_issues: list[str] = Field([], description="Defects, remediation work, disclosures")
    tenants: list[str] = []
    other_notes: list[str] = []


class ConnectorStatus(str, Enum):
    OK = "ok"
    NOT_CONFIGURED = "not_configured"
    NO_DATA = "no_data"
    ERROR = "error"


class ConnectorResult(BaseModel):
    connector: str
    status: ConnectorStatus
    summary: str = ""
    data: dict[str, Any] = {}
    source: str = Field("", description="Citation string: dataset, URL, or API endpoint")


class ChecklistItem(BaseModel):
    id: str
    section: str
    question: str
    type: str = ""
    timing: Literal["Pre", "Post", "Pre/Post", ""] = ""


class ChecklistAnswer(BaseModel):
    id: str
    response: Literal["Y", "N", "N/A", "TBD"]
    existing_conditions: str
    mitigation: str = ""
    priority: Literal["LOW", "MODERATE", "HIGH"] = "LOW"
    risk: Literal["LOW", "MODERATE", "HIGH"] = "LOW"
    cost_estimate: str = ""
    sources: list[str] = Field([], description="OM page refs, connector names, or URLs backing the answer")
    confirm_on_site: bool = False


class Verdict(BaseModel):
    id: str
    passed: bool
    issue: str = ""


class ReportRow(BaseModel):
    item: ChecklistItem
    answer: ChecklistAnswer
    verified: bool = False
    verifier_note: str = ""
