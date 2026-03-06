#!/usr/bin/env python3
"""Stage 0 drift and canonical documentation checks."""

from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CANONICAL_DIR = ROOT / "docs" / "canonical"
ADR_DIR = ROOT / "docs" / "adr"
INDEX_FILE = ROOT / "docs" / "CANONICAL_INDEX.md"

FORBIDDEN_TERMS = ["NIFTY", "BSE", "Asia/Kolkata"]


class DriftError(Exception):
    pass


def canonical_files() -> list[Path]:
    files = sorted(CANONICAL_DIR.glob("*.md")) + sorted(ADR_DIR.glob("*.md")) + [INDEX_FILE]
    return [f for f in files if f.exists()]


def check_forbidden_terms(path: Path, text: str) -> None:
    for term in FORBIDDEN_TERMS:
        pattern = re.escape(term)
        if term.isalpha():
            pattern = rf"\\b{pattern}\\b"
        if re.search(pattern, text, flags=re.IGNORECASE):
            raise DriftError(f"Forbidden term '{term}' found in canonical file: {path}")


def check_timezone_reference(path: Path, text: str) -> None:
    if "Africa/Nairobi" not in text:
        raise DriftError(f"Canonical file missing required timezone reference 'Africa/Nairobi': {path}")


def main() -> int:
    try:
        files = canonical_files()
        if not files:
            raise DriftError("No canonical files found to validate")

        for path in files:
            text = path.read_text(encoding="utf-8")
            check_forbidden_terms(path, text)
            check_timezone_reference(path, text)

        print("Stage 0 drift guard passed")
        return 0

    except DriftError as e:
        print(f"ERROR: {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
