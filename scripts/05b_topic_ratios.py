"""
05b_topic_ratios.py — Proportional representation analysis of LDA topics
=========================================================================

Compares how each corpus (KCI vs. angl) distributes across LDA topics,
normalized by corpus size. The ratio (KCI% / Angl%) reveals which
strands each tradition over- or under-represents relative to baseline.

This script is corpus-agnostic: it reads corpus labels from the data
and computes ratios for any number of sub-corpora. To adapt for a
different project, change only the data path and strand names.

Inputs:  _data/all_papers.json (with lda_topics field from 05)
         _data/strand_names.json (optional — falls back to "Topic N")
Outputs: _data/topic_ratios.json, console summary

Dependencies: none (stdlib only)
Run: python 05b_topic_ratios.py
"""

import json
import sys
import io
from pathlib import Path
from collections import defaultdict

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

# --- Config ---
config_path = Path(__file__).parent / "config.yaml"
import yaml
with open(config_path, encoding="utf-8") as f:
    config = yaml.safe_load(f)

_vr = Path(config["vault_root"])
VAULT_ROOT = _vr if _vr.is_absolute() else (Path(__file__).parent / _vr).resolve()
DATA_DIR = VAULT_ROOT / config["paths"]["data"]


def load_strand_names() -> dict:
    names_path = DATA_DIR / "strand_names.json"
    if names_path.exists():
        with open(names_path, encoding="utf-8") as f:
            return json.load(f)
    return {}


def analyze():
    # Load data
    with open(DATA_DIR / "all_papers.json", encoding="utf-8") as f:
        papers = json.load(f)

    strand_names = load_strand_names()

    # Only papers with LDA assignments
    modeled = [p for p in papers if p.get("lda_topics")]
    print("=== Topic Ratio Analysis ===\n")
    print(f"  Papers with LDA assignments: {len(modeled)}")

    # Discover corpora and topics from data
    corpora = sorted(set(p.get("corpus", "unknown") for p in modeled))
    all_topics = sorted(set(t for p in modeled for t in p.get("lda_topics", [])))

    # Corpus sizes
    corpus_sizes = {}
    for c in corpora:
        corpus_sizes[c] = sum(1 for p in modeled if p.get("corpus") == c)
        print(f"  {c}: {corpus_sizes[c]} papers ({corpus_sizes[c]/len(modeled)*100:.1f}%)")

    print(f"\n  Baseline share: {' / '.join(f'{c} {corpus_sizes[c]/len(modeled)*100:.1f}%' for c in corpora)}")

    # Count per topic per corpus
    topic_corpus_counts = defaultdict(lambda: defaultdict(int))
    for p in modeled:
        corpus = p.get("corpus", "unknown")
        for tid in p.get("lda_topics", []):
            topic_corpus_counts[tid][corpus] += 1

    # Build results
    results = []
    for tid in all_topics:
        name = strand_names.get(str(tid), f"Topic {tid}")
        counts = topic_corpus_counts[tid]
        total = sum(counts.values())

        row = {
            "topic_id": tid,
            "name": name,
            "total": total,
            "corpora": {},
        }

        for c in corpora:
            count = counts.get(c, 0)
            pct_of_corpus = count / corpus_sizes[c] * 100 if corpus_sizes[c] else 0
            pct_of_topic = count / total * 100 if total else 0
            row["corpora"][c] = {
                "count": count,
                "pct_of_corpus": round(pct_of_corpus, 1),
                "pct_of_topic": round(pct_of_topic, 1),
            }

        # Ratio: first corpus % / second corpus %
        # (generalizes to 2+ corpora by computing pairwise)
        if len(corpora) == 2:
            c1, c2 = corpora
            pct1 = row["corpora"][c1]["pct_of_corpus"]
            pct2 = row["corpora"][c2]["pct_of_corpus"]
            row["ratio"] = round(pct1 / pct2, 2) if pct2 > 0 else None
            row["ratio_label"] = f"{c1}/{c2}"

            if row["ratio"] and row["ratio"] >= 1.3:
                row["signal"] = f"{c1} overrep"
            elif row["ratio"] and row["ratio"] <= 0.7:
                row["signal"] = f"{c1} underrep"
            else:
                row["signal"] = "balanced"

        results.append(row)

    # Sort by ratio descending
    results.sort(key=lambda r: r.get("ratio", 0) or 0, reverse=True)

    # Print table
    if len(corpora) == 2:
        c1, c2 = corpora
        print(f"\n  {'Topic':<42} {c1+' %':>7} {c2+' %':>7} {'Ratio':>6}  Signal")
        print(f"  {'-'*42} {'-'*7} {'-'*7} {'-'*6}  {'-'*15}")
        for r in results:
            name = r["name"][:42]
            pct1 = r["corpora"][c1]["pct_of_corpus"]
            pct2 = r["corpora"][c2]["pct_of_corpus"]
            ratio = r.get("ratio", 0)
            signal = r.get("signal", "")
            print(f"  {name:<42} {pct1:>6.1f}% {pct2:>6.1f}% {ratio:>5.2f}x  {signal}")
    else:
        # Multi-corpus: simpler table
        header = f"  {'Topic':<35}"
        for c in corpora:
            header += f" {c+' %':>8}"
        print(f"\n{header}")
        print(f"  {'-'*35}" + " --------" * len(corpora))
        for r in results:
            line = f"  {r['name'][:35]:<35}"
            for c in corpora:
                pct = r["corpora"][c]["pct_of_corpus"]
                line += f" {pct:>7.1f}%"
            print(line)

    # Save
    output_path = DATA_DIR / "topic_ratios.json"
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump({
            "corpus_sizes": corpus_sizes,
            "baseline": {c: round(corpus_sizes[c]/len(modeled)*100, 1) for c in corpora},
            "topics": results,
        }, f, ensure_ascii=False, indent=2)

    print(f"\n  Saved to: {output_path}")
    print("\n=== Done ===")


if __name__ == "__main__":
    analyze()
