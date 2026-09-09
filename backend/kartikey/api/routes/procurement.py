import uuid
from datetime import datetime, timezone
from typing import Dict, Any, List

from fastapi import APIRouter, Request, HTTPException
from fastapi.responses import JSONResponse
import httpx

from shared.models import (
    Analysis, InputType, Requirement, Finding, Verdict, StandardStatus,
)
from shared.utils import get_logger, utcnow
from kartikey.analysis.query_quality import UnanalysableInputError, assess_query
from kartikey.orchestration.pipeline import _step_extract, _step_retrieve, _step_analyze, _step_enrich

logger = get_logger(__name__)

router = APIRouter(prefix="/procurement", tags=["procurement_bff"])

async def _extract_text_from_image(content: bytes, content_type: str) -> str:
    """Uses Gemini Vision to perform OCR on a physical tender document photo."""
    # We will reuse the genai client configured in the llm_client
    from kartikey.analysis.llm_client import get_llm_client
    client = get_llm_client()
    
    try:
        from google.genai import types
        # Create a Blob for the image
        image_part = types.Part.from_bytes(data=content, mime_type=content_type)
        
        prompt = "Extract all text verbatim from this scanned document. Do not summarize or add notes, just output the text."
        
        genai_client = client._get_client()
        model_name = client._resolve_model()
        
        # We need a model that supports vision. Flash does.
        response = genai_client.models.generate_content(
            model=model_name,
            contents=[image_part, prompt]
        )
        return response.text.strip()
    except Exception as e:
        logger.error(f"Image OCR failed: {e}")
        raise HTTPException(status_code=500, detail="Failed to run OCR on the provided image")


@router.post("/analyze")
async def analyze_procurement(request: Request) -> JSONResponse:
    """
    Backend-for-Frontend (BFF) Bridge Endpoint.
    Runs the full analysis pipeline synchronously and shapes the response 
    to exactly match the frontend's expected MOCK_LED_LIGHTING_DATA schema.
    """
    content_type = request.headers.get("Content-Type", "")
    
    raw_text = ""
    category_hint = "LED Street Lighting"
    
    if "application/json" in content_type:
        body = await request.json()
        raw_text = body.get("raw_text", "")
        category_hint = body.get("category_hint", category_hint)
    elif "multipart/form-data" in content_type:
        form = await request.form()
        category_hint = form.get("category_hint", category_hint)
        file = form.get("file")
        
        if file and hasattr(file, "filename"):
            content = await file.read()
            if file.content_type.startswith("image/"):
                raw_text = await _extract_text_from_image(content, file.content_type)
            else:
                import tempfile
                from pathlib import Path
                from kartikey.document_processing.extractor import extract_text
                
                with tempfile.NamedTemporaryFile(delete=False, suffix=Path(file.filename).suffix) as tmp:
                    tmp.write(content)
                    tmp_path = Path(tmp.name)
                
                try:
                    raw_text = extract_text(tmp_path)
                except Exception as e:
                    logger.error(f"Extraction failed: {e}")
                    raise HTTPException(status_code=400, detail=str(e))
                finally:
                    if tmp_path.exists():
                        tmp_path.unlink()
    
    if not raw_text or not raw_text.strip():
        raise HTTPException(status_code=400, detail="No text or valid file provided")

    # Quality gate, same one the /analyses route uses. This endpoint runs the
    # pipeline steps directly and synchronously, so without an explicit check
    # here noise would reach retrieval, the applicability model and Gemini while
    # the caller waited. It also covers the OCR path above, where a photographed
    # tender can come back as character soup.
    quality = assess_query(raw_text)
    if not quality.is_meaningful:
        logger.info(
            "Rejected /procurement/analyze input as not analysable (%s): signals=%s",
            quality.signals.get("reason"), quality.signals,
        )
        raise HTTPException(
            status_code=422,
            detail={
                "error": "NOT_A_PROCUREMENT_REQUIREMENT",
                "message": quality.message,
                "signals": quality.signals,
            },
        )

    # ---------------------------------------------------------
    # Pipeline Execution
    # ---------------------------------------------------------
    analysis_id = f"PROC-2026-LIVE-{str(uuid.uuid4())[:8].upper()}"
    analysis = Analysis(
        id=analysis_id,
        input_type=InputType.TEXT,
        raw_text=raw_text,
    )

    try:
        extracted_text = await _step_extract(analysis)
    except UnanalysableInputError:
        # Must not be swallowed by the broad handler below. _step_extract runs the
        # same gate a second time on the text it resolved, and if it fires there
        # the input is not analysable — falling back to "use the raw text" would
        # push the very input we just rejected on through the whole pipeline.
        raise
    except Exception as e:
        logger.warning(f"AI Extraction failed, using raw text: {e}")
        extracted_text = raw_text
        
    retrieved_standards = await _step_retrieve(analysis, extracted_text)
    aiml_response = await _step_analyze(analysis, extracted_text, retrieved_standards)
    await _step_enrich(analysis, retrieved_standards, aiml_response)
    
    # ---------------------------------------------------------
    # Format to Frontend Schema
    # ---------------------------------------------------------
    extracted_reqs: List[Dict[str, Any]] = []
    standards_intelligence_map = {}
    
    # Check if analysis has findings
    if not analysis.findings:
        # Nothing was assessed. This block used to answer with four 100s and
        # "No restrictive clauses found." — a clean bill of health for a tender
        # the system had in fact failed to analyse, which is the single most
        # misleading thing it could return. The scores are now declared
        # unassessed and the status says the analysis produced no findings.
        return JSONResponse(content={
            "procurement_id": analysis.id,
            "created_at": analysis.created_at.isoformat(),
            "status": "NO_FINDINGS",
            "input_summary": {
                "title": f"Procurement Document Analysis",
                "category": category_hint,
                "source_type": "Technical Document",
                "department": "External Upload",
                "total_specs_extracted": len(analysis.requirements),
                "overall_risk_score": "not_assessed",
                "qco_mandatory": None,
                "bis_crs_required": None,
                "standards_count": 0
            },
            "extracted_requirements": [],
            "standards_intelligence": [],
            "restrictiveness_analysis": {
                "overall_assessment": "not_assessed",
                "flagged_count": 0,
                "summary": (
                    "No requirements could be assessed against the standards "
                    "knowledge base, so no restrictiveness conclusion can be drawn."
                ),
                "counterfactuals": []
            },
            "pre_publication_summary": {
                "scorecard": {
                    "completeness_score": None,
                    "defensibility_score": None,
                    "regulatory_compliance_score": None,
                    "vendor_neutrality_score": None
                },
                "missing_recommendations": [],
                "defensibility_statement": (
                    analysis.summary
                    or "No findings were produced for this document."
                ),
            },
            "data_availability": {
                "extracted_requirements": (
                    "not_identified" if not analysis.requirements else "not_assessed"
                ),
                "standards_intelligence": "not_assessed",
                "restrictiveness_analysis": "not_assessed",
                "scorecard": "not_assessed",
            },
        })
        
    for i, f in enumerate(analysis.findings):
        status = "VALID"
        severity = "SUCCESS"
        if f.verdict in [Verdict.POTENTIALLY_OVER_RESTRICTIVE, Verdict.CONFLICTING]:
            status = "RESTRICTIVE_FLAG"
            severity = "WARNING"
        elif f.verdict in [Verdict.MISSING_REQUIREMENT, Verdict.INCORRECT_STANDARD]:
            status = "MISSING_STANDARD_REF"
            severity = "INFO"
        
        # Defaults are explicit unavailability states, not placeholders. The
        # confidence used to be a constant 0.9 and the page a constant 1 — both
        # asserted a precision the record did not have, on the one panel whose
        # whole purpose is to show where a claim came from. Every field below is
        # either overwritten from a real Evidence record or left saying it is
        # unavailable.
        ev_chain = {
            "standard_code": "not_identified",
            "standard_title": "not_identified",
            "clause": "not_available",
            "quote": "not_available",
            "page_number": None,
            "confidence": f.confidence,
            "provenance_source": "not_available",
        }
        qco_notified = False

        if f.applicable_standards:
            std = f.applicable_standards[0]
            ev_chain["standard_code"] = std.designation
            ev_chain["standard_title"] = std.title
            qco_notified = bool(getattr(std, "qco_notified", False))

            if std.id not in standards_intelligence_map:
                # Currentness comes from the enrichment layer's assessment of
                # this citation, not from a constant. It used to report "CURRENT"
                # unconditionally, which contradicted the finding beside it
                # whenever the analysis had just concluded the cited edition was
                # superseded — the report argued with itself.
                currentness = (f.dimensions or {}).get("currentness") or {}
                availability = f.data_availability or {}

                standards_intelligence_map[std.id] = {
                    "id": std.id,
                    "code": std.designation,
                    "title": std.title,
                    "current_version": str(std.year) if std.year else "not_available",
                    # StandardStatus defaults to UNKNOWN when the catalogue record
                    # carries no status, so UNKNOWN is reported as unavailable
                    # rather than as a status BIS actually publishes.
                    "status": (
                        std.status.value.upper()
                        if std.status and std.status != StandardStatus.UNKNOWN
                        else "not_available"
                    ),
                    "status_badge": currentness.get("label") or "not_assessed",
                    "currentness_note": currentness.get("note") or "not_assessed",
                    "relevance_score": f.confidence,
                    "is_qco_mandatory": getattr(std, 'qco_notified', False),
                    # Real amendment records where the catalogue has them. BIS
                    # publishes amendments per standard and most of our records
                    # carry none, so an empty list is stated as such rather than
                    # implying the standard has never been amended.
                    "amendments": [
                        {
                            "number": a.amendment_number,
                            "year": a.year or "not_available",
                            "description": a.description or "not_available",
                            "gazette_so_number": a.gazette_so_number or "not_available",
                        }
                        for a in std.amendments
                    ],
                    "amendments_availability": (
                        "verified" if std.amendments else "not_available"
                    ),
                    "supersedes": std.supersedes or "not_available",
                    "superseded_by": std.superseded_by or "not_available",
                    # The standards this one depends on, as the catalogue records
                    # them. Previously hardcoded empty; the enrichment layer
                    # reports which of these the tender fails to cite.
                    "normative_references": list(dict.fromkeys(
                        list(std.normative_references) + list(std.related_standards)
                    )),
                    # No source in this project publishes ISO/IEC equivalence
                    # mappings, so this is declared unavailable rather than
                    # reported as "Unknown", which reads like a lookup failure.
                    "international_equivalent": "not_available",
                    "source_url": std.source_url or "not_available",
                    "field_availability": std.field_availability or {},
                    "section_availability": availability,
                    # Kept at the top level, not only inside qco_details, so the
                    # summary below can derive the CRS flag from the catalogue
                    # rather than asserting it.
                    "required_certification_scheme": (
                        getattr(
                            std.required_certification_scheme, "value",
                            std.required_certification_scheme,
                        ) or "not_available"
                    ),
                    "qco_details": {
                        "order_name": (
                            std.qco_gazette_so_number
                            or "Quality Control Order"
                        ),
                        "issuing_authority": (
                            getattr(std, 'qco_issuing_ministry', None) or "not_available"
                        ),
                        "effective_date": (
                            std.qco_effective_date.isoformat()
                            if std.qco_effective_date else "not_available"
                        ),
                        "crs_mandatory": (
                            getattr(
                                std.required_certification_scheme, "value",
                                std.required_certification_scheme,
                            ) == "crs"
                        ),
                    } if getattr(std, 'qco_notified', False) else None
                }
            else:
                standards_intelligence_map[std.id]["relevance_score"] = max(standards_intelligence_map[std.id].get("relevance_score", 0), f.confidence)
                
        if f.evidence:
            primary_ev = f.evidence[0]
            ev_chain["clause"] = primary_ev.section or primary_ev.document_section or "not_available"
            ev_chain["quote"] = primary_ev.excerpt if primary_ev.excerpt else "not_available"
            # No page when the evidence is a catalogue record rather than a page
            # of a document. Saying so beats pointing the officer at page 1.
            ev_chain["page_number"] = primary_ev.page
            ev_chain["provenance_source"] = primary_ev.source_name or "not_available"
            ev_chain["provenance_authority"] = primary_ev.authority or "not_available"
            ev_chain["provenance_url"] = primary_ev.url or "not_available"
            if primary_ev.confidence is not None:
                ev_chain["confidence"] = primary_ev.confidence
        else:
            # The verdict's own reasoning is the only thing on record. It is
            # labelled as such so the UI does not present it as a sourced quote.
            ev_chain["quote"] = "not_available"
            ev_chain["provenance_source"] = "not_available"
            ev_chain["provenance_authority"] = "not_available"
            ev_chain["provenance_url"] = "not_available"

        ev_chain["availability"] = (
            (f.data_availability or {}).get("evidence") or "not_assessed"
        )

        req = next((r for r in analysis.requirements if r.id == f.requirement_id), None)
        req_text = req.text if req else f"Requirement {i+1}"
        req_category = req.category.value.title() if req and req.category else "General"
        
        extracted_reqs.append({
            "id": f.requirement_id,
            "parameter": req_category,
            "specified_value": req_text,
            "category": req_category,
            "status": status,
            "severity": severity,
            "compliance_status": f.verdict.value.replace("_", " ").title(),
            "issue_description": f.reason,
            # Carried so the counterfactual below can quote the analysis's own
            # recommendation instead of composing a new one.
            "recommended_action": f.recommended_action or "not_identified",
            "qco_notified": qco_notified,
            "evidence_chain": ev_chain
        })

    missing_recs = []
    counterfactuals = []

    for r in extracted_reqs:
        if r["status"] == "MISSING_STANDARD_REF":
            missing_recs.append({
                "title": f"Consider referencing {r['evidence_chain']['standard_code']}",
                "description": r["issue_description"]
            })
        elif r["status"] == "RESTRICTIVE_FLAG":
            counterfactuals.append({
                "id": f"cf-{r['id']}",
                "requirement_id": r["id"],
                "parameter": r["parameter"],
                "current_clause": r["specified_value"],
                "proposed_relaxation": r["recommended_action"],
                "why_flagged": r["issue_description"],
                # Only the two effects this project can actually derive.
                #
                # The other two that used to sit here — a "+45% wider supplier
                # eligibility" and an "Estimated 8-12% lower unit cost" — were
                # constants with no input: no supplier registry and no price data
                # exists anywhere in this system, so neither number could have
                # been computed for any tender. On a screen a procurement officer
                # may cite to justify relaxing a clause, an invented percentage is
                # the most damaging thing the report could contain. They are now
                # declared unavailable, which is the true statement.
                "impact_analysis": {
                    "standards_compliance": (
                        f"Relaxation stays within {r['evidence_chain']['standard_code']}"
                        if r["evidence_chain"]["standard_code"] != "not_identified"
                        else "not_assessed"
                    ),
                    "mandatory_qco_impact": (
                        "Cannot be relaxed below the QCO's mandatory floor — this "
                        "product is QCO-notified and BIS certification is compulsory"
                        if r["qco_notified"]
                        else "No QCO applies to the matched standard"
                    ),
                    "vendor_pool_expansion": "not_available",
                    "cost_saving_estimate": "not_available",
                }
            })

    response_data = {
        "procurement_id": analysis.id,
        "created_at": analysis.created_at.isoformat(),
        "status": "ANALYSIS_COMPLETE",
        "input_summary": {
            "title": f"Procurement Document Analysis",
            "category": category_hint,
            "source_type": "Technical Document",
            "department": "External Upload",
            "total_specs_extracted": len(analysis.requirements),
            "overall_risk_score": "MEDIUM" if counterfactuals else "LOW",
            "qco_mandatory": any(s["is_qco_mandatory"] for s in standards_intelligence_map.values()),
            # Was hardcoded True, so the report claimed BIS CRS registration was
            # required for every tender it ever saw — including ones where no
            # matched standard is under CRS at all.
            "bis_crs_required": any(
                s["required_certification_scheme"] == "crs"
                for s in standards_intelligence_map.values()
            ),
            "standards_count": len(standards_intelligence_map)
        },
        "extracted_requirements": extracted_reqs,
        "standards_intelligence": list(standards_intelligence_map.values()),
        "restrictiveness_analysis": {
            "overall_assessment": "POTENTIALLY_RESTRICTIVE" if counterfactuals else "ACCEPTABLE",
            "flagged_count": len(counterfactuals),
            "summary": f"{len(counterfactuals)} technical parameters contain potentially restrictive clauses.",
            "counterfactuals": counterfactuals
        },
        "pre_publication_summary": {
            "scorecard": {
                # Percentage of requirements that were matched to at least one
                # standard. This is a real derivable metric: 0 matched = 0%,
                # all matched = 100%. The old base of 90 was invented.
                "completeness_score": (
                    round(
                        100 * sum(
                            1 for f in analysis.findings if f.applicable_standards
                        ) / len(analysis.findings)
                    )
                    if analysis.findings else None
                ),
                # Percentage of requirements that carry no restrictive flag.
                # Deducts only for issues the analysis actually raised.
                # The old base of 95 was invented.
                "defensibility_score": (
                    round(
                        100 * (len(analysis.findings) - len(counterfactuals))
                        / len(analysis.findings)
                    )
                    if analysis.findings else None
                ),
                # Deducts for the regulatory gaps the analysis actually found: a
                # citation of a superseded edition, or a QCO-notified product whose
                # certification requirement the tender never states. It was a flat
                # 100, which scored a tender as fully compliant on the same screen
                # that listed its compliance failures.
                "regulatory_compliance_score": max(
                    0,
                    100
                    - 10 * sum(
                        1 for f in analysis.findings
                        if f.verdict is Verdict.OUTDATED_REFERENCE
                    )
                    - 10 * sum(
                        1 for f in analysis.findings
                        if (f.dimensions or {}).get("certification", {}).get("qco_notified")
                        and not (f.dimensions or {}).get("certification", {}).get(
                            "tender_states_requirement", True
                        )
                    ),
                ),
                "vendor_neutrality_score": max(0, 100 - (len(counterfactuals) * 10))
            },
            "missing_recommendations": missing_recs,
            # The pipeline's derived headline, counted from the findings this run
            # produced, rather than a fixed sentence that said nothing about them.
            "defensibility_statement": analysis.summary or "not_available",
        }
    }
    
    return JSONResponse(content=response_data)
