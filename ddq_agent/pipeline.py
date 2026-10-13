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
    om_path: Path,
    llm: LLM | None = None,
    items: list[ChecklistItem] | None = None,
    connectors_fn: Callable[[PropertyProfile], list[ConnectorResult]] = run_connectors,
    max_rounds: int = MAX_VERIFY_ROUNDS,
    on_step: Callable[[str], None] = lambda msg: None,
) -> Review:
    llm = llm or LLM()
    items = items or load_template()
    om = pdf_block(om_path)
    log: list[str] = []

    def step(msg: str) -> None:
        log.append(msg)
        on_step(msg)

    step("Indexing the Offering Memorandum")
    profile = stages.extract_profile(llm, om)

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
