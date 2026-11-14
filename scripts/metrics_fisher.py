"""
metrics_fisher.py — Probe counts with two-sided Fisher's exact tests
=====================================================================

Runs against a finished run (after step 05). For each probe stem it counts
the papers in each corpus whose title + abstract contain the stem (the same
substring match the strand pages use), and tests the KCI / anglophone
difference with a two-sided Fisher's exact test on the 2x2 table
(matched / not matched x KCI / anglophone). A last row does the same for
papers matching ANY of the stems.

Scope is the whole modelled corpus, or one topic's members with --topic.

Denominators are the papers the model tagged with at least one topic, which
are the papers every ratio in the study is computed on. A record with no
usable English text gets a flat topic distribution, clears no threshold, and
is in neither count. --base all uses every record in scope instead.

Inputs:  _data/all_papers.json (with lda_topics from 05), probe file(s)
Outputs: console table (markdown); --out <file> also writes it

Dependencies: scipy, pyyaml
Run: python metrics_fisher.py                          (vocabulary-probes.txt)
     python metrics_fisher.py --probes hedge-probes.txt
     python metrics_fisher.py --stems conflict,ambival,debate,politic --topic 4
"""

import argparse
import io
import json
import sys
from pathlib import Path

import yaml
from scipy.stats import fisher_exact

sys.path.insert(0, str(Path(__file__).parent))
import _text

SCRIPT_DIR = Path(__file__).parent


def load_config():
    with open(SCRIPT_DIR / "config.yaml", encoding="utf-8") as f:
        cfg = yaml.safe_load(f)
    _vr = Path(cfg["vault_root"])
    vault_root = _vr if _vr.is_absolute() else (SCRIPT_DIR / _vr).resolve()
    return cfg, vault_root / cfg["paths"]["data"]


def read_stems(path):
    stems = []
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith("#"):
                stems.append(line.split("|")[0].strip())
    return stems


def probe_text(p):
    """Title + abstract, lower-cased. Same text 06_create_strand_pages.py matches."""
    abs_list = p.get("abstracts", [p.get("abstract", "")])
    return (p.get("title", "") + " " + " ".join(abs_list)).lower()


def row(label, k_hit, k_n, a_hit, a_n):
    _, pval = fisher_exact([[k_hit, k_n - k_hit], [a_hit, a_n - a_hit]],
                           alternative="two-sided")
    kp = 100.0 * k_hit / k_n if k_n else 0.0
    ap = 100.0 * a_hit / a_n if a_n else 0.0
    return "| %s | %.1f%% (%d) | %.1f%% (%d) | %+.1f | %s |" % (
        label, kp, k_hit, ap, a_hit, kp - ap,
        ("%.4f" % pval) if pval >= 0.0001 else "<0.0001")


def main():
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser()
    ap.add_argument("--probes", help="probe file (default vocabulary-probes.txt)")
    ap.add_argument("--stems", help="comma-separated stems instead of a probe file")
    ap.add_argument("--topic", type=int, help="restrict to this topic's members")
    ap.add_argument("--base", choices=["tagged", "all"], default="tagged")
    ap.add_argument("--out", help="also write the table to this file")
    args = ap.parse_args()

    cfg, data_dir = load_config()
    if args.stems:
        stems = [s.strip() for s in args.stems.split(",") if s.strip()]
    else:
        stems = read_stems(SCRIPT_DIR / (args.probes or "vocabulary-probes.txt"))

    with open(data_dir / "all_papers.json", encoding="utf-8") as f:
        papers = [p for p in json.load(f) if not _text.is_excluded(p)]
    if args.base == "tagged":
        papers = [p for p in papers if p.get("lda_topics")]
    if args.topic is not None:
        papers = [p for p in papers if args.topic in (p.get("lda_topics") or [])]

    kci = [probe_text(p) for p in papers if p.get("corpus") == "KCI"]
    angl = [probe_text(p) for p in papers if p.get("corpus") == "angl"]

    scope = "topic %d" % args.topic if args.topic is not None else "whole corpus"
    lines = ["%s, base %s: KCI %d, anglophone %d" % (scope, args.base, len(kci), len(angl)),
             "",
             "| stem | KCI | anglophone | gap (pp) | Fisher p (two-sided) |",
             "|---|---|---|---|---|"]
    for s in stems:
        lines.append(row(s, sum(s in t for t in kci), len(kci),
                         sum(s in t for t in angl), len(angl)))
    if len(stems) > 1:
        lines.append(row("any of these", sum(any(s in t for s in stems) for t in kci), len(kci),
                         sum(any(s in t for s in stems) for t in angl), len(angl)))
    out = "\n".join(lines)
    print(out)
    if args.out:
        Path(args.out).write_text(out + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
