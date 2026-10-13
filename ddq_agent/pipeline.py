"""OM to report: the workflow from the slide.

    OM received -> RSRA agent (index document, run connectors, research, assemble findings)
               -> Retrofit Specialist -> Verifier --(failed findings)--> RSRA ... -> Report
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from .agents import stages
from .checklist import load_template
from .connectors import run_connectors
from .llm import LLM, pdf_block
from .models import ChecklistItem, ConnectorResult, PropertyProfile, ReportRow

MAX_VERIFY_ROUNDS = 2


@dataclass
class Review:
    profile: PropertyProfile
    connectors: list[ConnectorResult]
    research_notes: str
    rows: list[ReportRow]
    rounds: int = 0
    log: list[str] = field(default_factory=list)


def run_review(
    om_path: Path | None = None,
    llm: LLM | None = None,
    items: list[ChecklistItem] | None = None,
    connectors_fn: Callable[[PropertyProfile], list[ConnectorResult]] = run_connectors,
    max_rounds: int = MAX_VERIFY_ROUNDS,
    on_step: Callable[[str], None] = lambda msg: None,
    address: str | None = None,
) -> Review:
    """Review a property from an OM PDF, an address, or both (the address then overrides the OM's)."""
    if om_path is None and not address:
        raise ValueError("Give an Offering Memorandum, an address, or both.")
    llm = llm or LLM()
    items = items or load_template()
    om = pdf_block(om_path) if om_path else None
    log: list[str] = []

    def step(msg: str) -> None:
        log.append(msg)
        on_step(msg)

    if om:
        step("Indexing the Offering Memorandum")
        profile = stages.extract_profile(llm, om)
        if address:
            profile.street_address, profile.city, profile.state, profile.postal_code = _split_address(address, profile)
    else:
        step("Looking up the property from its address")
        profile = stages.profile_from_address(llm, address)

    step("Running connectors")
    connector_results = connectors_fn(profile)
    evidence = stages.Evidence(profile=profile, connectors=connector_results)

    step("Researching gaps with web search")
    evidence.research_notes = stages.research(llm, om, evidence, items)

    step("Assembling findings")
    answers = stages.answer(llm, om, evidence, items)
    missing = [i for i in items if i.id not in answers]
    if missing:
        answers.update(stages.answer(llm, om, evidence, missing))

    step("Retrofit Specialist")
    answers = stages.retrofit(llm, evidence, items, answers)

    step("Verifier")
    verdicts = stages.verify(llm, om, evidence, items, answers)
    rounds = 0
    while rounds < max_rounds:
        failed = [i for i in items if i.id in verdicts and not verdicts[i.id].passed]
        if not failed:
            break
        rounds += 1
        step(f"Revising {len(failed)} findings the Verifier rejected (round {rounds})")
        feedback = {i.id: verdicts[i.id].issue for i in failed}
        revised = stages.answer(llm, om, evidence, failed, feedback=feedback, previous=answers)
        revised = stages.retrofit(llm, evidence, [i for i in failed if i.id in revised], revised)
        answers.update(revised)
        verdicts.update(stages.verify(llm, om, evidence, [i for i in failed if i.id in revised], revised))

    rows = []
    for item in items:
        if item.id not in answers:
            continue
        v = verdicts.get(item.id)
        rows.append(
            ReportRow(item=item, answer=answers[item.id], verified=bool(v and v.passed), verifier_note=v.issue if v else "")
        )
    step("Done")
    return Review(profile, connector_results, evidence.research_notes, rows, rounds, log)


def _split_address(address: str, profile: PropertyProfile) -> tuple:
    """Best-effort "street, city, ST zip" split; keeps the OM's value for any part that's missing."""
    parts = [p.strip() for p in address.split(",") if p.strip()]
    street = parts[0] if parts else profile.street_address
    city = parts[1] if len(parts) > 1 else profile.city
    state, postal = profile.state, profile.postal_code
    if len(parts) > 2:
        tail = parts[2].split()
        state = tail[0] if tail else state
        postal = tail[1] if len(tail) > 1 else postal
    return street, city, state, postal
