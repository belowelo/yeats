"""
02b_import_kci_excel.py — Add KCI website exports to the KCI harvest
=====================================================================

Reads .xls files exported from the KCI website search (논문 검색 -> 엑셀 반출)
into the same record format 02_harvest_kci.py writes, so every later step
treats them identically.

A record is imported only if:
  - one of its title fields contains a subject term (config subject_terms),
    which is the same title rule the API harvest applies, and
  - its year falls inside config date_range.
Records already in kci_raw.json (same KCI article ID) are left as they are.

The export's reference-list sheet (참고문헌) is kept on each record as
`references`. Nothing in the topic model reads it.

Inputs:  one or more .xls files or folders of them (KCI website export),
         config.yaml, _data/kci_raw.json (optional)
Outputs: _data/kci_raw.json (records added, never removed)

Dependencies: xlrd, pyyaml
Run: python 02b_import_kci_excel.py <file or folder> [<file or folder> ...]
"""

import json
import re
import sys
import io
from pathlib import Path

import xlrd
import yaml

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

SCRIPT_DIR = Path(__file__).parent
with open(SCRIPT_DIR / "config.yaml", encoding="utf-8") as f:
    config = yaml.safe_load(f)

_vr = Path(config["vault_root"])
VAULT_ROOT = _vr if _vr.is_absolute() else (SCRIPT_DIR / _vr).resolve()
DATA_DIR = VAULT_ROOT / config["paths"]["data"]
DATA_DIR.mkdir(parents=True, exist_ok=True)
OUTPUT_FILE = DATA_DIR / "kci_raw.json"

DATE_MIN, DATE_MAX = config["date_range"]
SUBJECT_TERMS = [t.lower() for t in config.get("subject_terms", [])]


def normalize_text(s: str) -> str:
    """Same normalisation as 02_harvest_kci.py."""
    if not s:
        return s
    replacements = {
        "“": '"', "”": '"',
        "‘": "'", "’": "'",
        "–": "-", "—": "-",
        " ": " ",
        "‐": "-", "‑": "-", "‒": "-",
    }
    for old, new in replacements.items():
        s = s.replace(old, new)
    s = re.sub(r' {2,}', ' ', s)
    return s.strip()


def unique(values):
    out = []
    for v in values:
        v = normalize_text(v)
        if v and v not in out:
            out.append(v)
    return out


def split_keywords(*fields):
    words = []
    for field in fields:
        for w in re.split(r"[,;]", field or ""):
            w = normalize_text(w)
            if w and w not in words:
                words.append(w)
    return words


def read_export(path: Path) -> list[dict]:
    wb = xlrd.open_workbook(str(path))
    sh = wb.sheet_by_name("논문목록")
    header = [str(sh.cell_value(0, c)).strip() for c in range(sh.ncols)]
    if "논문 ID" not in header:
        print(f"  skipped {path.name}: no '논문 ID' column (a reduced export)")
        return []
    rows = [{header[c]: str(sh.cell_value(r, c)).strip() for c in range(sh.ncols)}
            for r in range(1, sh.nrows)]
    refs = {}
    if "참고문헌" in wb.sheet_names():
        rs = wb.sheet_by_name("참고문헌")
        for r in range(1, rs.nrows):
            refs.setdefault(str(rs.cell_value(r, 0)).strip(), []).append(
                str(rs.cell_value(r, 1)).strip())
    for row in rows:
        row["_refs"] = refs.get(row["논문 ID"], [])
    return rows


def to_record(row: dict) -> dict:
    titles = unique([row.get("논문명", ""), row.get("논문외국어명", ""), row.get("논문영어명", "")])

    # Order: original language first, English last. Later steps read
    # abstracts[-1].
    english = normalize_text(row.get("영어초록", ""))
    abstracts = unique([row.get("초록", ""), row.get("외국어초록", "")])
    if english:
        abstracts = [a for a in abstracts if a != english] + [english]

    authors = [a.strip() for a in (row.get("저자명") or "").split(",") if a.strip()]
    if authors and row.get("주저자 소속기관"):
        authors[0] = f"{authors[0]}({row['주저자 소속기관']})"

    try:
        year = int((row.get("발행연도") or "")[:4])
    except ValueError:
        year = None

    return {
        "article_id": row.get("논문 ID", ""),
        "titles": titles,
        "title": titles[0] if titles else "",
        "authors": authors,
        "year": year,
        "doi": (row.get("DOI") or "").strip(),
        "journal": (row.get("학술지명") or "").strip(),
        "keywords": split_keywords(row.get("저자키워드"), row.get("외국어키워드"),
                                   row.get("영어키워드")),
        "abstracts": abstracts,
        "abstract": abstracts[0] if abstracts else "",
        "corpus": "KCI",
        "source": "kci_excel",
        "language": row.get("언어", ""),
        "references": row.get("_refs", []),
    }


def in_scope(rec: dict) -> bool:
    if rec["year"] is None or not (DATE_MIN <= rec["year"] <= DATE_MAX):
        return False
    blob = " ".join(rec["titles"]).lower()
    return any(t in blob for t in SUBJECT_TERMS) if SUBJECT_TERMS else True


def collect_paths(args):
    files = []
    for a in args:
        p = Path(a)
        if p.is_dir():
            files.extend(sorted(p.glob("*.xls")))
        elif p.exists():
            files.append(p)
        else:
            print(f"  not found: {p}")
    return files


if __name__ == "__main__":
    print("=== KCI Excel Import ===\n")
    files = collect_paths(sys.argv[1:])
    if not files:
        print("  No .xls files given. Usage: python 02b_import_kci_excel.py <file or folder>")
        sys.exit(1)

    existing = []
    if OUTPUT_FILE.exists():
        with open(OUTPUT_FILE, encoding="utf-8") as f:
            existing = json.load(f)
    have = {p.get("article_id") for p in existing if p.get("article_id")}
    print(f"  kci_raw.json: {len(existing)} records already present")

    added, dupes, out_of_scope = [], 0, 0
    for path in files:
        rows = read_export(path)
        n_before = len(added)
        for row in rows:
            rec = to_record(row)
            if not in_scope(rec):
                out_of_scope += 1
                continue
            if rec["article_id"] in have:
                dupes += 1
                continue
            have.add(rec["article_id"])
            added.append(rec)
        print(f"  {path.name}: {len(rows)} rows, {len(added) - n_before} added")

    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        json.dump(existing + added, f, ensure_ascii=False, indent=2)

    print(f"\n  added:                 {len(added)}")
    print(f"  already present:       {dupes}")
    print(f"  outside window/title:  {out_of_scope}")
    print(f"  kci_raw.json now:      {len(existing) + len(added)} records")
    print("\n=== Done ===")
