"""
02_harvest_kci.py — Harvest Korean Yeats papers from KCI Open API
=================================================================

Queries the Korea Citation Index (KCI) Open API for papers matching
configured search terms. Returns bilingual metadata (Korean + English
titles, abstracts, keywords) for all matching papers.

Two-pass harvest: (1) articleSearch for bulk retrieval with title search,
then (2) articleDetail for each paper to retrieve author keywords and
language metadata not available in the search response. Keywords are
particularly valuable for subject assignment, as they often name
specific works discussed (e.g., "Cathleen ni Houlihan", "Crazy Jane").

The KCI Open API supports keyword search by title, author, journal,
abstract, and date range — enabling targeted retrieval rather than
full-corpus harvesting. This is preferable to KCI's OAI-PMH endpoint,
which offers no server-side filtering and requires scanning the entire
Korean academic corpus (~500k+ records) with local keyword matching.

Inputs:  config.yaml (search terms, date range, API key)
Outputs: _data/kci_raw.json

Dependencies: pyyaml
Run: python 02_harvest_kci.py
"""

import json
import re
import time
import urllib.request
import urllib.parse
import xml.etree.ElementTree as ET
import yaml
from pathlib import Path


def normalize_text(s: str) -> str:
    """Normalize Unicode oddities from API responses."""
    if not s:
        return s
    replacements = {
        "\u201c": '"', "\u201d": '"',
        "\u2018": "'", "\u2019": "'",
        "\u2013": "-", "\u2014": "-",
        "\u00a0": " ",
        "\u2010": "-", "\u2011": "-", "\u2012": "-",
    }
    for old, new in replacements.items():
        s = s.replace(old, new)
    s = re.sub(r' {2,}', ' ', s)
    return s.strip()

# --- Load config ---
config_path = Path(__file__).parent / "config.yaml"
with open(config_path, encoding="utf-8") as f:
    config = yaml.safe_load(f)

SEARCH_TERMS = config["search_terms"]["kci"]
DATE_MIN, DATE_MAX = config["date_range"]

# API key: environment variable > .env file
import os
API_KEY = os.environ.get("KCI_API_KEY")
if not API_KEY:
    env_path = Path(__file__).parent / ".env"
    if env_path.exists():
        for line in env_path.read_text().splitlines():
            if line.startswith("KCI_API_KEY="):
                API_KEY = line.split("=", 1)[1].strip()
if not API_KEY:
    print("ERROR: Set KCI_API_KEY environment variable or create .env file.")
    print("See .env.example for format.")
    exit(1)
_vr = Path(config["vault_root"])
VAULT_ROOT = _vr if _vr.is_absolute() else (Path(__file__).parent / _vr).resolve()
DATA_DIR = VAULT_ROOT / config["paths"]["data"]
DATA_DIR.mkdir(parents=True, exist_ok=True)

OUTPUT_FILE = DATA_DIR / "kci_raw.json"

# --- KCI Open API ---
BASE_URL = "https://open.kci.go.kr/po/openapi/openApiSearch.kci"
PER_PAGE = 100  # max allowed by KCI


def fetch_page(title: str, page: int = 1) -> ET.Element:
    """Fetch a single page of results from KCI articleSearch endpoint."""
    params = {
        "key": API_KEY,
        "apiCode": "articleSearch",
        "title": title,
        "displayCount": str(PER_PAGE),
        "page": str(page),
    }
    if DATE_MIN:
        params["dateFrom"] = f"{DATE_MIN}01"
    if DATE_MAX:
        params["dateTo"] = f"{DATE_MAX}12"

    url = BASE_URL + "?" + urllib.parse.urlencode(params, encoding="utf-8")
    resp = urllib.request.urlopen(url)
    return ET.fromstring(resp.read())


def parse_records(root: ET.Element) -> list[dict]:
    """Extract paper metadata from KCI XML response."""
    papers = []
    for rec in root.findall(".//record"):
        ai = rec.find("articleInfo")
        ji = rec.find("journalInfo")
        if ai is None:
            continue

        # Bilingual titles
        titles = []
        for t in ai.findall(".//article-title"):
            txt = normalize_text(t.text or "")
            if txt:
                titles.append(txt)

        # Authors
        authors = []
        for a in ai.findall(".//author"):
            txt = normalize_text(a.text or "")
            if txt:
                authors.append(txt)

        # Bilingual abstracts
        abstracts = []
        for ab in ai.findall(".//abstract"):
            txt = normalize_text(ab.text or "")
            if txt:
                abstracts.append(txt)

        # Keywords
        keywords = []
        for kw in ai.findall(".//keyword"):
            txt = normalize_text(kw.text or "")
            if txt:
                keywords.append(txt)

        # Journal metadata
        year = None
        journal = ""
        if ji is not None:
            year = int(ji.findtext("pub-year") or 0) or None
            journal = (ji.findtext("journal-name") or "").strip()

        paper = {
            "article_id": ai.get("article-id", ""),
            "titles": titles,
            "title": titles[0] if titles else "",
            "authors": authors,
            "year": year,
            "doi": (ai.findtext(".//doi") or "").strip(),
            "journal": journal,
            "keywords": keywords,
            "abstracts": abstracts,
            "abstract": abstracts[0] if abstracts else "",
            "corpus": "KCI",
        }
        papers.append(paper)

    return papers


def harvest_kci():
    """
    Search KCI for all configured terms, paginate, and deduplicate
    by article_id. Multiple search terms may return overlapping results.
    """
    all_papers = {}  # article_id -> paper dict

    for term in SEARCH_TERMS:
        # Get first page to learn total
        root = fetch_page(term, page=1)
        total_el = root.findtext(".//total")
        if not total_el or total_el == "0":
            print(f'  "{term}": no results')
            continue

        total = int(total_el)
        pages_needed = (total + PER_PAGE - 1) // PER_PAGE
        print(f'  "{term}": {total} results ({pages_needed} pages)')

        # Parse first page
        for p in parse_records(root):
            all_papers.setdefault(p["article_id"], p)

        # Fetch remaining pages
        for pg in range(2, pages_needed + 1):
            time.sleep(0.3)
            root = fetch_page(term, page=pg)
            for p in parse_records(root):
                all_papers.setdefault(p["article_id"], p)
            print(f"    page {pg}/{pages_needed}, unique so far: {len(all_papers)}")

    return list(all_papers.values())


def fetch_detail(article_id: str) -> dict | None:
    """Fetch detailed metadata for a single paper (keywords, language, etc.)."""
    params = {
        "key": API_KEY,
        "apiCode": "articleDetail",
        "id": article_id,
    }
    url = BASE_URL + "?" + urllib.parse.urlencode(params, encoding="utf-8")
    try:
        resp = urllib.request.urlopen(url)
        root = ET.fromstring(resp.read())
    except Exception:
        return None

    ai = root.find(".//articleInfo")
    if ai is None:
        return None

    keywords = []
    for kw in ai.findall(".//keyword"):
        txt = (kw.text or "").strip()
        if txt:
            keywords.append(txt)

    language = (ai.findtext("article-language") or "").strip()

    return {"keywords": keywords, "language": language}


def enrich_with_details(papers: list[dict]):
    """Fetch articleDetail for each paper to get keywords and language."""
    print(f"\n  Fetching article details for {len(papers)} papers...")
    enriched = 0
    for i, paper in enumerate(papers):
        aid = paper.get("article_id")
        if not aid:
            continue

        detail = fetch_detail(aid)
        if detail:
            if detail["keywords"]:
                paper["keywords"] = detail["keywords"]
                enriched += 1
            if detail["language"]:
                paper["language"] = detail["language"]

        if (i + 1) % 50 == 0:
            print(f"    {i + 1}/{len(papers)} ({enriched} with keywords)")

        time.sleep(0.15)

    print(f"  Done: {enriched}/{len(papers)} papers enriched with keywords")


if __name__ == "__main__":
    import sys
    import io

    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
    print(f"=== KCI Harvest: '{config['subject']}' ({DATE_MIN}-{DATE_MAX}) ===\n")

    papers = harvest_kci()
    enrich_with_details(papers)

    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        json.dump(papers, f, ensure_ascii=False, indent=2)

    with_abstract = sum(1 for p in papers if p["abstract"])
    with_keywords = sum(1 for p in papers if p["keywords"])
    print("\n=== Done ===")
    print(f"  Total papers: {len(papers)}")
    print(f"  With abstracts: {with_abstract}")
    print(f"  With keywords: {with_keywords}")
    print(f"  Saved to: {OUTPUT_FILE}")
