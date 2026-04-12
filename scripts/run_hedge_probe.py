"""
run_hedge_probe.py — Run the hedge probe as a standalone analysis.

Non-destructive: does not touch strand pages or other pipeline outputs.
Reads the same _data/all_papers.json that 06_create_strand_pages.py reads,
runs the same substring-matching logic, and writes a markdown report to
probe-results-hedge.md at the vault root.

Produces corpus-wide and per-strand breakdowns for the hedge stems.

Run: python scripts/run_hedge_probe.py
"""

import json
import yaml
from pathlib import Path
from collections import Counter

# --- Load config + data ---
here = Path(__file__).parent
config_path = here / "config.yaml"
with open(config_path, encoding="utf-8") as f:
    config = yaml.safe_load(f)

_vr = Path(config["vault_root"])
VAULT_ROOT = _vr if _vr.is_absolute() else (here / _vr).resolve()
DATA_DIR = VAULT_ROOT / config["paths"]["data"]

with open(DATA_DIR / "all_papers.json", encoding="utf-8") as f:
    papers = json.load(f)
with open(DATA_DIR / "strand_names.json", encoding="utf-8") as f:
    names = json.load(f)

# --- Load hedge stems ---
probes_path = here / "hedge-probes.txt"
stems = []
with open(probes_path, encoding="utf-8") as f:
    for line in f:
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        stems.append(line.split("|")[0].strip())

print(f"Loaded {len(stems)} hedge stems from {probes_path.name}")


# --- Probe logic (identical to 06_create_strand_pages.compute_probe) ---
def get_text(p):
    abs_list = p.get("abstracts", [p.get("abstract", "")])
    return (p.get("title", "") + " " + " ".join(abs_list)).lower()


def compute_probe(subset, stems):
    per_stem = {}
    for stem in stems:
        per_stem[stem] = sum(1 for p in subset if stem in get_text(p))
    total = sum(1 for p in subset if any(s in get_text(p) for s in stems))
    return per_stem, total


# --- Corpus-wide ---
kci = [p for p in papers if p.get("corpus") == "KCI"]
angl = [p for p in papers if p.get("corpus") == "angl"]

kci_n = len(kci)
angl_n = len(angl)

kci_per, kci_total = compute_probe(kci, stems)
angl_per, angl_total = compute_probe(angl, stems)

# --- Write report ---
out_path = VAULT_ROOT / "probe-results-hedge.md"
lines = [
    "---",
    "type: probe_results",
    f"kci_total: {kci_n}",
    f"angl_total: {angl_n}",
    "probe: hedge",
    "---",
    "",
    "# Hedge Probe Results",
    "",
    f"Corpus: {kci_n} KCI, {angl_n} anglophone",
    "",
    "## Corpus-wide",
    "",
    "| Stem | KCI | KCI % | Angl | Angl % | Gap |",
    "|------|-----|-------|------|--------|-----|",
]

for stem in stems:
    kh = kci_per[stem]
    ih = angl_per[stem]
    kp = 100 * kh / kci_n if kci_n else 0
    ip = 100 * ih / angl_n if angl_n else 0
    gap = kp - ip
    lines.append(f"| {stem} | {kh} | {kp:.1f}% | {ih} | {ip:.1f}% | {gap:+.1f}pp |")

kp = 100 * kci_total / kci_n
ip = 100 * angl_total / angl_n
gap = kp - ip
lines.append(f"| **TOTAL** | {kci_total} | {kp:.1f}% | {angl_total} | {ip:.1f}% | {gap:+.1f}pp |")
lines.append("")

# --- Per-strand ---
lines.append("## By strand")
lines.append("")

# Collect unique strand ids
all_tids = set()
for p in papers:
    for t in p.get("lda_topics", []):
        all_tids.add(t)

for tid in sorted(all_tids):
    name = names.get(str(tid), f"Topic {tid}")
    tagged = [p for p in papers if tid in p.get("lda_topics", [])]
    s_kci = [p for p in tagged if p.get("corpus") == "KCI"]
    s_angl = [p for p in tagged if p.get("corpus") == "angl"]

    sk_n = len(s_kci)
    sa_n = len(s_angl)
    if sk_n == 0 or sa_n == 0:
        continue

    sk_per, sk_total = compute_probe(s_kci, stems)
    sa_per, sa_total = compute_probe(s_angl, stems)

    lines.append(f"### {name}")
    lines.append("")
    lines.append(f"KCI: {sk_n}, Angl: {sa_n}")
    lines.append("")
    lines.append("| Stem | KCI | KCI % | Angl | Angl % | Gap |")
    lines.append("|------|-----|-------|------|--------|-----|")

    for stem in stems:
        kh = sk_per[stem]
        ih = sa_per[stem]
        kp = 100 * kh / sk_n if sk_n else 0
        ip = 100 * ih / sa_n if sa_n else 0
        gap = kp - ip
        if kh == 0 and ih == 0:
            continue
        lines.append(f"| {stem} | {kh} | {kp:.1f}% | {ih} | {ip:.1f}% | {gap:+.1f}pp |")

    kp = 100 * sk_total / sk_n
    ip = 100 * sa_total / sa_n
    gap = kp - ip
    lines.append(f"| **TOTAL** | {sk_total} | {kp:.1f}% | {sa_total} | {ip:.1f}% | {gap:+.1f}pp |")
    lines.append("")

with open(out_path, "w", encoding="utf-8") as f:
    f.write("\n".join(lines))

print(f"Wrote {out_path}")
print()
print(f"Corpus-wide hedge probe:")
print(f"  KCI:  {kci_total}/{kci_n} = {100*kci_total/kci_n:.1f}%")
print(f"  Angl: {angl_total}/{angl_n} = {100*angl_total/angl_n:.1f}%")
print(f"  Gap:  {100*kci_total/kci_n - 100*angl_total/angl_n:+.1f}pp")
