"""Connector interface.

A connector takes what we know about the property and returns one ConnectorResult.
Connectors never raise: a missing credential is NOT_CONFIGURED, a failed call is ERROR,
so one broken data source can't stop a review. To add a data source (for example Audette
once you have API access), subclass Connector and add it to DEFAULT_CONNECTORS in
ddq_agent/connectors/__init__.py.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

import httpx

from .. import settings
from ..models import ConnectorResult, ConnectorStatus, PropertyProfile


@dataclass
class ConnectorContext:
    profile: PropertyProfile
    latitude: Optional[float] = None
    longitude: Optional[float] = None
    results: dict[str, ConnectorResult] = field(default_factory=dict)
    http: Optional[httpx.Client] = None

    def client(self) -> httpx.Client:
        if self.http is None:
            self.http = httpx.Client(timeout=30.0, follow_redirects=True)
        return self.http


class Connector:
    name: str = "connector"
    description: str = ""
    required_env: tuple[str, ...] = ()

    def missing_env(self) -> list[str]:
        return [k for k in self.required_env if not settings.get(k)]

    def run(self, ctx: ConnectorContext) -> ConnectorResult:
        missing = self.missing_env()
        if missing:
            return self.result(ConnectorStatus.NOT_CONFIGURED, f"Add {', '.join(missing)} in Settings to enable.")
        try:
            return self.fetch(ctx)
        except Exception as exc:  # one failing source must not stop the review
            return self.result(ConnectorStatus.ERROR, f"{type(exc).__name__}: {exc}")

    def fetch(self, ctx: ConnectorContext) -> ConnectorResult:
        raise NotImplementedError

    def result(self, status: ConnectorStatus, summary: str, data: dict | None = None, source: str = "") -> ConnectorResult:
        return ConnectorResult(connector=self.name, status=status, summary=summary, data=data or {}, source=source)
