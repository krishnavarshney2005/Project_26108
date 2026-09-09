"""
kartikey/analysis/requirement_extractor.py

Deterministic requirement extraction from tender document text.

Replaces the LLM-based extraction to ensure the critical path does not
depend on Gemini, preventing 120-second timeouts on complex or unrelated PDFs.
Combines explicit IS reference scanning with deterministic profile bucket extraction.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from shared.models import Requirement, RequirementCategory
from shared.utils import get_logger

from kartikey.analysis.profile_extractor import extract_profile
from kartikey.document_processing.extractor import scan_is_references, clause_at

logger = get_logger(__name__)

def extract_requirements(
    analysis_id: str,
    document_text: str,
    max_text_length: int = 150000,
) -> list[Requirement]:
    """
    Deterministically extract technical requirements from document text.
    """
    if not document_text or not document_text.strip():
        logger.warning("extract_requirements: empty document_text for analysis_id=%s", analysis_id)
        return []

    # 1. Deterministically extract profile buckets
    profile = extract_profile(document_text)

    # 2. Extract IS references directly
    is_refs = scan_is_references(document_text)

    # 3. Combine them into Requirement objects
    all_requirements: list[Requirement] = []
    seen_texts: set[str] = set()

    # Process explicit IS references first (highest confidence)
    for ref in is_refs:
        # Get the full sentence for the requirement, not just the isolated number
        text = clause_at(document_text, ref["char_offset"], len(ref["matched_text"]))
        normalized = text.strip().lower()
        if normalized in seen_texts:
            continue
        seen_texts.add(normalized)

        req = Requirement(
            id=str(uuid.uuid4()),
            analysis_id=analysis_id,
            text=text,
            normalized_text=text,
            category=RequirementCategory.TECHNICAL_SPECIFICATION,
            is_reference=ref["is_number"],
            cited_year=ref["year"],
            cited_designation=None,
            location=None,  # Could potentially extract context clause, but keep it simple
            extracted_at=datetime.now(tz=timezone.utc),
            extraction_confidence=0.95
        )
        all_requirements.append(req)

    # Process other buckets
    def add_from_bucket(bucket, category):
        for field in bucket:
            text = field.value
            normalized = text.strip().lower()
            if normalized in seen_texts:
                continue
            seen_texts.add(normalized)

            # Check if this bucket item happens to contain an IS reference
            bucket_refs = scan_is_references(text)
            is_ref = bucket_refs[0]["is_number"] if bucket_refs else None
            cited_year = bucket_refs[0]["year"] if bucket_refs else None

            req = Requirement(
                id=str(uuid.uuid4()),
                analysis_id=analysis_id,
                text=text,
                normalized_text=text,
                category=category,
                is_reference=is_ref,
                cited_year=cited_year,
                cited_designation=None,
                location=field.source_clause,
                extracted_at=datetime.now(tz=timezone.utc),
                extraction_confidence=0.85
            )
            all_requirements.append(req)

    add_from_bucket(profile.technical_parameters, RequirementCategory.TECHNICAL_SPECIFICATION)
    add_from_bucket(profile.performance_requirements, RequirementCategory.PERFORMANCE)
    add_from_bucket(profile.testing_requirements, RequirementCategory.TESTING)
    add_from_bucket(profile.regulatory_mentions, RequirementCategory.CERTIFICATION)

    logger.info(
        "extract_requirements: extracted %d requirements deterministically "
        "for analysis_id=%s", len(all_requirements), analysis_id
    )
    return all_requirements

