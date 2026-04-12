"""
05a_stopword_audit.py — Build and audit the complete stopword list for LDA
==========================================================================

Generates a consolidated stopword list from multiple sources, documents
each source, and audits the corpus for boilerplate contamination. The
output is a JSON file consumed by 05_lda_strands.py, ensuring the
stopword decisions are transparent and reproducible.

Sources:
  1. NLTK stopwords (English, French, Spanish, Portuguese, German, Italian)
  2. Domain stopwords: terms that appear in every Yeats abstract (e.g.,
     "yeats", "poem", "poetry") — carry no topical signal
  3. Korean grammatical morphemes: function words/particles that LDA
     picks up as pseudo-topics (e.g., 있다, 대한, 통해)
  4. Academic boilerplate: terms from scraped paywall pages, DOI
     metadata, and table-of-contents fragments that OpenAlex sometimes
     stores as "abstracts"

Also identifies and flags suspect abstracts (paywall scrapes, ToC
fragments) for optional exclusion.

Inputs:  _data/all_papers.json
Outputs: _data/stopwords.json, _data/boilerplate_flagged.json

Dependencies: nltk
Run: python 05a_stopword_audit.py
"""

import json
import re
from pathlib import Path
from collections import Counter

import nltk

# Ensure NLTK data is available
for resource in ["stopwords", "wordnet"]:
    try:
        nltk.data.find(f"corpora/{resource}")
    except LookupError:
        nltk.download(resource, quiet=True)

from nltk.corpus import stopwords

# --- Config ---
config_path = Path(__file__).parent / "config.yaml"
import yaml
with open(config_path, encoding="utf-8") as f:
    config = yaml.safe_load(f)

_vr = Path(config["vault_root"])
VAULT_ROOT = _vr if _vr.is_absolute() else (Path(__file__).parent / _vr).resolve()
DATA_DIR = VAULT_ROOT / config["paths"]["data"]


def build_stopwords() -> dict:
    """
    Build the complete stopword set from all sources.
    Returns a dict mapping each word to its source(s) for auditability.
    """
    stopword_registry = {}

    # 1. NLTK multilingual stopwords
    for lang in ["english", "french", "spanish", "portuguese", "german", "italian"]:
        for word in stopwords.words(lang):
            stopword_registry.setdefault(word, []).append(f"nltk_{lang}")

    # 2. Load researcher-editable stopwords from stopwords.txt
    stopwords_txt = Path(__file__).parent / "stopwords.txt"
    if stopwords_txt.exists():
        current_source = "custom"
        with open(stopwords_txt, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                if line.startswith("# ---"):
                    # Extract source name from section header
                    current_source = line.strip("# -").strip()
                    continue
                if line.startswith("#"):
                    continue
                stopword_registry.setdefault(line, []).append(current_source)
    else:
        print("  WARNING: stopwords.txt not found. Using NLTK stopwords only.")

    return stopword_registry


def flag_boilerplate_abstracts(papers: list) -> list:
    """
    Identify abstracts that are probably scraped page furniture rather
    than actual scholarly abstracts. These contaminate LDA.
    """
    boilerplate_patterns = [
        r"doi\.org",
        r"https?://",
        r"click to (increase|decrease)",
        r"you do not currently have access",
        r"search dropdown",
        r"toolbar search",
        r"download citation",
        r"cite icon cite",
        r"facebook.*twitter.*linkedin",
        r"auto suggest filter",
        # OpenAlex machine-generated keywords boilerplate
        r"keywords were added by machine",
        r"this process is experimental and the keywords may be updated",
        r"as the learning algorithm improves",
    ]
    compiled = [re.compile(p, re.IGNORECASE) for p in boilerplate_patterns]

    flagged = []
    for i, paper in enumerate(papers):
        abstract = paper.get("abstract", "")
        if not abstract:
            continue
        matches = [p.pattern for p in compiled if p.search(abstract)]
        if len(matches) >= 2:  # 2+ boilerplate signals = likely not a real abstract
            flagged.append({
                "index": i,
                "title": paper.get("title", ""),
                "corpus": paper.get("corpus", ""),
                "patterns_matched": matches,
                "abstract_preview": abstract[:200],
            })

    return flagged


def corpus_term_frequency(papers: list, stopword_set: set) -> list:
    """
    Count term frequency across all abstracts AFTER stopword removal,
    to verify no high-frequency noise terms remain.
    """
    counter = Counter()
    for paper in papers:
        abstract = paper.get("abstract", "")
        tokens = re.findall(r'[a-z]{3,}|[\uac00-\ud7a3]{2,}', abstract.lower())
        tokens = [t for t in tokens if t not in stopword_set]
        counter.update(set(tokens))  # document frequency, not raw count
    return counter.most_common(50)


if __name__ == "__main__":
    import sys
    import io
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

    print("=== Stopword Audit ===\n")

    # Build stopwords
    registry = build_stopwords()
    stopword_set = set(registry.keys())
    print(f"  Total stopwords: {len(stopword_set)}")

    # Count by source
    source_counts = Counter()
    for sources in registry.values():
        for s in sources:
            source_counts[s] += 1
    for source, count in sorted(source_counts.items()):
        print(f"    {source}: {count}")

    # Save stopwords with provenance
    stopwords_path = DATA_DIR / "stopwords.json"
    with open(stopwords_path, "w", encoding="utf-8") as f:
        json.dump({
            "total": len(stopword_set),
            "sources": dict(source_counts),
            "words": {w: srcs for w, srcs in sorted(registry.items())},
        }, f, ensure_ascii=False, indent=2)
    print(f"\n  Stopwords saved to: {stopwords_path}")

    # Flag boilerplate abstracts
    merged_path = DATA_DIR / "all_papers.json"
    with open(merged_path, encoding="utf-8") as f:
        papers = json.load(f)

    flagged = flag_boilerplate_abstracts(papers)
    print(f"\n  Boilerplate abstracts flagged: {len(flagged)} / {len(papers)}")

    flagged_path = DATA_DIR / "boilerplate_flagged.json"
    with open(flagged_path, "w", encoding="utf-8") as f:
        json.dump(flagged, f, ensure_ascii=False, indent=2)
    print(f"  Flagged papers saved to: {flagged_path}")

    if flagged:
        print("\n  Sample flagged abstracts:")
        for f in flagged[:5]:
            print(f"    [{f['corpus']}] {f['title'][:70]}")
            print(f"      patterns: {', '.join(f['patterns_matched'][:3])}")

    # Term frequency audit (post-stopword)
    print("\n  Top 50 terms after stopword removal (document frequency):")
    top_terms = corpus_term_frequency(papers, stopword_set)
    for term, count in top_terms:
        marker = "  <<<" if count > len(papers) * 0.3 else ""
        print(f"    {term:<25} {count:>5} ({count/len(papers)*100:.1f}%){marker}")

    print("\n=== Done ===")
    print("  >>> Review top terms for remaining noise.")
    print("  >>> Review boilerplate_flagged.json for bad abstracts.")
    print("  >>> Then re-run 05_lda_strands.py (it will load stopwords.json).")
