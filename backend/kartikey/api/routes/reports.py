"""
kartikey/api/routes/reports.py

GET /api/v1/analyses/{id}/report

Exports a completed analysis as a structured report (JSON or eventually PDF).
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException

from kartikey.api.routes.analyses import repository
from shared.contracts import AnalysisResponse
from shared.utils import get_logger

logger = get_logger(__name__)
router = APIRouter(prefix="/analyses", tags=["reports"])


@router.get("/{analysis_id}/report")
async def get_report(analysis_id: str) -> dict:
    """
    Export a completed analysis as a structured report.

    This is a placeholder for Step 9 (Report Generation).
    Eventually, this might return a PDF buffer or a heavily formatted JSON
    tailored for printing/downloading.
    """
    analysis = await repository.get(analysis_id)
    if not analysis:
        # This used to fall through to three hardcoded reports for the frontend's
        # mock IDs (an-001 / an-hindi / an-tamil), with invented standards and
        # findings — including a "compliant" verdict that is not in the Verdict
        # enum. Any unknown ID now 404s, which is the honest answer: a report is a
        # document a procurement officer may put in a tender file, and one that
        # was never produced by an analysis has no business being served.
        raise HTTPException(
            status_code=404,
            detail={
                "error": "ANALYSIS_NOT_FOUND",
                "message": f"No analysis found with id '{analysis_id}'.",
            },
        )

    if analysis.status not in {"completed", "partially_completed"}:
        raise HTTPException(
            status_code=400,
            detail={
                "error": "ANALYSIS_NOT_COMPLETED",
                "message": f"Cannot generate report for analysis in state '{analysis.status}'.",
            },
        )

    standards = []
    seen_standard_ids: set[str] = set()
    for finding in analysis.findings:
        for standard in finding.applicable_standards:
            if standard.id not in seen_standard_ids:
                standards.append(standard)
                seen_standard_ids.add(standard.id)

    return {
        "report_type": "procurement_compliance_report",
        "generated_at": analysis.updated_at.isoformat(),
        "analysis": AnalysisResponse(
            id=analysis.id,
            status=analysis.status,
            input_type=analysis.input_type,
            tender_id=analysis.tender_id,
            tender_title=analysis.tender_title,
            created_at=analysis.created_at.isoformat(),
            updated_at=analysis.updated_at.isoformat(),
            requirements=analysis.requirements,
            total_requirements=analysis.total_requirements,
            standards=standards,
            findings=analysis.findings,
            issues_found=analysis.issues_found,
            summary=analysis.summary,
            error_message=analysis.error_message,
            metadata=analysis.metadata,
            analysis_mode=analysis.metadata.get("analysis_mode", "fallback"),
            degraded_reason=analysis.metadata.get("degraded_reason"),
        ).model_dump(mode="json"),
    }

from fastapi import Response
from kartikey.api.reports_generator import generate_pdf_report

@router.get("/{analysis_id}/report/pdf")
async def get_pdf_report(analysis_id: str):
    """
    Export a completed analysis as a PDF report buffer.
    """
    json_report = await get_report(analysis_id)
    analysis_data = json_report["analysis"]
    
    pdf_bytes = generate_pdf_report(analysis_data)
    
    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={
            "Content-Disposition": f'attachment; filename="StandIQ-Report-{analysis_id}.pdf"'
        }
    )

import os
import httpx

@router.post("/{analysis_id}/report/email")
async def email_pdf_report(analysis_id: str):
    """
    Generate the PDF report and email it via the n8n webhook.
    """
    json_report = await get_report(analysis_id)
    analysis_data = json_report["analysis"]
    
    # 1. Generate PDF bytes
    pdf_bytes = generate_pdf_report(analysis_data)
    
    # 2. Extract metadata
    tender_title = analysis_data.get("tender_title", "Untitled Analysis")
    tender_id = analysis_data.get("tender_id") or analysis_id
    status = analysis_data.get("status", "completed")

    # No computed completeness score is available at this point without
    # re-running the procurement scoring logic (which lives in the BFF route
    # and needs the full Analysis object). The n8n template receives the
    # real issues_found count instead — the only genuinely derived metric
    # available here. Do not invent a percentage.
    issues_found = analysis_data.get("issues_found", 0) or 0
        
    # 3. Post to n8n webhook
    webhook_url = os.getenv("N8N_REPORT_WEBHOOK_URL", "https://kakakkakakak.app.n8n.cloud/webhook/send-report")
    
    import httpx
    
    try:
        async with httpx.AsyncClient() as client:
            files = {
                "report_pdf": ("StandIQ-Report.pdf", pdf_bytes, "application/pdf")
            }
            data = {
                "tender_title": tender_title,
                "tender_id": tender_id,
                "issues_found": str(issues_found),
                "status": status,
            }
            
            response = await client.post(webhook_url, data=data, files=files, timeout=15.0)
            
            if response.status_code >= 400:
                logger.error(f"Failed to trigger n8n webhook: {response.text}")
                raise HTTPException(status_code=502, detail="Failed to deliver email via n8n.")
                
            return {"success": True, "message": "Report successfully dispatched to n8n for email delivery."}
    except httpx.RequestError as e:
        logger.error(f"Error contacting n8n webhook: {str(e)}")
        raise HTTPException(status_code=502, detail="Failed to contact the email delivery service.")
