"""Thin wrapper around the Anthropic SDK used by every agent stage."""

from __future__ import annotations

import base64
import os
from pathlib import Path
from typing import Any, TypeVar

import anthropic
from pydantic import BaseModel

MODEL = os.environ.get("DDQ_MODEL", "claude-opus-5-5")
EFFORT = os.environ.get("DDQ_EFFORT", "high")
FALLBACK_BETA = "server-side-fallback-2026-07-01"
WEB_SEARCH_TOOL = {"type": "web_search_20260209", "name": "web_search", "max_uses": 15}
MAX_CONTINUATIONS = 5

T = TypeVar("T", bound=BaseModel)


class RefusalError(RuntimeError):
    pass


IMAGE_TYPES = {".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".gif": "image/gif", ".webp": "image/webp"}
TEXT_TYPES = {".txt", ".csv", ".md", ".json"}
SHEET_TYPES = {".xlsx", ".xlsm"}
SUPPORTED_SUFFIXES = {".pdf", *IMAGE_TYPES, *TEXT_TYPES, *SHEET_TYPES}


def _sheet_text(path: Path) -> str:
    import openpyxl

    wb = openpyxl.load_workbook(path, data_only=True, read_only=True)
    parts = []
    for ws in wb.worksheets:
        parts.append(f"## Sheet: {ws.title}")
        for row in ws.iter_rows(values_only=True):
            if any(v is not None for v in row):
                parts.append(",".join("" if v is None else str(v).replace("\n", " ") for v in row))
    return "\n".join(parts)


def document_block(path: Path, title: str | None = None) -> dict:
    """One supporting document as a content block the model can read and cite."""
    path = Path(path)
    suffix = path.suffix.lower()
    title = title or path.name
    if suffix == ".pdf":
        data = base64.standard_b64encode(path.read_bytes()).decode()
        return {"type": "document", "title": title, "source": {"type": "base64", "media_type": "application/pdf", "data": data}}
    if suffix in IMAGE_TYPES:
        data = base64.standard_b64encode(path.read_bytes()).decode()
        return {"type": "image", "source": {"type": "base64", "media_type": IMAGE_TYPES[suffix], "data": data}}
    if suffix in SHEET_TYPES:
        text = _sheet_text(path)
    elif suffix in TEXT_TYPES:
        text = path.read_text(errors="replace")
    else:
        raise ValueError(f"Unsupported document type: {path.name}")
    return {"type": "document", "title": title, "source": {"type": "text", "media_type": "text/plain", "data": text}}


def document_blocks(documents: list[tuple[Path, str]]) -> list[dict]:
    """All documents, each preceded by a label; the prefix is cached so every stage re-reads it cheaply."""
    blocks: list[dict] = []
    for path, title in documents:
        blocks.append({"type": "text", "text": f"Document: {title}"})
        blocks.append(document_block(path, title))
    if blocks:
        blocks[-1] = {**blocks[-1], "cache_control": {"type": "ephemeral"}}
    return blocks


def pdf_block(path: Path) -> dict:
    return {**document_block(path), "cache_control": {"type": "ephemeral"}}


class LLM:
    def __init__(self, client: Any = None, model: str = MODEL, effort: str = EFFORT):
        if client is None:
            from . import settings

            key = settings.get("ANTHROPIC_API_KEY")
            client = anthropic.Anthropic(api_key=key) if key else anthropic.Anthropic()
        self.client = client
        self.model = model
        self.effort = effort

    def _run(self, system: str, content: list[dict], tools: list[dict] | None = None, output_format=None):
        messages: list[dict] = [{"role": "user", "content": content}]
        for _ in range(MAX_CONTINUATIONS + 1):
            kwargs: dict[str, Any] = dict(
                model=self.model,
                max_tokens=64000,
                system=system,
                messages=messages,
                thinking={"type": "adaptive"},
                output_config={"effort": self.effort},
                betas=[FALLBACK_BETA],
                fallbacks="default",
            )
            if tools:
                kwargs["tools"] = tools
            if output_format is not None:
                kwargs["output_format"] = output_format
            with self.client.beta.messages.stream(**kwargs) as stream:
                message = stream.get_final_message()
            if message.stop_reason == "refusal":
                detail = getattr(message.stop_details, "explanation", "") if message.stop_details else ""
                raise RefusalError(f"Model declined the request. {detail}".strip())
            if message.stop_reason == "max_tokens":
                raise RuntimeError("Response hit max_tokens; split the request into smaller batches.")
            if message.stop_reason != "pause_turn":
                return message
            # A long server-tool turn paused; send it back so the model resumes it.
            messages = [messages[0], {"role": "assistant", "content": message.content}]
        raise RuntimeError("Turn still paused after the maximum number of continuations.")

    def text(self, system: str, content: list[dict], tools: list[dict] | None = None) -> str:
        message = self._run(system, content, tools)
        return "\n".join(b.text for b in message.content if b.type == "text").strip()

    def structured(self, system: str, content: list[dict], output_model: type[T]) -> T:
        message = self._run(system, content, output_format=output_model)
        for block in reversed(message.content):
            if block.type == "text" and getattr(block, "parsed_output", None) is not None:
                return block.parsed_output
        text = next(b.text for b in reversed(message.content) if b.type == "text")
        return output_model.model_validate_json(text)
