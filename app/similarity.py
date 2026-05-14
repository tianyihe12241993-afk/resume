"""Text similarity scoring for resume <-> JD comparison.

We use term-frequency cosine similarity (no IDF — IDF degenerates with only
two documents). This proxies ATS keyword-density matching reasonably well:
- Tokenizer keeps tech-name shapes intact (Node.js, C++, REST APIs, k8s).
- Stopwords list strips the common English filler so it doesn't dominate.
- Output is a 0..1 cosine score.

The function is dependency-free; no sklearn / no NLTK / no embedding API.
"""
from __future__ import annotations

import re
from collections import Counter
from math import sqrt
from pathlib import Path
from typing import Iterable

from docx import Document


_STOPWORDS = frozenset("""
a an the and or but if then so as at by for from in into of on onto out over to
up upon with within without is are was were be been being am do does did doing
done has have had having will would should could can may might must shall not
no this that these those there here where when which who whom whose why how
what i me my mine you your yours he him his she her hers it its we us our ours
they them their theirs about above below across after before during between
also any all each every other some such only own same than too very also via
across using used use uses including include includes etc e.g eg ie i.e
""".split())


# Tech-name-aware tokenizer. Letters/digits with internal . + # / - are kept
# as a single token (Node.js, C++, REST/SOAP, ci/cd, half-life). Bare numbers
# are dropped.
_TOKEN_RE = re.compile(r"[A-Za-z][A-Za-z0-9]*(?:[.\-+#/][A-Za-z0-9]+)*")


def tokenize(text: str) -> list[str]:
    if not text:
        return []
    out: list[str] = []
    for m in _TOKEN_RE.finditer(text.lower()):
        tok = m.group(0)
        # Strip a trailing punctuation char (e.g. "Node.js." -> "Node.js")
        while tok and tok[-1] in ".+#/-":
            tok = tok[:-1]
        if len(tok) <= 1 or tok in _STOPWORDS:
            continue
        out.append(tok)
    return out


def tf_cosine(a: str, b: str) -> float:
    """Cosine similarity of TF vectors over the union of `a` and `b` tokens.
    Returns 0.0 if either side is empty."""
    ca = Counter(tokenize(a))
    cb = Counter(tokenize(b))
    if not ca or not cb:
        return 0.0
    common = set(ca) & set(cb)
    if not common:
        return 0.0
    num = sum(ca[t] * cb[t] for t in common)
    da = sqrt(sum(v * v for v in ca.values()))
    db = sqrt(sum(v * v for v in cb.values()))
    return num / (da * db) if da and db else 0.0


def jaccard(a: str, b: str) -> float:
    """Jaccard index over the unique-token sets. Cheap structural overlap."""
    sa, sb = set(tokenize(a)), set(tokenize(b))
    if not sa or not sb:
        return 0.0
    return len(sa & sb) / len(sa | sb)


def docx_text(path: str | Path) -> str:
    """Concatenate all paragraph text from a .docx, in order."""
    doc = Document(str(path))
    return "\n".join(p.text for p in doc.paragraphs if p.text.strip())


def compare(resume_text: str, jd_text: str) -> dict:
    """Return both similarity metrics in a single dict."""
    return {
        "tf_cosine": round(tf_cosine(resume_text, jd_text), 4),
        "jaccard": round(jaccard(resume_text, jd_text), 4),
    }
