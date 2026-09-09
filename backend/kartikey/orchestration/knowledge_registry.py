"""
kartikey/orchestration/knowledge_registry.py

Singleton registry that holds the shared knowledge store instances.

This module is the bridge between Kartikey's pipeline and Kshiraj's knowledge layer.
It creates and owns the StandardsStore, EvidenceStore, and RetrievalService
instances used across the entire application.

Why a registry (not DI / FastAPI Depends):
  - The stores are stateful (in-memory dict with lock)
  - They must be shared across the pipeline BackgroundTask AND the API routes
  - FastAPI Depends creates new instances per-request, which breaks shared state
  - A module-level singleton is the correct pattern for shared in-memory state
    in a single-process FastAPI application (our MVP deployment model)

Initialization:
  - Call `initialize_knowledge_registry()` at FastAPI startup
  - This loads seed data into the stores
  - After that, `get_registry()` returns the populated instance

Production path (post-hackathon):
  - Replace in-memory stores with DB-backed implementations
  - Keep this registry — just swap the store implementations
  - The pipeline and API routes don't need to change
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from shared.utils import get_logger

logger = get_logger(__name__)


@dataclass
class KnowledgeRegistry:
    """
    Holds singleton instances of the knowledge layer components.
    All fields are set during initialization and are read-only after that.
    """
    standards_store: object   # StandardsStore
    evidence_store: object    # EvidenceStore
    retrieval_service: object # RetrievalService
    retrieval_mode: str = "lexical"
    retrieval_reason: str | None = None


# Module-level singleton — None until initialize_knowledge_registry() is called
_registry: KnowledgeRegistry | None = None


def _as_str_list(value: object) -> list[str]:
    """
    Coerce a catalogue list field to a list of clean strings.

    Anything that isn't a usable string is dropped rather than crashing the whole
    load — one malformed record must not cost us the other thousand.
    """
    if not isinstance(value, list):
        return []
    return [item.strip() for item in value if isinstance(item, str) and item.strip()]


def _parse_date(value: object):
    """Parse an ISO date from the catalogue, returning None on anything unusable."""
    from datetime import date as _date

    if isinstance(value, str) and value.strip():
        try:
            return _date.fromisoformat(value.strip()[:10])
        except ValueError:
            logger.debug("Unparseable date in catalogue: %r", value)
    return None


def _standard_from_catalogue(item: dict):
    """
    Build a Standard from one reconciled-catalogue record.

    Every field here is copied, never derived. The catalogue already applied the
    provenance filter (see shared/build_reconciled_catalogue.py) and recorded the
    outcome in `field_availability`, so this function's only job is to not lose
    anything on the way in. In particular it does not substitute a default for a
    `not_available` field — that state travels all the way to the API.
    """
    from shared.models import (
        CertificationScheme, DocumentType, Standard, StandardStatus,
    )

    currentness = item.get("currentness") or {}
    certification = item.get("certification") or {}

    scheme_value = certification.get("scheme")
    try:
        scheme = CertificationScheme(scheme_value) if scheme_value else None
    except ValueError:
        logger.debug("Unknown certification scheme %r in catalogue", scheme_value)
        scheme = CertificationScheme.OTHER

    try:
        status = StandardStatus(currentness.get("status") or "unknown")
    except ValueError:
        status = StandardStatus.UNKNOWN

    try:
        document_type = DocumentType(item.get("document_type") or "other")
    except ValueError:
        document_type = DocumentType.OTHER

    # A QCO is a certification mandate, so it is only asserted when the catalogue
    # verified the certification block. `qco` here is the order reference BIS
    # published ("QCO 2020"), which is why it lands in the gazette field.
    qco_notified = bool(certification.get("mandatory"))

    import hashlib
    is_num_str = item.get("is_number") or ""
    std_year = item.get("year")
    std_id = item.get("id")
    if not std_id:
        canonical_key = f"{is_num_str}:{std_year}" if std_year else is_num_str
        h = hashlib.md5(canonical_key.encode("utf-8") if canonical_key else b"unknown").hexdigest()
        std_id = f"{h[:8]}-{h[8:12]}-{h[12:16]}-{h[16:20]}-{h[20:]}"

    return Standard(
        id=std_id,
        is_number=is_num_str,
        year=item.get("year"),
        title=item.get("title") or "",
        # Prefer the one-line summary for retrieval and display where the source
        # provides one; the full scope stays available in the record.
        scope=item.get("scope"),
        document_type=document_type,

        normative_references=_as_str_list(item.get("normative_references")),
        related_standards=_as_str_list(item.get("related_standards")),

        keywords=_as_str_list(item.get("keywords")),
        product_categories=_as_str_list(item.get("product_categories")),
        test_methods=_as_str_list(item.get("test_methods")),

        status=status,
        supersedes=currentness.get("supersedes"),
        superseded_by=currentness.get("superseded_by"),
        latest_known_edition=currentness.get("latest_known_edition"),
        latest_known_year=currentness.get("latest_known_year"),

        qco_notified=qco_notified,
        qco_gazette_so_number=certification.get("qco"),
        qco_issuing_ministry=certification.get("source") if qco_notified else None,
        qco_effective_date=_parse_date(certification.get("qco_effective_date")),
        required_certification_scheme=scheme,

        source_url=(item.get("provenance") or {}).get("url") or "https://standardsbis.gov.in",
        provenance=item.get("provenance"),
        field_availability=item.get("field_availability") or {},
        retrieved_at=date.today(),
    )



def get_registry() -> KnowledgeRegistry:
    """Return the initialized knowledge registry."""
    if _registry is None:
        raise RuntimeError(
            "Knowledge registry has not been initialized. "
            "Call initialize_knowledge_registry() at application startup."
        )
    return _registry


def initialize_knowledge_registry() -> KnowledgeRegistry:
    """
    Initialize the knowledge registry with empty stores and wire up the retrieval service.

    Called once at FastAPI startup (see kartikey/api/main.py).
    After this call, get_registry() returns the populated registry.
    """
    global _registry

    import os
    import json
    from kshiraj.knowledge.standards_store import StandardsStore
    from kshiraj.knowledge.evidence_store import EvidenceStore
    from kshiraj.knowledge.retrieval_service import RetrievalService
    from kshiraj.knowledge.embedding_service import EmbeddingService
    from kshiraj.knowledge.vector_store import VectorStore
    from kshiraj.knowledge.hybrid_retrieval import HybridRetrievalService
    from shared.config import settings

    standards_store = StandardsStore()
    evidence_store = EvidenceStore()

    # 1. Load the reconciled catalogue.
    #
    # This is the canonical real-data catalogue, built from the BIS standards
    # catalogue + the ai-engine knowledge base + the curated additions by
    # shared/build_reconciled_catalogue.py. It supersedes bis_full_catalog_1015.json,
    # which carried no scope, no cross-references and no certification data for any
    # of its 1015 records, and was missing the IS 10322 / IS 1944 parts entirely.
    #
    # Regenerate with:  .venv/bin/python -m shared.build_reconciled_catalogue
    dataset_path = os.path.join(
        os.path.dirname(__file__), "../../shared/bis_catalogue_reconciled.json",
    )
    standards_list = []

    if os.path.exists(dataset_path):
        logger.info("Loading reconciled BIS catalogue from %s", dataset_path)
        with open(dataset_path, "r", encoding="utf-8") as f:
            data = json.load(f)

        skipped = 0
        for item in data:
            try:
                std = _standard_from_catalogue(item)
            except Exception as exc:
                # One bad record must not cost us the catalogue.
                skipped += 1
                logger.warning(
                    "Skipping catalogue record %r: %s", item.get("is_number"), exc,
                )
                continue
            if not std.is_number or not std.title:
                skipped += 1
                continue
            standards_list.append(std)
            standards_store.add(std)

        with_scope = sum(1 for s in standards_list if s.scope)
        with_refs = sum(
            1 for s in standards_list if s.normative_references or s.related_standards
        )
        with_cert = sum(1 for s in standards_list if s.qco_notified)
        logger.info(
            "Loaded %d standards into StandardsStore "
            "(scope=%d, cross-references=%d, certification=%d, skipped=%d).",
            len(standards_list), with_scope, with_refs, with_cert, skipped,
        )

    else:
        logger.warning(f"BIS dataset not found at {dataset_path}")

    # 2. Initialize Lexical Retrieval
    lexical_service = RetrievalService(
        standards_store=standards_store,
        evidence_store=evidence_store,
    )

    # 3. Initialize semantic retrieval when its optional runtime is available.
    # Lexical retrieval is already a complete fallback and must keep the API
    # bootable when Qdrant, sentence-transformers, or model assets are absent.
    retrieval_service = lexical_service
    retrieval_mode = "lexical"
    retrieval_reason = "Semantic retrieval is not initialized."
    if settings.semantic_retrieval_enabled:
      try:
        embedding_service = EmbeddingService(model_name="BAAI/bge-small-en-v1.5")
        vector_store = VectorStore(dimension=embedding_service.dimension)

        if standards_list:
            logger.info("Indexing standards in VectorStore (this may take a few seconds)...")
            vector_store.create_collections_if_needed()

            batch_size = 100
            for i in range(0, len(standards_list), batch_size):
                batch = standards_list[i:i + batch_size]
                texts = [f"{s.is_number} {s.title} {s.scope}" for s in batch]
                embeddings = embedding_service.encode_batch(texts)
                vector_store.upsert_standards(batch, embeddings)
            logger.info("VectorStore indexing complete.")

        retrieval_service = HybridRetrievalService(
            standards_store=standards_store,
            evidence_store=evidence_store,
            lexical_service=lexical_service,
            embedding_service=embedding_service,
            vector_store=vector_store,
            lexical_weight=0.4,
            vector_weight=0.6,
        )
        retrieval_mode = "hybrid"
        retrieval_reason = None
      except Exception as exc:
        logger.warning(
            "Semantic retrieval is unavailable (%s); using lexical retrieval.",
            exc,
        )
        retrieval_reason = str(exc)
    else:
        retrieval_reason = "Semantic retrieval is disabled; set SEMANTIC_RETRIEVAL_ENABLED=true after preparing the embedding model."

    _registry = KnowledgeRegistry(
        standards_store=standards_store,
        evidence_store=evidence_store,
        retrieval_service=retrieval_service,
        retrieval_mode=retrieval_mode,
        retrieval_reason=retrieval_reason,
    )

    logger.info("Knowledge registry initialized.")
    return _registry
