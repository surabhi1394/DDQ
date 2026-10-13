"""The agent stages from the workflow: RSRA (profile, research, answers), Retrofit Specialist, Verifier."""

from __future__ import annotations

import json
from importlib import resources
from typing import Literal

import yaml
from pydantic import BaseModel

from ..llm import LLM, WEB_SEARCH_TOOL
from ..models import ChecklistAnswer, ChecklistItem, ConnectorResult, PropertyProfile, Verdict
from . import prompts


class Evidence(BaseModel):
    """Everything the agents may rely on besides the OM itself."""

    profile: PropertyProfile
    connectors: list[ConnectorResult]
    research_notes: str = ""

    def as_text(self) -> str:
        connectors = [c.model_dump(mode="json") for c in self.connectors]
        return (
            "<property_profile>\n" + self.profile.model_dump_json(indent=1, exclude_none=True) + "\n</property_profile>\n"
            "<connector_results>\n" + json.dumps(connectors, indent=1) + "\n</connector_results>\n"
            "<research_notes>\n" + (self.research_notes or "(none)") + "\n</research_notes>"
        )


class AnswerSet(BaseModel):
    answers: list[ChecklistAnswer]


class RetrofitUpdate(BaseModel):
    id: str
    mitigation: str
    cost_estimate: str
    priority: Literal["LOW", "MODERATE", "HIGH"]
    risk: Literal["LOW", "MODERATE", "HIGH"]
    sources: list[str]


class RetrofitSet(BaseModel):
    updates: list[RetrofitUpdate]


class VerdictSet(BaseModel):
    verdicts: list[Verdict]


def _questions_text(items: list[ChecklistItem], feedback: dict[str, str] | None = None) -> str:
    lines = []
    for i in items:
        line = f"[{i.id}] ({i.section}; type {i.type or '-'}; {i.timing or 'unspecified'}) {i.question}"
        if feedback and i.id in feedback:
            line += f"\n    Reviewer feedback on the previous draft: {feedback[i.id]}"
        lines.append(line)
    return "\n".join(lines)


def _cost_library() -> str:
    return yaml.safe_dump(yaml.safe_load(resources.files("ddq_agent.data").joinpath("cost_library.yaml").read_text()))


def profile_from_address(llm: LLM, address: str) -> PropertyProfile:
    """No OM: build the profile from public sources with web search."""
    notes = llm.text(
        prompts.ADDRESS_RESEARCH_SYSTEM,
        [{"type": "text", "text": f"Property address: {address}"}],
        tools=[WEB_SEARCH_TOOL],
    )
    return llm.structured(
        prompts.PROFILE_SYSTEM,
        [{"type": "text", "text": f"Property address: {address}\n\nPublic research notes:\n{notes}\n\n"
          "Extract the property profile from these notes. Keep the address exactly as given unless the notes correct it."}],
        PropertyProfile,
    )


def extract_profile(llm: LLM, docs: list[dict]) -> PropertyProfile:
    return llm.structured(
        prompts.PROFILE_SYSTEM,
        docs + [{"type": "text", "text": "Extract the property profile from these documents."}],
        PropertyProfile,
    )


def research(llm: LLM, docs: list[dict], evidence: Evidence, items: list[ChecklistItem]) -> str:
    content = docs + [
        {"type": "text", "text": evidence.as_text()},
        {"type": "text", "text": "Checklist the research must support:\n" + _questions_text(items)},
    ]
    return llm.text(prompts.RESEARCH_SYSTEM, content, tools=[WEB_SEARCH_TOOL])


def answer(
    llm: LLM,
    docs: list[dict],
    evidence: Evidence,
    items: list[ChecklistItem],
    feedback: dict[str, str] | None = None,
    previous: dict[str, ChecklistAnswer] | None = None,
) -> dict[str, ChecklistAnswer]:
    text = "Answer these checklist questions:\n" + _questions_text(items, feedback)
    if previous:
        text += "\n\nYour previous drafts of these answers:\n" + json.dumps(
            [previous[i.id].model_dump() for i in items if i.id in previous], indent=1
        )
    if not docs:
        text += "\n\nNo documents were provided for this property; rely on the connectors and research notes."
    content = docs + [{"type": "text", "text": evidence.as_text()}, {"type": "text", "text": text}]
    result = llm.structured(prompts.ANSWER_SYSTEM, content, AnswerSet)
    return _keep_requested(result.answers, items)


def retrofit(llm: LLM, evidence: Evidence, items: list[ChecklistItem], answers: dict[str, ChecklistAnswer]) -> dict[str, ChecklistAnswer]:
    drafts = [{"question": i.question, **answers[i.id].model_dump()} for i in items if i.id in answers]
    content = [
        {"type": "text", "text": evidence.as_text()},
        {"type": "text", "text": "<cost_library>\n" + _cost_library() + "</cost_library>"},
        {"type": "text", "text": "Drafted answers:\n" + json.dumps(drafts, indent=1)},
    ]
    result = llm.structured(prompts.RETROFIT_SYSTEM, content, RetrofitSet)
    updated = dict(answers)
    for u in result.updates:
        if u.id in updated:
            a = updated[u.id]
            updated[u.id] = a.model_copy(
                update={
                    "mitigation": u.mitigation,
                    "cost_estimate": u.cost_estimate,
                    "priority": u.priority,
                    "risk": u.risk,
                    "sources": list(dict.fromkeys(a.sources + u.sources)),
                }
            )
    return updated


def verify(llm: LLM, docs: list[dict], evidence: Evidence, items: list[ChecklistItem], answers: dict[str, ChecklistAnswer]) -> dict[str, Verdict]:
    drafts = [{"question": i.question, "timing": i.timing, **answers[i.id].model_dump()} for i in items if i.id in answers]
    content = docs + [
        {"type": "text", "text": evidence.as_text()},
        {"type": "text", "text": "Answers to verify:\n" + json.dumps(drafts, indent=1)},
    ]
    result = llm.structured(prompts.VERIFIER_SYSTEM, content, VerdictSet)
    verdicts = {v.id: v for v in result.verdicts if v.id in answers}
    # An answer the verifier skipped is not verified.
    for i in items:
        if i.id in answers and i.id not in verdicts:
            verdicts[i.id] = Verdict(id=i.id, passed=False, issue="Verifier did not return a verdict.")
    return verdicts


def _keep_requested(answers: list[ChecklistAnswer], items: list[ChecklistItem]) -> dict[str, ChecklistAnswer]:
    wanted = {i.id for i in items}
    return {a.id: a for a in answers if a.id in wanted}
