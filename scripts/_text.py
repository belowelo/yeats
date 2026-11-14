"""
_text.py — shared text handling for the pipeline
=================================================

The preprocessing used to pick a document's text, clean it and lemmatise it
lived in 05_lda_strands.py only. Every ad-hoc analysis script therefore
reimplemented it, and the reimplementations drifted. This module is the one
copy. 03b_clean.py and 05_lda_strands.py both import it, so the token count
that decides whether a record is usable is computed exactly once.

No I/O at import time except the stopword list, which is optional.
"""

import json
import re
import unicodedata
from pathlib import Path

_KOREAN = r'[가-힣]'


def load_stopwords(data_dir: Path) -> set:
    """Load stopwords.json (written by 05a). Returns a minimal fallback set
    if the audit has not been run yet, so that 03b can run before 05a."""
    path = Path(data_dir) / "stopwords.json"
    if path.exists():
        with open(path, encoding="utf-8") as f:
            return set(json.load(f)["words"].keys())
    return {
        "yeats", "yeat", "poem", "poetry", "poet", "poetic",
        "paper", "study", "article", "research", "analysis", "argue",
        "work", "literary", "literature", "irish", "ireland",
        "william", "butler",
        "예이츠", "시", "시인", "문학", "연구", "논문", "분석",
    }


def lda_text(paper: dict) -> str:
    """The text a paper is modelled on.

    KCI records carry [Korean, English] in `abstracts`; the English one is
    last. Latin script only reaches the model (see preprocess), so a KCI
    paper distributes across topics on its English abstract, on the same
    footing as an anglophone one. The KCI/anglophone ratio per topic IS the
    signal, so mixing scripts would defeat it.
    """
    parts = paper.get("abstracts") or [paper.get("abstract", "")]
    if len(parts) > 1:
        return parts[-1] or ""
    return (parts[0] if parts else paper.get("abstract", "")) or ""


def full_text(paper: dict) -> str:
    """Title plus every abstract, lowercased. Used for probe matching and for
    subject-term detection, not for modelling. Keeps Korean: a record that
    writes the subject only in Hangul must still count as mentioning it."""
    parts = paper.get("abstracts") or [paper.get("abstract", "")]
    return ((paper.get("title") or "") + " " + " ".join(p or "" for p in parts)).lower()


def preprocess(text: str, stopwords: set, lemmatizer=None) -> str:
    """Lowercase, strip URLs/DOIs/OpenAlex keyword boilerplate, keep Latin
    tokens of 3+ characters, lemmatise, drop stopwords."""
    if lemmatizer is None:
        from nltk.stem import WordNetLemmatizer
        lemmatizer = WordNetLemmatizer()

    text = text.lower()
    text = re.sub(r'https?://\S+', '', text)
    text = re.sub(r'doi[:\s]*10\.\S+', '', text)
    text = re.sub(r'these keywords were added by machine.*?learning algorithm improves\.?',
                  '', text, flags=re.DOTALL)
    tokens = re.findall(r'[a-z]{3,}', text)
    return " ".join(
        lem for t in tokens
        if (lem := lemmatizer.lemmatize(t)) not in stopwords
    )


def norm_title(s: str) -> str:
    """Aggressive title normalisation for duplicate detection: strip
    diacritics and markup, keep only alphanumerics and Hangul."""
    s = unicodedata.normalize("NFKD", s or "")
    s = "".join(c for c in s if not unicodedata.combining(c))
    s = unicodedata.normalize("NFC", s).lower()
    s = re.sub(r'<[^>]+>', '', s)
    s = re.sub(r'[^a-z0-9가-힣]+', ' ', s).strip()
    return re.sub(r'\s+', ' ', s)


def korean_char_count(text: str) -> int:
    return len(re.findall(_KOREAN, text))


def is_excluded(paper: dict) -> bool:
    """The one place downstream scripts should ask whether a record was
    cleaned out. Records predating 03b have no `cleaning` key and count as
    kept, so the pipeline still runs on an un-cleaned corpus."""
    return bool((paper.get("cleaning") or {}).get("excluded"))
