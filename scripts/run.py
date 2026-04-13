"""
run.py — Interactive batch wizard for the Yeats comparative reception pipeline
===============================================================================

Walks through all pipeline steps in sequence with pauses for researcher input,
re-run loops, and inline strand naming / probe creation.

Usage:
  python run.py

Individual scripts remain directly runnable for targeted re-runs.
"""

import sys
import io
import json
import re
import subprocess
from pathlib import Path

# Auto-install dependencies if missing
def _ensure_deps():
    deps = {"nltk": "nltk", "sklearn": "scikit-learn", "requests": "requests", "yaml": "pyyaml"}
    missing = []
    for module, package in deps.items():
        try:
            __import__(module)
        except ImportError:
            missing.append(package)
    if missing:
        print(f"  installing dependencies: {', '.join(missing)}...")
        subprocess.check_call([sys.executable, "-m", "pip", "install", *missing, "-q"])
        print("  done.\n")

_ensure_deps()

# Fix Windows console encoding
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

SCRIPT_DIR = Path(__file__).parent
_probe_args = []  # set by step_7, reused by step_8
VAULT_ROOT = None  # loaded from config


# ============================================================================
# TEXT — edit these to change what the user sees at each step.
# ============================================================================

TEXT = {
    "banner": """
  ╔══════════════════════════════════════════════════════════╗
  ║     comparative scholar database creator                 ║
  ║     kci + openalex, v0.1                                 ║
  ╚══════════════════════════════════════════════════════════╝

  before you begin:
    - edit "config.yaml" to set your search terms, date range, and LDA parameters
    - edit the ".env" file with your KCI API key
    - edit works.txt / works.csv with your subject's works + match terms
    - edit stopwords.txt and vocabulary-probes.txt for your topic

  all configuration files live in this folder. the wizard will walk you through each step.
""",

    "step_labels": [
        "collate (01 + 02)",
        "export scholarship clippings (03)",
        "false positive cleanup",
        "assign subjects (04)",
        "edit stopwords + create LDA topic strands (05a + 05 + 05b)",
        "name topic strands",
        "additional vocabulary probes + create strand pages (06)",
        "create frontmatter for clippings (07)",
    ],

    "step_1_header": "STEP 1: collate",
    "step_1_both_exist": "both database collection files already exist.",
    "step_1_reharvest": "re-collect?",
    "step_1_run_openalex": "run openalex collection?",
    "step_1_run_kci": "run KCI collection?",

    "step_2_header": "STEP 2: export scholarship clippings",
    "step_2_info": "this creates one obsidian page per paper. browse the vault afterward to check for anything that shouldn't be there.",

    "step_3_header": "STEP 3: false positive cleanup",
    "step_3_prompt": "if you found anything that isn't meant to be there,\nedit false-positives.txt with terms to filter, then press enter...",
    "step_3_fp_loaded": "false-positives.txt: {count} filter terms loaded",
    "step_3_fp_missing": "no false-positives.txt found. skipping cleanup.",
    "step_3_removed": "removed {count} false positive papers ({pages} pages deleted).",
    "step_3_none": "no false positives found.",
    "step_3_rerun": "re-run cleanup with updated false-positives.txt?",

    "step_4_header": "STEP 4: assign subjects",
    "step_4_works_loaded": "edit works.csv and run works_convert.py to assign subjects \n(e.g. poems and text titles for literature) \nto clippings via works.txt: \n{count} works loaded",
    "step_4_works_missing": "WARNING: works.txt not found!",
    "step_4_prompt": "edit works.txt if needed, then press enter...",
    "step_4_rerun": "re-run with updated works.txt?",

    "step_5_header": "STEP 5: edit stopwords + create LDA topic strands",
    "step_5_sw_loaded": "stopwords.txt: {count} stopwords loaded",
    "step_5_sw_missing": "WARNING: stopwords.txt not found!",
    "step_5_prompt": "edit stopwords.txt if needed, then press enter...",
    "step_5_params_header": "LDA parameters:",
    "step_5_rerun": "adjust params, edit stopwords.txt, and re-run LDA?",

    "step_6_header": "STEP 6: name topic strands",
    "step_6_intro": "{count} topics identified:",
    "step_6_topic_line": "topic {tid}: {terms}",
    "step_6_current_name": "  current name: {name}",
    "step_6_name_keep": "name (enter to keep)",
    "step_6_name_new": "name",
    "step_6_name_required": "name (required)",
    "step_6_saved": "strand names saved to {path}",
    "step_6_error": "ERROR: lda_topics.json not found. run step 5 first.",

    "step_7_header": "STEP 7: additional vocabulary probes + create strand pages",
    "step_7_probes_loaded": "vocabulary-probes.txt: {count} probe stems loaded",
    "step_7_probes_missing": "no vocabulary-probes.txt found.",
    "step_7_description": "define probe stems (substring matches against title + abstract).",
    "step_7_edit_prompt": "edit probes interactively?",
    "step_7_menu": "  [a] add  [d] delete  [done] save and continue",
    "step_7_add_stem": "stem (e.g., 'politic')",
    "step_7_delete_which": "which number to delete?",
    "step_7_saved": "saved {count} probes to vocabulary-probes.txt",
    "step_7_skip": "skipping probes (no file). strand pages will have empty probe tables.",
    "step_7_alt_prompt": "use a different probe file? enter path (or enter to use default)",
    "step_7_generate": "press enter to generate strand pages...",

    "step_8_header": "STEP 8: create frontmatter for clippings",
    "step_8_info": "writes strand assignments + probe matches to every paper page.",

    "start_prompt": "start from step",
    "continue_prompt": "continue to step {num} ({label})?",
    "paused": "paused. re-run the wizard to resume.",

    "done_header": "DONE",
    "done_message": "open the vault in obsidian to explore the results.",

    "error_script": "ERROR: {name} exited with code {code}",
    "error_continue": "continue anyway?",
    "error_abort": "aborted.",
    "script_running": "running {name}...",
    "script_done": "{name} completed successfully.",
}


# ============================================================================
# UTILITIES
# ============================================================================

def resolve_vault_root(config):
    """Resolve vault_root to an absolute path (relative paths are relative to SCRIPT_DIR)."""
    raw = config["vault_root"]
    p = Path(raw)
    if not p.is_absolute():
        p = (SCRIPT_DIR / p).resolve()
    return p


def load_config():
    """Load config.yaml, resolve vault_root, and prompt if it looks like first run."""
    global VAULT_ROOT
    import yaml
    with open(SCRIPT_DIR / "config.yaml", encoding="utf-8") as f:
        config = yaml.safe_load(f)

    VAULT_ROOT = resolve_vault_root(config)

    # First-run check: if vault root doesn't exist yet, ask
    if not VAULT_ROOT.exists():
        print(f"\n  vault root not found: {VAULT_ROOT}")
        new_path = prompt("vault root path", str(VAULT_ROOT))
        config["vault_root"] = new_path
        with open(SCRIPT_DIR / "config.yaml", "w", encoding="utf-8") as f:
            yaml.dump(config, f, default_flow_style=False, allow_unicode=True, sort_keys=False)
        VAULT_ROOT = resolve_vault_root(config)

    return config


def data_path(filename):
    return VAULT_ROOT / "_data" / filename


def prompt(text, default=""):
    """Prompt with optional default."""
    if default:
        val = input(f"  {text} [{default}]: ").strip()
        return val if val else default
    return input(f"  {text}: ").strip()


def confirm(text, default_yes=True):
    """Yes/no prompt."""
    suffix = "(Y/n)" if default_yes else "(y/N)"
    val = input(f"  {text} {suffix} ").strip().lower()
    if not val:
        return default_yes
    return val in ("y", "yes")


def run_script(name, env_overrides=None, extra_args=None):
    """Run a pipeline script with real-time stdout passthrough."""
    script_path = SCRIPT_DIR / name
    print(f"\n  {TEXT['script_running'].format(name=name)}")
    print(f"  {'=' * 60}")

    env = None
    if env_overrides:
        import os
        env = os.environ.copy()
        env.update(env_overrides)

    cmd = [sys.executable, str(script_path)]
    if extra_args:
        cmd.extend(extra_args)

    result = subprocess.run(
        cmd,
        cwd=str(SCRIPT_DIR),
        env=env,
    )

    print(f"  {'=' * 60}")
    if result.returncode != 0:
        print(f"  {TEXT['error_script'].format(name=name, code=result.returncode)}")
        if not confirm(TEXT["error_continue"], default_yes=False):
            print(f"\n  {TEXT['error_abort']}")
            sys.exit(1)
    else:
        print(f"  {TEXT['script_done'].format(name=name)}")
    return result.returncode == 0


def sanitize_filename(s, max_len=100):
    """Match the filename logic in 03_create_paper_pages.py."""
    s = re.sub(r'[\\/:*?"<>|]', '', s)
    s = re.sub(r'\s+', ' ', s).strip()
    if len(s) > max_len:
        s = s[:max_len].rsplit(' ', 1)[0]
    return s


# ============================================================================
# WIZARD STEPS
# ============================================================================

def step_1_harvest(config):
    """Step 1: Harvest from OpenAlex + KCI."""
    print("\n" + "=" * 64)
    print(f"  {TEXT['step_1_header']}")
    print("=" * 64)

    terms_oa = config["search_terms"]["openalex"]
    terms_kci = config["search_terms"]["kci"]
    date_range = config["date_range"]
    print(f"\n  OpenAlex terms: {terms_oa}")
    print(f"  KCI terms:     {terms_kci}")
    print(f"  Date range:    {date_range[0]}-{date_range[1]}")

    oa_exists = data_path("openalex_raw.json").exists()
    kci_exists = data_path("kci_raw.json").exists()

    if oa_exists and kci_exists:
        print(f"\n  {TEXT['step_1_both_exist']}")
        if not confirm(TEXT["step_1_reharvest"], default_yes=False):
            return

    if not oa_exists or confirm(f"\n  {TEXT['step_1_run_openalex']}"):
        run_script("01_harvest_openalex.py")

    if not kci_exists or confirm(f"\n  {TEXT['step_1_run_kci']}"):
        run_script("02_harvest_kci.py")


def step_2_papers(config):
    """Step 2: Create paper pages (no filtering — that's step 3)."""
    print("\n" + "=" * 64)
    print(f"  {TEXT['step_2_header']}")
    print("=" * 64)

    print(f"\n  {TEXT['step_2_info']}")
    run_script("03_create_paper_pages.py")


def step_3_cleanup(config):
    """Step 3: False positive cleanup — browse vault, edit false-positives.txt, remove matches."""
    print("\n" + "=" * 64)
    print(f"  {TEXT['step_3_header']}")
    print("=" * 64)

    import yaml
    with open(SCRIPT_DIR / "config.yaml", encoding="utf-8") as f:
        cfg = yaml.safe_load(f)
    papers_kci = Path(cfg["vault_root"]) / cfg["paths"]["papers_kci"]
    papers_oa = Path(cfg["vault_root"]) / cfg["paths"]["papers_openalex"]

    while True:
        input(f"\n  {TEXT['step_3_prompt']}")

        fp_path = SCRIPT_DIR / "false-positives.txt"
        if not fp_path.exists():
            print(f"\n  {TEXT['step_3_fp_missing']}")
            break

        with open(fp_path, encoding="utf-8") as f:
            terms = [line.strip() for line in f if line.strip() and not line.startswith("#")]
        print(f"\n  {TEXT['step_3_fp_loaded'].format(count=len(terms))}")

        if not terms:
            print(f"\n  {TEXT['step_3_none']}")
            break

        # Load all_papers.json, find matches, remove them
        ap_path = data_path("all_papers.json")
        if not ap_path.exists():
            print("\n  ERROR: all_papers.json not found. Run step 2 first.")
            break

        with open(ap_path, encoding="utf-8") as f:
            all_papers = json.load(f)

        to_remove = []
        for i, p in enumerate(all_papers):
            text = ((p.get("title") or "") + " " + (p.get("abstract") or "")).lower()
            if any(term in text for term in terms):
                to_remove.append(i)

        if not to_remove:
            print(f"\n  {TEXT['step_3_none']}")
            break

        # Delete paper pages
        pages_deleted = 0
        for idx in to_remove:
            p = all_papers[idx]
            year = p.get("year", "unknown")
            title = p.get("title", "Untitled")
            fname = sanitize_filename(f"{year} - {title}") + ".md"
            corpus = p.get("corpus", "angl")
            subdir = papers_kci if corpus == "KCI" else papers_oa
            fpath = subdir / fname
            if fpath.exists():
                fpath.unlink()
                pages_deleted += 1

        # Remove from all_papers.json
        kept = [p for i, p in enumerate(all_papers) if i not in set(to_remove)]
        with open(ap_path, "w", encoding="utf-8") as f:
            json.dump(kept, f, ensure_ascii=False, indent=2)

        print(f"\n  {TEXT['step_3_removed'].format(count=len(to_remove), pages=pages_deleted)}")

        if not confirm(f"\n  {TEXT['step_3_rerun']}", default_yes=False):
            break


def step_4_subject(config):
    """Step 4: Subject assignment (iterative)."""
    print("\n" + "=" * 64)
    print(f"  {TEXT['step_4_header']}")
    print("=" * 64)

    works_path = SCRIPT_DIR / "works.txt"
    if works_path.exists():
        with open(works_path, encoding="utf-8") as f:
            count = sum(1 for line in f if line.strip() and not line.startswith("#"))
        print(f"\n  {TEXT['step_4_works_loaded'].format(count=count)}")
    else:
        print(f"\n  {TEXT['step_4_works_missing']}")

    while True:
        input(f"\n  {TEXT['step_4_prompt']}")
        run_script("04_subject_assign.py")

        if not confirm(f"\n  {TEXT['step_4_rerun']}", default_yes=False):
            break


def step_5_lda(config):
    """Step 5: Stopwords + LDA + ratios (iterative)."""
    print("\n" + "=" * 64)
    print(f"  {TEXT['step_5_header']}")
    print("=" * 64)

    sw_path = SCRIPT_DIR / "stopwords.txt"
    if sw_path.exists():
        with open(sw_path, encoding="utf-8") as f:
            count = sum(1 for line in f if line.strip() and not line.startswith("#"))
        print(f"\n  {TEXT['step_5_sw_loaded'].format(count=count)}")
    else:
        print(f"\n  {TEXT['step_5_sw_missing']}")

    while True:
        input(f"\n  {TEXT['step_5_prompt']}")

        # LDA parameters
        lda = config.get("lda", {})
        print(f"\n  {TEXT['step_5_params_header']}")
        num_topics = int(prompt("num_topics", str(lda.get("num_topics", 10))))
        no_below = int(prompt("no_below (min doc frequency)", str(lda.get("no_below", 5))))
        no_above = float(prompt("no_above (max doc fraction)", str(lda.get("no_above", 0.5))))
        topic_threshold = float(prompt("topic_threshold (multi-tag cutoff)", "0.20"))

        # Write params back to config for this run
        config["lda"]["num_topics"] = num_topics
        config["lda"]["no_below"] = no_below
        config["lda"]["no_above"] = no_above
        config["lda"]["topic_threshold"] = topic_threshold

        import yaml
        with open(SCRIPT_DIR / "config.yaml", "w", encoding="utf-8") as f:
            yaml.dump(config, f, default_flow_style=False, allow_unicode=True, sort_keys=False)

        # Run stopword audit → LDA → ratios
        run_script("05a_stopword_audit.py")
        run_script("05_lda_strands.py")
        run_script("05b_topic_ratios.py")

        if not confirm(f"\n  {TEXT['step_5_rerun']}", default_yes=False):
            break


def step_6_name_strands():
    """Step 6: Name strands interactively."""
    print("\n" + "=" * 64)
    print(f"  {TEXT['step_6_header']}")
    print("=" * 64)

    topics_path = data_path("lda_topics.json")
    if not topics_path.exists():
        print(f"\n  {TEXT['step_6_error']}")
        return

    with open(topics_path, encoding="utf-8") as f:
        lda = json.load(f)

    names_path = data_path("strand_names.json")
    existing_names = {}
    if names_path.exists():
        with open(names_path, encoding="utf-8") as f:
            existing_names = json.load(f)

    num_topics = int(lda["num_topics"])
    print(f"\n  {TEXT['step_6_intro'].format(count=num_topics)}\n")

    names = {}
    for tid in range(num_topics):
        terms = lda["topics"][str(tid)]
        existing = existing_names.get(str(tid), "")
        print(f"  {TEXT['step_6_topic_line'].format(tid=tid, terms=', '.join(terms[:10]))}")
        if existing and "NAME ME" not in existing:
            print(f"  {TEXT['step_6_current_name'].format(name=existing)}")
            new_name = prompt(TEXT["step_6_name_keep"], existing)
        else:
            new_name = prompt(TEXT["step_6_name_new"])
            while not new_name:
                new_name = prompt(TEXT["step_6_name_required"])
        names[str(tid)] = new_name
        print()

    with open(names_path, "w", encoding="utf-8") as f:
        json.dump(names, f, ensure_ascii=False, indent=2)

    print(f"  {TEXT['step_6_saved'].format(path=names_path)}")
    print()
    for tid, name in names.items():
        print(f"    {tid}: {name}")


def step_7_probes_and_strands():
    """Step 7: Vocabulary probes + strand page generation."""
    global _probe_args

    print("\n" + "=" * 64)
    print(f"  {TEXT['step_7_header']}")
    print("=" * 64)

    probes_path = SCRIPT_DIR / "vocabulary-probes.txt"

    if probes_path.exists():
        with open(probes_path, encoding="utf-8") as f:
            existing = [line.strip() for line in f if line.strip() and not line.startswith("#")]
        print(f"\n  {TEXT['step_7_probes_loaded'].format(count=len(existing))}")
        for line in existing:
            stem = line.split("|")[0].strip()
            print(f"    - {stem}")
    else:
        print(f"\n  {TEXT['step_7_probes_missing']}")

    # Ask for alternate probe file
    alt = prompt(TEXT["step_7_alt_prompt"], "")
    _probe_args = []
    if alt:
        alt_path = Path(alt)
        if not alt_path.is_absolute():
            alt_path = SCRIPT_DIR / alt_path
        if alt_path.exists():
            _probe_args = ["--probes", str(alt_path)]
            print(f"  Using probe file: {alt_path.name}")
        else:
            print(f"  File not found: {alt_path}. Falling back to default.")

    print(f"\n  {TEXT['step_7_description']}")
    print()

    if not _probe_args and confirm(TEXT["step_7_edit_prompt"]):
        stems = []
        if probes_path.exists():
            with open(probes_path, encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if line and not line.startswith("#"):
                        stems.append(line)

        while True:
            print(f"\n  Current probes ({len(stems)}):")
            for i, s in enumerate(stems):
                print(f"    {i+1}. {s}")

            print(f"\n  {TEXT['step_7_menu']}")
            action = prompt("").lower()

            if action in ("done", "save", ""):
                break
            elif action == "a":
                stem = prompt(TEXT["step_7_add_stem"])
                if stem:
                    stems.append(stem)
            elif action == "d":
                num = prompt(TEXT["step_7_delete_which"])
                try:
                    idx = int(num) - 1
                    if 0 <= idx < len(stems):
                        removed = stems.pop(idx)
                        print(f"    Removed: {removed}")
                except ValueError:
                    pass

        # Write probes file
        with open(probes_path, "w", encoding="utf-8") as f:
            f.write("# Vocabulary probe stems (step 06 + 07)\n\n")
            for s in stems:
                f.write(s + "\n")
        print(f"\n  {TEXT['step_7_saved'].format(count=len(stems))}")
    else:
        if not _probe_args and not probes_path.exists():
            print(f"  {TEXT['step_7_skip']}")

    input(f"\n  {TEXT['step_7_generate']}")
    run_script("06_create_strand_pages.py", extra_args=_probe_args)


def step_8_frontmatter():
    """Step 8: Update paper frontmatter."""
    print("\n" + "=" * 64)
    print(f"  {TEXT['step_8_header']}")
    print("=" * 64)

    print(f"\n  {TEXT['step_8_info']}")
    run_script("07_paper_frontmatter.py", extra_args=_probe_args)


# ============================================================================
# MAIN
# ============================================================================

def main():
    print(TEXT["banner"])

    config = load_config()
    print(f"  Subject: {config['subject']}")
    print(f"  Vault:   {config['vault_root']}")
    print(f"  Date:    {config['date_range'][0]}-{config['date_range'][1]}")

    labels = TEXT["step_labels"]
    steps = [
        (labels[0], step_1_harvest),
        (labels[1], step_2_papers),
        (labels[2], step_3_cleanup),
        (labels[3], step_4_subject),
        (labels[4], step_5_lda),
        (labels[5], step_6_name_strands),
        (labels[6], step_7_probes_and_strands),
        (labels[7], step_8_frontmatter),
    ]

    print("\n  Pipeline steps:")
    for i, (label, _) in enumerate(steps, 1):
        print(f"    {i}. {label}")

    start = prompt(f"\n  {TEXT['start_prompt']}", "1")
    start_idx = int(start) - 1

    for i, (label, func) in enumerate(steps):
        if i < start_idx:
            continue

        if i > start_idx:
            if not confirm(f"\n  {TEXT['continue_prompt'].format(num=i+1, label=label)}"):
                print(f"\n  {TEXT['paused']}")
                break

        if func in (step_1_harvest, step_2_papers, step_3_cleanup, step_4_subject, step_5_lda):
            func(config)
        else:
            func()

    print("\n" + "=" * 64)
    print(f"  {TEXT['done_header']}")
    print("=" * 64)
    print(f"\n  {TEXT['done_message']}")
    print(f"  Vault: {config['vault_root']}")
    print()


if __name__ == "__main__":
    main()
