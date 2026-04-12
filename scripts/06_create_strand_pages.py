"""
06_create_strand_pages.py — Generate Obsidian pages for LDA research strands
=============================================================================

Creates one markdown page per LDA topic in the strands/ directory, with
YAML frontmatter, distribution stats, co-tagging tables, and vocabulary
probe results. All content is computed from data files — no researcher
commentary is included (that belongs in lda_findings.md).

Also generates strand reading files in strands/reading/ — one per topic,
containing every paper title + abstract organized by corpus, plus an
exceptions section listing papers that break the dominant co-tagging pattern.

Inputs:  _data/all_papers.json, _data/strand_names.json,
         _data/lda_topics.json, _data/topic_ratios.json, config.yaml
Outputs: strands/<strand_name>.md, strands/reading/<strand_name>.md

Dependencies: pyyaml
Run: python 06_create_strand_pages.py
"""

import json
import sys
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
STRANDS_DIR = VAULT_ROOT / config["paths"]["strands"]

# --- Load data ---
with open(DATA_DIR / "all_papers.json", encoding="utf-8") as f:
    papers = json.load(f)
with open(DATA_DIR / "strand_names.json", encoding="utf-8") as f:
    names = json.load(f)
with open(DATA_DIR / "lda_topics.json", encoding="utf-8") as f:
    lda = json.load(f)
with open(DATA_DIR / "topic_ratios.json", encoding="utf-8") as f:
    ratios_data = json.load(f)

# Build ratio lookup by topic_id
ratios = {t["topic_id"]: t for t in ratios_data["topics"]}

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
    print(f"  Warning: {_probes_path} not found, probe tables will be empty")


def get_text(p):
    """Title + abstract text for probe matching."""
    abs_list = p.get("abstracts", [p.get("abstract", "")])
    return (p.get("title", "") + " " + " ".join(abs_list)).lower()


def compute_cotags(subset, tid):
    """Count co-occurring topics for a subset of papers, excluding tid."""
    cotags = Counter()
    for p in subset:
        for t in p.get("lda_topics", []):
            if t != tid:
                cotags[t] += 1
    return cotags


def compute_solo(subset):
    """Count papers tagged with exactly one topic."""
    return sum(1 for p in subset if len(p.get("lda_topics", [])) == 1)


def compute_probe(subset, stems):
    """Per-stem and aggregate probe hit counts."""
    per_stem = {}
    for stem in stems:
        per_stem[stem] = sum(1 for p in subset if stem in get_text(p))
    total = sum(1 for p in subset if any(s in get_text(p) for s in stems))
    return per_stem, total


def build_page(tid):
    """Build markdown content for a strand page."""
    name = names[str(tid)]
    terms = lda["topics"][str(tid)]
    r = ratios[tid]

    tagged = [p for p in papers if tid in p.get("lda_topics", [])]
    kci = [p for p in tagged if p.get("corpus") == "KCI"]
    angl = [p for p in tagged if p.get("corpus") == "angl"]

    total = r["total"]
    kci_count = r["corpora"]["KCI"]["count"]
    angl_count = r["corpora"]["angl"]["count"]
    ratio = r["ratio"]
    signal = r["signal"]

    kci_corpus_pct = r["corpora"]["KCI"]["pct_of_corpus"]
    angl_corpus_pct = r["corpora"]["angl"]["pct_of_corpus"]

    # --- Frontmatter ---
    lines = [
        "---",
        "type: strand",
        f"topic_id: {tid}",
        f"total: {total}",
        f"kci_count: {kci_count}",
        f"angl_count: {angl_count}",
        f"kci_corpus_pct: {kci_corpus_pct}",
        f"angl_corpus_pct: {angl_corpus_pct}",
        f"kci_ratio: {ratio}",
        f'signal: "{signal}"',
        "---",
        "",
        f"# {name}",
        "",
        f"**Strand {tid}** | {total} papers | KCI: {kci_count} ({kci_corpus_pct}% of corpus) | Angl: {angl_count} ({angl_corpus_pct}% of corpus) | Ratio: {ratio}x ({signal})",
        "",
        f"**Top LDA terms:** {', '.join(terms)}",
        "",
        "---",
        "",
    ]

    # --- Co-tagging patterns ---
    lines.append("## Co-tagging patterns")
    lines.append("")
    lines.append("| Corpus | Co-tag | Count | Rate |")
    lines.append("|--------|--------|-------|------|")

    for label, subset in [("KCI", kci), ("Angl", angl)]:
        cotags = compute_cotags(subset, tid)
        for t, c in cotags.most_common():
            cotag_name = names.get(str(t), f"Topic {t}")
            rate = c / len(subset) * 100 if subset else 0
            lines.append(f"| {label} | [[{cotag_name}]] | {c} | {rate:.1f}% |")

    lines.append("")

    kci_solo = compute_solo(kci)
    angl_solo = compute_solo(angl)
    if kci:
        lines.append(f"KCI solo rate: {kci_solo}/{len(kci)} ({kci_solo/len(kci)*100:.1f}%)")
    if angl:
        lines.append(f"Angl solo rate: {angl_solo}/{len(angl)} ({angl_solo/len(angl)*100:.1f}%)")
    lines.append("")

    # --- Vocabulary probe ---
    lines.append("## Vocabulary probe")
    lines.append("")
    lines.append("| Stem | KCI | KCI % | Angl | Angl % | Gap |")
    lines.append("|------|-----|-------|------|--------|-----|")

    kci_per, kci_total = compute_probe(kci, probe_stems)
    angl_per, angl_total = compute_probe(angl, probe_stems)

    for stem in probe_stems:
        kh = kci_per[stem]
        ih = angl_per[stem]
        kp = kh / len(kci) * 100 if kci else 0
        ip = ih / len(angl) * 100 if angl else 0
        gap = kp - ip
        if kh or ih:
            lines.append(f"| {stem} | {kh} | {kp:.1f}% | {ih} | {ip:.1f}% | {gap:+.1f}pp |")

    kp = kci_total / len(kci) * 100 if kci else 0
    ip = angl_total / len(angl) * 100 if angl else 0
    gap = kp - ip
    lines.append(f"| **TOTAL** | {kci_total} | {kp:.1f}% | {angl_total} | {ip:.1f}% | {gap:+.1f}pp |")
    lines.append("")

    # --- Reading file content (merged) ---
    lines.append("---")
    lines.append("")
    lines.append("## Abstracts")
    lines.append("")
    lines.append(f"{len(tagged)} papers ({len(kci)} KCI, {len(angl)} angl)")
    lines.append("")

    kci_sorted = sorted(kci, key=lambda p: p.get("year", 0))
    angl_sorted = sorted(angl, key=lambda p: p.get("year", 0))

    for label, subset in [("KCI", kci_sorted), ("Angl", angl_sorted)]:
        lines.append(f"### {label} ({len(subset)} papers)")
        lines.append("")
        for p in subset:
            title = p.get("title", "Untitled")
            year = p.get("year", "?")
            authors = ", ".join(p.get("authors", []))
            works = p.get("works_discussed", [])
            topics = p.get("lda_topics", [])
            topic_names = [names.get(str(t), f"T{t}") for t in topics if t != tid]

            lines.append(f"#### {title} ({year})")
            if authors:
                lines.append(f"*{authors}*")
            if works:
                lines.append(f"**Works:** {', '.join(works)}")
            if topic_names:
                lines.append(f"**Co-tags:** {', '.join(topic_names)}")
            lines.append("")
            lines.append(get_abstract_display(p))
            lines.append("")
            lines.append("---")
            lines.append("")

    # --- Exceptions ---
    lines.append("## Exceptions")
    lines.append("")

    for label, subset in [("KCI", kci_sorted), ("Angl", angl_sorted)]:
        if not subset:
            continue
        cotags = compute_cotags(subset, tid)
        if not cotags:
            continue
        top_cotag_id, top_cotag_count = cotags.most_common(1)[0]
        top_cotag_name = names.get(str(top_cotag_id), f"Topic {top_cotag_id}")
        top_rate = top_cotag_count / len(subset) * 100

        exceptions = [p for p in subset if top_cotag_id not in p.get("lda_topics", [])]

        lines.append(f"### {label} papers NOT co-tagged with {top_cotag_name} ({top_rate:.0f}% dominant)")
        lines.append("")
        if exceptions:
            for p in exceptions:
                title = p.get("title", "Untitled")
                year = p.get("year", "?")
                topics = [names.get(str(t), f"T{t}") for t in p.get("lda_topics", []) if t != tid]
                tag_str = f" — co-tags: {', '.join(topics)}" if topics else " — solo"
                lines.append(f"- {title} ({year}){tag_str}")
        else:
            lines.append("*None — all papers co-tag with dominant partner.*")
        lines.append("")

    solo = [p for p in tagged if len(p.get("lda_topics", [])) == 1]
    if solo:
        lines.append("### Solo papers (no co-tags)")
        lines.append("")
        for p in solo:
            title = p.get("title", "Untitled")
            year = p.get("year", "?")
            corpus = p.get("corpus", "?")
            lines.append(f"- [{corpus}] {title} ({year})")
        lines.append("")

    return "\n".join(lines)


def get_abstract_display(p):
    """Get abstract text for display in reading files."""
    abstracts = p.get("abstracts", [])
    if not abstracts:
        ab = p.get("abstract", "")
        return ab if ab else "*No abstract available.*"
    if len(abstracts) == 1:
        return abstracts[0] if abstracts[0] else "*No abstract available.*"
    # Bilingual: use English only (last element)
    return abstracts[-1] if abstracts[-1] else "*No abstract available.*"


if __name__ == "__main__":
    import sys
    import io
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

    STRANDS_DIR.mkdir(parents=True, exist_ok=True)

    # Clear existing strand pages
    for f in STRANDS_DIR.glob("*.md"):
        f.unlink()
        print(f"  Removed: {f.name}")

    # Generate strand pages
    for tid in range(int(lda["num_topics"])):
        name = names[str(tid)]

        content = build_page(tid)
        fpath = STRANDS_DIR / f"{name}.md"
        fpath.write_text(content, encoding="utf-8")
        print(f"  Created: {fpath.name}")

    # --- Corpus-wide data (used by corpus pages + comparison) ---
    all_kci = [p for p in papers if p.get("corpus") == "KCI"]
    all_angl = [p for p in papers if p.get("corpus") == "angl"]
    kci_per, kci_total = compute_probe(all_kci, probe_stems)
    angl_per, angl_total = compute_probe(all_angl, probe_stems)

    # --- Corpus overview pages (KCI.md, OpenAlex.md) ---
    # Appends strand distribution + vocab probes to existing hub pages
    # (hub pages with paper wikilinks are created by 03_create_paper_pages.py)

    def short_name(full_name):
        """First 3 terms of a strand name."""
        return ", ".join(full_name.split(", ")[:3])

    def build_corpus_section(corpus_key, corpus_label, corpus_papers):
        """Build strand distribution + probe tables for a single corpus."""
        modeled = [p for p in corpus_papers if p.get("lda_topics")]
        lines = [
            "",
            "---",
            "",
            "## Strand distribution",
            "",
            f"**{len(modeled)}** papers with LDA assignments",
            "",
            "| Label | Topic Strand | % of corpus | Ratio | Lean |",
            "| ----- | ------------ | ----------- | ----- | ---- |",
        ]

        sorted_tids = sorted(
            range(int(lda["num_topics"])),
            key=lambda t: ratios[t]["corpora"].get(corpus_key, {}).get("pct_of_corpus", 0),
            reverse=True,
        )

        for tid in sorted_tids:
            name = names[str(tid)]
            r = ratios[tid]
            c_data = r["corpora"].get(corpus_key, {})
            pct = c_data.get("pct_of_corpus", 0)
            ratio_val = r.get("ratio", 0)
            lean = "KCI" if ratio_val and ratio_val >= 1.3 else ("OA" if ratio_val and ratio_val <= 0.7 else "-")
            lines.append(f"| {tid} | [[{short_name(name)}]] | {pct:.1f}% | {ratio_val:.2f}x | {lean} |")

        lines.append("")

        # Vocabulary probe for this corpus
        lines.append("## Vocabulary probe")
        lines.append("")
        lines.append(f"| | {corpus_label} |")
        lines.append("| --------- | ----- |")

        per_stem, total_hits = compute_probe(modeled, probe_stems)
        for stem in probe_stems:
            count = per_stem[stem]
            pct = count / len(modeled) * 100 if modeled else 0
            if count:
                lines.append(f"| {stem} | {pct:.1f}% |")

        pct = total_hits / len(modeled) * 100 if modeled else 0
        lines.append(f"| **TOTAL** | {pct:.1f}% |")
        lines.append("")

        return "\n".join(lines)

    for corpus_key, hub_filename in [("KCI", "KCI.md"), ("angl", "OpenAlex.md")]:
        hub_path = VAULT_ROOT / hub_filename
        corpus_papers = [p for p in papers if p.get("corpus") == corpus_key]

        # Read existing hub content (paper wikilinks from 03)
        existing = ""
        if hub_path.exists():
            existing = hub_path.read_text(encoding="utf-8")

        # Strip any previous strand/probe sections (re-runnable)
        marker = "\n---\n\n## Strand distribution"
        if marker in existing:
            existing = existing[:existing.index(marker)]

        # Append new sections
        new_content = existing.rstrip() + build_corpus_section(corpus_key, hub_filename.replace(".md", ""), corpus_papers)
        hub_path.write_text(new_content, encoding="utf-8")
        print(f"  Updated: {hub_filename} (strand distribution + vocab probes)")

    # --- Comparison page ---
    comp_lines = [
        "---",
        "type: comparison",
        f"kci_total: {len(all_kci)}",
        f"angl_total: {len(all_angl)}",
        "---",
        "",
        "# Corpus Comparison",
        "",
        f"**[[KCI]]:** {len(all_kci)} papers | **[[OpenAlex]]:** {len(all_angl)} papers",
        "",
        "---",
        "",
        "## Strand distribution",
        "",
        "| Label | Topic Strand | % of KCI | % of OA | Ratio | |",
        "| ----- | ------------ | -------- | ------- | ----- | --- |",
    ]

    sorted_tids = sorted(
        range(int(lda["num_topics"])),
        key=lambda t: ratios[t].get("ratio", 0) or 0,
        reverse=True,
    )

    for tid in sorted_tids:
        name = names[str(tid)]
        r = ratios[tid]
        kci_pct = r["corpora"]["KCI"]["pct_of_corpus"]
        angl_pct = r["corpora"]["angl"]["pct_of_corpus"]
        ratio_val = r.get("ratio", 0)
        lean = "KCI" if ratio_val and ratio_val >= 1.3 else ("OA" if ratio_val and ratio_val <= 0.7 else "-")
        comp_lines.append(f"| {tid} | [[{short_name(name)}]] | {kci_pct:.1f}% | {angl_pct:.1f}% | {ratio_val:.2f}x | {lean} |")

    comp_lines.append("")

    # Vocabulary probe comparison
    comp_lines.append("## Vocabulary probe comparison")
    comp_lines.append("")
    comp_lines.append("| | KCI | OA | gap |")
    comp_lines.append("| --------- | ----- | ----- | ----- |")

    for stem in probe_stems:
        kp = kci_per[stem] / len(all_kci) * 100 if all_kci else 0
        ip = angl_per[stem] / len(all_angl) * 100 if all_angl else 0
        gap = kp - ip
        if kci_per[stem] or angl_per[stem]:
            comp_lines.append(f"| {stem} | {kp:.1f}% | {ip:.1f}% | {gap:+.1f}% |")

    kp = kci_total / len(all_kci) * 100 if all_kci else 0
    ip = angl_total / len(all_angl) * 100 if all_angl else 0
    gap = kp - ip
    comp_lines.append(f"| **TOTAL** | {kp:.1f}% | {ip:.1f}% | {gap:+.1f}% |")
    comp_lines.append("")

    comp_path = VAULT_ROOT / "comparison.md"
    comp_path.write_text("\n".join(comp_lines), encoding="utf-8")
    print(f"  Created: {comp_path.name}")

    print(f"\nDone. {lda['num_topics']} strand pages written to {STRANDS_DIR}")
