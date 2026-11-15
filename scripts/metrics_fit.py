"""
metrics_fit.py — Fit quality of a finished run: perplexity, C_v, NPMI
=====================================================================

Runs against a finished run (after step 05). Reads the fit record 05 writes
into lda_topics.json (seed, iterations, perplexity) and scores each topic's
top words for coherence against the modelled abstracts:

  C_v   (Roder, Both & Hinneburg 2015): boolean sliding window of 110 tokens,
        NPMI context vectors, cosine against the topic's summed vector.
  NPMI  (Bouma 2009; Lau, Newman & Baldwin 2014): mean pairwise normalised
        PMI over a 10-token sliding window.

Both use the topic's top 10 words and the same preprocessed text the model
saw (05's stopwords and lemmatiser), so a topic is scored on the evidence the
model had. Higher is more coherent; NPMI below zero means the top words occur
together less often than chance would predict.

Perplexity and coherence answer different questions. Perplexity compares fits
of the same k; to compare k, refit at each k and score each fit with this.

--rank-seeds refits the model at the configured k from every seed in the
published set and reports where the configured seed falls once the fits are
ordered by perplexity, lowest first. The vectoriser is fit once and shared, so
every fit scores the same documents against the same vocabulary and only the
random initialisation moves between them.

What that ranking is: a reproduction record. It shows whether the deposited
fit is an ordinary draw among initialisations or an outlier among them. It is
not evidence that k is right — every fit in the ranking has the same k, and
perplexity has no absolute scale — and a rank is not a quality: the seeds in
the band below the best are fits of the same corpus that differ only in where
they started.

Inputs:  _data/lda_topics.json, _data/all_papers.json, _data/stopwords.json
Outputs: console table (markdown); --out <file> also writes it

Dependencies: numpy, nltk, pyyaml; scikit-learn for --rank-seeds, which is
the only mode that refits anything. Nothing here writes to _data/.
Run: python metrics_fit.py [--top 10] [--out file.md]
     python metrics_fit.py --rank-seeds [--seeds 5,21,42] [--progress p.json]
"""

import argparse
import collections
import io
import json
import math
import sys
from pathlib import Path

import numpy as np
import yaml
from nltk.stem import WordNetLemmatizer

sys.path.insert(0, str(Path(__file__).parent))
import _text

SCRIPT_DIR = Path(__file__).parent
EPS = 1e-12

# The seeds the paper reports: the original twelve of the stability run, then
# the forty-seed wider sample. --seeds overrides the list; the default is the
# published set and does not change.
#
# 123 falls in both halves, so the two lists name 52 slots but 51 distinct
# initialisations. The ranking is over the distinct ones: fitting 123 twice
# would put the same fit in the table twice and inflate the denominator.
PUBLISHED_SEEDS = ([42, 7, 123, 2024, 31337, 1, 2, 3, 5, 8, 13, 21]
                   + list(range(100, 140)))


class WindowCounts:
    """Word and word-pair counts over sliding windows of `size` tokens.
    A document shorter than the window counts as one window."""

    def __init__(self, docs, size):
        self.cnt, self.co, self.n = collections.Counter(), collections.Counter(), 0
        for toks in docs:
            if len(toks) <= size:
                windows = [set(toks)]
            else:
                windows = (set(toks[i:i + size]) for i in range(len(toks) - size + 1))
            for w in windows:
                self.n += 1
                present = sorted(w)
                self.cnt.update(present)
                for i in range(len(present)):
                    for j in range(i + 1, len(present)):
                        self.co[(present[i], present[j])] += 1

    def npmi(self, a, b):
        if a == b:
            return 1.0
        pair = (a, b) if a < b else (b, a)
        p_ab = self.co.get(pair, 0) / self.n
        p_a = self.cnt.get(a, 0) / self.n
        p_b = self.cnt.get(b, 0) / self.n
        if p_a <= 0 or p_b <= 0:
            return 0.0
        den = -math.log(p_ab + EPS)
        return math.log((p_ab + EPS) / (p_a * p_b)) / den if den else 0.0


def c_npmi(words, wc):
    vals = [wc.npmi(words[i], words[j])
            for i in range(len(words)) for j in range(i + 1, len(words))]
    return float(np.mean(vals)) if vals else 0.0


def c_v(words, wc):
    m = np.array([[wc.npmi(a, b) for b in words] for a in words])
    total = m.sum(axis=0)
    sims = []
    for i in range(len(words)):
        d = np.linalg.norm(m[i]) * np.linalg.norm(total)
        sims.append(float(np.dot(m[i], total) / d) if d > 0 else 0.0)
    return float(np.mean(sims))


def modelled_docs(papers, stopwords):
    """The documents 05 fits, tokenised the way 05 tokenises them."""
    lem = WordNetLemmatizer()
    docs = []
    for p in papers:
        if _text.is_excluded(p):
            continue
        text = _text.lda_text(p)
        if len(text.strip()) < 50:
            continue
        toks = _text.preprocess(text, stopwords, lem).split()
        if len(toks) >= 5:
            docs.append(toks)
    return docs


def shared_dtm(docs, lda):
    """One document-term matrix for every fit in a ranking, built with 05's
    vectoriser settings. Perplexities computed over different vocabularies are
    not comparable, so the vectoriser is fit once here and never per seed."""
    from sklearn.feature_extraction.text import CountVectorizer
    vec = CountVectorizer(min_df=lda.get("no_below", 5),
                          max_df=lda.get("no_above", 0.5),
                          max_features=lda.get("max_features", 10000))
    return vec.fit_transform([" ".join(d) for d in docs])


def rank_seeds(dtm, seeds, lda, progress=None):
    """Refit at the configured k from each seed and return
    {seed: {perplexity, n_iter, converged}}.

    Every parameter but random_state comes from config.yaml, n_jobs included:
    it is an explicit integer there because -1 resolves to the host core count
    and the numbers move with the machine. `progress` names a JSON file
    rewritten after each fit, so a long sweep stays inspectable while it runs
    and an interrupted one resumes from the seeds already fitted."""
    from sklearn.decomposition import LatentDirichletAllocation

    k, max_iter = int(lda.get("num_topics", 10)), int(lda.get("max_iter", 500))
    # The sweep is only resumable onto the same corpus, k and ceiling.
    stamp = {"k": k, "max_iter": max_iter,
             "documents": dtm.shape[0], "vocabulary": dtm.shape[1]}
    done = {}
    if progress and Path(progress).exists():
        prev = json.loads(Path(progress).read_text(encoding="utf-8"))
        if prev.get("fit_over") == stamp:
            done = {int(s): r for s, r in prev.get("seeds", {}).items()}

    for seed in seeds:
        if seed in done:
            continue
        model = LatentDirichletAllocation(
            n_components=k,
            max_iter=max_iter,
            learning_method=lda.get("learning_method", "batch"),
            random_state=seed,
            n_jobs=lda.get("n_jobs", 16),
            evaluate_every=lda.get("evaluate_every", 10),
            perp_tol=lda.get("perp_tol", 0.1),
        )
        model.fit(dtm)
        done[seed] = {"perplexity": float(model.perplexity(dtm)),
                      "n_iter": int(model.n_iter_),
                      "converged": int(model.n_iter_) < max_iter}
        if progress:
            Path(progress).write_text(
                json.dumps({"fit_over": stamp,
                            "seeds": {str(s): done[s] for s in sorted(done)}},
                           indent=1), encoding="utf-8")
    return {s: done[s] for s in seeds}


def ranking_report(results, seed, deposited=None):
    """The rank line rin quotes, then the per-seed table, lowest perplexity
    first. Returns (rank_tag_for_the_fit_line, lines)."""
    order = sorted(results, key=lambda s: results[s]["perplexity"])
    pxs = [results[s]["perplexity"] for s in order]
    rank = order.index(seed) + 1 if seed in results else None
    stalled = [s for s in order if not results[s]["converged"]]

    tag = " (rank %d of %d seeds)" % (rank, len(order)) if rank else ""
    lines = []
    if rank:
        lines.append("seed %d: perplexity %.2f — rank %d of %d (range %.2f–%.2f)"
                     % (seed, results[seed]["perplexity"], rank, len(order),
                        pxs[0], pxs[-1]))
        if deposited is not None and abs(results[seed]["perplexity"] - deposited) > 0.005:
            lines.append("! the refit gives %.2f where the deposited record says %.2f"
                         " — the sweep is not on 05's code path"
                         % (results[seed]["perplexity"], deposited))
    else:
        lines.append("configured seed %d is not in the ranked set" % seed)
    lines += ["",
              "%d fits of the same k over the same documents and vocabulary;"
              " %d did not converge within the iteration ceiling."
              % (len(order), len(stalled)),
              "",
              "| rank | seed | perplexity | n_iter | converged |",
              "|---|---|---|---|---|"]
    for i, s in enumerate(order, 1):
        r = results[s]
        mark = "**%d**" % s if s == seed else "%d" % s
        lines.append("| %d | %s | %.2f | %d | %s |"
                     % (i, mark, r["perplexity"], r["n_iter"],
                        "yes" if r["converged"] else "NO"))
    return tag, lines


def main():
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser()
    ap.add_argument("--top", type=int, default=10, help="top words per topic")
    ap.add_argument("--out", help="also write the table to this file")
    ap.add_argument("--rank-seeds", action="store_true",
                    help="refit at the configured k from every published seed and"
                         " report where the configured seed ranks by perplexity")
    ap.add_argument("--seeds",
                    help="comma-separated seeds, overriding the published set")
    ap.add_argument("--progress",
                    help="with --rank-seeds: JSON file rewritten after each fit")
    args = ap.parse_args()

    with open(SCRIPT_DIR / "config.yaml", encoding="utf-8") as f:
        cfg = yaml.safe_load(f)
    _vr = Path(cfg["vault_root"])
    data_dir = (_vr if _vr.is_absolute() else (SCRIPT_DIR / _vr).resolve()) / cfg["paths"]["data"]

    with open(data_dir / "lda_topics.json", encoding="utf-8") as f:
        lda = json.load(f)
    with open(data_dir / "all_papers.json", encoding="utf-8") as f:
        papers = json.load(f)
    docs = modelled_docs(papers, _text.load_stopwords(data_dir))
    w10, w110 = WindowCounts(docs, 10), WindowCounts(docs, 110)

    fit = lda.get("fit", {})
    rank_tag, rank_lines = "", []
    if args.rank_seeds:
        lda_cfg = cfg.get("lda", {})
        seeds = ([int(s) for s in args.seeds.split(",")] if args.seeds
                 else list(PUBLISHED_SEEDS))
        seeds = list(dict.fromkeys(seeds))  # distinct, in the order given
        results = rank_seeds(shared_dtm(docs, lda_cfg), seeds, lda_cfg, args.progress)
        rank_tag, rank_lines = ranking_report(
            results, int(lda_cfg.get("seed", fit.get("seed", 0))),
            lda.get("perplexity"))

    lines = ["k %s · seed %s · perplexity %s%s · %s iterations of %s%s · %d documents"
             % (lda["num_topics"], fit.get("seed", "?"), lda.get("perplexity"), rank_tag,
                fit.get("n_iter", "?"), fit.get("max_iter", "?"),
                "" if fit.get("converged", True) else " (did NOT converge)", len(docs)),
             "",
             "| topic | top words | C_v | NPMI |",
             "|---|---|---|---|"]
    cvs, nps = [], []
    for tid in range(int(lda["num_topics"])):
        words = lda["topics"][str(tid)][:args.top]
        cv, npm = c_v(words, w110), c_npmi(words, w10)
        cvs.append(cv)
        nps.append(npm)
        lines.append("| %d | %s | %.3f | %+.3f |" % (tid, ", ".join(words[:6]), cv, npm))
    lines.append("| mean | | %.3f | %+.3f |" % (np.mean(cvs), np.mean(nps)))
    if rank_lines:
        lines += [""] + rank_lines
    out = "\n".join(lines)
    print(out)
    if args.out:
        Path(args.out).write_text(out + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
