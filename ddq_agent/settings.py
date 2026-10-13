"""API keys, data files and custom sources entered in the tool's Settings page.

Saved values live in <DDQ_DATA_DIR>/settings.json (owner-only permissions) and take precedence
over environment variables of the same name. Secret values are never sent back to the browser.
"""

from __future__ import annotations

import json
import os
import re
import threading
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Literal

_lock = threading.Lock()


@dataclass(frozen=True)
class Field:
    key: str
    label: str
    source: str
    kind: Literal["secret", "text", "file"] = "secret"
    help: str = ""


FIELDS: list[Field] = [
    Field("ANTHROPIC_API_KEY", "Anthropic API key", "Claude (required)", help="console.anthropic.com > API keys"),
    Field("ESPM_USERNAME", "Portfolio Manager username", "ENERGY STAR", "text",
          "Account with web services access; the property must be shared with it."),
    Field("ESPM_PASSWORD", "Portfolio Manager password", "ENERGY STAR"),
    Field("ESPM_PROPERTY_ID", "Default property id", "ENERGY STAR", "text", "Used when the documents don't state one."),
    Field("FIRST_STREET_API_KEY", "First Street API key", "First Street",
          help="First Street (riskfactor.com) property-level flood, fire, heat, wind and air risk."),
    Field("FIRST_STREET_URL", "First Street lookup URL", "First Street", "text",
          "Optional. The endpoint from your First Street plan, using {lat} {lon} or {address}."),
    Field("CRREM_PATHWAYS_CSV", "CRREM pathways CSV", "CRREM", "file",
          "Columns: country, property_type, year, energy_kwh_m2, carbon_kgco2e_m2"),
    Field("CAMBIUM_CSV", "Cambium emission factors CSV", "NREL Cambium", "file",
          "Columns: state, year, scenario, lrmer_kg_per_mwh"),
    Field("PHYSRISK_API_URL", "physrisk API URL", "physrisk", "text", "Your physrisk-api deployment."),
    Field("BPD_API_KEY", "BPD API key", "Building Performance Database"),
    Field("AUDETTE_API_KEY", "Audette API key", "Audette"),
]
FIELD_KEYS = {f.key for f in FIELDS}

CUSTOM_PLACEHOLDERS = ("lat", "lon", "address", "street", "city", "state", "zip")


def _path() -> Path:
    return Path(os.environ.get("DDQ_DATA_DIR", "ddq_data")) / "settings.json"


def _load() -> dict:
    path = _path()
    if not path.exists():
        return {"values": {}, "custom_sources": []}
    data = json.loads(path.read_text())
    data.setdefault("values", {})
    data.setdefault("custom_sources", [])
    return data


def _save(data: dict) -> None:
    path = _path()
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, indent=1))
    os.chmod(tmp, 0o600)
    tmp.replace(path)


def get(key: str, default: str | None = None) -> str | None:
    value = _load()["values"].get(key)
    return value if value else os.environ.get(key, default)


def set_values(values: dict[str, str]) -> None:
    """Save non-empty values for known fields; a value of None clears the field."""
    with _lock:
        data = _load()
        for key, value in values.items():
            if key not in FIELD_KEYS:
                raise KeyError(key)
            if value is None:
                data["values"].pop(key, None)
            elif value.strip():
                data["values"][key] = value.strip()
        _save(data)


def data_file_path(key: str, filename: str) -> Path:
    safe = re.sub(r"[^A-Za-z0-9._-]+", "_", filename)[-80:] or "data.csv"
    folder = _path().parent / "datasets"
    folder.mkdir(parents=True, exist_ok=True)
    return folder / f"{key.lower()}-{safe}"


def describe() -> dict:
    """What the Settings page shows: which fields are set (never their secret values)."""
    data = _load()
    fields = []
    for f in FIELDS:
        saved = data["values"].get(f.key)
        value = saved or os.environ.get(f.key)
        shown = None
        if value and f.kind == "text":
            shown = value
        elif value and f.kind == "file":
            shown = Path(value).name
        fields.append({**asdict(f), "set": bool(value), "from_env": bool(value and not saved), "value": shown})
    return {"fields": fields, "custom_sources": [_public_source(s) for s in data["custom_sources"]]}


def _public_source(source: dict) -> dict:
    return {k: v for k, v in source.items() if k != "header_value"} | {"has_key": bool(source.get("header_value"))}


def custom_sources() -> list[dict]:
    return _load()["custom_sources"]


def add_custom_source(name: str, url: str, header_name: str = "", header_value: str = "", notes: str = "") -> dict:
    name, url = name.strip(), url.strip()
    if not name or not re.fullmatch(r"https?://\S+", url):
        raise ValueError("A custom source needs a name and an http(s) URL.")
    unknown = set(re.findall(r"{(\w+)}", url)) - set(CUSTOM_PLACEHOLDERS)
    if unknown:
        raise ValueError(f"Unknown placeholder(s) in URL: {', '.join(sorted(unknown))}")
    with _lock:
        data = _load()
        slug = re.sub(r"[^a-z0-9]+", "_", name.lower()).strip("_") or "source"
        existing = {s["id"] for s in data["custom_sources"]}
        source_id, n = slug, 2
        while source_id in existing:
            source_id, n = f"{slug}_{n}", n + 1
        source = {"id": source_id, "name": name, "url": url, "header_name": header_name.strip(),
                  "header_value": header_value.strip(), "notes": notes.strip()}
        data["custom_sources"].append(source)
        _save(data)
    return _public_source(source)


def remove_custom_source(source_id: str) -> None:
    with _lock:
        data = _load()
        data["custom_sources"] = [s for s in data["custom_sources"] if s["id"] != source_id]
        _save(data)
