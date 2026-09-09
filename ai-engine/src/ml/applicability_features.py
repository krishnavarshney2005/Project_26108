"""
ai-engine/src/ml/applicability_features.py

Builds the 14-feature DataFrame required by the V1 applicability model.

Signature:
    build_applicability_features(
        requirement_text: str,
        candidate: dict,
        all_candidates: list,
    ) -> pd.DataFrame   # 1 row x 14 columns

Missing values are represented as float('nan') -- never 0.
The downstream joblib pipeline handles its own imputation.
"""

from __future__ import annotations

import logging
import re
from typing import List

import pandas as pd
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Column order MUST match training exactly
# ---------------------------------------------------------------------------
FEATURE_COLUMNS: List[str] = [
    "embedding_cosine_sim",
    "embedding_cosine_sim_rank",
    "bm25_score",
    "bm25_score_rank",
    "tfidf_cosine_sim",
    "token_jaccard",
    "technical_keyword_overlap_ratio",
    "numeric_param_match_ratio",
    "numeric_param_count_requirement",
    "numeric_param_count_standard",
    "unit_overlap_ratio",
    "rrf_score",
    "rrf_rank",
    "requirement_length_ratio",
]

NaN = float("nan")

# ---------------------------------------------------------------------------
# Regex patterns (compiled once at import time)
# ---------------------------------------------------------------------------
_TECH_KW_RE = re.compile(
    r'\b(?:[A-Z]{2,}|IP\d+|\d+(?:\.\d+)?(?:W|kW|V|A|Hz|mm|cm|m|kg|lx|lm))\b'
)
_NUM_RE = re.compile(r'\b\d+(?:\.\d+)?\b')
_UNIT_RE = re.compile(
    r'\b(?:W|kW|V|A|Hz|mm|cm|m|kg|g|lx|lm|cd|K|nm|dB|IP\d+)\b',
    re.IGNORECASE,
)


# ---------------------------------------------------------------------------
# Helper: rank a candidate among all_candidates by a score field (desc)
# Returns 1-based rank, or NaN if not found / score missing.
# ---------------------------------------------------------------------------
def _rank_by(candidate: dict, all_candidates: list, score_field: str) -> float:
    candidate_id = candidate.get("is_number")

    scored = []
    for c in all_candidates:
        val = c.get(score_field)
        if val is not None:
            scored.append((c.get("is_number"), float(val)))

    if not scored:
        return NaN

    scored.sort(key=lambda t: t[1], reverse=True)

    for rank_1based, (cid, _) in enumerate(scored, start=1):
        if cid == candidate_id:
            return float(rank_1based)

    return NaN


# ---------------------------------------------------------------------------
# Helper: build candidate text
# ---------------------------------------------------------------------------
def _scope_text(candidate: dict) -> str:
    """
    Extract the scope prose from either knowledge-base shape.

    The full KB stores a provenance dict {value, source_type, verified}; the
    older 50-record dev KB stores a bare string, or null. Joining the raw dict
    into candidate text raised TypeError, which the caller in Recommender
    swallowed as "ML reranking failed" -- so on the full KB the applicability
    model silently never scored anything. Normalise instead of assuming.
    """
    scope = candidate.get("scope")
    if isinstance(scope, dict):
        return scope.get("value") or ""
    if isinstance(scope, str):
        return scope
    return ""


def _candidate_text(candidate: dict) -> str:
    return " ".join(
        filter(
            None,
            [
                candidate.get("title") or "",
                _scope_text(candidate),
                candidate.get("search_text") or "",
            ],
        )
    ).strip()


# ---------------------------------------------------------------------------
# Feature: TF-IDF cosine similarity
# ---------------------------------------------------------------------------
def _tfidf_cosine(req_text: str, cand_text: str) -> float:
    if not req_text.strip() or not cand_text.strip():
        return NaN
    try:
        vec = TfidfVectorizer(sublinear_tf=True)
        tfidf = vec.fit_transform([req_text, cand_text])
        return float(cosine_similarity(tfidf[0:1], tfidf[1:2])[0][0])
    except Exception as exc:
        logger.debug("tfidf_cosine failed: %s", exc)
        return NaN


# ---------------------------------------------------------------------------
# Feature: token Jaccard similarity
# ---------------------------------------------------------------------------
def _token_jaccard(req_text: str, cand_text: str) -> float:
    a = set(req_text.lower().split())
    b = set(cand_text.lower().split())
    union = a | b
    if not union:
        return NaN
    return float(len(a & b) / len(union))


# ---------------------------------------------------------------------------
# Feature: technical keyword overlap ratio
# ---------------------------------------------------------------------------
def _tech_keyword_overlap(req_text: str, cand_text: str) -> float:
    req_kws = _TECH_KW_RE.findall(req_text)
    if not req_kws:
        return NaN
    cand_lower = cand_text.lower()
    matches = sum(1 for kw in req_kws if kw.lower() in cand_lower)
    return float(matches / len(req_kws))


# ---------------------------------------------------------------------------
# Feature: numeric parameter counts and match ratio
# ---------------------------------------------------------------------------
def _numeric_features(req_text: str, cand_text: str):
    """Returns (match_ratio, count_req, count_std)."""
    req_nums = _NUM_RE.findall(req_text)
    std_nums = _NUM_RE.findall(cand_text)
    count_req = float(len(req_nums))
    count_std = float(len(std_nums))

    if count_req == 0:
        match_ratio = NaN
    else:
        cand_lower = cand_text.lower()
        matches = sum(1 for n in req_nums if n in cand_lower)
        match_ratio = float(matches / count_req)

    return match_ratio, count_req, count_std


# ---------------------------------------------------------------------------
# Feature: unit overlap ratio
# ---------------------------------------------------------------------------
def _unit_overlap(req_text: str, cand_text: str) -> float:
    req_units = set(u.upper() for u in _UNIT_RE.findall(req_text))
    std_units = set(u.upper() for u in _UNIT_RE.findall(cand_text))
    if not req_units:
        return NaN
    union = req_units | std_units
    if not union:
        return NaN
    return float(len(req_units & std_units) / len(union))


# ---------------------------------------------------------------------------
# Feature: requirement length ratio
# ---------------------------------------------------------------------------
def _length_ratio(req_text: str, cand_text: str) -> float:
    cand_words = cand_text.split()
    if not cand_words:
        return NaN
    return float(len(req_text.split()) / len(cand_words))


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------
def build_applicability_features(
    requirement_text: str,
    candidate: dict,
    all_candidates: list,
) -> pd.DataFrame:
    """
    Build a single-row DataFrame with exactly 14 features for the
    V1 applicability model.

    Parameters
    ----------
    requirement_text : str
        The raw user query / requirement string.
    candidate : dict
        A single retrieval candidate dict (as produced by HybridRetriever).
    all_candidates : list
        The full list of candidates from the same retrieval pass, used to
        compute rank-based features.

    Returns
    -------
    pd.DataFrame
        Shape (1, 14).  Missing values are float('nan').
    """
    cand_text = _candidate_text(candidate)

    # --- retrieval scores (direct) ---
    embedding_cosine_sim = candidate.get("semantic_score")
    if embedding_cosine_sim is None:
        embedding_cosine_sim = NaN

    bm25_score = candidate.get("bm25_score")
    if bm25_score is None:
        bm25_score = NaN

    rrf_score = candidate.get("rrf_score")
    if rrf_score is None:
        rrf_score = NaN

    # --- rank features ---
    embedding_cosine_sim_rank = _rank_by(candidate, all_candidates, "semantic_score")
    bm25_score_rank = _rank_by(candidate, all_candidates, "bm25_score")
    rrf_rank = _rank_by(candidate, all_candidates, "rrf_score")

    # --- text similarity features ---
    tfidf_cosine_sim = _tfidf_cosine(requirement_text, cand_text)
    token_jaccard = _token_jaccard(requirement_text, cand_text)
    technical_keyword_overlap_ratio = _tech_keyword_overlap(requirement_text, cand_text)

    # --- numeric features ---
    (
        numeric_param_match_ratio,
        numeric_param_count_requirement,
        numeric_param_count_standard,
    ) = _numeric_features(requirement_text, cand_text)

    # --- unit overlap ---
    unit_overlap_ratio = _unit_overlap(requirement_text, cand_text)

    # --- length ratio ---
    requirement_length_ratio = _length_ratio(requirement_text, cand_text)

    row = {
        "embedding_cosine_sim": embedding_cosine_sim,
        "embedding_cosine_sim_rank": embedding_cosine_sim_rank,
        "bm25_score": bm25_score,
        "bm25_score_rank": bm25_score_rank,
        "tfidf_cosine_sim": tfidf_cosine_sim,
        "token_jaccard": token_jaccard,
        "technical_keyword_overlap_ratio": technical_keyword_overlap_ratio,
        "numeric_param_match_ratio": numeric_param_match_ratio,
        "numeric_param_count_requirement": numeric_param_count_requirement,
        "numeric_param_count_standard": numeric_param_count_standard,
        "unit_overlap_ratio": unit_overlap_ratio,
        "rrf_score": rrf_score,
        "rrf_rank": rrf_rank,
        "requirement_length_ratio": requirement_length_ratio,
    }

    return pd.DataFrame([row], columns=FEATURE_COLUMNS)
