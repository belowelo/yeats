"""
01_harvest_openalex.py — Harvest anglophone Yeats papers from OpenAlex
======================================================================

Queries the OpenAlex REST API for papers with the configured subject
in the title, within a date range. Reconstructs abstracts from
OpenAlex's inverted-index compression format. Paginates via cursor.

OpenAlex provides broad humanities coverage without authentication,
making it suitable for corpus construction where volume matters more
than citation-graph depth.

Inputs:  config.yaml (search terms, date range)
Outputs: _data/openalex_raw.json

Dependencies: requests, pyyaml
Run: python 01_harvest_openalex.py
"""

import json
import re
import time
import requests
import yaml
from pathlib import Path


def normalize_text(s: str) -> str:
    """Normalize Unicode oddities from API responses.
    Replaces smart quotes, en/em dashes, non-breaking spaces, etc.
    with their ASCII equivalents."""
    if not s:
        return s
    replacements = {
        "\u201c": '"', "\u201d": '"',  # smart double quotes
        "\u2018": "'", "\u2019": "'",  # smart single quotes
        "\u2013": "-", "\u2014": "-",  # en/em dash
        "\u00a0": " ",                 # non-breaking space
        "\u2010": "-",                 # hyphen
        "\u2011": "-",                 # non-breaking hyphen
        "\u2012": "-",                 # figure dash
    }
    for old, new in replacements.items():
        s = s.replace(old, new)
    # Collapse multiple spaces
    s = re.sub(r' {2,}', ' ', s)
    return s.strip()

# --- Load config ---
config_path = Path(__file__).parent / "config.yaml"
with open(config_path, encoding="utf-8") as f:
    config = yaml.safe_load(f)

SEARCH_TERMS = config["search_terms"]["openalex"]
DATE_MIN, DATE_MAX = config["date_range"]
_vr = Path(config["vault_root"])
VAULT_ROOT = _vr if _vr.is_absolute() else (Path(__file__).parent / _vr).resolve()
DATA_DIR = VAULT_ROOT / config["paths"]["data"]
DATA_DIR.mkdir(parents=True, exist_ok=True)

OUTPUT_FILE = DATA_DIR / "openalex_raw.json"

BASE_URL = "https://api.openalex.org/works"
HEADERS = {"User-Agent": "yeats-pipeline (academic research)"}
PER_PAGE = 200  # max allowed by OpenAlex


def reconstruct_abstract(inverted_index: dict) -> str:
    """Reconstruct abstract text from OpenAlex's inverted-index format."""
    if not inverted_index:
        return ""
    position_word = {}
    for word, positions in inverted_index.items():
        for pos in positions:
            position_word[pos] = word
    return " ".join(position_word[i] for i in sorted(position_word.keys()))


def harvest_openalex():
    """Harvest all matching papers via cursor-based pagination.

    Runs a separate paginated query for each search term in config,
    then deduplicates by OpenAlex ID. This catches possessive forms
    (e.g., "Yeats's") that title.search treats as distinct tokens.
    """
    seen_ids = set()
    all_papers = []

    for search_query in SEARCH_TERMS:
        print(f"  Search term: \"{search_query}\"")
        params = {
            "filter": f"title.search:{search_query},publication_year:{DATE_MIN}-{DATE_MAX}",
            "per_page": PER_PAGE,
            "cursor": "*",
            "select": "id,title,authorships,publication_year,doi,abstract_inverted_index,cited_by_count,primary_location"
        }

        page = 0
        while True:
            page += 1
            print(f"    page {page}... ", end="", flush=True)

            resp = requests.get(BASE_URL, params=params, headers=HEADERS)
            resp.raise_for_status()
            data = resp.json()

            results = data.get("results", [])
            if not results:
                print("done.")
                break

            new = 0
            for work in results:
                oa_id = work.get("id", "")
                if oa_id in seen_ids:
                    continue
                seen_ids.add(oa_id)

                # Extract author names
                authors = []
                for authorship in work.get("authorships", []):
                    name = authorship.get("author", {}).get("display_name")
                    if name:
                        authors.append(name)

                # Extract journal name
                loc = work.get("primary_location") or {}
                source = loc.get("source") or {}
                journal = source.get("display_name", "")

                paper = {
                    "title": normalize_text(work.get("title", "")),
                    "authors": [normalize_text(a) for a in authors],
                    "year": work.get("publication_year"),
                    "doi": work.get("doi", ""),
                    "abstract": normalize_text(reconstruct_abstract(work.get("abstract_inverted_index") or {})),
                    "cited_by_count": work.get("cited_by_count", 0),
                    "source_journal": normalize_text(journal),
                    "openalex_id": oa_id,
                    "corpus": "angl"  # tag for later merging
                }
                all_papers.append(paper)
                new += 1

            print(f"{new} new, {len(results) - new} dupes (total unique: {len(all_papers)})")

            # Get next cursor
            next_cursor = data.get("meta", {}).get("next_cursor")
            if not next_cursor:
                print("    No more pages.")
                break
            params["cursor"] = next_cursor

            # Polite delay
            time.sleep(0.2)

    return all_papers


if __name__ == "__main__":
    print(f"=== OpenAlex Harvest: '{config['subject']}' ({DATE_MIN}-{DATE_MAX}) ===\n")

    papers = harvest_openalex()

    # Save raw data
    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        json.dump(papers, f, ensure_ascii=False, indent=2)

    # Quick stats
    with_abstract = sum(1 for p in papers if p["abstract"])
    print("\n=== Done ===")
    print(f"  Total papers: {len(papers)}")
    print(f"  With abstracts: {with_abstract}")
    print(f"  Without abstracts: {len(papers) - with_abstract}")
    print(f"  Saved to: {OUTPUT_FILE}")
