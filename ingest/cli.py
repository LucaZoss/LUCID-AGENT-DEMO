"""CLI entry for non-interactive CSV preview (tests / CI)."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from ingest.importer import preview_csv_file


def main() -> None:
    """Print JSON preview for a single CSV path."""
    parser = argparse.ArgumentParser(description="Preview CSV import mapping")
    parser.add_argument("csv_path", type=Path, help="Path to a .csv file")
    args = parser.parse_args()
    if not args.csv_path.is_file():
        print(f"not found: {args.csv_path}", file=sys.stderr)
        sys.exit(1)
    prev = preview_csv_file(args.csv_path.resolve())
    det = prev["detection"]
    if hasattr(det, "message"):
        prev["detection"] = {"error": det.message, "missing": det.missing_required}
    else:
        prev["detection"] = {
            "column_map": det.column_map,
            "sign_rule": det.sign_rule,
            "encoding": det.encoding,
            "delimiter": det.delimiter,
        }
    print(json.dumps(prev, indent=2))


if __name__ == "__main__":
    main()
