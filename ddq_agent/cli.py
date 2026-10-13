"""Command line: `ddq review OM.pdf`, `ddq connectors`, `ddq eval generated.xlsx expected.xlsx`."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


def _review(args) -> int:
    from .pipeline import run_review
    from .report import write_report

    if not args.om and not args.address and not args.doc:
        print("Give an OM PDF, --address, --doc, or a combination.", file=sys.stderr)
        return 2
    docs = []
    for spec in args.doc or []:
        label, sep, path = spec.partition("=")
        if not sep:
            label, path = "Other", spec
        docs.append((Path(path), f"{label}: {Path(path).name}"))
    review = run_review(
        Path(args.om) if args.om else None,
        address=args.address,
        documents=docs,
        max_rounds=args.rounds,
        on_step=lambda m: print(f"- {m}", file=sys.stderr),
    )
    stem = Path(args.om).stem if args.om else "".join(c if c.isalnum() else "_" for c in (args.address or "review"))[:40]
    out = Path(args.out or f"{stem}.ddq.xlsx")
    write_report(review, out)
    needs_review = sum(1 for r in review.rows if not r.verified)
    print(f"Wrote {out}: {len(review.rows)} questions, {needs_review} flagged for human review.")
    if args.json:
        from .store import review_to_dict

        Path(args.json).write_text(json.dumps(review_to_dict(review), indent=2))
    return 0


def _serve(args) -> int:
    import uvicorn

    from .app import create_app

    print(f"DDQ tool running at http://{args.host}:{args.port}")
    uvicorn.run(create_app(workers=args.workers), host=args.host, port=args.port)
    return 0


def _connectors(args) -> int:
    from . import settings
    from .connectors import DEFAULT_CONNECTORS
    from .connectors.climate import CustomSource

    for c in [cls() for cls in DEFAULT_CONNECTORS] + [CustomSource(s) for s in settings.custom_sources()]:
        missing = c.missing_env()
        state = "needs " + ", ".join(missing) if missing else "ready"
        print(f"{c.name:16} {state:40} {c.description}")
    print(f"{'web_search':16} {'ready':40} Claude web search (server tool), used in the research step.")
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

    p = sub.add_parser("review", help="Run the review on an Offering Memorandum PDF and/or an address")
    p.add_argument("om", nargs="?", help="Path to the OM PDF (optional when --address is given)")
    p.add_argument("--address", help="Property address, e.g. '1260 S Park Ave, Salt Lake City, UT 84105'")
    p.add_argument("-o", "--out", help="Output .xlsx (default: <om name>.ddq.xlsx)")
    p.add_argument("--doc", action="append", metavar="LABEL=PATH",
                   help="Extra document, e.g. 'Phase I ESA=phase1.pdf'. Repeat for more. PDF, image, xlsx, csv or text")
    p.add_argument("--json", help="Also write the full review as JSON")
    p.add_argument("--rounds", type=int, default=2, help="Max Verifier revision rounds (default 2)")
    p.set_defaults(func=_review)

    p = sub.add_parser("serve", help="Run the web tool (new reviews, dashboard, Excel download)")
    p.add_argument("--host", default="127.0.0.1")
    p.add_argument("--port", type=int, default=8000)
    p.add_argument("--workers", type=int, default=2, help="Reviews that can run at the same time")
    p.set_defaults(func=_serve)

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
