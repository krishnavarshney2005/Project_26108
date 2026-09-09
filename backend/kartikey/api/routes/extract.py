"""
kartikey/api/routes/extract.py

POST /api/v1/analyses/extract-profile — the profile preview behind the
"Understanding Procurement Requirements" screen (step 1 → 2 of a new analysis).

This endpoint is a *preview*. It does not create an analysis, touch the knowledge
base, or produce findings; the frontend calls it so the officer can check what
the system read out of their document before committing to a full run. The real
work happens when they confirm, at POST /api/v1/analyses.

Order of operations, and why
----------------------------
The deterministic extractor runs first and always. Gemini runs after it, under a
hard timeout, and may only fill prose fields the document did not state. So:

  * the response is never empty, whatever Gemini is doing;
  * a 429 costs a few seconds of enrichment, not the request;
  * no requirement row can come from a model.

It used to be the other way round — a single blocking Gemini call produced the
whole screen, and on failure the endpoint returned two invented requirements and
the product name "Unknown Entity". That is the path this file replaced.

`extraction_mode` and `llm_refined_fields` are in the response so the frontend
can say which fields came from where. A screen that mixes document quotes with
model output and labels neither is not an audit trail.
"""

from __future__ import annotations

import asyncio
import uuid

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from typing import Optional

from shared.config import settings
from shared.utils import get_logger

from kartikey.analysis.profile_extractor import (
    LLM_REFINABLE_FIELDS,
    NOT_STATED,
    extract_profile,
    merge_llm_context,
)
from kartikey.analysis.query_quality import assess_query
from kartikey.document_processing.storage import get_extracted_text

logger = get_logger(__name__)

router = APIRouter(prefix="/analyses/extract-profile", tags=["analyses"])

# Enrichment only, so it gets a short leash rather than the pipeline's budget.
# The officer is watching a spinner; the deterministic profile is already built
# and waiting behind it.
_LLM_ENRICHMENT_TIMEOUT_SECONDS = 8.0

# Longest slice of document sent for enrichment. The product name and application
# are stated at the top of a tender, not on page 40.
_LLM_CONTEXT_CHARS = 6000

_CONTEXT_SYSTEM_PROMPT = (
    "You read Indian public-procurement documents. Extract only what the "
    "document states. If the document does not state a field, return null for "
    "it — never guess, and never substitute a placeholder."
)


class ExtractProfileRequest(BaseModel):
    text: Optional[str] = ""
    document_id: Optional[str] = None
    category: Optional[str] = "General"


def _context_prompt(content: str) -> str:
    return f"""Return ONLY a JSON object with these exact keys, using null where
the document does not state the value:
- "product": the main product, equipment or service being procured (max 7 words)
- "application": the intended use case or location (max 10 words)
- "environment": operating environment conditions the document states

Document:
{content[:_LLM_CONTEXT_CHARS]}
"""


async def _llm_context(content: str) -> dict | None:
    """
    Ask Gemini for the prose fields, or give up quietly.

    Every failure mode lands in the same place: no context, and the deterministic
    profile stands. The timeout is the important one — `generate_json` retries a
    429 with a growing sleep across candidate models, so without a deadline this
    call does not fail, it waits.
    """
    from kartikey.analysis.llm_client import get_llm_client

    try:
        client = get_llm_client()
        context = await asyncio.wait_for(
            asyncio.to_thread(
                client.generate_json,
                prompt=_context_prompt(content),
                system_prompt=_CONTEXT_SYSTEM_PROMPT,
            ),
            timeout=_LLM_ENRICHMENT_TIMEOUT_SECONDS,
        )
        return context if isinstance(context, dict) else None
    except asyncio.TimeoutError:
        logger.info(
            "extract-profile: LLM enrichment exceeded %.0fs; returning the "
            "deterministic profile.", _LLM_ENRICHMENT_TIMEOUT_SECONDS,
        )
        return None
    except Exception as exc:
        # Includes AnalysisError for LLM_NOT_CONFIGURED / LLM_QUOTA_EXHAUSTED.
        # None of them is a client error: the caller's document was fine and the
        # profile they asked for has already been built.
        logger.info(
            "extract-profile: LLM enrichment unavailable (%s: %s); returning the "
            "deterministic profile.", type(exc).__name__, exc,
        )
        return None


@router.post("")
async def extract_profile_endpoint(body: ExtractProfileRequest):
    content = ""
    if body.text and body.text.strip():
        content = body.text
    elif body.document_id:
        content = get_extracted_text(body.document_id)
        if not content:
            raise HTTPException(
                status_code=404, detail="Document text not found or empty",
            )
    else:
        raise HTTPException(
            status_code=400, detail="Either text or document_id is required",
        )

    # Gibberish gate — deterministic, and ahead of any extraction so a
    # non-procurement input is rejected rather than described.
    quality = assess_query(content)
    if not quality.is_meaningful:
        raise HTTPException(
            status_code=422,
            detail={
                "error": "NOT_A_PROCUREMENT_REQUIREMENT",
                "message": quality.message,
                "signals": quality.signals,
            },
        )

    preview_id = f"ext_{uuid.uuid4().hex[:8]}"

    # 1. Deterministic extraction. This is the response; everything after it is
    #    optional improvement.
    profile = extract_profile(content, fallback_category=body.category or "")

    # 2. Optional LLM enrichment of prose fields the document did not state.
    #    Only worth a network round trip if there is actually a gap to fill:
    #    merge_llm_context refuses to overwrite a field the document stated, so
    #    calling Gemini when all three are already populated buys nothing and
    #    costs up to the full timeout — which on an exhausted quota is exactly
    #    the delay that made this screen look like it had hung.
    refined: list[str] = []
    gaps = [name for name in LLM_REFINABLE_FIELDS
            if getattr(profile, name) == NOT_STATED]
    if gaps and settings.google_api_key:
        profile, refined = merge_llm_context(profile, await _llm_context(content))

    logger.info(
        "extract-profile: %s — %d field(s) extracted deterministically, "
        "%d refined by LLM (%s).",
        preview_id, profile.total_fields, len(refined),
        ", ".join(refined) or "none",
    )

    payload = profile.as_dict()
    payload["preview_id"] = preview_id
    payload["extraction_mode"] = "deterministic+llm" if refined else "deterministic"
    payload["llm_refined_fields"] = refined
    return payload
