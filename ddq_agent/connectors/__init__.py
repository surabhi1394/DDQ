"""Connector registry. Order matters: geocode feeds the location-based connectors, and
ENERGY STAR feeds CRREM."""

from __future__ import annotations

from ..models import ConnectorResult, PropertyProfile
from .base import Connector, ConnectorContext
from .energy_star import EnergyStar
from .location import FemaFlood, Geocode
from .pathways import Cambium, Crrem
from .plugins import Audette, Bpd, Physrisk
from .regs import FinesRegs

DEFAULT_CONNECTORS: list[type[Connector]] = [
    Geocode,
    FemaFlood,
    Physrisk,
    EnergyStar,
    Crrem,
    Cambium,
    Bpd,
    FinesRegs,
    Audette,
]


def run_connectors(
    profile: PropertyProfile, connectors: list[Connector] | None = None, ctx: ConnectorContext | None = None
) -> list[ConnectorResult]:
    ctx = ctx or ConnectorContext(profile=profile)
    connectors = connectors if connectors is not None else [c() for c in DEFAULT_CONNECTORS]
    for connector in connectors:
        ctx.results[connector.name] = connector.run(ctx)
    return list(ctx.results.values())


__all__ = ["Connector", "ConnectorContext", "DEFAULT_CONNECTORS", "run_connectors"]
