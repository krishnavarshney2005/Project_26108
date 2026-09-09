"""
kshiraj/knowledge/hybrid_retrieval.py

Hybrid retrieval service combining lexical BM25/keyword retrieval (RetrievalService)
and semantic vector retrieval (VectorStore + EmbeddingService).

Applies score normalization, weighted linear fusion, deduplication, and deterministic
candidate ranking without modifying existing RetrievalService interfaces.
"""

from __future__ import annotations

from typing import Dict, List, Optional, Union

from shared.models import Evidence, Standard, StandardStatus
from shared.utils import get_logger

from kshiraj.knowledge.embedding_service import EmbeddingService
from kshiraj.knowledge.evidence_store import EvidenceStore
from kshiraj.knowledge.retrieval_service import (
    CandidateStandard,
    RetrievalQuery,
    RetrievalResult,
    RetrievalService,
)
from kshiraj.knowledge.standards_store import StandardsStore
from kshiraj.knowledge.vector_store import VectorStore

logger = get_logger(__name__)


class HybridRetrievalService:
    """
    Hybrid retrieval layer fusing lexical score and vector semantic similarity.
    """

    def __init__(
        self,
        standards_store: StandardsStore,
        evidence_store: EvidenceStore,
        lexical_service: Optional[RetrievalService] = None,
        embedding_service: Optional[EmbeddingService] = None,
        vector_store: Optional[VectorStore] = None,
        lexical_weight: float = 0.4,
        vector_weight: float = 0.6,
    ) -> None:
        """
        Initialize HybridRetrievalService.

        Parameters
        ----------
        standards_store:
            Reference to primary StandardsStore repository.
        evidence_store:
            Reference to primary EvidenceStore repository.
        lexical_service:
            Optional RetrievalService instance (created if None).
        embedding_service:
            Optional EmbeddingService instance (created if None).
        vector_store:
            Optional VectorStore instance (created if None).
        lexical_weight:
            Weight for normalized lexical match score (default 0.4).
        vector_weight:
            Weight for normalized vector similarity score (default 0.6).
        """
        self.standards_store = standards_store
        self.evidence_store = evidence_store
        self.lexical_service = lexical_service or RetrievalService(standards_store, evidence_store)
        self.embedding_service = embedding_service or EmbeddingService()
        self.vector_store = vector_store or VectorStore()
        self.lexical_weight = lexical_weight
        self.vector_weight = vector_weight

    def index_standard(self, standard: Standard) -> None:
        """Create and store vector embedding for a single Standard model."""
        text = f"{standard.designation} {standard.title} {standard.scope or ''} {standard.technical_committee or ''}"
        try:
            vec = self.embedding_service.encode_text(text)
            self.vector_store.upsert_standards([standard], [vec])
        except Exception as exc:
            logger.warning("Failed to index standard %s in vector store: %s", standard.id, exc)

    def index_standards_batch(self, standards: List[Standard]) -> None:
        """Create and store vector embeddings for a list of Standard models."""
        if not standards:
            return
        texts = [
            f"{s.designation} {s.title} {s.scope or ''} {s.technical_committee or ''}"
            for s in standards
        ]
        try:
            vecs = self.embedding_service.encode_batch(texts)
            self.vector_store.upsert_standards(standards, vecs)
        except Exception as exc:
            logger.warning("Failed to batch index %s standards in vector store: %s", len(standards), exc)

    def index_evidence(self, evidence: Evidence) -> None:
        """Create and store vector embedding for a single Evidence model."""
        text = f"{evidence.source_name} {evidence.authority or ''} {evidence.excerpt}"
        try:
            vec = self.embedding_service.encode_text(text)
            self.vector_store.upsert_evidence([evidence], [vec])
        except Exception as exc:
            logger.warning("Failed to index evidence %s in vector store: %s", evidence.id, exc)

    def index_evidence_batch(self, evidence_items: List[Evidence]) -> None:
        """Create and store vector embeddings for a list of Evidence models."""
        if not evidence_items:
            return
        texts = [f"{e.source_name} {e.authority or ''} {e.excerpt}" for e in evidence_items]
        try:
            vecs = self.embedding_service.encode_batch(texts)
            self.vector_store.upsert_evidence(evidence_items, vecs)
        except Exception as exc:
            logger.warning("Failed to batch index %s evidence items in vector store: %s", len(evidence_items), exc)

    def search_standards(
        self,
        query: Union[str, RetrievalQuery],
        top_k: Optional[int] = None,
        status_filter: Optional[List[StandardStatus]] = None,
        include_evidence: bool = False,
    ) -> RetrievalResult:
        """
        Execute hybrid lexical + semantic retrieval.

        Parameters
        ----------
        query:
            Raw query string or structured RetrievalQuery object.
        top_k:
            Optional result truncation limit.
        status_filter:
            Optional list of allowed StandardStatus values.
        include_evidence:
            Whether to attach matching Evidence items to candidates.

        Returns
        -------
        RetrievalResult
            Fused, ranked candidate standards.
        """
        if isinstance(query, str):
            rq = RetrievalQuery(
                query_text=query,
                status_filter=status_filter,
                include_evidence=include_evidence,
                top_k=top_k,
            )
        else:
            rq = query

        q_text = rq.query_text.strip() if rq.query_text else ""
        effective_top_k = rq.top_k if rq.top_k is not None else top_k

        if not q_text:
            return RetrievalResult(query=rq, candidates=[], total_candidates=0)

        # 1. Execute Lexical Retrieval (with fallback safety)
        lex_candidates_by_id: Dict[str, CandidateStandard] = {}
        max_lex_score = 1.0
        try:
            lex_result = self.lexical_service.search_standards(rq)
            lex_candidates_by_id = {c.standard.id: c for c in lex_result.candidates}
            if lex_result.candidates:
                max_lex_score = max((c.score for c in lex_result.candidates), default=1.0)
                if max_lex_score <= 0:
                    max_lex_score = 1.0
        except Exception as exc:
            logger.warning("Lexical retrieval error, relying on vector search: %s", exc)

        # 2. Execute Vector Semantic Retrieval (with fallback safety)
        vector_hits: List[Dict[str, Any]] = []
        try:
            query_vec = self.embedding_service.encode_text(q_text)
            st_filter = rq.status_filter[0] if rq.status_filter and len(rq.status_filter) == 1 else None
            vector_hits = self.vector_store.search_standards(
                query_vector=query_vec,
                top_k=effective_top_k or 20,
                status_filter=st_filter,
            )
        except Exception as exc:
            logger.warning("Vector search failed or unavailable, falling back to lexical search: %s", exc)

        vector_scores_by_id: Dict[str, float] = {}
        for hit in vector_hits:
            std_id = hit.get("id")
            score = hit.get("score", 0.0)
            if std_id:
                vector_scores_by_id[std_id] = float(score)

        # Collect union of candidate standard IDs
        all_candidate_ids = set(lex_candidates_by_id.keys()).union(set(vector_scores_by_id.keys()))

        fused_candidates: List[CandidateStandard] = []

        for std_id in all_candidate_ids:
            std_obj = self.standards_store.get_by_id(std_id)
            if std_obj is None:
                continue

            # Check status filter if set
            if rq.status_filter is not None and std_obj.status not in rq.status_filter:
                continue

            # Lexical score
            lex_candidate = lex_candidates_by_id.get(std_id)
            raw_lex = lex_candidate.score if lex_candidate else 0.0
            norm_lex = min(1.0, max(0.0, raw_lex / max_lex_score))

            # Vector score (cosine similarity score is in [-1, 1], normalize to [0, 1])
            raw_vec = vector_scores_by_id.get(std_id, 0.0)
            norm_vec = min(1.0, max(0.0, (raw_vec + 1.0) / 2.0)) if raw_vec != 0.0 else 0.0

            # Fused score
            final_score = (self.lexical_weight * norm_lex) + (self.vector_weight * norm_vec)

            # Minimum similarity threshold to drop noise (e.g., out-of-domain queries 
            # dragging in the "least bad" candidates). Genuine matches typically score > 0.70.
            logger.info(f"Hybrid retrieval candidate: {std_obj.is_number} with final_score={final_score}, norm_vec={norm_vec}")
            if final_score < 0.45:
                continue

            matched_terms = lex_candidate.matched_terms if lex_candidate else []
            ev_list = lex_candidate.evidence if lex_candidate else []

            # Populate relevance_score on Standard copy
            std_copy = std_obj.model_copy()
            std_copy.relevance_score = round(final_score, 4)
            std_copy.semantic_score = round(norm_vec, 4)


            candidate = CandidateStandard(
                standard=std_copy,
                score=round(final_score, 4),
                matched_terms=matched_terms,
                evidence=ev_list,
            )
            fused_candidates.append(candidate)

        # Sort candidates descending by score, then is_number ascending for deterministic tie-breaking
        fused_candidates.sort(key=lambda c: (-c.score, c.standard.is_number))

        total_candidates = len(fused_candidates)
        if effective_top_k is not None:
            fused_candidates = fused_candidates[:effective_top_k]

        return RetrievalResult(
            query=rq,
            candidates=fused_candidates,
            total_candidates=total_candidates,
        )

    # Convenience alias for backwards compatibility
    def search(
        self,
        query: Union[str, RetrievalQuery],
        top_k: Optional[int] = None,
        status_filter: Optional[List[StandardStatus]] = None,
        include_evidence: bool = False,
    ) -> RetrievalResult:
        """Alias for search_standards."""
        return self.search_standards(
            query=query,
            top_k=top_k,
            status_filter=status_filter,
            include_evidence=include_evidence,
        )
