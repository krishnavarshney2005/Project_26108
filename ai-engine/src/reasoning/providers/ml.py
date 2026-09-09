import logging
from src.reasoning.providers.base import ReasoningProvider
from src.ml.applicability_model import get_applicability_model
from src.ml.applicability_features import build_applicability_features

logger = logging.getLogger(__name__)

class MLReasoner(ReasoningProvider):
    def analyze(self, req_text, req_type, standards, is_reference=None, cited_year=None):
        if not standards:
            return {
                "verdict": "unsupported",
                "reason": "No standard in the knowledge base covers this requirement's domain.",
                "action": "Review requirement for compliance with alternative domains.",
                "confidence": 0.0,
            }
        
        model = get_applicability_model()
        if not model:
            # If the model failed to load, fall back immediately
            raise RuntimeError("ApplicabilityModel is unavailable")

        best_score = -1.0
        best_std = None

        # IMPORTANT: rank-based features must be calculated against the COMPLETE
        # retrieved candidate set, not one candidate at a time. The trained model
        # expects embedding_cosine_sim_rank, bm25_score_rank, and rrf_rank to be
        # relative to the same candidate universe used for scoring.
        candidate_pairs = []
        for std in standards:
            candidate_pairs.append(
                (
                    std,
                    {
                        # Use the key expected by applicability_features.py.
                        "is_number": getattr(std, "is_number", ""),
                        "title": getattr(std, "title", ""),
                        "summary": "",
                        "scope": getattr(std, "scope", ""),
                        "search_text": getattr(std, "search_text", ""),
                        # Kshiraj's current retrieval contract exposes semantic_score
                        # and relevance_score, but not raw BM25/RRF. Keep BM25 missing
                        # as NaN and preserve the existing relevance_score -> rrf_score
                        # compatibility mapping.
                        "bm25_score": getattr(std, "bm25_score", float("nan")),
                        "semantic_score": getattr(std, "semantic_score", float("nan")),
                        "rrf_score": getattr(std, "relevance_score", float("nan")),
                    },
                )
            )

        all_candidates = [candidate for _, candidate in candidate_pairs]

        for std, candidate_dict in candidate_pairs:
            # The model must see the full candidate universe here. Passing
            # [candidate_dict] makes every candidate rank 1 and destroys the
            # relative-rank signals the model was trained on.
            try:
                features_df = build_applicability_features(
                    requirement_text=req_text,
                    candidate=candidate_dict,
                    all_candidates=all_candidates,
                )

                logger.debug(
                    "ML features for %s: %s",
                    getattr(std, "is_number", ""),
                    features_df.to_dict(orient="records"),
                )
                pred = model.predict(features_df)
                logger.debug(
                    "ML prediction for %s: %s",
                    getattr(std, "is_number", ""),
                    pred,
                )

                score = pred.get("applicability_score")
                if score is not None and score > best_score:
                    best_score = score
                    best_std = std
            except Exception as exc:
                logger.warning(
                    "ML feature extraction failed for standard %s: %s",
                    getattr(std, "is_number", ""),
                    exc,
                )
                
        if best_std and best_score >= 0.5:
            return {
                "verdict": "justified",
                "reason": f"The ML applicability model (v2) matched this requirement to {best_std.is_number} with a probability of {best_score:.2f}.",
                "action": "Requirement verified against applicable standard.",
                "confidence": best_score,
                "matched_is_number": best_std.is_number
            }
        elif best_std:
            return {
                "verdict": "requires_human_verification",
                "reason": f"The ML applicability model (v2) could not confidently match this requirement (best match {best_std.is_number} at {best_score:.2f}).",
                "action": "Manually verify specification.",
                "confidence": max(0.1, best_score),
                "matched_is_number": None
            }
        else:
            return {
                "verdict": "requires_human_verification",
                "reason": "The ML applicability model failed to score the candidates.",
                "action": "Manually verify specification.",
                "confidence": 0.0,
                "matched_is_number": None
            }
