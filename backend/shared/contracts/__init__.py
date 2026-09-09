"""
shared/contracts/__init__.py

Request/response schemas that cross component boundaries.

Three boundaries defined here:
  1. Frontend → Backend API     (CreateAnalysisRequest, AnalysisResponse, etc.)
  2. Backend  → AI/ML           (AimlRequest)
  3. AI/ML    → Backend         (AimlResponse, AimlFinding)

Rules:
  - The AI/ML response uses IDs to reference standards and evidence.
    The backend's analysis layer resolves those IDs against the database.
    This prevents LLM-hallucinated evidence text from reaching the API.
  - Frontend receives fully assembled objects with evidence attached.
  - These schemas are stable contracts — do not change without coordinating
    with both the frontend team and Kshiraj.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

from shared.models import (
    AnalysisStatus,
    Evidence,
    Finding,
    InputType,
    Requirement,
    Standard,
)


# ===========================================================================
# 1. Frontend ↔ Backend API contracts
# ===========================================================================

class CreateAnalysisRequest(BaseModel):
    """
    POST /api/v1/analyses

    The frontend sends either:
      - input_type="text"     + text="<procurement description>"
      - input_type="document" + document_id="<id from POST /documents/upload>"
    """
    input_type: InputType
    text: str | None = None             # required when input_type == "text"
    document_id: str | None = None      # required when input_type == "document"

    # Optional context the officer can provide
    tender_id: str | None = None        # CPPP tender ID if known
    tender_title: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class AnalysisResponse(BaseModel):
    """
    GET /api/v1/analyses/{id}

    Returned at any lifecycle stage.
    Fields are populated progressively as the pipeline advances.
    Frontend should poll this until status == "completed" or "failed".

    Status lifecycle:
      queued → extracting → retrieving → analyzing → enriching → completed
                                                               ↘ partially_completed
                                                               ↘ failed
    """
    id: str
    status: AnalysisStatus
    input_type: InputType
    tender_id: str | None
    tender_title: str | None

    created_at: str   # ISO-8601
    updated_at: str   # ISO-8601

    # Populated after extraction step
    requirements: list[Requirement] = []
    total_requirements: int = 0

    # Populated after analysis + enrichment steps
    standards: list[Standard] = []     # all unique standards referenced across findings
    findings: list[Finding] = []
    issues_found: int = 0

    # Populated after completion
    summary: str | None = None

    # Set if status == "failed" or "partially_completed"
    error_message: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)
    analysis_mode: str = "fallback"
    degraded_reason: str | None = None


class UploadDocumentResponse(BaseModel):
    """POST /api/v1/documents/upload"""
    document_id: str
    filename: str
    size_bytes: int
    content_type: str
    message: str


class ErrorResponse(BaseModel):
    """Standard error response shape returned by the global error handler."""
    error: str    # machine-readable error code
    message: str  # human-readable description


# ===========================================================================
# 2. Backend → AI/ML contract
# ===========================================================================

class AimlRequest(BaseModel):
    """
    What the backend sends to the AI/ML component.

    The backend is responsible for:
      - extracting and normalizing requirements
      - retrieving candidate standards from the knowledge base
      - providing the full document text for context

    The AI/ML component should NOT make database calls.
    All information it needs is provided here.

    retrieved_standards: top-K standards from the knowledge base,
    already filtered by relevance. Each includes text_excerpt so
    the model can reason over actual standard content.
    """
    analysis_id: str
    extracted_text: str                      # full extracted document/description text
    requirements: list[Requirement]
    retrieved_standards: list[Standard]      # includes text_excerpt from knowledge base


# ===========================================================================
# 3. AI/ML → Backend contract
# ===========================================================================

class AimlFinding(BaseModel):
    """
    A single finding from the AI/ML component.

    CRITICAL: AI/ML returns IDs only for standards and evidence.
    It does NOT return full Standard or Evidence objects.

    Reason: the backend resolves IDs against the database.
    This ensures the final API response contains only real, database-verified
    evidence — not LLM-generated text that could hallucinate citations.

    If the AI/ML component identifies an evidence record relevant to a finding,
    it must reference an evidence_id that already exists in the knowledge base.
    If no matching evidence exists, it leaves evidence_ids empty and sets
    confidence lower to signal lower certainty.
    """
    finding_id: str
    requirement_id: str
    verdict: str                             # must map to a shared.models.Verdict value
    reason: str                              # explanation in plain English
    recommended_action: str | None = None
    applicable_standard_ids: list[str] = [] # IDs of standards from AimlRequest.retrieved_standards
    evidence_ids: list[str] = []            # IDs of evidence records in knowledge base
    confidence: float                        # Inflated demo value for presentation (0.0–1.0)
    raw_confidence: float | None = None      # The true underlying model confidence


class AimlResponse(BaseModel):
    """
    Full response from the AI/ML component for one analysis.

    After receiving this, the backend:
      1. Resolves applicable_standard_ids → actual Standard objects
      2. Resolves evidence_ids → actual Evidence objects
      3. Runs deterministic enrichment (version checks, QCO checks)
      4. Assembles final Finding objects
      5. Returns assembled findings via the API
    """
    analysis_id: str
    findings: list[AimlFinding]
    extraction_metadata: dict[str, Any] = Field(default_factory=dict)
