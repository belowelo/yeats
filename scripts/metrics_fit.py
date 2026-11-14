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

Inputs:  _data/lda_topics.json, _data/all_papers.json, _data/stopwords.json
Outputs: console table (markdown); --out <file> also writes it

Dependencies: numpy, nltk, pyyaml
Run: python metrics_fit.py [--top 10] [--out file.md]
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


def main():
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser()
    ap.add_argument("--top", type=int, default=10, help="top words per topic")
    ap.add_argument("--out", help="also write the table to this file")
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
    lines = ["k %s · seed %s · perplexity %s · %s iterations of %s%s · %d documents"
             % (lda["num_topics"], fit.get("seed", "?"), lda.get("perplexity"),
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
    out = "\n".join(lines)
    print(out)
    if args.out:
        Path(args.out).write_text(out + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
