"""Standalone command-line entry point for the isolated module."""

from __future__ import annotations

import argparse
from pathlib import Path

from .adapter import load_xer_snapshot
from .engine import analyse
from .reporting import write_report_bundle
from .store import LayerStore


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="rlpa-apvab-v2",
        description=(
            "Programme-only Retrospective Longest Path Analysis. The first "
            "file is treated as the baseline and the last as the final update."
        ),
    )
    parser.add_argument("files", nargs="+", help="XER files in chronological order")
    parser.add_argument("--anchor", help="Completion milestone Activity ID")
    parser.add_argument(
        "--output", default="rlpa_apvab_v2_output",
        help="New report-bundle directory",
    )
    parser.add_argument(
        "--reject", action="append", default=[],
        help="Candidate interpretation or graph element ID rejected by expert",
    )
    parser.add_argument(
        "--no-store", action="store_true",
        help="Do not persist the append-only SQLite audit store",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    snapshots = []
    for file_index, path in enumerate(args.files):
        declared = (
            "baseline" if file_index == 0 and len(args.files) > 1
            else "as-built" if file_index == len(args.files) - 1
            else "update"
        )
        snapshots.append(load_xer_snapshot(
            path, declared_programme_type=declared
        ))
    result = analyse(
        snapshots,
        anchor_task_code=args.anchor,
        rejected_element_ids=args.reject,
    )
    output = Path(args.output)
    report_index = write_report_bundle(result, output)
    if not args.no_store:
        store = LayerStore(output / "layers.sqlite")
        store.save_graph(result.graph)
        store.save_run(result.run)
    print(report_index.resolve())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
