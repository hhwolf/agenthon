"""BM25 relevance of each document to the unit's assets (allowed: lexical index, no embeddings).

Practice corpora carry deliberately off-topic speeches and salted variants. Documents that
mention none of the asset/bank terms are ranked after everything on topic and are the first to be
dropped when the corpus does not fit the request budget.
"""

from __future__ import annotations

import math
import re
from collections import Counter
from dataclasses import dataclass

from . import constants as C

_TOKEN_RE = re.compile(r"[a-z][a-z0-9'&-]{1,}")

# Asset id -> discriminative terms (multi-word phrases are split into tokens; distinctive tokens carry weight).
ASSET_TERMS: dict[str, tuple[str, ...]] = {
    "JPY": ("yen", "japan", "japanese", "boj", "bank of japan", "kuroda", "shirakawa", "abenomics"),
    "EUR": ("euro", "ecb", "european central bank", "eurozone", "euro area", "draghi", "lagarde", "trichet"),
    "GBP": ("sterling", "pound", "boe", "bank of england", "mpc", "united kingdom", "britain", "brexit", "carney", "bailey"),
    "CHF": ("franc", "swiss", "snb", "swiss national bank", "switzerland", "jordan"),
    "AUD": ("australian", "australia", "rba", "reserve bank of australia", "aussie"),
    "CAD": ("canadian", "canada", "bank of canada", "boc", "loonie", "poloz", "macklem"),
    "NZD": ("new zealand", "rbnz", "kiwi"),
    "SEK": ("krona", "sweden", "swedish", "riksbank"),
    "NOK": ("krone", "norway", "norwegian", "norges bank"),
    "DKK": ("danish", "denmark", "nationalbank", "krone"),
    "CNY": ("renminbi", "yuan", "china", "chinese", "pboc", "people's bank of china"),
    "INR": ("rupee", "india", "indian", "rbi", "reserve bank of india"),
    "BRL": ("brazil", "brazilian", "bcb", "banco central", "copom", "selic"),
    "MXN": ("peso", "mexico", "mexican", "banxico"),
    "KRW": ("won", "korea", "korean", "bok"),
    "ZAR": ("rand", "south africa", "sarb"),
    "TRY": ("lira", "turkey", "turkish", "cbrt"),
    "CPI_ALL": ("inflation", "cpi", "consumer price", "consumer prices", "core inflation", "price index"),
    "UNRATE": ("unemployment", "jobless", "labor market", "labour market", "payrolls", "employment situation"),
    "PAYEMS": ("payrolls", "nonfarm", "employment", "jobs report", "labor market", "hiring"),
}
_UST_TERMS = ("treasury", "treasuries", "yield", "yields", "fomc", "federal reserve", "fed funds",
              "federal funds", "rate hike", "basis points", "tightening", "easing", "powell", "yellen", "bernanke")
_FACTOR_TERMS = ("equity", "equities", "stock market", "stocks", "s&p", "risk assets", "earnings",
                 "valuation", "volatility", "financial conditions", "risk appetite")
_GENERIC_CB = ("monetary policy", "policy rate", "central bank")


def asset_terms(asset: str) -> tuple[str, ...]:
    a = asset.upper()
    if a in ASSET_TERMS:
        return ASSET_TERMS[a]
    if a.startswith("UST") or a.startswith("DGS") or "Y" in a and a.replace("UST_", "").rstrip("Y").isdigit():
        return _UST_TERMS
    if a.startswith("CPI"):
        return ASSET_TERMS["CPI_ALL"]
    if a in {"MKT", "SMB", "HML", "RMW", "CMA", "QMJ", "UMD", "MOM", "BAB", "MKT-RF"}:
        return _FACTOR_TERMS
    return (a.lower(),)


def tokenize(text: str) -> list[str]:
    return _TOKEN_RE.findall(text.lower())


def query_terms(assets: tuple[str, ...], extra: set[str] | None = None) -> tuple[set[str], set[str]]:
    """Return (asset_specific_tokens, all_query_tokens)."""
    specific: set[str] = set()
    for a in assets:
        for term in asset_terms(a):
            specific.update(tokenize(term))
    specific -= {"of", "the", "bank", "central", "reserve", "price", "index", "market", "rate"}
    if extra:  # card prose names the actors of the setup (e.g. "Fed", "taper", "election"); count them as specific
        specific.update(t for t in extra if len(t) >= 5)
    allq = set(specific)
    for term in _GENERIC_CB:
        allq.update(tokenize(term))
    return specific, allq


@dataclass(frozen=True)
class Relevance:
    bm25: float          # raw BM25 score against the full query
    normalised: float    # bm25 / max over the corpus (0..1)
    specific_hits: int   # distinct asset/bank tokens present
    off_topic: bool      # no asset/bank token at all


def score_documents(texts: dict[str, str], assets: tuple[str, ...], extra: set[str] | None = None,
                    *, max_chars: int = 200_000) -> dict[str, Relevance]:
    """BM25 (k1, b from constants) of every document against the asset query. Pure Python, stdlib only."""
    specific, allq = query_terms(assets, extra)
    tokens = {d: tokenize(t[:max_chars]) for d, t in texts.items()}
    n = len(tokens)
    if n == 0:
        return {}
    avgdl = sum(len(t) for t in tokens.values()) / n
    df: Counter = Counter()
    tfs: dict[str, Counter] = {}
    for d, toks in tokens.items():
        tf = Counter(toks)
        tfs[d] = tf
        for q in allq:
            if q in tf:
                df[q] += 1
    scores: dict[str, float] = {}
    hits: dict[str, int] = {}
    for d, tf in tfs.items():
        dl = max(1, len(tokens[d]))
        s = 0.0
        for q in allq:
            f = tf.get(q, 0)
            if not f:
                continue
            idf = math.log(1 + (n - df[q] + 0.5) / (df[q] + 0.5))
            s += idf * f * (C.BM25_K1 + 1) / (f + C.BM25_K1 * (1 - C.BM25_B + C.BM25_B * dl / avgdl))
        scores[d] = s
        hits[d] = sum(1 for q in specific if q in tf)
    top = max(scores.values()) if scores else 0.0
    return {d: Relevance(bm25=scores[d], normalised=(scores[d] / top if top > 0 else 0.0),
                         specific_hits=hits[d], off_topic=hits[d] == 0) for d in tokens}
