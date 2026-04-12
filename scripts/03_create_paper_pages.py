"""
03_create_paper_pages.py — Generate Obsidian vault pages from harvested data
=============================================================================

Merges OpenAlex and KCI harvest data, deduplicates by DOI, filters out
non-literary false positives (e.g., biology papers about the YEATS protein
domain), and generates one Obsidian markdown page per paper with YAML
frontmatter. Also creates stub pages for each Yeats work in config.yaml.

Inputs:  _data/openalex_raw.json, _data/kci_raw.json, config.yaml,
         works.txt, false-positives.txt
Outputs: papers/*.md, works/*.md, _data/all_papers.json

Dependencies: pyyaml
Run: python 03_create_paper_pages.py
"""

import html
import json
import re
import unicodedata
import yaml
from pathlib import Path

# --- Load config ---
config_path = Path(__file__).parent / "config.yaml"
with open(config_path, encoding="utf-8") as f:
    config = yaml.safe_load(f)

_vr = Path(config["vault_root"])
VAULT_ROOT = _vr if _vr.is_absolute() else (Path(__file__).parent / _vr).resolve()
DATA_DIR = VAULT_ROOT / config["paths"]["data"]
PAPERS_DIR = VAULT_ROOT / config["paths"]["papers"]
PAPERS_KCI_DIR = VAULT_ROOT / config["paths"]["papers_kci"]
PAPERS_OA_DIR = VAULT_ROOT / config["paths"]["papers_openalex"]
WORKS_DIR = VAULT_ROOT / config["paths"]["works"]
STRANDS_DIR = VAULT_ROOT / config["paths"]["strands"]

PAPERS_DIR.mkdir(parents=True, exist_ok=True)
PAPERS_KCI_DIR.mkdir(parents=True, exist_ok=True)
PAPERS_OA_DIR.mkdir(parents=True, exist_ok=True)
WORKS_DIR.mkdir(parents=True, exist_ok=True)
STRANDS_DIR.mkdir(parents=True, exist_ok=True)


ITALIC_TAGS = re.compile(
    r"<(?:em|i|italic)>(.*?)</(?:em|i|italic)>",
    re.IGNORECASE | re.DOTALL,
)
UNCLOSED_ITALIC = re.compile(
    r"<(?:em|i|italic)>(.*?)<(?:em|i|italic)>",
    re.IGNORECASE | re.DOTALL,
)


def decode_text(text: str) -> str:
    """Decode HTML entities, convert HTML italics to markdown, normalize quotes."""
    prev = None
    result = text
    for _ in range(3):
        prev = result
        result = html.unescape(result)
        if result == prev:
            break
    result = ITALIC_TAGS.sub(r"_\1_", result)
    result = UNCLOSED_ITALIC.sub(r"_\1_", result)
    result = re.sub(r"</?(?:em|i|italic|p)>", "", result, flags=re.IGNORECASE)
    result = result.replace("\r\n", "\n").replace("\r", "")
    # Smart quotes → straight quotes
    result = result.replace("\u201c", '"').replace("\u201d", '"')
    result = result.replace("\u2018", "'").replace("\u2019", "'")
    # Literal \n → actual newline
    result = result.replace("\\n", "\n")
    # Strip &#13; remnants (carriage return entities that survived unescape)
    result = result.replace("\r", "")
    return result


def decode_paper(paper: dict) -> dict:
    """Decode HTML entities in all text fields of a paper dict."""
    for key in ("title", "abstract", "source_journal"):
        if paper.get(key):
            paper[key] = decode_text(paper[key])
    for list_key in ("authors", "keywords"):
        if paper.get(list_key):
            paper[list_key] = [decode_text(v) for v in paper[list_key]]
    if paper.get("titles"):
        paper["titles"] = [decode_text(v) for v in paper["titles"]]
    if paper.get("abstracts"):
        paper["abstracts"] = [decode_text(v) for v in paper["abstracts"]]
    return paper


def sanitize_filename(s: str, max_len: int = 100) -> str:
    """Make a string safe for use as a filename on Windows + Obsidian."""
    s = re.sub(r'[\\/:*?"<>|]', '', s)
    s = re.sub(r'\s+', ' ', s).strip()
    if len(s) > max_len:
        s = s[:max_len].rsplit(' ', 1)[0]  # break at word boundary
    return s


def make_paper_page(paper: dict) -> tuple[str, str]:
    """
    Generate (filename, markdown_content) for a paper.
    Returns the filename (without .md) and the full file content.
    """
    title = paper.get("title", "Untitled")
    year = paper.get("year", "unknown")
    authors = paper.get("authors", [])
    doi = paper.get("doi", "")
    abstract = paper.get("abstract", "")
    corpus = paper.get("corpus", "angl")
    keywords = paper.get("keywords", [])
    cited_by = paper.get("cited_by_count", 0)
    journal = paper.get("source_journal", "")

    # For KCI papers, use bilingual info if available
    titles = paper.get("titles", [title])
    abstracts = paper.get("abstracts", [abstract])

    # Filename: "Year - Title"
    fname = sanitize_filename(f"{year} - {title}")

    # Build YAML frontmatter
    # Using block scalar (|) for abstract to handle multiline
    fm_lines = [
        "---",
        f'title: "{title.replace(chr(34), chr(39))}"',
    ]
    if len(titles) > 1:
        fm_lines.append(f'title_alt: "{titles[1].replace(chr(34), chr(39))}"')
    fm_lines.append(f'authors: {json.dumps(authors, ensure_ascii=False)}')
    fm_lines.append(f"year: {year}")
    fm_lines.append(f'source: "{corpus}"')
    if doi:
        fm_lines.append(f'doi: "{doi}"')
    if journal:
        fm_lines.append(f'journal: "{journal.replace(chr(34), chr(39))}"')
    if keywords:
        fm_lines.append(f'keywords: {json.dumps(keywords, ensure_ascii=False)}')
    if cited_by:
        fm_lines.append(f"cited_by_count: {cited_by}")
    fm_lines.append('strand: ""  # filled by 05_lda_strands.py')
    fm_lines.append('works_discussed: []  # filled by 04_subject_assign.py')
    fm_lines.append("---")

    # Build body
    body_lines = []

    # Abstract section — use English only for bilingual papers
    if abstracts:
        body_lines.append("\n## Abstract\n")
        if len(abstracts) > 1:
            # Bilingual: show only English (last element)
            body_lines.append(abstracts[-1] + "\n")
        else:
            body_lines.append(abstracts[0] + "\n")

    # Links section (placeholder — filled by subject assignment)
    body_lines.append("\n## Links\n")
    body_lines.append("*Works discussed will be linked by `04_subject_assign.py`.*\n")

    content = "\n".join(fm_lines) + "\n" + "\n".join(body_lines)
    return fname, content


def strip_accents(s: str) -> str:
    """Remove diacritics from a string (e.g., Ní → Ni)."""
    return "".join(
        c for c in unicodedata.normalize("NFD", s)
        if unicodedata.category(c) != "Mn"
    )


def load_works():
    """Load works from works.txt (pipe-delimited)."""
    works_path = Path(__file__).parent / "works.txt"
    works = []
    with open(works_path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            parts = [p.strip() for p in line.split("|")]
            if len(parts) >= 4:
                works.append({"title": parts[0], "type": parts[1], "year": parts[2]})
    return works


def create_work_stubs():
    """Create placeholder pages for each Yeats work defined in works.txt.
    Uses ASCII filenames with Obsidian aliases for accented titles."""
    works = load_works()
    created = 0
    for work in works:
        title = work["title"]
        ascii_title = strip_accents(title)
        fname = sanitize_filename(ascii_title)
        fpath = WORKS_DIR / f"{fname}.md"
        if fpath.exists():
            continue
        # Add aliases frontmatter if title has accents
        alias_line = ""
        if ascii_title != title:
            alias_line = f'\naliases: ["{title}"]'
        content = f"""---
title: "{title}"
type: work
author: "W.B. Yeats"{alias_line}
---

# {title}

*Papers discussing this work will link here via `04_subject_assign.py`.*
"""
        fpath.write_text(content, encoding="utf-8")
        created += 1
    return created


if __name__ == "__main__":
    print("=== Paper Page Creation ===\n")

    # Load harvested data
    all_papers = []

    openalex_path = DATA_DIR / "openalex_raw.json"
    kci_path = DATA_DIR / "kci_raw.json"

    if openalex_path.exists():
        with open(openalex_path, encoding="utf-8") as f:
            openalex_papers = json.load(f)
        print(f"  Loaded {len(openalex_papers)} papers from OpenAlex")
        all_papers.extend(openalex_papers)
    else:
        print(f"  WARNING: {openalex_path} not found. Run 01_harvest_openalex.py first.")

    if kci_path.exists():
        with open(kci_path, encoding="utf-8") as f:
            kci_papers = json.load(f)
        print(f"  Loaded {len(kci_papers)} papers from KCI")
        all_papers.extend(kci_papers)
    else:
        print(f"  WARNING: {kci_path} not found. Run 02_harvest_kci.py first.")

    if not all_papers:
        print("  No papers to process. Exiting.")
        exit(1)

    # Decode HTML entities in all text fields
    for p in all_papers:
        decode_paper(p)
    print(f"  Decoded HTML entities in {len(all_papers)} papers")

    # Deduplicate by DOI, then by normalized title
    seen_dois = set()
    seen_titles = set()
    unique_papers = []
    doi_dupes = 0
    title_dupes = 0
    for paper in all_papers:
        doi = (paper.get("doi") or "").strip().lower()
        if doi and doi in seen_dois:
            doi_dupes += 1
            continue
        # Normalize title: lowercase, strip HTML tags, collapse whitespace
        raw_title = (paper.get("title") or "").strip()
        norm_title = re.sub(r"<[^>]+>", "", raw_title).lower().strip()
        norm_title = re.sub(r"\s+", " ", norm_title)
        if norm_title and norm_title in seen_titles:
            title_dupes += 1
            continue
        if doi:
            seen_dois.add(doi)
        if norm_title:
            seen_titles.add(norm_title)
        unique_papers.append(paper)

    print(f"  Deduplicated: {doi_dupes} by DOI, {title_dupes} by title, {len(unique_papers)} unique papers")

    # Remove papers without abstracts (no value for topic modeling or gap analysis)
    no_abstract = sum(1 for p in unique_papers if not (p.get("abstract") or "").strip())
    unique_papers = [p for p in unique_papers if (p.get("abstract") or "").strip()]
    print(f"  Removed {no_abstract} papers without abstracts, {len(unique_papers)} remain")

    # --- Abstract language cleanup ---

    # For bilingual KCI papers, use English abstract only (index -1).
    # KCI API returns [Korean, English] in order; using the section position
    # avoids the old regex approach which failed on English-only "Korean" fields.
    bilingual_fixed = 0
    for p in unique_papers:
        abstracts = p.get("abstracts", [])
        if len(abstracts) > 1:
            p["abstract"] = abstracts[-1]  # English is always last
            bilingual_fixed += 1
    print(f"  Used English abstract for {bilingual_fixed} bilingual papers")

    # Remove Korean-dominant abstracts (Korean text with only proper nouns in Latin).
    def is_korean_dominant(paper):
        text = paper.get("abstract", "")
        ko = len(re.findall(r'[\uac00-\ud7a3]', text))
        latin_words = re.findall(r'[a-zA-Z]{3,}', text)
        # If Korean chars dominate and Latin words are mostly just names/titles
        return ko > 50 and len(latin_words) < 30

    ko_dominant = sum(1 for p in unique_papers if is_korean_dominant(p))
    unique_papers = [p for p in unique_papers if not is_korean_dominant(p)]
    print(f"  Removed {ko_dominant} Korean-dominant abstracts, {len(unique_papers)} remain")

    # Remove foreign-language abstracts (French, Portuguese, German, Italian, etc.).
    # Detects by counting common romance/Germanic function words.
    _foreign_words = re.compile(
        r'\b(?:cette|dans|avec|pour|mais|donc|sont|peut|fait|tout|tous|toute'
        r'|della|degli|delle|anche|essere|sono|molto'
        r'|como|pero|desde|sobre|tambien|puede|todo|todos'
        r'|eine|eines|durch|werden|nicht|dass|diese|seiner)\b'
    )

    def is_foreign(paper):
        text = paper.get("abstract", "")
        hits = _foreign_words.findall(text.lower())
        return len(hits) >= 5

    foreign = sum(1 for p in unique_papers if is_foreign(p))
    unique_papers = [p for p in unique_papers if not is_foreign(p)]
    print(f"  Removed {foreign} foreign-language abstracts, {len(unique_papers)} remain\n")

    # Create paper pages in corpus subdirectories
    created = 0
    skipped = 0
    for paper in unique_papers:
        fname, content = make_paper_page(paper)
        corpus = paper.get("corpus", "angl")
        subdir = PAPERS_KCI_DIR if corpus == "KCI" else PAPERS_OA_DIR
        fpath = subdir / f"{fname}.md"
        if fpath.exists():
            skipped += 1
            continue
        fpath.write_text(content, encoding="utf-8")
        created += 1

    # Create work stubs
    works_created = create_work_stubs()

    # Save merged + deduplicated data for downstream scripts
    merged_path = DATA_DIR / "all_papers.json"
    with open(merged_path, "w", encoding="utf-8") as f:
        json.dump(unique_papers, f, ensure_ascii=False, indent=2)

    # Create corpus hub pages with wikilinks to all papers
    hub_configs = [
        ("KCI", PAPERS_KCI_DIR, VAULT_ROOT / "KCI.md"),
        ("OpenAlex", PAPERS_OA_DIR, VAULT_ROOT / "OpenAlex.md"),
    ]
    for hub_name, papers_dir, hub_path in hub_configs:
        stems = sorted(p.stem for p in papers_dir.glob("*.md"))
        links = "\n".join(f"- [[{stem}]]" for stem in stems)
        hub_content = f"---\ntype: corpus\n---\n\n# {hub_name}\n\n## Papers\n\n{links}\n"
        hub_path.write_text(hub_content, encoding="utf-8")
        print(f"  Hub page: {hub_name}.md ({len(stems)} papers)")

    print("\n=== Done ===")
    print(f"  Paper pages created: {created}")
    print(f"  Paper pages skipped (already exist): {skipped}")
    print(f"  Work stubs created: {works_created}")
    print(f"  Merged data saved to: {merged_path}")
