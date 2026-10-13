"""Command line: `ddq review OM.pdf`, `ddq connectors`, `ddq eval generated.xlsx expected.xlsx`."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


def _review(args) -> int:
    from .pipeline import run_review
    from .report import write_report

    review = run_review(Path(args.om), max_rounds=args.rounds, on_step=lambda m: print(f"- {m}", file=sys.stderr))
    out = Path(args.out or Path(args.om).with_suffix(".ddq.xlsx").name)
    write_report(review, out)
    needs_review = sum(1 for r in review.rows if not r.verified)
    print(f"Wrote {out}: {len(review.rows)} questions, {needs_review} flagged for human review.")
    if args.json:
        Path(args.json).write_text(
            json.dumps(
                {
                    "profile": review.profile.model_dump(mode="json"),
                    "connectors": [c.model_dump(mode="json") for c in review.connectors],
                    "research_notes": review.research_notes,
                    "rows": [r.model_dump(mode="json") for r in review.rows],
                },
                indent=2,
            )
        )
    return 0


def _connectors(args) -> int:
    from .connectors import DEFAULT_CONNECTORS

    for cls in DEFAULT_CONNECTORS:
        c = cls()
        missing = c.missing_env()
        state = "needs " + ", ".join(missing) if missing else "ready"
        print(f"{c.name:12} {state:40} {c.description}")
    print(f"{'web_search':12} {'ready':40} Claude web search (server tool), used in the research step.")
    return 0


def _eval(args) -> int:
    from .evaluate import score

    s = score(Path(args.generated), Path(args.expected))
    print(f"Compared {s.compared} questions")
    print(f"Response agreement: {s.response_accuracy:.0%} ({s.response_matches}/{s.compared})")
    print(f"Priority agreement: {s.priority_accuracy:.0%}")
    for q, want, got in s.mismatches:
        print(f"  expected {want:4} got {got:4}  {q[:90]}")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="ddq", description="ESG DDQ over-the-desk review agent")
    sub = parser.add_subparsers(required=True)

    p = sub.add_parser("review", help="Run the review on an Offering Memorandum PDF")
    p.add_argument("om", help="Path to the OM PDF")
    p.add_argument("-o", "--out", help="Output .xlsx (default: <om name>.ddq.xlsx)")
    p.add_argument("--json", help="Also write the full review as JSON")
    p.add_argument("--rounds", type=int, default=2, help="Max Verifier revision rounds (default 2)")
    p.set_defaults(func=_review)

    p = sub.add_parser("connectors", help="Show which data connectors are configured")
    p.set_defaults(func=_connectors)

    p = sub.add_parser("eval", help="Compare a generated DDQ with a hand-completed one")
    p.add_argument("generated")
    p.add_argument("expected")
    p.set_defaults(func=_eval)

    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
