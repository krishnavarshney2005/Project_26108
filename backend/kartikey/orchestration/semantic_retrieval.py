"""
kartikey/orchestration/semantic_retrieval.py

Thin async client that ranks candidate standards using the ai-engine's
hybrid retriever, for use by pipeline._step_retrieve.

Why this exists
---------------
The ai-engine owns a hybrid FAISS + BM25 + Reciprocal-Rank-Fusion retriever
over a 1028-record BIS knowledge base, with the corpus embeddings pre-built to
disk. It measures 93% R@5 on coverable queries. This backend's own
retrieval_service.py is a weighted lexical token-count scorer -- a good, always
available fallback, but a weaker ranker.

Rather than duplicate the retriever here (which would pull torch + faiss + the
embedding model + 1028 vectors into this process and blow the 512 MB memory
budget -- the exact problem the ai-engine solved by pre-building its indexes),
this module calls the ai-engine over HTTP, mirroring the transport pattern in
kshiraj/aiml_client/client.py.

Design notes
------------
- **The ai-engine RANKS; our StandardsStore remains the source of record.**
  The response is a list of standards in relevance order; each is looked up by
  is_number via get_by_is_number(). Downstream, findings.py resolves standards
  through `standards_lookup = {std.id: std for std in list_all()}` and silently
  skips ids it cannot find, so returning objects that are not in the store
  would make them disappear from the findings. Returning the store's own
  records keeps ids stable and avoids re-deriving metadata from a second schema.

  Both knowledge bases use the same is_number convention
  ("IS 302 : Part 2 : Sec 2"), and StandardsStore keys on strip().casefold()
  with a part-stripped fallback, so parts and sections match exactly while a
  family citation ("IS 10322") still resolves to its parts.

- **Catalog drift is reported, not patched.** This module used to build a thin
  Standard from the ai-engine payload and register it in the store whenever it
  ranked an is_number our catalogue lacked. That existed because the old
  shared/bis_full_catalog_1015.json was missing 22 of the ai-engine's 1028
  is_numbers, and the absentees were concentrated in exactly the high-value
  territory a demo hits: IS 10322 (luminaires), IS 16107 (LED street luminaire),
  IS 1554 (cables), IS 12615 (efficient motors).

  That data problem is now fixed at the source. shared/bis_catalogue_reconciled.json
  is built from the ai-engine knowledge base itself, so every is_number the
  ai-engine can rank is present with its real scope, references and
  certification — measured at 0 unresolvable across all 1028 KB records and all
  50 dev-base records. The backfill was therefore removed rather than left as
  dead code that could quietly resurrect a synthetic record.

  An unresolvable is_number now logs a warning and is skipped. If the ai-engine
  is ever deployed with a knowledge base newer than the backend's catalogue that
  warning is the signal to regenerate it
  (`.venv/bin/python -m shared.build_reconciled_catalogue`) — which is strictly
  better than shipping a record with a scope and status we never verified.

- **Never raises into the pipeline.** Every failure path returns None, which the
  caller reads as "ranking unavailable, use the local retrieval service". A
  ranking upgrade must not be able to fail an analysis.

- Disabled by default: does nothing unless settings.aiml_recommend_url is set.
"""

from __future__ import annotations

import asyncio

import httpx

from shared.config import get_settings
from shared.models import Standard
from shared.utils import get_logger

logger = get_logger(__name__)

# Cap on in-flight requests to the ai-engine. An analysis can carry dozens of
# requirements; firing them all at once would swamp a single Render instance
# that is also holding the FAISS index in memory.
_MAX_CONCURRENCY = 4


async def rank_standards_via_aiml(
    queries: list[str],
    standards_store,
    top_k: int = 3,
) -> list[Standard] | None:
    """
    Rank standards for each query using the ai-engine, resolved to store records.

    Parameters
    ----------
    queries:
        One query string per requirement (an IS reference or the raw text).
    standards_store:
        The StandardsStore to resolve is_numbers against. It is read, never
        written: a recommendation it cannot resolve is skipped and logged.
    top_k:
        Candidates to request per query.

    Returns
    -------
    list[Standard] | None
        Distinct store records in first-seen relevance order, or None if the
        ai-engine is not configured, unreachable, or returned nothing usable.
        None always means "fall back to local retrieval" -- including the case
        where the ai-engine ranked cleanly but found no matches, since the
        lexical scorer is worth a second attempt before giving the user zero
        candidates. A non-empty list is never empty.
    """
    settings = get_settings()
    if not settings.aiml_recommend_enabled:
        return None

    url = settings.aiml_recommend_url.strip()
    clean_queries = [q.strip() for q in queries if q and q.strip()]
    if not clean_queries:
        return None

    semaphore = asyncio.Semaphore(_MAX_CONCURRENCY)

    try:
        async with httpx.AsyncClient(timeout=settings.aiml_timeout_seconds) as client:

            async def one(query_text: str) -> list[dict]:
                async with semaphore:
                    return await _fetch_recommendations(client, url, query_text, top_k)

            # return_exceptions=True so one bad query cannot cancel the rest.
            results = await asyncio.gather(
                *(one(q) for q in clean_queries),
                return_exceptions=True,
            )

    except Exception as exc:
        # Covers client construction and anything gather did not absorb.
        logger.warning(
            "ai-engine ranking unavailable (%s) — falling back to local retrieval.", exc
        )
        return None

    ranked: list[dict] = []
    failures = 0
    for res in results:
        if isinstance(res, BaseException):
            failures += 1
            continue
        ranked.extend(res)

    if failures == len(results):
        logger.warning(
            "All %d ai-engine ranking calls failed — falling back to local retrieval.",
            failures,
        )
        return None
    if failures:
        # Partial success is still an upgrade over lexical, but say so plainly
        # rather than letting a half-empty candidate set look complete.
        logger.warning(
            "%d of %d ai-engine ranking calls failed; continuing with partial results.",
            failures, len(results),
        )

    standards = _resolve_to_store(ranked, standards_store)
    if not standards:
        logger.warning(
            "ai-engine returned %d recommendations but none could be resolved — "
            "falling back to local retrieval.",
            len(ranked),
        )
        return None

    logger.info(
        "ai-engine ranking resolved %d distinct standards from %d queries.",
        len(standards), len(clean_queries),
    )
    return standards


async def _fetch_recommendations(
    client: httpx.AsyncClient,
    url: str,
    query_text: str,
    top_k: int,
) -> list[dict]:
    """POST one query to /recommend and return its recommendations in rank order."""
    response = await client.post(
        url,
        json={"query": query_text, "top_k": top_k},
        headers={"Content-Type": "application/json"},
    )
    response.raise_for_status()
    payload = response.json()

    if not isinstance(payload, dict):
        raise ValueError(f"expected a JSON object from {url}, got {type(payload).__name__}")

    # The ai-engine answers 503 while its index is still loading, and reports
    # soft failures as an "error" key inside a 200 body.
    if payload.get("error"):
        raise ValueError(f"ai-engine reported: {payload['error']}")

    return [
        rec for rec in (payload.get("recommendations") or [])
        if isinstance(rec, dict) and isinstance(rec.get("is_number"), str)
    ]


def _resolve_to_store(recommendations: list[dict], standards_store) -> list[Standard]:
    """
    Map ranked recommendations onto StandardsStore records, preserving rank order.

    The store is the source of record. An is_number it does not carry is skipped
    and reported, never synthesised — see the module docstring on catalogue drift.
    """
    resolved: list[Standard] = []
    seen_ids: set[str] = set()
    unresolved: list[str] = []

    for rec in recommendations:
        is_number = rec["is_number"]
        matches = standards_store.get_by_is_number(is_number)

        if not matches:
            unresolved.append(is_number)
            continue

        for std in matches:
            if std.id not in seen_ids:
                seen_ids.add(std.id)
                resolved.append(std)

    if unresolved:
        logger.warning(
            "%d ai-engine recommendation(s) are absent from the reconciled "
            "catalogue and were skipped: %s%s — regenerate it with "
            "`python -m shared.build_reconciled_catalogue`.",
            len(unresolved),
            ", ".join(unresolved[:5]),
            "…" if len(unresolved) > 5 else "",
        )

    return resolved
