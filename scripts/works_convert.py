"""
works_convert.py — Import works from CSV into works.txt
========================================================

Reads works.csv (editable in Excel/Sheets) and writes works.txt
(the pipe-delimited format the pipeline reads).

A pre-populated works.csv ships with the pipeline. Edit it in a
spreadsheet, then run this script to update works.txt.

Usage:
  python works_convert.py
"""

import csv
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).parent
WORKS_TXT = SCRIPT_DIR / "works.txt"
WORKS_CSV = SCRIPT_DIR / "works.csv"


def from_csv():
    """Convert works.csv → works.txt."""
    if not WORKS_CSV.exists():
        print(f"  ERROR: {WORKS_CSV} not found.")
        sys.exit(1)

    with open(WORKS_CSV, encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        works = list(reader)

    with open(WORKS_TXT, "w", encoding="utf-8") as f:
        f.write("# Works list for subject assignment (step 04)\n")
        f.write("# Format: Title | type | year | match_term1, match_term2\n")
        f.write("# One work per line. Lines starting with # are comments.\n")
        f.write("# Match terms are case-insensitive substrings checked against title + abstract.\n\n")
        for w in works:
            f.write(f"{w['title']} | {w['type']} | {w['year']} | {w['match_terms']}\n")

    print(f"  Wrote {len(works)} works to {WORKS_TXT}")


if __name__ == "__main__":
    from_csv()
