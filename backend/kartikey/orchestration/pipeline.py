"""
kartikey/orchestration/pipeline.py

Analysis pipeline — the state machine that coordinates the full workflow.

State transitions:
    queued → extracting → retrieving → analyzing → enriching → completed
                                                              ↘ partially_completed
                                                              ↘ failed

This module is invoked as a FastAPI BackgroundTask (no Celery/Redis for MVP).
Each step calls into the appropriate subsystem:

  _step_extract   → kartikey/document_processing + AI/ML requirement extraction (Step 5)
  _step_retrieve  → kshiraj/knowledge/retrieval_service (Step 7)
  _step_analyze   → kshiraj/aiml_client (Step 6)
  _step_enrich    → kshiraj/enrichment + kartikey/analysis/findings (Step 7)

Step 4 (this step) focuses on:
  - Robust per-step error handling with PARTIAL_COMPLETED state
  - Correct state transitions even when sub-steps fail
  - Populating interim results (IS references from preliminary scan)
    so the frontend has something to show before full AI analysis is ready
  - Clear logging at every transition

IMPORTANT:
  The pipeline mutates the Analysis object in the shared store.
  The GET /analyses/{id} endpoint reads from the same store.
  This is safe in single-process uvicorn (the default for MVP).
  If multi-worker deployment is needed later, replace the in-memory
  store with a database-backed approach.
"""

from __future__ import annotations

import asyncio
import traceback
from collections.abc import Awaitable, Callable

from shared.models import Analysis, AnalysisStatus, InputType, Requirement, RequirementCategory
from shared.utils import AnalysisError, get_logger, utcnow

logger = get_logger(__name__)


# ===========================================================================
# Entry point — called by FastAPI BackgroundTasks
# ===========================================================================

async def run_analysis_pipeline(
    analysis_id: str,
    store: dict[str, Analysis],
    persist: Callable[[Analysis], Awaitable[None]] | None = None,
) -> None:
    """
    Coordinate the full analysis pipeline for one analysis job.

    Parameters
    ----------
    analysis_id:
        The ID of the analysis to run.
    store:
        Shared in-memory dict of analyses (keyed by analysis_id).
        Mutated in place as the pipeline progresses.
    """
    analysis = store.get(analysis_id)
    if not analysis:
        logger.error("Pipeline started for unknown analysis_id=%s — aborting.", analysis_id)
        return

    async def checkpoint() -> None:
        if persist is None:
            return
        try:
            await persist(analysis)
        except Exception as exc:
            logger.error("Could not persist analysis %s: %s", analysis.id, exc)

    logger.info(
        "Pipeline started: analysis_id=%s input_type=%s",
        analysis_id,
        analysis.input_type.value,
    )

    extracted_text: str = ""
    retrieved_standards: list = []
    aiml_response = None

    try:
        # ----------------------------------------------------------------
        # Step 1: Extract text + preliminary requirement scan
        # ----------------------------------------------------------------
        _transition(analysis, AnalysisStatus.EXTRACTING)
        await checkpoint()
        extracted_text = await _step_extract(analysis)

        # ----------------------------------------------------------------
        # Step 2: Retrieve relevant standards from knowledge base
        # ----------------------------------------------------------------
        _transition(analysis, AnalysisStatus.RETRIEVING)
        await checkpoint()
        retrieved_standards = await _step_retrieve(analysis, extracted_text)

        # ----------------------------------------------------------------
        # Step 3: AI/ML analysis
        # ----------------------------------------------------------------
        _transition(analysis, AnalysisStatus.ANALYZING)
        await checkpoint()
        aiml_response = await _step_analyze(analysis, extracted_text, retrieved_standards)

        # ----------------------------------------------------------------
        # Step 4: Enrich — version checks, QCO, compliance, findings assembly
        # ----------------------------------------------------------------
        _transition(analysis, AnalysisStatus.ENRICHING)
        await checkpoint()
        await _step_enrich(analysis, retrieved_standards, aiml_response)

        # ----------------------------------------------------------------
        # Finalize counts and mark completed
        # ----------------------------------------------------------------
        analysis.total_requirements = len(analysis.requirements)
        analysis.issues_found = sum(
            1 for f in analysis.findings
            if f.verdict.value != "justified"
        )

        # If we have requirements but zero findings, something partially failed
        if analysis.total_requirements > 0 and not analysis.findings:
            _transition(analysis, AnalysisStatus.PARTIALLY_COMPLETED)
            analysis.error_message = (
                "Requirements were extracted but analysis could not produce findings. "
                "This may be because the AI/ML or retrieval layer is not yet wired."
            )
        else:
            _transition(analysis, AnalysisStatus.COMPLETED)

        await checkpoint()

        logger.info(
            "Pipeline finished: analysis_id=%s status=%s requirements=%d issues=%d",
            analysis_id,
            analysis.status.value,
            analysis.total_requirements,
            analysis.issues_found,
        )

    except AnalysisError as exc:
        # Known, recoverable errors from our own code
        logger.error(
            "Pipeline failed [%s]: %s (analysis_id=%s)",
            exc.code, exc.message, analysis_id,
        )
        analysis.error_message = f"[{exc.code}] {exc.message}"
        _transition(analysis, AnalysisStatus.FAILED)
        await checkpoint()

    except Exception:
        # Unexpected errors — log full traceback, never let background task crash silently
        logger.error(
            "Pipeline unexpected failure for analysis_id=%s:\n%s",
            analysis_id,
            traceback.format_exc(),
        )
        analysis.error_message = "An unexpected internal error occurred."
        _transition(analysis, AnalysisStatus.FAILED)
        await checkpoint()


# ===========================================================================
# Pipeline steps
# ===========================================================================

async def _step_extract(analysis: Analysis) -> str:
    """
    Load the document text and run a preliminary IS reference scan.

    For TEXT input:   raw_text is used directly.
    For DOCUMENT input: loads the already-extracted text from storage.

    Interim result: populates analysis.requirements with candidate requirements
    found by the regex IS reference scanner. These are PRELIMINARY — they will
    be replaced by proper AI-extracted requirements in Step 5.
    The interim requirements allow the frontend to show something useful
    before the full AI analysis completes.

    Full AI requirement extraction is wired in Step 5.
    """
    # --- Load text ---
    if analysis.input_type == InputType.TEXT:
        if not analysis.raw_text or not analysis.raw_text.strip():
            raise AnalysisError(
                "Analysis has input_type=TEXT but raw_text is empty.",
                code="MISSING_INPUT",
            )
        extracted_text = analysis.raw_text
        logger.debug(
            "_step_extract: using raw_text (%d chars) for analysis_id=%s",
            len(extracted_text), analysis.id,
        )

    elif analysis.input_type == InputType.DOCUMENT:
        if not analysis.document_id:
            raise AnalysisError(
                "Analysis has input_type=DOCUMENT but document_id is missing.",
                code="MISSING_DOCUMENT_ID",
            )
        from kartikey.document_processing.storage import get_extracted_text
        extracted_text = get_extracted_text(analysis.document_id)
        if not extracted_text:
            raise AnalysisError(
                f"No extracted text found for document_id={analysis.document_id}. "
                "Ensure the document was uploaded successfully via POST /documents/upload.",
                code="NO_EXTRACTED_TEXT",
            )
        logger.debug(
            "_step_extract: loaded document text (%d chars) for document_id=%s",
            len(extracted_text), analysis.document_id,
        )
    else:
        raise AnalysisError(
            f"Unknown input_type: {analysis.input_type}",
            code="INVALID_INPUT_TYPE",
        )

    # --- AI-powered requirement extraction (Step 5) ---
    # Try the LLM extractor first. If unavailable (no API key / quota exhausted),
    # fall back to the regex IS reference scanner so the pipeline always produces
    # some output and doesn't hard-fail just because the LLM is unreachable.
    from kartikey.analysis.requirement_extractor import extract_requirements
    from kartikey.document_processing.extractor import scan_is_references
    from shared.utils import AnalysisError as _AnalysisError
    from shared.config import settings

    ai_extraction_succeeded = False
    try:
        ai_requirements = await asyncio.wait_for(
            asyncio.to_thread(
                extract_requirements,
                analysis_id=analysis.id,
                document_text=extracted_text,
            ),
            timeout=settings.aiml_timeout_seconds,
        )
        analysis.requirements = ai_requirements
        analysis.total_requirements = len(ai_requirements)
        ai_extraction_succeeded = True
        logger.info(
            "_step_extract: AI extraction succeeded — %d requirements found. analysis_id=%s",
            len(ai_requirements), analysis.id,
        )
    except asyncio.TimeoutError:
        logger.warning(
            "_step_extract: LLM extraction exceeded %ss; using regex fallback for analysis_id=%s.",
            settings.aiml_timeout_seconds,
            analysis.id,
        )
        analysis.metadata["extraction_fallback"] = True
        analysis.metadata["extraction_fallback_reason"] = "LLM_TIMEOUT"
    except _AnalysisError as exc:
        if exc.code in ("LLM_NOT_CONFIGURED", "LLM_QUOTA_EXHAUSTED", "LLM_NO_MODEL_AVAILABLE"):
            # LLM unavailable — fall back to regex scan gracefully
            logger.warning(
                "_step_extract: LLM unavailable (%s: %s). "
                "Falling back to regex IS reference scan for analysis_id=%s.",
                exc.code, exc.message, analysis.id,
            )
            analysis.metadata["extraction_fallback"] = True
            analysis.metadata["extraction_fallback_reason"] = exc.code
        else:
            # LLM responded but errored mid-extraction — re-raise to fail the pipeline
            raise

    # Regex fallback — runs when LLM is unavailable OR when LLM found zero requirements
    if not ai_extraction_succeeded or not analysis.requirements:
        is_refs = scan_is_references(extracted_text)
        if is_refs:
            logger.info(
                "_step_extract: regex scan found %d IS reference(s) as %s. analysis_id=%s",
                len(is_refs),
                "fallback" if not ai_extraction_succeeded else "supplement",
                analysis.id,
            )
            regex_requirements = [
                Requirement(
                    analysis_id=analysis.id,
                    text=ref["matched_text"],
                    normalized_text=ref["matched_text"],
                    category=RequirementCategory.TECHNICAL_SPECIFICATION,
                    is_reference=ref["is_number"],
                    cited_year=ref["year"],
                    cited_designation=ref["matched_text"],
                    extraction_confidence=0.6,
                )
                for ref in is_refs
            ]
            analysis.requirements = regex_requirements
            analysis.total_requirements = len(regex_requirements)
        else:
            logger.info(
                "_step_extract: no requirements found by AI or regex. analysis_id=%s",
                analysis.id,
            )

    return extracted_text




async def _step_retrieve(
    analysis: Analysis,
    extracted_text: str,
) -> list[Standard]:
    """
    Search the knowledge base for standards matching the extracted requirements.
    Delegates to the retrieval service for vector/lexical search.
    """
    await asyncio.sleep(0)

    if not analysis.requirements:
        logger.info(
            "_step_retrieve: no requirements to retrieve standards for. analysis_id=%s",
            analysis.id,
        )
        return []

    from kartikey.orchestration.knowledge_registry import get_registry
    from kshiraj.knowledge.retrieval_service import RetrievalQuery

    registry = get_registry()
    retrieved_standards: list[Standard] = []
    seen_ids: set[str] = set()

    # IS-number exact lookup pass
    for req in analysis.requirements:
        if not req.is_reference:
            continue
        matches = registry.standards_store.get_by_is_number(req.is_reference)
        for std in matches:
            if std.id not in seen_ids:
                seen_ids.add(std.id)
                # An explicit citation is a perfect match by definition
                std_copy = std.model_copy()
                std_copy.relevance_score = 1.0
                std_copy.semantic_score = 1.0
                retrieved_standards.append(std_copy)

    # Two-pass: collect all unique semantic candidates first (preserving best score per standard),
    # then sort globally by score descending before applying the global cap.
    # This ensures high-scoring standards from later requirements (e.g. IS 10242 at req 5 rank 1,
    # score=0.86) are not displaced by lower-scoring standards that happened to arrive earlier.
    semantic_scores: dict[str, float] = {}   # id -> best fused score seen
    semantic_stds: dict[str, object] = {}    # id -> Standard object

    for req in analysis.requirements:
        query_text = req.is_reference if req.is_reference else req.text
        query = RetrievalQuery(
            query_text=query_text,
            top_k=8,
            include_evidence=False,
        )

        result = registry.retrieval_service.search_standards(query)

        for candidate in result.candidates:
            sid = candidate.standard.id
            if sid in seen_ids:
                continue  # already added via exact-match pass; skip
            score = candidate.score or 0.0
            if sid not in semantic_scores or score > semantic_scores[sid]:
                semantic_scores[sid] = score
                candidate.standard.relevance_score = score
                semantic_stds[sid] = candidate.standard

    # Sort by best score descending, then extend exact-match list
    sorted_semantic = sorted(semantic_stds.values(), key=lambda s: semantic_scores[s.id], reverse=True)
    retrieved_standards.extend(sorted_semantic)

    logger.info(
        "_step_retrieve: found %d distinct standards across %d requirements. analysis_id=%s",
        len(retrieved_standards), len(analysis.requirements), analysis.id,
    )

    return retrieved_standards[:35]


# ===========================================================================
# 3. Analyze (Step 8)
# ===========================================================================

async def _step_analyze(
    analysis: Analysis,
    extracted_text: str,
    retrieved_standards: list[Standard],
) -> AimlResponse | None:
    """
    Send requirements + retrieved standards to the AI/ML component for analysis.
    """
    await asyncio.sleep(0)

    if not analysis.requirements:
        logger.info(
            "_step_analyze: no requirements to analyze. analysis_id=%s",
            analysis.id,
        )
        return None

    logger.info(
        "_step_analyze: starting AI analysis for %d requirements against %d standards. analysis_id=%s",
        len(analysis.requirements),
        len(retrieved_standards),
        analysis.id,
    )
    
    from shared.contracts import AimlRequest
    from kshiraj.aiml_client.client import AimlClient
    from shared.utils import AnalysisError as _AnalysisError
    from shared.config import settings
    
    request = AimlRequest(
        analysis_id=analysis.id,
        extracted_text=extracted_text,
        requirements=analysis.requirements,
        retrieved_standards=retrieved_standards,
    )
    
    try:
        client = AimlClient(timeout=settings.aiml_timeout_seconds)
        response = await client.run_analysis(request)
        analysis.metadata["analysis_mode"] = "remote" if not client.is_mock else "fallback"
        if client.is_mock:
            analysis.metadata["degraded_reason"] = "No AI/ML service is configured; deterministic analysis was used."
        return response
    except _AnalysisError as exc:
        logger.warning(
            "_step_analyze: AI/ML call failed (%s). "
            "Falling back to compliance-only logic. analysis_id=%s",
            exc.code, analysis.id,
        )
        analysis.metadata["analysis_mode"] = "fallback"
        analysis.metadata["degraded_reason"] = f"AI/ML service unavailable: {exc.message}"
        return None


# ===========================================================================
# 4. Enrich — Findings Assembly & Compliance Rules (Step 6/7)
# ===========================================================================

async def _step_enrich(
    analysis: Analysis,
    retrieved_standards: list[Standard],
    aiml_response: object,
) -> None:
    """
    Assemble final findings by merging AI/ML results with deterministic
    compliance checks against the retrieved standards.
    """
    await asyncio.sleep(0)

    from kartikey.orchestration.knowledge_registry import get_registry
    from kartikey.analysis.findings import assemble_findings
    from shared.models import StandardStatus

    registry = get_registry()

    # --- Live BIS Metadata Enrichment ---
    try:
        from kshiraj.bis_live_ingestion.adapters.bis_client import BISClient
        from kshiraj.bis_live_ingestion.sync import BISSyncService
        
        bis_client = BISClient()
        sync_service = BISSyncService(bis_client, registry.standards_store)
        
        # 1. Identify Explicitly Cited
        cited = {req.is_reference for req in analysis.requirements if getattr(req, "is_reference", None)}
        
        # 2. Identify Applicable/Final (Defensive parsing of aiml_response)
        aiml_applicable_ids = set()
        if aiml_response and hasattr(aiml_response, "findings"):
            findings_list = getattr(aiml_response, "findings", [])
            for f in findings_list:
                if getattr(f, "verdict", "") in ("justified", "applicable", "requires_human_verification"):
                    std_ids = getattr(f, "applicable_standard_ids", [])
                    if isinstance(std_ids, list):
                        aiml_applicable_ids.update(std_ids)
                        
        sync_count = 0
        for std in retrieved_standards:
            if sync_count >= 3:
                break
                
            needs_sync = False
            if std.is_number in cited:
                needs_sync = True
            elif getattr(std, "id", None) in aiml_applicable_ids:
                needs_sync = True
            elif getattr(std, "status", None) == StandardStatus.UNKNOWN:
                needs_sync = True
                
            if needs_sync:
                # Build exact canonical designation
                designation = std.is_number
                if std.part and std.section:
                    designation += f" ({std.part}/{std.section})"
                elif std.part:
                    designation += f" ({std.part})"
                if std.year:
                    designation += f":{std.year}"
                
                result = sync_service.sync_designation(designation)
                
                # Persist evidence
                if result.evidence:
                    for ev in result.evidence:
                        registry.evidence_store.upsert(ev)
                        
                sync_count += 1
                
        # Refresh retrieved_standards from the store so they reflect the merged data
        updated_stds = []
        for std in retrieved_standards:
            fresh = registry.standards_store.get_by_id(std.id)
            if fresh:
                fresh_copy = fresh.model_copy()
                fresh_copy.relevance_score = std.relevance_score
                fresh_copy.semantic_score = getattr(std, "semantic_score", None)
                updated_stds.append(fresh_copy)
            else:
                updated_stds.append(std)
        retrieved_standards = updated_stds
        
    except Exception as exc:
        import logging
        logging.getLogger(__name__).warning("Live BIS enrichment failed, continuing with offline catalog: %s", exc)
    # ------------------------------------

    # Pass lookup dicts to the assembler so it can resolve any ID the AI/ML returns
    # to a real object. This enforces the anti-hallucination guardrail.
    # Build from store first, then overlay retrieved copies — retrieved copies carry
    # the actual relevance_score from the retrieval pass, which flows through to the
    # API response and powers the frontend applicability score display.
    standards_lookup = {std.id: std for std in registry.standards_store.list_all()}
    for std in retrieved_standards:
        if std.id in standards_lookup and std.relevance_score is not None:
            standards_lookup[std.id] = std
    # We fetch all evidence here; a production DB would use IN queries.
    evidence_lookup = {ev.id: ev for ev in registry.evidence_store.list_all()}

    findings = assemble_findings(
        analysis=analysis,
        retrieved_standards=retrieved_standards,
        aiml_response=aiml_response,
        standards_lookup=standards_lookup,
        evidence_lookup=evidence_lookup,
    )
    analysis.findings = findings

    logger.info(
        "_step_enrich: assembled %d findings for analysis_id=%s "
        "(AI/ML wired=%s, retrieved_standards=%d)",
        len(findings),
        analysis.id,
        aiml_response is not None,
        len(retrieved_standards),
    )


# ===========================================================================
# Internal helpers
# ===========================================================================

def _transition(analysis: Analysis, new_status: AnalysisStatus) -> None:
    """Update analysis status and timestamp, and log the transition."""
    old = analysis.status.value
    analysis.status = new_status
    analysis.updated_at = utcnow()
    logger.info(
        "Analysis %s: %s → %s",
        analysis.id, old, new_status.value,
    )
