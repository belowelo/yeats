"""
07_paper_frontmatter.py — Add strand assignments and probe matches to paper pages
==================================================================================

Updates YAML frontmatter on each paper page in papers/ with:
  - strands: wikilinked list of assigned LDA topics
  - strand_probs: topic probability for each assigned strand
  - probe_matches: which vocabulary probe stems matched

Reads LDA assignments from all_papers.json (populated by 05_lda_strands.py)
and probe stems from config.yaml. Preserves all existing frontmatter fields
and body content.

Inputs:  _data/all_papers.json, _data/strand_names.json, config.yaml,
         papers/*.md (existing pages from 03_create_paper_pages.py)
Outputs: papers/*.md (frontmatter updated in-place)

Dependencies: pyyaml
Run: python 07_paper_frontmatter.py
"""

import json
import re
import sys
import yaml
from pathlib import Path

# --- Load config ---
config_path = Path(__file__).parent / "config.yaml"
with open(config_path, encoding="utf-8") as f:
    config = yaml.safe_load(f)

_vr = Path(config["vault_root"])
VAULT_ROOT = _vr if _vr.is_absolute() else (Path(__file__).parent / _vr).resolve()
DATA_DIR = VAULT_ROOT / config["paths"]["data"]
PAPERS_KCI_DIR = VAULT_ROOT / config["paths"]["papers_kci"]
PAPERS_OA_DIR = VAULT_ROOT / config["paths"]["papers_openalex"]

# --- Load data ---
with open(DATA_DIR / "all_papers.json", encoding="utf-8") as f:
    papers = json.load(f)
with open(DATA_DIR / "strand_names.json", encoding="utf-8") as f:
    names = json.load(f)

# Vocabulary probe stems from external file (override with --probes <file>)
_probes_path = Path(__file__).parent / "vocabulary-probes.txt"
if "--probes" in sys.argv:
    _idx = sys.argv.index("--probes")
    _probes_path = Path(__file__).parent / sys.argv[_idx + 1]

probe_stems = []
if _probes_path.exists():
    with open(_probes_path, encoding="utf-8") as _f:
        for _line in _f:
            _line = _line.strip()
            if not _line or _line.startswith("#"):
                continue
            probe_stems.append(_line.split("|")[0].strip())
    print(f"  Probes: {_probes_path.name} ({len(probe_stems)} stems)")
else:
    print(f"  Warning: {_probes_path} not found, probe matches will be empty")


import unicodedata


def strip_accents(s: str) -> str:
    """Remove diacritics from a string (e.g., Ní → Ni)."""
    return "".join(
        c for c in unicodedata.normalize("NFD", s)
        if unicodedata.category(c) != "Mn"
    )


def wikilink_work(title: str) -> str:
    """Create a wikilink for a work title, using display alias if accented.

    Strips any existing [[ ]] wrapping first to prevent double-bracketing.
    If the ASCII filename differs from the display title (accents), uses
    [[ASCII Name|Display Name]] syntax.
    """
    # Strip existing wikilink brackets if present
    t = title.strip()
    while t.startswith("[[") and t.endswith("]]"):
        t = t[2:-2]

    ascii_name = strip_accents(t)
    if ascii_name != t:
        return f"[[{ascii_name}|{t}]]"
    return f"[[{t}]]"


def sanitize_filename(s: str, max_len: int = 100) -> str:
    """Make a string safe for use as a filename on Windows + Obsidian.
    Identical to 03_create_paper_pages.py."""
    s = re.sub(r'[\\/:*?"<>|]', '', s)
    s = re.sub(r'\s+', ' ', s).strip()
    if len(s) > max_len:
        s = s[:max_len].rsplit(' ', 1)[0]
    return s


def get_text(p):
    """Title + abstract text for probe matching."""
    abs_list = p.get("abstracts", [p.get("abstract", "")])
    return (p.get("title", "") + " " + " ".join(abs_list)).lower()


def build_lookup(papers):
    """Map sanitized filename (without .md) → paper dict."""
    lookup = {}
    for p in papers:
        title = p.get("title", "Untitled")
        year = p.get("year", "unknown")
        fname = sanitize_filename(f"{year} - {title}")
        lookup[fname] = p
    return lookup


def parse_page(text):
    """Split a page into (frontmatter_str, body_str).
    Returns (fm_text, body_text) where fm_text is between --- delimiters."""
    parts = text.split("---", 2)
    if len(parts) >= 3:
        return parts[1], parts[2]
    return "", text


def build_frontmatter(p, existing_fm_text):
    """Build updated YAML frontmatter incorporating strand data."""
    # Parse existing frontmatter
    try:
        fm = yaml.safe_load(existing_fm_text) or {}
    except yaml.YAMLError:
        fm = {}

    # Remove old fields
    fm.pop("strand", None)
    fm.pop("strands", None)
    fm.pop("strand_probs", None)
    fm.pop("probe_matches", None)

    # Corpus hub wikilink
    corpus = p.get("corpus", "angl")
    corpus_map = {"KCI": "[[KCI]]", "angl": "[[OpenAlex]]"}
    fm["source"] = corpus_map.get(corpus, corpus)

    # Add strand assignments
    topic_ids = p.get("lda_topics", [])
    topic_probs = p.get("lda_topic_probs", {})

    strand_links = []
    strand_probs = {}
    for tid in sorted(topic_ids, key=lambda t: float(topic_probs.get(str(t), 0)), reverse=True):
        sname = names.get(str(tid), f"Topic {tid}")
        strand_links.append(f"[[{sname}]]")
        prob = topic_probs.get(str(tid))
        if prob is not None:
            strand_probs[sname] = round(float(prob), 3)

    fm["strands"] = strand_links
    if strand_probs:
        fm["strand_probs"] = strand_probs

    # Add probe matches
    text = get_text(p)
    matches = [s for s in probe_stems if s in text]
    fm["probe_matches"] = matches

    # Reconstruct YAML — use manual construction for clean output
    lines = []
    # Preserve key ordering: title, title_alt, authors, year, source, doi, journal,
    # keywords, cited_by_count, strands, strand_probs, probe_matches, works_discussed
    key_order = [
        "title", "title_alt", "authors", "year", "source", "doi", "journal",
        "keywords", "cited_by_count", "strands", "strand_probs",
        "probe_matches", "works_discussed",
    ]

    emitted = set()
    for key in key_order:
        if key in fm:
            lines.append(format_yaml_field(key, fm[key]))
            emitted.add(key)

    # Any remaining keys not in the order
    for key, val in fm.items():
        if key not in emitted:
            lines.append(format_yaml_field(key, val))

    return "\n".join(lines)


def format_yaml_field(key, val):
    """Format a single YAML field for frontmatter."""
    if key == "source" and val.startswith("[["):
        return f"source: \"{val}\""
    elif key == "strands":
        items = "\n".join(f'  - "{v}"' for v in val)
        return f"strands:\n{items}"
    elif key == "strand_probs":
        items = "\n".join(f"  {k}: {v}" for k, v in val.items())
        return f"strand_probs:\n{items}"
    elif key == "probe_matches":
        return f"probe_matches: {json.dumps(val, ensure_ascii=False)}"
    elif key == "works_discussed":
        if not val:
            return "works_discussed: []"
        items = "\n".join(f'  - "{wikilink_work(v)}"' for v in val)
        return f"works_discussed:\n{items}"
    elif key == "authors":
        return f"authors: {json.dumps(val, ensure_ascii=False)}"
    elif key == "keywords":
        return f"keywords: {json.dumps(val, ensure_ascii=False)}"
    elif isinstance(val, str):
        if '"' in val:
            val = val.replace('"', "'")
        return f'{key}: "{val}"'
    elif isinstance(val, bool):
        return f"{key}: {str(val).lower()}"
    elif isinstance(val, (int, float)):
        return f"{key}: {val}"
    elif isinstance(val, list):
        return f"{key}: {json.dumps(val, ensure_ascii=False)}"
    else:
        return f"{key}: {val}"


if __name__ == "__main__":
    print("=== Paper Frontmatter Update ===\n")

    lookup = build_lookup(papers)
    print(f"Loaded {len(papers)} papers, {len(lookup)} unique filenames")

    updated = 0
    skipped = 0
    unmatched = 0

    all_paper_files = sorted(PAPERS_KCI_DIR.glob("*.md")) + sorted(PAPERS_OA_DIR.glob("*.md"))
    for fpath in all_paper_files:
        fname = fpath.stem  # filename without .md

        # Match to all_papers entry
        p = lookup.get(fname)
        if p is None:
            skipped += 1
            continue

        # Skip papers with no LDA assignments
        if not p.get("lda_topics"):
            skipped += 1
            continue

        # Read existing page
        text = fpath.read_text(encoding="utf-8")
        fm_text, body = parse_page(text)

        # Build new frontmatter
        new_fm = build_frontmatter(p, fm_text)

        # Reconstruct page
        new_text = f"---\n{new_fm}\n---{body}"

        fpath.write_text(new_text, encoding="utf-8")
        updated += 1

    print(f"\nUpdated: {updated}")
    print(f"Skipped (no match or no LDA): {skipped}")
    print(f"Total paper files: {updated + skipped}")
