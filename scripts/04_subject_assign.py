"""
04_subject_assign.py — Match papers to Yeats works via keyword matching
========================================================================

Assigns papers to specific Yeats works using case-insensitive substring
matching against titles, abstracts, and keywords. Supports bilingual
match terms (English + Korean) defined in config.yaml.

Substring matching is used deliberately over ML classification: it is
fully transparent, easily auditable, and allows the researcher to review
and correct assignments manually. A paper may be assigned to multiple
works (dual-tagging).

Inputs:  _data/all_papers.json, works.txt
Outputs: _data/subject_assignments.json, updated papers/*.md, updated _data/all_papers.json

Dependencies: pyyaml
Run: python 04_subject_assign.py
"""

import json
import re
import unicodedata
import yaml
from pathlib import Path
from collections import Counter

# --- Load config ---
config_path = Path(__file__).parent / "config.yaml"
with open(config_path, encoding="utf-8") as f:
    config = yaml.safe_load(f)

_vr = Path(config["vault_root"])
VAULT_ROOT = _vr if _vr.is_absolute() else (Path(__file__).parent / _vr).resolve()
DATA_DIR = VAULT_ROOT / config["paths"]["data"]
PAPERS_KCI_DIR = VAULT_ROOT / config["paths"]["papers_kci"]
PAPERS_OA_DIR = VAULT_ROOT / config["paths"]["papers_openalex"]
# Load works from works.txt (pipe-delimited)
_works_path = Path(__file__).parent / "works.txt"
WORKS = []
with open(_works_path, encoding="utf-8") as _f:
    for _line in _f:
        _line = _line.strip()
        if not _line or _line.startswith("#"):
            continue
        _parts = [p.strip() for p in _line.split("|")]
        if len(_parts) >= 4:
            _terms = [t.strip() for t in _parts[3].split(",")]
            WORKS.append({"title": _parts[0], "match_terms": _terms})


def sanitize_filename(s: str, max_len: int = 100) -> str:
    s = re.sub(r'[\\/:*?"<>|]', '', s)
    s = re.sub(r'\s+', ' ', s).strip()
    if len(s) > max_len:
        s = s[:max_len].rsplit(' ', 1)[0]
    return s


def assign_works(paper: dict) -> list[str]:
    """
    Check which Yeats works a paper discusses.
    Returns list of work titles that matched.

    Simple substring matching — intentionally transparent.
    The researcher corrects false positives/negatives manually.
    """
    # Build searchable text from paper
    text_parts = [paper.get("title", "")]
    text_parts.extend(paper.get("titles", []))
    text_parts.append(paper.get("abstract", ""))
    text_parts.extend(paper.get("abstracts", []))
    text_parts.extend(paper.get("keywords", []))
    searchable = " ".join(text_parts).lower()

    matched_works = []
    for work in WORKS:
        for term in work["match_terms"]:
            if term.lower() in searchable:
                matched_works.append(work["title"])
                break  # one match per work is enough

    return matched_works


def update_paper_file(paper: dict, matched_works: list[str]):
    """Update the paper's .md file with work assignments."""
    year = paper.get("year", "unknown")
    title = paper.get("title", "Untitled")
    fname = sanitize_filename(f"{year} - {title}")

    # Check both corpus subdirs
    corpus = paper.get("corpus", "angl")
    subdir = PAPERS_KCI_DIR if corpus == "KCI" else PAPERS_OA_DIR
    fpath = subdir / f"{fname}.md"

    if not fpath.exists():
        return False

    content = fpath.read_text(encoding="utf-8")

    # Update works_discussed in frontmatter
    works_yaml = json.dumps(matched_works, ensure_ascii=False)
    replacement = f'works_discussed: {works_yaml}'
    content = re.sub(
        r'works_discussed: \[.*?\]',
        lambda m: replacement,
        content
    )

    # Update links section with wikilinks
    links_section = "\n## Links\n\n"
    if matched_works:
        links_section += "**Discusses:**\n"
        for w in matched_works:
            ascii_w = "".join(
                c for c in unicodedata.normalize("NFD", w)
                if unicodedata.category(c) != "Mn"
            )
            if ascii_w != w:
                links_section += f"- [[{ascii_w}|{w}]]\n"
            else:
                links_section += f"- [[{w}]]\n"
    else:
        links_section += "*No specific Yeats works identified. General Yeats scholarship.*\n"

    # Replace the links section
    content = re.sub(
        r'\n## Links\n.*?(?=\n## |\Z)',
        links_section,
        content,
        flags=re.DOTALL
    )

    fpath.write_text(content, encoding="utf-8")
    return True


if __name__ == "__main__":
    print("=== Subject Assignment ===\n")

    # Load merged data
    merged_path = DATA_DIR / "all_papers.json"
    if not merged_path.exists():
        print(f"  ERROR: {merged_path} not found. Run 03_create_paper_pages.py first.")
        exit(1)

    with open(merged_path, encoding="utf-8") as f:
        all_papers = json.load(f)

    print(f"  Loaded {len(all_papers)} papers\n")

    # Assign works
    assignments = {}  # paper_title -> [work_titles]
    work_counts = Counter()  # work_title -> count
    corpus_work_counts = {"KCI": Counter(), "angl": Counter()}

    papers_with_match = 0
    papers_without = 0

    for paper in all_papers:
        matched = assign_works(paper)
        title = paper.get("title", "Untitled")
        assignments[title] = matched
        paper["works_discussed"] = matched  # add to data

        if matched:
            papers_with_match += 1
            for w in matched:
                work_counts[w] += 1
                corpus = paper.get("corpus", "angl")
                corpus_work_counts[corpus][w] += 1
        else:
            papers_without += 1

        # Update .md file
        update_paper_file(paper, matched)

    # Save assignments
    assign_path = DATA_DIR / "subject_assignments.json"
    with open(assign_path, "w", encoding="utf-8") as f:
        json.dump(assignments, f, ensure_ascii=False, indent=2)

    # Print summary table
    print(f"  Papers with work match: {papers_with_match}")
    print(f"  Papers without match (general scholarship): {papers_without}")
    print()

    print(f"  {'Work':<35} {'Total':>6} {'KCI':>6} {'Angl':>6}")
    print(f"  {'-'*35} {'-'*6} {'-'*6} {'-'*6}")
    for work_title, count in work_counts.most_common():
        kci = corpus_work_counts["KCI"].get(work_title, 0)
        angl = corpus_work_counts["angl"].get(work_title, 0)
        print(f"  {work_title:<35} {count:>6} {kci:>6} {angl:>6}")

    # Write back to all_papers.json so downstream scripts have works_discussed
    merged_path = DATA_DIR / "all_papers.json"
    with open(merged_path, "w", encoding="utf-8") as f:
        json.dump(all_papers, f, ensure_ascii=False, indent=2)

    print(f"\n  Assignments saved to: {assign_path}")
    print(f"  Updated: {merged_path}")
    print("\n  >>> REVIEW: check _data/subject_assignments.json for false positives.")
