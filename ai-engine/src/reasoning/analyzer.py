"""
ai-engine/src/reasoning/analyzer.py

Orchestrates per-requirement analysis:
  1. ML classification of requirement type (or keyword fallback)
  2. Deterministic currentness check (superseded/outdated standards)
  3. LLM reasoning with richer context (structured requirements + standard summaries)

Fixes:
  - extraction_metadata now correctly reflects the actual reasoning mode
  - LLM prompt now receives structured technical parameters, not just raw text
"""

import logging
import os
import uuid

from src.reasoning.providers.ml import MLReasoner
from src.reasoning.providers.mock import MockReasoner
from src.reasoning.providers.gemini import GeminiReasoner

logger = logging.getLogger(__name__)


def _classify_requirement(text: str) -> str:
    """
    Simple keyword-based requirement classification.
    Replaces the ML model dependency (which requires a trained .joblib file).
    """
    text_lower = text.lower()
    if any(k in text_lower for k in ["watt", " w ", "power", "efficacy", "lm/w", "lumens"]):
        return "power_performance"
    if any(k in text_lower for k in ["volt", " v ", "vac", "current", "hz", "frequency"]):
        return "electrical"
    if any(k in text_lower for k in ["ip ", "ingress", "protection", "weatherproof", "outdoor"]):
        return "environmental_protection"
    if any(k in text_lower for k in ["bis", "isi", "crs", "qco", "certification", "mandatory", "mark"]):
        return "certification"
    if any(k in text_lower for k in ["is ", "iec ", "iso ", "standard", "compliance"]):
        return "standards_reference"
    if any(k in text_lower for k in ["surge", "spd", "lightning", "transient"]):
        return "protection"
    if any(k in text_lower for k in ["thd", "harmonic", "power factor", "pf "]):
        return "power_quality"
    if any(k in text_lower for k in ["cct", "color temp", "colour temp", "kelvin", " k "]):
        return "optical"
    return "general"


class Analyzer:
    def __init__(self):
        # AI_MODE selects the reasoning provider:
        #   "ml"     — the trained applicability model, offline and deterministic
        #   "mock"   — keyword heuristics, for tests and local development
        #   anything else (default) — Gemini
        #
        # MLReasoner was imported here but never constructed, so the applicability
        # model could not be reached through /analyze at all no matter how the
        # environment was configured. It is also the right thing to fall back to
        # when Gemini cannot start: the model is real and offline, whereas the
        # mock is keyword matching dressed as analysis, and a demo that silently
        # degrades to it looks like a working system when it is not.
        mode = os.getenv("AI_MODE", "ml")
        if mode == "mock":
            self.provider = MockReasoner()
            self._mode = "mock"
        elif mode == "gemini":
            try:
                self.provider = GeminiReasoner()
                self._mode = "gemini"
            except Exception as exc:
                logger.warning(
                    "Could not initialise GeminiReasoner (%s) — falling back to "
                    "the applicability model.", exc,
                )
                try:
                    self.provider = MLReasoner()
                    self._mode = "ml_fallback"
                except Exception as ml_exc:
                    logger.warning(
                        "The applicability model is unavailable too (%s) — "
                        "falling back to mock.", ml_exc,
                    )
                    self.provider = MockReasoner()
                    self._mode = "mock_fallback"
        else:
            # Default to ML
            try:
                self.provider = MLReasoner()
                self._mode = "ml"
            except Exception as exc:
                logger.warning(
                    "The applicability model is unavailable (%s) — "
                    "falling back to mock.", exc,
                )
                self.provider = MockReasoner()
                self._mode = "mock_fallback"

    def process(self, request) -> dict:
        import concurrent.futures

        findings = []

        def process_req(req):
            # 1. Classify requirement type
            req_type = _classify_requirement(req.text)

            # 2. ML/LLM reasoning with richer context
            res = self.provider.analyze(
                req_text=req.text,
                req_type=req_type,
                standards=request.retrieved_standards,
                is_reference=req.is_reference,
                cited_year=req.cited_year,
            )

            verdict = res.get("verdict", "requires_human_verification")
            reason = res.get("reason", "")
            action = res.get("action", "Manually verify specification against standards.")
            raw_conf = float(res.get("confidence", 0.5))
            conf = 0.70 + (raw_conf * 0.29)
            
            matched_is = res.get("matched_is_number")
            matched_ids = []
            if matched_is and isinstance(matched_is, str) and matched_is.strip().lower() != "null":
                matched_is_lower = matched_is.strip().lower()
                for s in request.retrieved_standards:
                    if matched_is_lower in s.is_number.lower():
                        matched_ids.append(s.id)
            
            # Fallback: if justified and we have a reference, assume the reference is what matched
            if not matched_ids and verdict == "justified" and req.is_reference:
                req_ref_lower = req.is_reference.strip().lower()
                matched_ids = [s.id for s in request.retrieved_standards if req_ref_lower in s.is_number.lower()]

            # 3. Deterministic currentness check on the SELECTED standard(s)
            outdated_stds = [
                s for s in request.retrieved_standards
                if s.id in matched_ids
                and s.status.lower() in ("superseded", "withdrawn", "cancelled")
            ]

            if outdated_stds:
                # Deterministic override — superseded standard is always flagged
                names = ", ".join(s.is_number for s in outdated_stds[:2])
                verdict = "outdated_reference"
                reason = (
                    f"The selected standard(s) {names} are marked as superseded or withdrawn "
                    "in the BIS metadata. This specification should reference the current edition."
                )
                action = "Update the tender specification to cite the current edition of the standard."
                raw_conf = 0.95
                conf = 0.95

            return {
                "finding_id": str(uuid.uuid4()),
                "requirement_id": req.id,
                "verdict": verdict,
                "reason": reason,
                "recommended_action": action,
                "applicable_standard_ids": matched_ids,
                "evidence_ids": [],
                "confidence": conf,
                "raw_confidence": raw_conf,
            }

        # Process all requirements concurrently (up to 5 at a time) to prevent massive latency
        with concurrent.futures.ThreadPoolExecutor(max_workers=5) as executor:
            findings = list(executor.map(process_req, request.requirements))

        return {
            "analysis_id": request.analysis_id,
            "findings": findings,
            "extraction_metadata": {
                "reasoning_mode": self._mode,
                "requirements_analysed": len(findings),
            },
        }
