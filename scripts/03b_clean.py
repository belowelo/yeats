"""
03b_clean.py — Corpus cleaning, corpus assignment, and the cleaning audit
=========================================================================

Applies the exclusion rules and the corpus assignment, and writes the
cleaning audit.

Non-destructive: every record stays in all_papers.json and gains a `cleaning`
field. Downstream scripts skip the excluded ones via _text.is_excluded().

Inputs:  _data/all_papers.json, config.yaml, false-positives.txt,
         _data/boilerplate_flagged.json (optional, from 05a),
         _data/stopwords.json (optional, from 05a)
Outputs: _data/all_papers.json (annotated in place),
         _data/cleaning_report.json, _data/cleaning_report.md,
         _data/cleaning_candidates.md,
         pages of reassigned records moved to papers/kci/,
         pages of excluded records deleted unless --no-prune

Dependencies: pyyaml, nltk
Run: python 03b_clean.py [--no-prune] [--dry-run]
"""

import argparse
import collections
import difflib
import io
import json
import re
import sys
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).parent))
import _text

SCRIPT_DIR = Path(__file__).parent


# ---------------------------------------------------------------- config

def load_config():
    with open(SCRIPT_DIR / "config.yaml", encoding="utf-8") as f:
        cfg = yaml.safe_load(f)
    _vr = Path(cfg["vault_root"])
    vault_root = _vr if _vr.is_absolute() else (SCRIPT_DIR / _vr).resolve()
    return cfg, vault_root


def load_rules():
    """Read false-positives.txt.

    One rule per line. A prefix declares what the rule matches:

        term:   phrase, matched case-insensitively in title + abstract
        title:  one exact title (use this for a single bad record)
        venue:  exact source journal name

    An unprefixed line is read as `term:`, so a file written before prefixes
    existed still works unchanged.
    """
    path = SCRIPT_DIR / "false-positives.txt"
    rules = []
    if not path.exists():
        return rules
    with open(path, encoding="utf-8") as f:
        for lineno, line in enumerate(f, 1):
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            kind, _, value = line.partition(":")
            kind = kind.strip().lower()
            if kind in ("term", "title", "venue") and value.strip():
                rules.append({"kind": kind, "value": value.strip(), "line": lineno})
            else:
                rules.append({"kind": "term", "value": line, "line": lineno})
    return rules


# ---------------------------------------------------------------- checks

_FOREIGN_WORDS = re.compile(
    r'\b(?:cette|dans|avec|pour|mais|donc|sont|peut|fait|tout|tous|toute'
    r'|della|degli|delle|anche|essere|sono|molto'
    r'|como|pero|desde|sobre|tambien|puede|todo|todos'
    r'|eine|eines|durch|werden|nicht|dass|diese|seiner)\b'
)


def is_korean_dominant(text: str) -> bool:
    """Korean body text with only proper nouns in Latin script. Such a record
    has no usable English abstract even though an abstract field exists."""
    ko = _text.korean_char_count(text)
    latin_words = re.findall(r'[a-zA-Z]{3,}', text)
    return ko > 50 and len(latin_words) < 30


def is_foreign(text: str) -> bool:
    return len(_FOREIGN_WORDS.findall(text.lower())) >= 5


def flag(paper: dict, rule: str, excluding: bool = True):
    c = paper.setdefault("cleaning", {"excluded": False, "rules": [], "candidates": []})
    if excluding:
        c["excluded"] = True
        if rule not in c["rules"]:
            c["rules"].append(rule)
    else:
        if rule not in c["candidates"]:
            c["candidates"].append(rule)


# ---------------------------------------------------------------- main

def clean(papers, cfg, stopwords, data_dir):
    """Annotate every record. Returns (counts, candidates, reassignments)."""
    cl = cfg.get("cleaning", {})
    min_chars = cl.get("min_abstract_chars", 50)
    min_tokens = cl.get("min_tokens", 5)
    field_vocab = [w.lower() for w in cl.get("field_vocabulary", [])]
    subject_terms = [t.lower() for t in cfg.get("subject_terms", [])]
    kor_venues = set(cl.get("reassign_to_kci_venues", []))
    dup_cutoff = cl.get("duplicate_title_cutoff", 0.90)

    counts = collections.Counter()
    rule_hits = collections.Counter()
    from nltk.stem import WordNetLemmatizer
    lem = WordNetLemmatizer()

    for p in papers:
        p["cleaning"] = {"excluded": False, "rules": [], "candidates": []}

    # --- 1. rules from false-positives.txt -----------------------------
    rules = load_rules()
    for p in papers:
        blob = _text.full_text(p)
        title_norm = " ".join((p.get("title") or "").split())
        venue = (p.get("source_journal") or "").strip()
        for r in rules:
            key = "%s:%s" % (r["kind"], r["value"])
            if r["kind"] == "term" and r["value"].lower() in blob:
                flag(p, key); rule_hits[key] += 1
            elif r["kind"] == "title" and " ".join(r["value"].split()) == title_norm:
                flag(p, key); rule_hits[key] += 1
            elif r["kind"] == "venue" and r["value"] == venue:
                flag(p, key); rule_hits[key] += 1

    # A `term:` rule may match nothing. A `title:` rule names exactly one
    # record, so a miss means the title string does not occur.
    unmatched_rules, inert_guards = [], []
    for r in rules:
        key = "%s:%s" % (r["kind"], r["value"])
        if rule_hits[key]:
            continue
        (unmatched_rules if r["kind"] in ("title", "venue") else inert_guards).append(key)

    # --- 2. boilerplate / hand-flagged records, keyed by TITLE ---------
    # 05a writes this file with an integer `index` into all_papers.json.
    # Keyed here by title instead.
    bp_path = data_dir / "boilerplate_flagged.json"
    bp_titles, bp_missing = set(), []
    if bp_path.exists():
        with open(bp_path, encoding="utf-8") as f:
            bp = json.load(f)
        bp_titles = {e["title"] for e in bp if e.get("title")}
        present = {p.get("title") for p in papers}
        bp_missing = sorted(t for t in bp_titles if t not in present)
        for p in papers:
            if p.get("title") in bp_titles:
                flag(p, "flagged:boilerplate-or-hand-removed")

    # --- 3. abstract usability ----------------------------------------
    for p in papers:
        text = _text.lda_text(p)
        if not text.strip():
            flag(p, "no-abstract")
            continue
        if len(text.strip()) < min_chars:
            flag(p, "abstract-too-short")
            continue
        if is_korean_dominant(text):
            flag(p, "korean-dominant-abstract")
            continue
        if is_foreign(text):
            flag(p, "foreign-language-abstract")
            continue
        if len(_text.preprocess(text, stopwords, lem).split()) < min_tokens:
            flag(p, "too-few-tokens")

    # --- 4. corpus assignment -----------------------------------------
    # Venues listed in config under reassign_to_kci_venues are moved to the KCI
    # side; where KCI already holds the same paper, the OpenAlex copy is
    # dropped as a duplicate.
    kci_titles = {}
    for p in papers:
        if p.get("corpus") == "KCI":
            for t in (p.get("titles") or [p.get("title", "")]):
                n = _text.norm_title(t)
                if len(n) > 10:
                    kci_titles.setdefault(n, p)
    kci_list = list(kci_titles)

    reassigned, kor_dupes = [], []
    for p in papers:
        if p.get("corpus") != "angl":
            continue
        if (p.get("source_journal") or "") not in kor_venues:
            continue
        n = _text.norm_title(p.get("title"))
        if n in kci_titles or difflib.get_close_matches(n, kci_list, n=1, cutoff=dup_cutoff):
            flag(p, "duplicate-of-kci-record")
            kor_dupes.append(p.get("title"))
        else:
            p["cleaning"]["reassigned_from"] = "angl"
            p["corpus"] = "KCI"
            reassigned.append({"title": p.get("title"),
                               "venue": p.get("source_journal")})

    # --- 5. candidates: surfaced, never dropped -----------------------
    # Surfaces records for review; never drops them. Ranks rather than flags.
    # Two signals:
    #
    #   subject-term-not-a-word  — the subject matches only inside a longer
    #       token. Always surfaced.
    #   field-vocabulary density — how many distinct field words the record
    #       uses, ordered against HOW MUCH TEXT HAD THE CHANCE to use them.
    #       Zero field words in a 1,500-character abstract is suspicious;
    #       zero in a two-line book listing is not. Weak on its own, so it
    #       only ORDERS a short review queue rather than accusing anything.
    #
    # The queue is the lowest-density records, longest abstract first, up to
    # candidate_review_size.
    review_size = cl.get("candidate_review_size", 30)
    word_res = [re.compile(r'(?<![0-9a-z가-힣])%s(?![0-9a-z])' % re.escape(t))
                for t in subject_terms]

    scored = []
    for p in papers:
        if p["cleaning"]["excluded"]:
            continue
        blob = _text.full_text(p)
        density = sum(1 for w in field_vocab if w in blob)
        as_word = any(r.search(blob) for r in word_res) if word_res else True
        present = any(t in blob for t in subject_terms) if subject_terms else True
        why = []
        if not present:
            why.append("subject-term-absent")
        elif not as_word:
            why.append("subject-term-not-a-word")
        scored.append((density, -len(_text.lda_text(p)), why, p))

    strong = [s for s in scored if s[2]]
    rest = sorted((s for s in scored if not s[2]), key=lambda s: (s[0], s[1]))
    queue = strong + rest[:review_size]

    candidates = []
    for density, neglen, why, p in queue:
        flags = list(why) or ["low-field-vocabulary (%d field words in %d chars)"
                              % (density, -neglen)]
        for w in flags:
            flag(p, w, excluding=False)
        candidates.append({"title": p.get("title"), "corpus": p.get("corpus"),
                           "year": p.get("year"), "why": flags,
                           "field_words": density,
                           "venue": p.get("source_journal"),
                           "abstract_preview": (_text.lda_text(p) or "")[:240]})
    n_strong = len(strong)

    for p in papers:
        if p["cleaning"]["excluded"]:
            for r in p["cleaning"]["rules"]:
                counts[r] += 1

    return dict(rule_hits=rule_hits, unmatched_rules=unmatched_rules,
                inert_guards=inert_guards,
                bp_missing=bp_missing, counts=counts, candidates=candidates,
                reassigned=reassigned, kor_dupes=kor_dupes, n_rules=len(rules),
                n_strong=n_strong)


def year_spread(papers):
    """Per-corpus decade counts. The window harvested is not the window
    compared, and this is the number that says so."""
    out = {}
    for p in papers:
        if _text.is_excluded(p):
            continue
        y = p.get("year")
        if not isinstance(y, int):
            continue
        out.setdefault(p.get("corpus", "?"), collections.Counter())[y // 10 * 10] += 1
    return {c: dict(sorted(v.items())) for c, v in out.items()}


def write_report(papers, res, cfg, vault_root, data_dir):
    kept = [p for p in papers if not _text.is_excluded(p)]
    sizes = collections.Counter(p.get("corpus") for p in kept)
    spread = year_spread(papers)

    report = {
        "subject": cfg.get("subject"),
        "harvested": len(papers),
        "modelled": len(kept),
        "by_corpus": dict(sizes),
        "excluded_total": len(papers) - len(kept),
        "excluded_by_rule": dict(res["counts"]),
        "rules_in_file": res["n_rules"],
        "rules_matching_nothing": res["unmatched_rules"],
        "inert_guard_terms": res["inert_guards"],
        "flagged_titles_matching_no_record": res["bp_missing"],
        "reassigned_to_kci": res["reassigned"],
        "dropped_as_kci_duplicates": res["kor_dupes"],
        "candidates_surfaced": len(res["candidates"]),
        "candidates_strong_signal": res["n_strong"],
        "year_spread_by_decade": spread,
    }
    with open(data_dir / "cleaning_report.json", "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)

    L = []
    L.append("# Cleaning report — %s\n" % cfg.get("subject"))
    L.append("Harvested **%d** records; **%d** modelled "
             "(%s).\n" % (len(papers), len(kept),
                          ", ".join("%s %d" % (k, v) for k, v in sorted(sizes.items()))))
    L.append("## Excluded, by rule\n")
    L.append("| rule | records |")
    L.append("|---|---|")
    for r, n in sorted(res["counts"].items(), key=lambda x: -x[1]):
        L.append("| `%s` | %d |" % (r, n))
    L.append("| **total excluded** | **%d** |\n" % (len(papers) - len(kept)))

    L.append("## Corpus assignment\n")
    L.append("- Reassigned OpenAlex -> KCI (Korean venue): **%d**" % len(res["reassigned"]))
    L.append("- Dropped as duplicates of records KCI already held: **%d**\n"
             % len(res["kor_dupes"]))
    if res["reassigned"]:
        by_venue = collections.Counter(r["venue"] for r in res["reassigned"])
        L.append("| venue | reassigned |")
        L.append("|---|---|")
        for v, n in by_venue.most_common():
            L.append("| %s | %d |" % (v, n))
        L.append("")

    L.append("## Year spread of the modelled corpus\n")
    decades = sorted({d for v in spread.values() for d in v})
    L.append("| decade | " + " | ".join(spread) + " |")
    L.append("|---" * (len(spread) + 1) + "|")
    for d in decades:
        L.append("| %ds | " % d + " | ".join(str(spread[c].get(d, 0)) for c in spread) + " |")
    L.append("\nHarvest window in config.yaml: `%s`.\n" % (cfg.get("date_range"),))

    if res["inert_guards"]:
        L.append("## Inert guard terms\n")
        L.append("%d `term:` rule(s) matched no record in this harvest.\n"
                 % len(res["inert_guards"]))
        L.append(", ".join("`%s`" % g.split(":", 1)[1] for g in res["inert_guards"]))
        L.append("")

    if res["unmatched_rules"] or res["bp_missing"]:
        L.append("## Rules that matched nothing\n")
        L.append("`title:` and `venue:` rules, and flagged titles, that matched no "
                 "record in this harvest.\n")
        for r in res["unmatched_rules"]:
            L.append("- `%s` (false-positives.txt)" % r)
        for t in res["bp_missing"]:
            L.append("- flagged title not present in the corpus: `%s`" % t)
        L.append("")

    L.append("## Candidates\n")
    L.append("**%d** records matched a subject-agnostic check and were kept. "
             "Listed in `cleaning_candidates.md`.\n"
             % len(res["candidates"]))
    (data_dir / "cleaning_report.md").write_text("\n".join(L), encoding="utf-8")

    C = ["# Cleaning candidates — %s\n" % cfg.get("subject"),
         "*Records matched by a candidate check and kept in the corpus. Each "
         "entry lists the checks it matched and a preview of its abstract.*\n"]
    for c in sorted(res["candidates"], key=lambda x: (x["corpus"] or "", str(x["year"]))):
        C.append("---\n")
        C.append("**%s**  \n*%s · %s · %s*  \nflags: %s\n"
                 % (c["title"], c["corpus"], c["year"], c["venue"] or "no venue",
                    ", ".join("`%s`" % w for w in c["why"])))
        if c["abstract_preview"]:
            C.append("> %s…\n" % c["abstract_preview"].replace("\n", " "))
    (data_dir / "cleaning_candidates.md").write_text("\n".join(C), encoding="utf-8")

    return report


def page_name(p):
    """The filename 03_create_paper_pages.py gives a record, without .md."""
    name = re.sub(r'[][\\/:*?"<>|#^]', '', "%s - %s" % (p.get("year", "unknown"),
                                                    p.get("title", "Untitled")))
    name = re.sub(r'\s+', ' ', name).strip()
    if len(name) > 100:
        name = name[:100].rsplit(' ', 1)[0]
    return name


def prune_pages(papers, cfg, vault_root):
    """Delete the vault page of every excluded record. Recoverable by re-running
    03; the data file keeps the record either way."""
    kci = vault_root / cfg["paths"]["papers_kci"]
    oa = vault_root / cfg["paths"]["papers_openalex"]
    deleted = 0
    for p in papers:
        if not _text.is_excluded(p):
            continue
        name = page_name(p)
        for d in (kci, oa):
            f = d / (name + ".md")
            if f.exists():
                f.unlink()
                deleted += 1
    return deleted


def move_reassigned_pages(papers, cfg, vault_root):
    """Move the page of every record reassigned from the anglophone corpus to
    the KCI corpus into the KCI directory. Returns (moved, blocked), where
    blocked counts records whose target filename is already taken."""
    kci = vault_root / cfg["paths"]["papers_kci"]
    oa = vault_root / cfg["paths"]["papers_openalex"]
    moved, blocked = 0, 0
    for p in papers:
        if _text.is_excluded(p):
            continue
        if (p.get("cleaning") or {}).get("reassigned_from") != "angl":
            continue
        src = oa / (page_name(p) + ".md")
        dst = kci / (page_name(p) + ".md")
        if not src.exists():
            continue
        if dst.exists():
            blocked += 1
            continue
        kci.mkdir(parents=True, exist_ok=True)
        src.replace(dst)
        moved += 1
    return moved, blocked


if __name__ == "__main__":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser()
    ap.add_argument("--no-prune", action="store_true",
                    help="leave vault pages of excluded records in place")
    ap.add_argument("--dry-run", action="store_true",
                    help="report only; do not write all_papers.json or touch pages")
    args = ap.parse_args()

    cfg, VAULT_ROOT = load_config()
    DATA_DIR = VAULT_ROOT / cfg["paths"]["data"]

    print("=== Cleaning: %s ===\n" % cfg.get("subject"))
    with open(DATA_DIR / "all_papers.json", encoding="utf-8") as f:
        papers = json.load(f)
    print("  Loaded %d records" % len(papers))

    stopwords = _text.load_stopwords(DATA_DIR)
    if not (DATA_DIR / "stopwords.json").exists():
        print("  ! stopwords.json not found — using the fallback set. The"
              " token-count check will be approximate until 05a has run.")

    res = clean(papers, cfg, stopwords, DATA_DIR)
    report = write_report(papers, res, cfg, VAULT_ROOT, DATA_DIR)

    print("\n  %-38s %d" % ("rules in false-positives.txt:", res["n_rules"]))
    for r, n in sorted(res["counts"].items(), key=lambda x: -x[1]):
        print("  %-38s %d" % (r + ":", n))
    print("  %-38s %d" % ("reassigned OpenAlex -> KCI:", len(res["reassigned"])))
    print("  %-38s %d" % ("dropped as KCI duplicates:", len(res["kor_dupes"])))
    print("  %-38s %d  (%d on a strong signal)" % ("candidates surfaced:",
          len(res["candidates"]), res["n_strong"]))
    if res["inert_guards"]:
        print("  %-38s %d" % ("inert term: guards:", len(res["inert_guards"])))
    print("\n  modelled: %d  (%s)" % (
        report["modelled"],
        ", ".join("%s %d" % (k, v) for k, v in sorted(report["by_corpus"].items()))))

    bad = res["unmatched_rules"] + res["bp_missing"]
    if bad:
        print("\n  %d rule(s) matched no record:" % len(bad))
        for b in bad:
            print("       %s" % b)
        if cfg.get("cleaning", {}).get("strict_rules", True):
            print("\n  strict_rules is on. Fix or remove these, then re-run.")
            print("  (Set cleaning.strict_rules: false in config.yaml to"
                  " downgrade this to a warning.)")
            sys.exit(2)

    if args.dry_run:
        print("\n  --dry-run: nothing written except the reports.")
    else:
        with open(DATA_DIR / "all_papers.json", "w", encoding="utf-8") as f:
            json.dump(papers, f, ensure_ascii=False, indent=2)
        print("\n  Annotated all_papers.json in place (no record removed).")
        moved, blocked = move_reassigned_pages(papers, cfg, VAULT_ROOT)
        print("  Moved %d page(s) to the KCI directory with the record." % moved)
        if blocked:
            print("  %d reassigned page(s) left in place: the KCI directory already"
                  " holds that filename." % blocked)
        if not args.no_prune:
            print("  Pruned %d vault page(s) of excluded records." % prune_pages(papers, cfg, VAULT_ROOT))

    print("\n=== Done ===")
    print("  _data/cleaning_report.md       — exclusions, corpus assignment, year spread")
    print("  _data/cleaning_candidates.md   — records matched by a candidate check")
