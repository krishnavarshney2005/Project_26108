"""
ai-engine/src/recommender.py

Orchestrates the full recommendation pipeline:
  1. parse_query    — LLM-powered structured query understanding
  2. HybridRetriever — BM25 + FAISS cosine (Reciprocal Rank Fusion)
  3. rank_results   — multi-signal reranking with proper evidence objects
  4. check_currentness — deterministic version/supersession check
  5. detect_gaps    — real requirement vs standard coverage gaps
"""

import json
import logging
import os
import re

# ---------------------------------------------------------------------------
# OpenMP safety — set before the heavy imports below. faiss, torch,
# scikit-learn and lightgbm each bundle their own libomp; loading a second
# OpenMP runtime into one process segfaults (SIGSEGV) on macOS. This makes
# `from src.recommender import Recommender` safe on its own (tests/scripts),
# independent of api/main.py. setdefault() so an explicit env var still wins.
# ---------------------------------------------------------------------------
os.environ.setdefault("KMP_DUPLICATE_LIB_OK", "TRUE")
os.environ.setdefault("OMP_NUM_THREADS", "1")

from src.embedding import generate_embeddings
from src.search import HybridRetriever, VectorStore
from src.ranking import rank_results
from src.gap_detector import detect_gaps
from src.query_understanding import parse_query
from src.currentness import check_currentness, check_explicit_reference
from src.ml.applicability_model import load_applicability_model
from src.ml.applicability_features import build_applicability_features

logger = logging.getLogger(__name__)


# BIS designations are written with inconsistent punctuation — "IS 10322 : Part 5
# : Sec 3" and "IS 10322 Part 5 Sec 3" denote the same standard. Collapsing both
# to a canonical form lets a cited designation be compared against a candidate's
# is_number without depending on how the citation happened to be typed.
_DESIGNATION_PUNCT_RE = re.compile(r"[:\-–—,()]+")
_DESIGNATION_WS_RE = re.compile(r"\s+")


def _normalise_designation(text: str) -> str:
    collapsed = _DESIGNATION_PUNCT_RE.sub(" ", (text or "").casefold())
    return _DESIGNATION_WS_RE.sub(" ", collapsed).strip()


class Recommender:
    def __init__(self, data_path: str = "data/bis_full_knowledge_base.json"):
        self.data_path = data_path
        self.standards: list = []
        self.retriever = None
        self._load_and_index()

        # ML Applicability Model
        import os as _os
        _root = _os.path.abspath(_os.path.join(_os.path.dirname(__file__), "..", ".."))
        self.applicability_model = load_applicability_model(
            model_path=_os.path.join(_root, "standiq_applicability_model_v2.joblib"),
            metadata_path=_os.path.join(_root, "standiq_applicability_model_v2_metadata.json"),
        )
        if self.applicability_model:
            logger.info("Applicability ML model loaded: %s", self.applicability_model.model_version)
        else:
            logger.warning("Applicability ML model unavailable -- deterministic ranking only.")

    def _load_and_index(self) -> None:
        if not os.path.exists(self.data_path):
            fallback = "data/bis_50_knowledge_base.json"
            if os.path.exists(fallback):
                logger.warning(
                    "Full KB not found at '%s', falling back to '%s'.",
                    self.data_path, fallback
                )
                self.data_path = fallback
            else:
                logger.error("No knowledge base found — Recommender will not function.")
                return

        try:
            with open(self.data_path, "r", encoding="utf-8") as f:
                self.standards = json.load(f)
        except Exception as exc:
            logger.error("Failed to load knowledge base: %s", exc)
            return

        if not self.standards:
            logger.error("Knowledge base at '%s' is empty.", self.data_path)
            return

        logger.info("Loaded %d standards from %s", len(self.standards), self.data_path)

        # ------------------------------------------------------------------
        # FAST PATH (Render-safe): load the pre-built FAISS index + BM25
        # pickle that build_index.py serialized to disk. This skips the
        # SentenceTransformer batch-embedding of every standard on startup —
        # the exact step that spiked RAM past the 512 MB limit and OOM-crashed
        # the server. Cost is a few MB read from disk; no heavy compute.
        # ------------------------------------------------------------------
        if self._load_precomputed_retriever():
            logger.info(
                "Recommender ready — %d standards indexed (pre-built artifacts).",
                len(self.standards),
            )
            return

        # ------------------------------------------------------------------
        # FALLBACK (local dev / missing or stale artifacts): build indexes
        # from scratch. Re-uses the cached embeddings .npy when the KB is
        # unchanged, otherwise re-embeds (needs the ST model resident in RAM).
        # ------------------------------------------------------------------
        is_render = os.getenv("RENDER") == "true" or os.getenv("ENVIRONMENT") == "production"
        if is_render:
            logger.error("Render deployment MUST use pre-built artifacts. Fallback disabled.")
            raise RuntimeError("Render deployment MUST use pre-built artifacts. Fallback disabled to prevent OOM.")
            
        try:
            cache_path = self.data_path.replace(".json", "_embeddings.npy")
            kb_mtime = os.path.getmtime(self.data_path)
            import numpy as np

            if os.path.exists(cache_path) and os.path.getmtime(cache_path) >= kb_mtime:
                logger.info("Loading embeddings from cache: %s", cache_path)
                embeddings = np.load(cache_path)
                if embeddings.shape[0] != len(self.standards):
                    logger.warning(
                        "Cache has %d vectors but KB has %d records — regenerating.",
                        embeddings.shape[0], len(self.standards)
                    )
                    raise ValueError("cache/kb size mismatch")
            else:
                logger.info(
                    "Generating embeddings for %d standards (no valid cache)…",
                    len(self.standards)
                )
                search_texts = [std.get("search_text", "") for std in self.standards]
                embeddings = generate_embeddings(search_texts)
                try:
                    np.save(cache_path, embeddings)
                    logger.info("Embedding cache saved to %s", cache_path)
                except Exception as cache_exc:
                    logger.warning("Could not save embedding cache: %s", cache_exc)

            logger.info("Building HybridRetriever (BM25 + FAISS)…")
            self.retriever = HybridRetriever().fit(self.standards, embeddings)
            logger.info("Recommender ready — %d standards indexed (built from scratch).", len(self.standards))

        except Exception as exc:
            logger.error("Failed to build retrieval index: %s", exc)
            self.retriever = None

    def _load_precomputed_retriever(self) -> bool:
        """
        Reconstruct the HybridRetriever from the artifacts produced by
        build_index.py (`*_faiss.index` + `*_bm25.pkl`), validated against
        `*_index_meta.json`, WITHOUT re-embedding or re-fitting anything.

        Returns True if the retriever was loaded and wired up; False to tell
        the caller to fall back to building indexes from scratch.
        """
        is_render = os.getenv("RENDER") == "true" or os.getenv("ENVIRONMENT") == "production"

        def fail(msg: str, exc: Exception = None):
            if is_render:
                logger.error(f"PREBUILT INDEX FATAL ERROR (RENDER): {msg}")
                if exc:
                    raise RuntimeError(f"Render prebuilt index failure: {msg}") from exc
                else:
                    raise RuntimeError(f"Render prebuilt index failure: {msg}")
            else:
                if exc:
                    logger.warning(f"Local prebuilt index bypass: {msg} - {exc}")
                else:
                    logger.warning(f"Local prebuilt index bypass: {msg}")
                return False

        try:
            import faiss
            logger.info("Diagnostic (c): FAISS import SUCCESS")
        except Exception as e:
            return fail("FAISS import failed", e)

        import joblib

        base      = os.path.splitext(self.data_path)[0]
        bm25_path = f"{base}_bm25.pkl"
        idx_path  = f"{base}_faiss.index"
        meta_path = f"{base}_index_meta.json"

        if not (os.path.exists(bm25_path) and os.path.exists(idx_path)):
            return fail("Pre-built artifacts missing from disk")

        # --- a. metadata read ---
        if os.path.exists(meta_path):
            try:
                with open(meta_path, "r", encoding="utf-8") as f:
                    meta = json.load(f)
                logger.info("Diagnostic (a): metadata read SUCCESS")
            except Exception as exc:
                return fail(f"Unreadable index metadata {meta_path}", exc)

            rc = meta.get("record_count")
            
            # --- b. knowledge-base SHA256 validation ---
            expected_sha = meta.get("kb_sha256")
            if expected_sha:
                import hashlib
                h = hashlib.sha256()
                with open(self.data_path, "rb") as fh:
                    for chunk in iter(lambda: fh.read(65536), b""):
                        h.update(chunk)
                actual_sha = h.hexdigest()
                if actual_sha != expected_sha:
                    return fail(f"KB checksum changed. Expected: {expected_sha}, Actual: {actual_sha}")
                logger.info("Diagnostic (b): knowledge-base SHA256 validation SUCCESS")

        try:
            # --- e. BM25/joblib load ---
            try:
                bm25 = joblib.load(bm25_path)
                logger.info("Diagnostic (e): BM25/joblib load SUCCESS")
            except Exception as e:
                return fail("BM25 joblib load failed", e)

            # --- f. document/index count validation (BM25) ---
            if getattr(bm25, "n_docs", None) != len(self.standards):
                return fail(f"BM25 pickle has {getattr(bm25, 'n_docs', '?')} docs but KB has {len(self.standards)}")

            # --- d. FAISS index load ---
            try:
                index = faiss.read_index(idx_path)
                logger.info("Diagnostic (d): FAISS index load SUCCESS")
            except Exception as e:
                return fail("FAISS index load failed", e)

            # --- f. document/index count validation (FAISS) ---
            if index.ntotal != len(self.standards):
                return fail(f"FAISS index has {index.ntotal} vectors but KB has {len(self.standards)}")
            
            logger.info("Diagnostic (f): document/index count validation SUCCESS")

            # --- g. final prebuilt retriever initialization ---
            retriever = HybridRetriever()
            retriever.standards = self.standards
            retriever.bm25 = bm25
            vector_store = VectorStore(dimension=index.d)
            vector_store.index = index      # replace the empty IndexFlatIP
            retriever.vector_store = vector_store
            self.retriever = retriever

            logger.info(
                "Diagnostic (g): final prebuilt retriever initialization SUCCESS. Loaded: BM25=%s (%d docs), FAISS=%s (%d vectors, dim=%d).",
                os.path.basename(bm25_path), bm25.n_docs,
                os.path.basename(idx_path), index.ntotal, index.d,
            )
            return True

        except Exception as exc:
            return fail("Unexpected failure during prebuilt artifact loading", exc)

    def _select_top_k(self, ranked_results: list, query: str, top_k: int) -> list:
        """
        Truncate to top_k without silently discarding a standard the query cites.

        ML applicability reranking optimises for topical applicability. That is
        the right objective for prose queries, but it demotes exact designation
        matches: a query of "IS 6134 : Part 2" retrieves that standard at
        deterministic rank 1, and the reranker can push it past top_k. The
        backend sends exactly this query shape whenever a requirement carries an
        is_reference, so the cited standard would be dropped before compliance
        checking ever saw it.

        This guarantees membership only. The reranker still decides ordering,
        and nothing is promoted that retrieval did not already surface.
        """
        selected = ranked_results[:top_k]
        if not ranked_results or top_k <= 0:
            return selected

        haystack = f" {_normalise_designation(query)} "
        cited = [
            candidate
            for candidate in ranked_results
            if (designation := _normalise_designation(candidate.get("is_number") or ""))
            and f" {designation} " in haystack
        ]
        if not cited:
            return selected

        selected_ids = {id(candidate) for candidate in selected}
        missing = [c for c in cited if id(c) not in selected_ids]
        if not missing:
            return selected

        cited_ids = {id(candidate) for candidate in cited}
        promoted = [c for c in selected if id(c) in cited_ids] + missing
        fillers = [c for c in selected if id(c) not in cited_ids]
        merged = promoted + fillers[: max(0, top_k - len(promoted))]

        # Restore the reranker's relative ordering among the survivors, so the
        # only difference from a plain truncation is which rows survive.
        rank_of = {id(candidate): i for i, candidate in enumerate(ranked_results)}
        merged.sort(key=lambda candidate: rank_of[id(candidate)])
        merged = merged[:top_k]
        for position, candidate in enumerate(merged, 1):
            candidate["rank"] = position

        logger.info(
            "Preserved %d explicitly cited standard(s) through top-%d truncation: %s",
            len(missing), top_k, [c.get("is_number") for c in missing],
        )
        return merged

    def recommend(self, query: str, top_k: int = 5) -> dict:
        if self.retriever is None:
            return {"error": "Recommender not initialized — dataset missing or empty."}

        if not query or not query.strip():
            return {"error": "Query cannot be empty."}

        try:
            # ----------------------------------------------------------------
            # 1. Structured query understanding
            # ----------------------------------------------------------------
            query_understanding = parse_query(query)
            logger.info(
                "Query understood: product=%s domain=%s tech_reqs=%d",
                query_understanding.get("product"),
                query_understanding.get("domain"),
                len(query_understanding.get("technical_requirements") or []),
            )

            # ----------------------------------------------------------------
            # 2. Hybrid retrieval — BM25 + FAISS via Reciprocal Rank Fusion
            # ----------------------------------------------------------------
            query_emb = generate_embeddings(query)
            candidates = self.retriever.search(query, query_emb, top_k=20)

            # ----------------------------------------------------------------
            # 3. Reranking with structured evidence
            # ----------------------------------------------------------------
            ranked_results = rank_results(candidates, query_understanding)
            # ----------------------------------------------------------------
            # 3b. ML Applicability Reranking (after deterministic rank_results)
            # ----------------------------------------------------------------
            if self.applicability_model:
                try:
                    for candidate in ranked_results:
                        feat_df = build_applicability_features(
                            requirement_text=query,
                            candidate=candidate,
                            all_candidates=ranked_results,
                        )
                        ml_result = self.applicability_model.predict(feat_df)
                        candidate["applicability_score"] = ml_result["applicability_score"]
                        candidate["applicability_class"] = ml_result["applicability_class"]
                        candidate["applicability_model_version"] = ml_result["model_version"]
                        candidate["applicability_feature_coverage"] = ml_result["feature_coverage"]
                    # Soft rerank: sort by ML score desc, tiebreak with relevance_score
                    ranked_results = sorted(
                        ranked_results,
                        key=lambda x: (x.get("applicability_score") or 0.0, x.get("relevance_score", 0.0)),
                        reverse=True,
                    )
                    for i, r in enumerate(ranked_results, 1):
                        r["rank"] = i
                    logger.info("ML applicability reranking applied to %d candidates.", len(ranked_results))
                except Exception as ml_exc:
                    logger.error("ML reranking failed: %s -- using deterministic ranking.", ml_exc)
            final_recommendations = self._select_top_k(ranked_results, query, top_k)

            if not final_recommendations:
                return {
                    "query": query,
                    "query_understanding": query_understanding,
                    "recommendations": [],
                    "potential_gaps": [],
                    "currentness": {},
                    "confidence": "low",
                }

            # ----------------------------------------------------------------
            # 4. Currentness & Gaps for EACH recommendation
            # ----------------------------------------------------------------
            output_recs = []
            related_stds = set()
            test_methods = set()
            safety_stds = set()
            norm_refs = set()

            for std in final_recommendations:
                # 1. Currentness
                std_currentness = check_currentness(std)
                std["currentness"] = std_currentness
                
                # 2. Gaps
                std_gaps = detect_gaps(std, query_understanding)
                std["potential_gaps"] = std_gaps

                # 3. Clean up before output
                if "embedding" in std:
                    del std["embedding"]
                
                # Collect aggregate info (from top 3)
                if len(output_recs) < 3:
                    for r in (std.get("related_standards") or []):
                        related_stds.add(r)
                    for t in (std.get("test_methods") or []):
                        test_methods.add(t)
                    for n in (std.get("normative_references") or []):
                        norm_refs.add(n)
                    if std.get("standard_type") == "Safety" or "safety" in (std.get("title") or "").lower():
                        safety_stds.add(std.get("is_number"))

                output_recs.append(std)

            # Check explicit references if any were found in the text
            explicit_refs = query_understanding.get("explicit_standard_refs") or []
            additional_currentness = {}
            for ref in explicit_refs[:3]:
                verdict = check_explicit_reference(ref, cited_year=None, standards=self.standards)
                if verdict:
                    additional_currentness[ref] = verdict

            # Overall confidence from top result
            top_confidence = output_recs[0].get("confidence", "low") if output_recs else "low"

            return {
                "query":                 query,
                "query_understanding":   query_understanding,
                "recommendations":       output_recs,
                "related_standards":     sorted(related_stds),
                "test_methods":          sorted(test_methods),
                "safety_standards":      sorted(s for s in safety_stds if s),
                "normative_references":  sorted(norm_refs),
                "additional_currentness": additional_currentness,
                "confidence":            top_confidence,
                "applicability_model_version": self.applicability_model.model_version if self.applicability_model else None,
            }

        except Exception as exc:
            logger.error("Recommendation pipeline failed for query '%s': %s", query[:80], exc)
            return {
                "error": f"Recommendation failed: {str(exc)}",
                "query": query,
            }
