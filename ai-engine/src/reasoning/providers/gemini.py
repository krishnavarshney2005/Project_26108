"""
ai-engine/src/reasoning/providers/gemini.py

Gemini-powered reasoning provider.

Improvements:
  - analyze() now accepts is_reference and cited_year from the requirement record
  - Prompt includes structured standard summaries (not just IS number + title)
  - Prompt references cited IS number and year when available
  - Falls back gracefully on any API error
"""

import json
import logging

from src.llm_config import GEMINI_MODEL, get_gemini_api_key, get_gemini_client

from .base import ReasoningProvider

logger = logging.getLogger(__name__)


class GeminiReasoner(ReasoningProvider):
    def __init__(self):
        self.api_key = get_gemini_api_key()
        if not self.api_key:
            logger.warning("No Gemini API key set (GOOGLE_API_KEY) — Gemini reasoning unavailable.")
        self.model = GEMINI_MODEL
        self._client = None

    def _get_client(self):
        if self._client is None:
            self._client = get_gemini_client()
        return self._client

    def analyze(self, req_text, req_type, standards, is_reference=None, cited_year=None):
        """
        Analyze a procurement requirement against candidate BIS standards.

        Parameters
        ----------
        req_text      : str  — raw requirement text from the tender
        req_type      : str  — classified requirement category
        standards     : list — retrieved standard objects (have .is_number, .title, .status)
        is_reference  : str | None — explicit IS number cited in this requirement
        cited_year    : int | None — year of the cited edition (e.g. 2018)
        """
        if not self.api_key:
            return self._fallback("Gemini API key (GOOGLE_API_KEY) not configured.")

        # Truncate very long requirement texts to stay within Gemini's context window.
        # Tender documents can be huge; individual requirements usually shouldn't exceed 500 chars.
        MAX_REQ_TEXT = 2000
        if len(req_text) > MAX_REQ_TEXT:
            logger.warning(
                "req_text truncated from %d to %d chars for Gemini analysis.",
                len(req_text), MAX_REQ_TEXT
            )
            req_text = req_text[:MAX_REQ_TEXT] + "… [truncated]"

        if not standards:
            return {
                "verdict": "requires_human_verification",
                "reason": (
                    f"No retrieved standards could be confidently matched against "
                    f"the {req_type} requirement."
                ),
                "action": "Manually verify specification against applicable BIS standards.",
                "confidence": 0.4,
            }

        # Build richer standards context — include status and scope where available
        stds_lines = []
        for s in standards[:5]:  # limit to top 5 for token budget
            status = getattr(s, "status", "unknown")
            title = getattr(s, "title", "")
            is_num = getattr(s, "is_number", "")
            stds_lines.append(f"- {is_num}: {title} [Status: {status}]")
        stds_context = "\n".join(stds_lines)

        # Build citation context
        citation_note = ""
        if is_reference:
            year_str = f":{cited_year}" if cited_year else ""
            citation_note = f"\nNote: The tender explicitly cites '{is_reference}{year_str}' in this requirement."

        prompt = f"""You are an expert Indian Standards (BIS) compliance auditor reviewing a government procurement tender.

REQUIREMENT TEXT:
"{req_text}"

REQUIREMENT TYPE: {req_type}{citation_note}

CANDIDATE BIS STANDARDS (retrieved for this requirement):
{stds_context}

TASK:
1. Determine whether this procurement requirement is justified, problematic, or unclear from a BIS compliance perspective.
2. If the tender cites a specific IS number, check whether that standard is the correct and current one for this requirement.
3. Provide a concise, evidence-grounded reason (2-3 sentences maximum).
4. Recommend a concrete action for the procurement officer.
5. Provide a confidence score (0.0 = very uncertain, 1.0 = very certain).

VERDICT OPTIONS:
- justified                  : requirement is correct and supported by the cited/matched standard
- outdated_reference         : cited standard exists but is superseded or outdated
- incorrect_standard         : wrong IS standard cited for this requirement
- wrong_scope                : standard exists but doesn't cover this specific use case
- potentially_over_restrictive : requirement is stricter than the standard mandates
- ambiguous                  : requirement text is unclear or could be interpreted multiple ways
- requires_human_verification: insufficient information to make a determination

Respond ONLY with a valid JSON object:
{{
  "verdict": "one of the options above",
  "reason": "concise explanation referencing specific standard numbers",
  "action": "concrete recommended action for the procurement officer",
  "confidence": 0.85,
  "matched_is_number": "IS 1234 (or null if none applies)"
}}"""

        try:
            from google.genai import types
            client = self._get_client()
            response = client.models.generate_content(
                model=self.model,
                contents=prompt,
                config=types.GenerateContentConfig(
                    response_mime_type="application/json",
                    temperature=0.1,
                ),
            )
            result = json.loads(response.text)
            logger.info(
                "Gemini verdict for req_type=%s: %s (confidence=%.2f)",
                req_type, result.get("verdict"), result.get("confidence", 0)
            )
            return result

        except Exception as exc:
            logger.error("Gemini analysis failed: %s", exc)
            return self._fallback(str(exc))

    @staticmethod
    def _fallback(reason: str) -> dict:
        return {
            "verdict": "requires_human_verification",
            "reason": f"AI reasoning unavailable: {reason}",
            "action": "Manually verify specification against applicable BIS standards.",
            "confidence": 0.1,
        }
