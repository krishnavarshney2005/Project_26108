"""
kartikey/api/routes/simulator.py

Impact Simulator API (Step 9).

This endpoint allows procurement officers to perform "What-If" analysis:
"What happens if I remove this strict requirement?"
"What happens if I change IP65 to IP66?"

The simulator looks at the proposed change and:
1. If REMOVING a requirement: Checks if that requirement was tied to a mandatory QCO.
   If yes, warns the officer that removing it makes the tender non-compliant.
2. If MODIFYING a requirement: Re-runs the AI analysis on the new text against
   the knowledge base to see if the new requirement is supported by standards.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone

from fastapi import APIRouter, BackgroundTasks, HTTPException, Path
from pydantic import BaseModel, Field

from shared.models import (
    Analysis,
    Requirement,
    SimulationScenario,
)
from shared.utils import get_logger, utcnow
from kartikey.api.routes.analyses import repository
from kartikey.orchestration.knowledge_registry import get_registry

logger = get_logger(__name__)
router = APIRouter(prefix="/analyses", tags=["simulator"])


class SimulateRequest(BaseModel):
    requirement_id: str
    change_type: str = Field(..., description="'remove' or 'modify'")
    modified_text: str | None = Field(None, description="Required if change_type is 'modify'")


@router.post("/{analysis_id}/simulate", response_model=SimulationScenario)
async def run_simulation(
    request: SimulateRequest,
    background_tasks: BackgroundTasks,
    analysis_id: str = Path(..., description="ID of the completed analysis"),
) -> SimulationScenario:
    """
    Run a simulation to evaluate the impact of changing or removing a requirement.
    
    This is highly valuable for procurement officers to justify their decisions
    (e.g., rejecting a supplier's request to relax a requirement because it violates a QCO).
    """
    analysis = await repository.get(analysis_id)
    if not analysis:
        raise HTTPException(status_code=404, detail="Analysis not found")
        
    if analysis.status.value != "completed":
        raise HTTPException(
            status_code=400, 
            detail="Can only run simulations on completed analyses."
        )

    # Find the original requirement and its finding
    original_req = next((r for r in analysis.requirements if r.id == request.requirement_id), None)
    if not original_req:
        raise HTTPException(status_code=404, detail="Requirement not found in this analysis")

    original_finding = next((f for f in analysis.findings if f.requirement_id == request.requirement_id), None)

    # Create the scenario record
    scenario = SimulationScenario(
        analysis_id=analysis_id,
        requirement_id=request.requirement_id,
        change_type=request.change_type,
        modified_text=request.modified_text,
        status="completed",  # For MVP, we run it synchronously if fast enough, or async. Let's do it inline for speed.
    )

    registry = get_registry()

    if request.change_type == "remove":
        # Simulate removing the requirement
        # Check if the original finding was enforcing a mandatory QCO
        was_mandatory = False
        qco_info = None
        
        if original_finding and original_finding.currentness and original_finding.currentness.get("qco_notified"):
            was_mandatory = True
            qco_info = original_finding.currentness.get("qco_issuing_ministry") or "Government Authority"

        if was_mandatory:
            scenario.impact_summary = (
                "CRITICAL VIOLATION: Removing this requirement would violate a mandatory "
                f"Quality Control Order (QCO) issued by {qco_info}. "
                "Suppliers are legally required to hold BIS certification for this product. "
                "Removing this clause makes the tender non-compliant."
            )
            scenario.mandatory_violations.append("QCO_VIOLATION")
        else:
            scenario.impact_summary = (
                "SAFE TO REMOVE: This requirement is not tied to any mandatory government QCO. "
                "Removing it may expand the supplier base and increase competition, "
                "but you should verify it does not compromise operational performance."
            )
            
    elif request.change_type == "modify":
        if not request.modified_text:
            raise HTTPException(status_code=400, detail="modified_text is required for 'modify' change_type")
            
        # For modification, we need to re-run the pipeline logic for this single requirement.
        # To avoid duplicating pipeline logic, we'll invoke the AI/ML client directly.
        from shared.contracts import AimlRequest
        from kshiraj.aiml_client.client import AimlClient
        from kartikey.analysis.findings import assemble_findings
        
        # 1. Create a dummy requirement
        sim_req = Requirement(
            analysis_id=analysis_id,
            text=request.modified_text,
            category=original_req.category,  # assume same category
        )
        
        # 2. Retrieve standards for the new text
        from kshiraj.knowledge.retrieval_service import RetrievalQuery
        query = RetrievalQuery(query_text=request.modified_text, top_k=3, include_evidence=False)
        result = registry.retrieval_service.search_standards(query)
        retrieved_stds = [c.standard for c in result.candidates]
        
        # 3. Analyze with AI
        aiml_req = AimlRequest(
            analysis_id=analysis_id,
            extracted_text=analysis.raw_text or "",
            requirements=[sim_req],
            retrieved_standards=retrieved_stds,
        )
        
        try:
            client = AimlClient()
            aiml_resp = await client.run_analysis(aiml_req)
            
            # 4. Enrich
            standards_lookup = {std.id: std for std in registry.standards_store.list_all()}
            evidence_lookup = {ev.id: ev for ev in registry.evidence_store.list_all()}
            
            # We mock a small Analysis object to pass to assemble_findings
            mock_analysis = Analysis(id=analysis_id, input_type=analysis.input_type)
            mock_analysis.requirements = [sim_req]
            
            sim_findings = assemble_findings(
                analysis=mock_analysis,
                retrieved_standards=retrieved_stds,
                aiml_response=aiml_resp,
                standards_lookup=standards_lookup,
                evidence_lookup=evidence_lookup,
            )
            
            scenario.affected_findings = sim_findings
            
            if sim_findings:
                f = sim_findings[0]
                if f.verdict.value == "justified":
                    scenario.impact_summary = "ACCEPTABLE MODIFICATION: The new requirement is supported by current active standards."
                elif f.verdict.value in ["outdated_reference", "incorrect_standard"]:
                    scenario.impact_summary = f"RISKY MODIFICATION: The new text cites problematic standards ({f.verdict.value})."
                else:
                    scenario.impact_summary = f"UNCLEAR IMPACT: The modification resulted in '{f.verdict.value}'. Verify with technical team."
            else:
                scenario.impact_summary = "Could not generate findings for the modified requirement."
                
        except Exception as e:
            logger.error("Simulation modification failed: %s", e)
            scenario.status = "failed"
            scenario.impact_summary = f"Simulation failed during AI evaluation: {str(e)}"
    
    else:
        raise HTTPException(status_code=400, detail=f"Unknown change_type: {request.change_type}")

    # Note: In MVP we don't persist scenarios, but in a real app we'd save it to the DB here.
    return scenario
