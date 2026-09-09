"""
kartikey/analysis/findings.py

Findings assembler — the final step in the analysis pipeline.

This module takes:
  1. AI/ML output (AimlResponse with per-requirement findings + evidence_ids/standard_ids)
  2. Compliance check results (version, status, QCO — all deterministic)
  3. Retrieved standards from the knowledge base

And produces:
  Final Finding objects with full evidence chains that are returned to the frontend.

The assembly process has a strict rule:
  The LLM may SUGGEST a verdict. The compliance checks may take the headline
  from it when they find something more severe. Database facts always beat LLM
  reasoning for factual questions.

  But "more severe" only ranks verdicts, and the two sources do not answer the
  same question: the deterministic rules read years and status flags, so they can
  only ever speak to currentness; whether a clause is over-restrictive or covers
  the wrong product is the AI's axis alone. Ranking across those axes and keeping
  only the winner loses real findings — an over-restrictive clause that also
  cited a stale year came back as merely "outdated". So `Finding.dimensions`
  records what each axis concluded and `verdict` is the headline summary of them,
  not a replacement. See `_CURRENTNESS_VERDICTS` and `_build_dimensions`.

Evidence assembly rule:
  AI/ML returns evidence_ids and standard_ids (references to DB records).
  This assembler resolves those IDs against the knowledge stores.
  It NEVER uses LLM-generated evidence text directly in the final response.
  This is the core anti-hallucination guardrail of the system.

Two assembly paths, both fully supported:
  - If AI/ML answered: AimlFindings drive verdict + evidence, with the
    deterministic checks as the second axis (`_assemble_with_aiml`).
  - If it did not (no service configured, or the LLM path degraded): findings
    come from the deterministic checks alone (`_assemble_compliance_only`). This
    path produces real, useful findings for IS-citation requirements but cannot
    reason about performance specs, so it reports applicability as
    "not_assessed" rather than implying it checked.
"""

from __future__ import annotations

from shared.contracts import AimlFinding, AimlResponse
from shared.models import (
    Analysis,
    Evidence,
    Finding,
    Requirement,
    Standard,
    StandardStatus,
    Verdict,
)
from shared.utils import AnalysisError, get_logger

from kartikey.analysis.compliance import ComplianceResult, run_compliance_checks
from kshiraj.enrichment.crossref_extractor import CrossRefExtractor

logger = get_logger(__name__)

# Deterministic, stateless, no network — safe as a module-level singleton.
_crossref_extractor = CrossRefExtractor()


# ===========================================================================
# Public interface
# ===========================================================================

def assemble_findings(
    analysis: Analysis,
    retrieved_standards: list[Standard],
    aiml_response: AimlResponse | None,
    standards_lookup: dict[str, Standard],
    evidence_lookup: dict[str, Evidence],
) -> list[Finding]:
    """
    Assemble final Finding objects for an analysis.

    Parameters
    ----------
    analysis:
        The Analysis object (contains requirements).
    retrieved_standards:
        Standards retrieved by the knowledge layer, ranked by relevance.
    aiml_response:
        Optional response from the AI/ML component.
        None when AI/ML is not yet wired (Steps 1-6).
    standards_lookup:
        Dict of standard_id → Standard for resolving AI/ML references.
        Populated from the knowledge store.
    evidence_lookup:
        Dict of evidence_id → Evidence for resolving AI/ML references.
        Populated from the evidence store.

    Returns
    -------
    list[Finding]
        Final assembled findings with full evidence chains.
    """
    if not analysis.requirements:
        logger.info(
            "assemble_findings: no requirements to process for analysis_id=%s",
            analysis.id,
        )
        return []

    findings: list[Finding] = []

    if aiml_response is not None:
        # --- Path A: AI/ML is wired — use AI findings as primary, compliance as override ---
        findings = _assemble_with_aiml(
            analysis=analysis,
            aiml_response=aiml_response,
            retrieved_standards=retrieved_standards,
            standards_lookup=standards_lookup,
            evidence_lookup=evidence_lookup,
        )
    else:
        # --- Path B: AI/ML not yet wired — use compliance-only findings ---
        # This runs in Steps 5-6 before the AI/ML client is connected.
        # It still produces real, useful findings based on IS reference matches.
        findings = _assemble_compliance_only(
            analysis=analysis,
            retrieved_standards=retrieved_standards,
        )

    for finding in findings:
        finding.data_availability = _assess_availability(finding)

    logger.info(
        "assemble_findings: produced %d findings for analysis_id=%s",
        len(findings), analysis.id,
    )
    return findings


def _assess_availability(finding: Finding) -> dict[str, str]:
    """
    Label each optional report section as present, absent, or never checked.

    The distinction that matters is between "we looked and there is nothing" and
    "we never looked". Both arrive at the frontend as an empty list, and only the
    second is a defect — but a UI that cannot tell them apart has to treat every
    empty section as suspect. So each label below is derived from whether the
    check ran, not from whether it found anything:

        not_identified  the check ran and the answer was genuinely nothing
        not_available   the BIS source does not publish this field
        not_assessed    the stage that produces it did not run

    Nothing here fills a section in. A standard with no published scope still
    has no scope; this only records why.
    """
    availability: dict[str, str] = {}

    availability["applicable_standards"] = (
        "verified" if finding.applicable_standards else "not_identified"
    )

    # A standard the tender cites that was assessed and found not to govern the
    # requirement. Empty is the normal case; "not_identified" says the check ran
    # and found no such standard, which is different from never having looked.
    availability["cited_standards"] = (
        "verified" if finding.cited_standards else "not_identified"
    )

    # Cross-references are only meaningful once a standard has been matched. With
    # no standard there was nothing to extract references from, which is a
    # different statement from "this standard has no references".
    #
    # Keyed on everything assessed, not just what stayed applicable: references
    # are extracted from a cited standard whether or not it turned out to cover
    # the right material, so gating on applicable_standards alone would label a
    # populated section "not_assessed".
    assessed = finding.applicable_standards or finding.cited_standards
    if finding.cross_references:
        availability["cross_references"] = "verified"
    elif assessed:
        availability["cross_references"] = "not_identified"
    else:
        availability["cross_references"] = "not_assessed"

    availability["evidence"] = "verified" if finding.evidence else "not_available"

    dimensions = finding.dimensions or {}

    availability["currentness"] = (
        "verified" if finding.currentness or dimensions.get("currentness")
        else "not_assessed"
    )

    # Certification is asserted only from a verified source, so its absence is a
    # gap in the published record rather than a failed check.
    certification = dimensions.get("certification")
    availability["certification"] = "verified" if certification else "not_available"

    # The applicability block is always present in shape — when no AI/ML pass ran
    # it is filled with nulls and source="not_assessed". Testing its truthiness
    # therefore labelled that placeholder "verified", so a degraded run reported
    # an assessment it had not made. The block's own source field is the answer.
    applicability = dimensions.get("applicability") or {}
    availability["applicability"] = (
        "verified"
        if applicability and applicability.get("source") not in (None, "not_assessed")
        else "not_assessed"
    )

    # Same reasoning as applicability: the scope block is always present in
    # shape, and most catalogue records state no material in their title, so
    # "not assessed" is the normal case rather than a defect. Its own `assessed`
    # flag is what distinguishes a comparison that was made from one that could
    # not be.
    scope = dimensions.get("scope") or {}
    availability["scope"] = "verified" if scope.get("assessed") else "not_assessed"

    availability["recommended_action"] = (
        "verified" if finding.recommended_action else "not_identified"
    )

    return availability


# ===========================================================================
# Assembly paths
# ===========================================================================

def _assemble_with_aiml(
    analysis: Analysis,
    aiml_response: AimlResponse,
    retrieved_standards: list[Standard],
    standards_lookup: dict[str, Standard],
    evidence_lookup: dict[str, Evidence],
) -> list[Finding]:
    """
    Assemble findings using AI/ML output as the primary source.

    For each AimlFinding:
      1. Resolve standard_ids → Standard objects from the knowledge store
      2. Resolve evidence_ids → Evidence objects from the evidence store
      3. Run compliance checks on the matched standards (deterministic override)
      4. Merge: use stricter of (AI verdict, compliance verdict)
      5. Assemble final Finding with full evidence chain
    """
    # Build a quick lookup from requirement_id → Requirement
    req_lookup: dict[str, Requirement] = {r.id: r for r in analysis.requirements}

    # Computed once: "does the tender mention this IS anywhere" is a property of
    # the whole tender, not of one requirement.
    tender_cited = _tender_cited_is_numbers(analysis)

    findings: list[Finding] = []

    for aiml_finding in aiml_response.findings:
        req = req_lookup.get(aiml_finding.requirement_id)
        if not req:
            logger.warning(
                "AimlFinding references unknown requirement_id=%s — skipping.",
                aiml_finding.requirement_id,
            )
            continue
            
        # Guardrail: If the model's confidence in its match is very low (e.g. 0.1),
        # treat it as "no applicable standard found" rather than propagating all 
        # retrieved candidates. Match the Gemini wrong_scope honesty.
        raw_conf = getattr(aiml_finding, "raw_confidence", None)
        if raw_conf is None:
            raw_conf = aiml_finding.confidence

        if raw_conf < 0.2:
            aiml_finding.applicable_standard_ids = []
            aiml_finding.verdict = Verdict.UNSUPPORTED.value
            aiml_finding.reason = "No standard in the catalogue matches this requirement's domain."

        # Resolve standard IDs
        assessed_standards: list[Standard] = []
        for sid in aiml_finding.applicable_standard_ids:
            std = standards_lookup.get(sid)
            if std:
                assessed_standards.append(std)
            else:
                logger.warning(
                    "AimlFinding references unknown standard_id=%s — skipping.", sid,
                )

        # Resolve evidence IDs — anti-hallucination guardrail
        ai_evidence: list[Evidence] = []
        for eid in aiml_finding.evidence_ids:
            ev = evidence_lookup.get(eid)
            if ev:
                ai_evidence.append(ev)
            else:
                logger.warning(
                    "AimlFinding references unknown evidence_id=%s — skipping.", eid,
                )

        # Run compliance checks on matched standards
        compliance_results: list[ComplianceResult] = []
        for std in assessed_standards:
            try:
                result = run_compliance_checks(req, std)
                compliance_results.append(result)
            except Exception as exc:
                logger.error(
                    "Compliance check failed for req=%s std=%s: %s",
                    req.id[:8], std.designation, exc,
                )

        # The scope check may have established that a cited standard does not
        # govern this requirement. Split before the finding is assembled so
        # `applicable_standards` means what it says.
        applicable_standards, cited_standards = _split_by_applicability(
            assessed_standards, compliance_results,
        )

        # Determine final verdict: AI vs compliance — stricter wins
        try:
            ai_verdict = Verdict(aiml_finding.verdict)
        except ValueError:
            logger.warning(
                "Unknown verdict '%s' from AI/ML — defaulting to UNABLE_TO_DETERMINE.",
                aiml_finding.verdict,
            )
            ai_verdict = Verdict.UNABLE_TO_DETERMINE

        final_verdict, final_confidence, verdict_source, best_cr = _merge_verdicts(
            ai_verdict=ai_verdict,
            ai_confidence=aiml_finding.confidence,
            compliance_results=compliance_results,
        )

        # Ensure the standard driving the deterministic finding is in applicable_standards
        if best_cr is not None and best_cr.suggested_verdict != Verdict.WRONG_SCOPE:
            override_std = next((s for s in assessed_standards if s.id == best_cr.standard_id), None)
            if override_std and override_std.id not in (s.id for s in applicable_standards):
                applicable_standards.append(override_std)
                cited_standards = [s for s in cited_standards if s.id != override_std.id]

        # Collect all evidence
        all_evidence = list(ai_evidence)
        for cr in compliance_results:
            all_evidence.extend(cr.evidence)

        # Build currentness context
        currentness = _build_currentness_context(compliance_results)

        # Keep each axis intact — the headline verdict is a summary of these,
        # not a replacement for them.
        dimensions = _build_dimensions(
            headline_verdict=final_verdict,
            resolution=verdict_source,
            compliance_results=compliance_results,
            ai_verdict=ai_verdict,
            ai_confidence=aiml_finding.confidence,
        )

        # Dependencies the cited standards pull in. Computed over everything that
        # was assessed, not just what stayed applicable: a tender citing IS 1554
        # inherits its dependency on IS 8130 whether or not IS 1554 turns out to
        # cover the right material, and that is information the officer needs
        # while deciding what to do about the citation.
        cross_references = _build_cross_references(assessed_standards, tender_cited)

        # Determine if human review is needed
        needs_human = (
            final_verdict == Verdict.REQUIRES_HUMAN_VERIFICATION
            or final_confidence < 0.60
            or any(cr.qco_check.qco_notified for cr in compliance_results)
        )

        finding = Finding(
            requirement_id=req.id,
            analysis_id=analysis.id,
            verdict=final_verdict,
            reason=_append_dependency_note(
                _build_reason(
                    aiml_finding=aiml_finding,
                    compliance_results=compliance_results,
                    verdict_source=verdict_source,
                    ai_verdict=ai_verdict,
                ),
                cross_references,
            ),
            recommended_action=_build_recommended_action(
                final_verdict, compliance_results, cross_references,
            ),
            applicable_standards=applicable_standards,
            cited_standards=cited_standards,
            currentness=currentness,
            dimensions=dimensions,
            cross_references=cross_references,
            evidence=all_evidence,
            confidence=final_confidence,
            requires_human_verification=needs_human,
            verification_reason=(
                "Low confidence score or QCO-notified product requires officer review."
                if needs_human else None
            ),
        )
        findings.append(finding)

    return findings


def _assemble_compliance_only(
    analysis: Analysis,
    retrieved_standards: list[Standard],
) -> list[Finding]:
    """
    Assemble findings using only compliance checks (no AI/ML).

    For each requirement:
      - Match against retrieved standards by IS number
      - Run compliance checks on matched standards
      - Produce a Finding based purely on deterministic rules

    This path runs before the AI/ML client is connected.
    It produces real, useful findings for IS-citation requirements
    but cannot reason about non-IS requirements (performance specs, etc.)
    """
    # Build IS-number → [Standard] lookup from retrieved standards
    is_number_to_standards: dict[str, list[Standard]] = {}
    for std in retrieved_standards:
        key = std.is_number.strip().casefold()
        is_number_to_standards.setdefault(key, []).append(std)

    tender_cited = _tender_cited_is_numbers(analysis)

    findings: list[Finding] = []

    for req in analysis.requirements:
        if not req.is_reference:
            # Can't do compliance checks without an IS reference
            finding = Finding(
                requirement_id=req.id,
                analysis_id=analysis.id,
                verdict=Verdict.UNABLE_TO_DETERMINE,
                reason=(
                    f"Requirement '{req.text[:80]}...' does not cite a specific Indian Standard. "
                    "Cannot perform automated compliance check. "
                    "Full AI analysis will assess this requirement when the AI/ML layer is wired."
                ),
                recommended_action="Review manually or wait for full AI analysis.",
                applicable_standards=[],
                currentness=None,
                evidence=[],
                confidence=0.0,
                requires_human_verification=True,
                verification_reason="No IS reference — cannot automate compliance check.",
            )
            findings.append(finding)
            continue

        # Find matching standards for this IS reference
        req_key = req.is_reference.strip().casefold()
        matched_standards = is_number_to_standards.get(req_key, [])

        if not matched_standards:
            # IS cited but not found in knowledge base
            finding = Finding(
                requirement_id=req.id,
                analysis_id=analysis.id,
                verdict=Verdict.UNABLE_TO_DETERMINE,
                reason=(
                    f"Standard '{req.is_reference}' cited in the tender was not found "
                    "in the knowledge base. Cannot verify its current status."
                ),
                recommended_action=(
                    "Verify this IS number on the BIS 'Know Your Standard' portal "
                    "(standardsbis.gov.in) and confirm it is active."
                ),
                applicable_standards=[],
                currentness=None,
                evidence=[],
                confidence=0.3,
                requires_human_verification=True,
                verification_reason=f"'{req.is_reference}' not found in knowledge base.",
            )
            findings.append(finding)
            continue

        # Run compliance checks on all matched standards
        compliance_results: list[ComplianceResult] = []
        for std in matched_standards:
            try:
                cr = run_compliance_checks(req, std)
                compliance_results.append(cr)
            except Exception as exc:
                logger.error(
                    "Compliance check failed: req=%s std=%s: %s",
                    req.id[:8], std.designation, exc,
                )

        if not compliance_results:
            findings.append(Finding(
                requirement_id=req.id,
                analysis_id=analysis.id,
                verdict=Verdict.UNABLE_TO_DETERMINE,
                reason="Compliance checks could not be completed.",
                recommended_action="Review manually.",
                applicable_standards=matched_standards,
                evidence=[],
                confidence=0.0,
                requires_human_verification=True,
                verification_reason="Compliance check error.",
            ))
            continue

        # Use the most severe compliance result
        best_cr = min(compliance_results, key=lambda cr: _verdict_severity(cr.suggested_verdict))
        all_evidence = [ev for cr in compliance_results for ev in cr.evidence]
        cross_references = _build_cross_references(matched_standards, tender_cited)
        applicable_standards, cited_standards = _split_by_applicability(
            matched_standards, compliance_results,
        )

        needs_human = (
            best_cr.suggested_verdict == Verdict.REQUIRES_HUMAN_VERIFICATION
            or best_cr.confidence < 0.60
            or any(cr.qco_check.qco_notified for cr in compliance_results)
        )

        finding = Finding(
            requirement_id=req.id,
            analysis_id=analysis.id,
            verdict=best_cr.suggested_verdict,
            reason=_append_dependency_note(
                _build_compliance_reason(req, compliance_results), cross_references,
            ),
            recommended_action=_build_recommended_action(
                best_cr.suggested_verdict, compliance_results, cross_references,
            ),

            applicable_standards=applicable_standards,
            cited_standards=cited_standards,
            currentness=_build_currentness_context(compliance_results),
            dimensions=_build_dimensions(
                headline_verdict=best_cr.suggested_verdict,
                resolution="compliance_only",
                compliance_results=compliance_results,
            ),
            cross_references=cross_references,
            evidence=all_evidence,
            confidence=best_cr.confidence,
            requires_human_verification=needs_human,
            verification_reason=(
                "QCO-notified product or low confidence — officer review recommended."
                if needs_human else None
            ),
        )
        findings.append(finding)

    return findings


# ===========================================================================
# Verdict merging
# ===========================================================================

# Severity order — lower index = more severe problem
_VERDICT_SEVERITY_ORDER = [
    Verdict.INCORRECT_STANDARD,
    Verdict.CONFLICTING,
    Verdict.OUTDATED_REFERENCE,
    Verdict.WRONG_SCOPE,
    Verdict.MISSING_REQUIREMENT,
    Verdict.POTENTIALLY_OVER_RESTRICTIVE,
    Verdict.POTENTIALLY_UNNECESSARY,
    Verdict.UNSUPPORTED,
    Verdict.AMBIGUOUS,
    Verdict.REQUIRES_HUMAN_VERIFICATION,
    Verdict.UNABLE_TO_DETERMINE,
    Verdict.JUSTIFIED,
]

# Which axis a verdict speaks to.
#
# The deterministic rules can only ever reach a conclusion about currentness,
# status, or certification — they read years and status flags out of the
# catalogue. They have no view on whether a clause narrows the vendor pool or
# describes the wrong product. Those are the AI's axis.
#
# The split matters because severity is not comparable across axes. In the
# ordering above OUTDATED_REFERENCE outranks POTENTIALLY_OVER_RESTRICTIVE, so a
# clause that was both over-restrictive *and* cited a stale year used to be
# reported purely as "outdated": fix the year and the tender looks clean, while
# the restriction that actually excluded suppliers is never mentioned.
_CURRENTNESS_VERDICTS = frozenset({
    Verdict.OUTDATED_REFERENCE,
    Verdict.INCORRECT_STANDARD,   # withdrawn standard — a lifecycle fact
})


def _verdict_axis(verdict: Verdict) -> str:
    """Return "currentness" or "applicability" for a verdict."""
    return "currentness" if verdict in _CURRENTNESS_VERDICTS else "applicability"


def _verdict_severity(verdict: Verdict) -> int:
    """Lower return value = more severe."""
    try:
        return _VERDICT_SEVERITY_ORDER.index(verdict)
    except ValueError:
        return len(_VERDICT_SEVERITY_ORDER)


def _merge_verdicts(
    ai_verdict: Verdict,
    ai_confidence: float,
    compliance_results: list[ComplianceResult],
) -> tuple[Verdict, float, str, ComplianceResult | None]:
    """
    Choose the headline verdict from the AI verdict and the compliance verdicts.
    The more severe (higher priority in severity order) verdict wins.

    Returns (final_verdict, final_confidence, source_description, best_compliance)

    This picks *one* value because the API contract and the frontend badge need
    one. It is not the whole assessment: `_build_dimensions` records what each
    axis concluded, so a verdict that loses here is still reported rather than
    discarded. See `_CURRENTNESS_VERDICTS`.
    """
    if not compliance_results:
        return ai_verdict, ai_confidence, "ai_only", None

    # Find the most severe compliance verdict
    best_compliance = min(
        compliance_results,
        key=lambda cr: _verdict_severity(cr.suggested_verdict),
    )

    ai_severity = _verdict_severity(ai_verdict)
    compliance_severity = _verdict_severity(best_compliance.suggested_verdict)

    if compliance_severity < ai_severity:
        # Compliance check found a more severe issue — it becomes the headline.
        # "override" is now only about which one leads: the AI verdict survives
        # in dimensions["applicability"].
        return best_compliance.suggested_verdict, best_compliance.confidence, "compliance_override", best_compliance
    elif ai_severity < compliance_severity:
        # AI found something the compliance rules didn't catch
        return ai_verdict, ai_confidence, "ai_primary", best_compliance
    else:
        # Same severity — average confidences, keep AI reasoning
        avg_confidence = (ai_confidence + best_compliance.confidence) / 2
        return ai_verdict, avg_confidence, "ai_and_compliance_agree", best_compliance


# ===========================================================================
# Cited vs applicable
# ===========================================================================

def _split_by_applicability(
    assessed: list[Standard],
    compliance_results: list[ComplianceResult],
) -> tuple[list[Standard], list[Standard]]:
    """
    Partition the assessed standards into `(applicable, cited_not_applicable)`.

    A standard the scope check found to cover a different material than the
    requirement specified is not applicable to it, however correctly it is
    numbered and however confidently the tender cites it. Reporting it under
    `applicable_standards` is the single hardest error for an officer to catch,
    because the report looks like it agrees with them.

    Order is preserved on both sides, and a standard whose scope check did not
    run stays applicable — "not assessed" is not evidence of a mismatch.
    """
    mismatched = {
        cr.standard_id for cr in compliance_results if cr.scope_check.mismatch
    }
    if not mismatched:
        return list(assessed), []

    applicable = [std for std in assessed if std.id not in mismatched]
    cited_only = [std for std in assessed if std.id in mismatched]
    return applicable, cited_only


# ===========================================================================
# Dimensions
# ===========================================================================

def _currentness_label(cr: ComplianceResult | None) -> str:
    """
    One word for the version situation, for the report and the UI badge.

    UNVERIFIABLE is deliberately distinct from OUTDATED: "we checked and it is
    stale" and "we could not check" call for different actions from the officer.
    """
    if cr is None:
        return "UNKNOWN"

    status = cr.status_check.status
    if status == StandardStatus.WITHDRAWN:
        return "WITHDRAWN"
    if status == StandardStatus.SUPERSEDED:
        return "SUPERSEDED"

    vc = cr.version_check
    if vc.is_year_omitted:
        return "YEAR_OMITTED"
    if vc.current_year is None:
        return "UNVERIFIABLE"
    if vc.gap_years is not None and vc.gap_years < 0:
        return "AHEAD_OF_CATALOGUE"
    return "CURRENT" if vc.is_current else "OUTDATED"


def _build_dimensions(
    headline_verdict: Verdict,
    resolution: str,
    compliance_results: list[ComplianceResult],
    ai_verdict: Verdict | None = None,
    ai_confidence: float | None = None,
) -> dict:
    """
    Record what each axis concluded, independently of which one leads.

    Called on both assembly paths. On the compliance-only path there is no AI
    verdict, so `applicability` reports that it was not assessed rather than
    silently borrowing the deterministic verdict.
    """
    best = (
        min(compliance_results, key=lambda cr: _verdict_severity(cr.suggested_verdict))
        if compliance_results else None
    )

    if ai_verdict is not None:
        applicability: dict = {
            "verdict": ai_verdict.value,
            "confidence": ai_confidence,
            "source": "ai",
        }
    else:
        applicability = {
            "verdict": None,
            "confidence": None,
            "source": "not_assessed",
            "note": (
                "No AI/ML analysis was available for this requirement; only the "
                "deterministic checks ran."
            ),
        }

    currentness: dict = {
        "label": _currentness_label(best),
        "source": "version_checker",
        "note": "No applicable standard identified; currentness cannot be determined.",
    }
    if best is not None:
        currentness.update({
            "confidence": best.confidence,
            "is_current": best.version_check.is_current,
            "cited_year": best.version_check.cited_year,
            "current_year": best.version_check.current_year,
            "gap_years": best.version_check.gap_years,
            "status": best.status_check.status.value,
            "note": best.version_check.note,
        })
        # Only carry the verdict here when it is actually a currentness verdict.
        # `best` is the most severe result across every axis, so this block used
        # to print WRONG_SCOPE — an applicability conclusion — under
        # dimensions["currentness"], where a reader would take it as a statement
        # about the edition year. The numbers above are unconditional because
        # they are always the version checker's own output.
        if _verdict_axis(best.suggested_verdict) == "currentness":
            currentness["verdict"] = best.suggested_verdict.value

    # What the cited standard covers, versus what the requirement specified.
    #
    # A separate axis rather than a note on `applicability`, because the two
    # answer different questions and are established differently: applicability
    # is the AI's judgement of whether the standard governs the requirement,
    # while this is a set difference over BIS's own titles. Reporting them
    # together would let a "not_assessed" on one imply the other.
    scope_result = next(
        (cr for cr in compliance_results if cr.scope_check.mismatch), None
    ) or next(
        (cr for cr in compliance_results if cr.scope_check.checked), None
    )
    if scope_result is None:
        scope: dict = {
            "assessed": False,
            "mismatch": None,
            "source": "not_assessed",
            "note": (
                best.scope_check.note if best is not None else
                "No applicable standard identified; scope cannot be assessed."
            ),
        }
    else:
        sc = scope_result.scope_check
        scope = {
            "assessed": True,
            "mismatch": sc.mismatch,
            "attribute": sc.attribute,
            "required_material": sc.required_material,
            "required_as_written": sc.required_as_written,
            "covered_material": sc.covered_material,
            "cited_standard": scope_result.standard_designation,
            "alternatives": sc.alternatives,
            "source": "catalogue_titles",
            "note": sc.note,
        }

    certification = {
        "qco_notified": bool(best and best.qco_check.qco_notified),
        "scheme": (
            best.qco_check.certification_scheme.value
            if best and best.qco_check.certification_scheme else None
        ),
        "issuing_ministry": best.qco_check.issuing_ministry if best else None,
        # The order that imposes the requirement, and the date from which it
        # binds. QCOCheck has carried both all along and this block dropped them,
        # which left the report asserting "BIS certification is mandatory" with
        # nothing an officer could cite when a bidder disputed it. A mandatory-
        # certification claim is only auditable if it names its gazette notification.
        "gazette_so_number": best.qco_check.gazette_so_number if best else None,
        "effective_date": (
            best.qco_check.effective_date.isoformat()
            if best and best.qco_check.effective_date else None
        ),
        "note": best.qco_check.note if best else None,
        "source": "knowledge_base",
    }

    dimensions = {
        "applicability": applicability,
        "currentness": currentness,
        "scope": scope,
        "certification": certification,
        "headline": {
            "verdict": headline_verdict.value,
            "axis": _verdict_axis(headline_verdict),
            "resolution": resolution,
        },
    }

    # Say so explicitly when the headline comes from a different axis than the
    # AI's judgement. Without this the report reads as though the AI agreed.
    if ai_verdict is not None and resolution == "compliance_override":
        if _verdict_axis(ai_verdict) != _verdict_axis(headline_verdict):
            dimensions["headline"]["note"] = (
                f"Headline reports the {_verdict_axis(headline_verdict)} problem "
                f"because it is more severe. The {_verdict_axis(ai_verdict)} "
                f"finding ({ai_verdict.value}) still applies and is reported above."
            )
        else:
            dimensions["headline"]["note"] = (
                f"Deterministic checks reached a more severe conclusion on the same "
                f"axis than the AI's {ai_verdict.value}."
            )

    return dimensions


# ===========================================================================
# Cross-references (dependency chain)
# ===========================================================================

def _tender_cited_is_numbers(analysis: Analysis) -> set[str]:
    """
    Every IS number the tender mentions anywhere, as base numbers.

    Requirement text is scanned as well as the structured `is_reference` field.
    A dependency named in prose but not picked as a requirement's primary
    citation is still cited, and reporting it as missing would be a false alarm
    in front of a procurement officer.
    """
    parts: list[str] = []
    for req in analysis.requirements:
        parts.extend(
            p for p in (req.is_reference, req.cited_designation, req.text) if p
        )
    if not parts:
        return set()
    result = _crossref_extractor.extract("\n".join(parts))
    return {n.upper() for n in result.referenced_is_numbers}


def _build_cross_references(
    applicable_standards: list[Standard],
    tender_cited: set[str],
) -> list[dict]:
    """
    For each applicable standard, the standards it depends on and which of those
    the tender never mentions.

    Comparison is at base-IS-number granularity ("IS 10322", not
    "IS 10322 (Part 5/Sec 3)"), which is what CrossRefExtractor reports and the
    level a tender cites at. A consequence: a part referencing a sibling part of
    the same standard is treated as self-referential and dropped, because citing
    any part of IS 10322 does cite IS 10322.
    """
    entries: list[dict] = []

    for std in applicable_standards:
        extracted = _crossref_extractor.extract(std)
        own = {
            n.upper()
            for n in _crossref_extractor.extract(std.is_number).referenced_is_numbers
        }
        references = [
            n for n in extracted.referenced_is_numbers if n.upper() not in own
        ]
        if not references:
            continue

        unmet = [n for n in references if n.upper() not in tender_cited]

        note = (
            f"{std.designation} references {', '.join(references)}."
            + (
                " The tender does not cite "
                + ", ".join(unmet)
                + " — a bid compliant with the cited standard may still fail "
                "these dependencies."
                if unmet else " All of these are cited in the tender."
            )
        )

        entries.append({
            "source": std.is_number,
            "source_designation": std.designation,
            "references": references,
            "unmet": unmet,
            "note": note,
        })

    return entries


def _append_dependency_note(reason: str, cross_references: list[dict]) -> str:
    """Surface unmet dependencies in the finding's prose, not just its JSON."""
    unmet = sorted({n for entry in cross_references for n in entry["unmet"]})
    if not unmet:
        return reason
    return (
        f"{reason} [Dependencies] The cited standard(s) depend on "
        f"{', '.join(unmet)}, which the tender does not reference."
    )


# ===========================================================================
# Text builders
# ===========================================================================

def _build_reason(
    aiml_finding: AimlFinding,
    compliance_results: list[ComplianceResult],
    verdict_source: str,
    ai_verdict: Verdict | None = None,
) -> str:
    parts = [aiml_finding.reason]

    if verdict_source == "compliance_override" and compliance_results:
        best = min(compliance_results, key=lambda cr: _verdict_severity(cr.suggested_verdict))
        # Name the AI's verdict when the deterministic checks lead on a different
        # axis. The AI's prose is already in parts[0], but without its label the
        # report reads as though the AI had reached the headline verdict.
        if (
            ai_verdict is not None
            and _verdict_axis(ai_verdict) != _verdict_axis(best.suggested_verdict)
        ):
            parts.append(
                f"[{_verdict_axis(ai_verdict).title()}] This finding "
                f"({ai_verdict.value}) still applies independently of the "
                "version issue below."
            )
        parts.append(f"[Compliance override] {best.version_check.note}")
        parts.append(f"[Status] {best.status_check.note}")
        if best.scope_check.mismatch:
            parts.append(f"[Scope] {best.scope_check.note}")
        if best.qco_check.qco_notified:
            parts.append(f"[QCO] {best.qco_check.note}")
    elif compliance_results:
        best = min(compliance_results, key=lambda cr: _verdict_severity(cr.suggested_verdict))
        if not best.version_check.is_current:
            parts.append(f"[Version] {best.version_check.note}")
        if best.scope_check.mismatch:
            parts.append(f"[Scope] {best.scope_check.note}")
        if best.qco_check.qco_notified:
            parts.append(f"[QCO] {best.qco_check.note}")

    return " ".join(parts)


def _build_compliance_reason(
    requirement: Requirement,
    compliance_results: list[ComplianceResult],
) -> str:
    """Build a human-readable reason from compliance-only results."""
    if not compliance_results:
        return "No compliance data available."

    best = min(compliance_results, key=lambda cr: _verdict_severity(cr.suggested_verdict))
    parts = [best.version_check.note, best.status_check.note]
    if best.scope_check.mismatch:
        parts.append(best.scope_check.note)
    if best.qco_check.qco_notified:
        parts.append(best.qco_check.note)

    return " ".join(parts)


def _build_recommended_action(
    verdict: Verdict,
    compliance_results: list[ComplianceResult],
    cross_references: list[dict] | None = None,
) -> str | None:
    """Build a recommended action for the procurement officer."""
    qco_notified = any(cr.qco_check.qco_notified for cr in compliance_results)
    superseded_by = next(
        (cr.status_check.superseded_by for cr in compliance_results
         if cr.status_check.superseded_by), None,
    )
    scope_mismatch = next(
        (cr.scope_check for cr in compliance_results if cr.scope_check.mismatch), None
    )

    actions = {
        Verdict.JUSTIFIED: (
            "No action required. Standard reference appears correct and current."
            + (" Ensure BIS certification (CM/L or R-number) is explicitly required in bid documents." if qco_notified else "")
        ),
        Verdict.OUTDATED_REFERENCE: (
            f"Update the IS reference to the current edition"
            + (f": {superseded_by}" if superseded_by else "")
            + ". Verify on standardsbis.gov.in."
        ),
        Verdict.INCORRECT_STANDARD: (
            "This standard has been withdrawn by BIS and cannot be used. "
            "Remove this requirement and identify the correct replacement standard."
        ),
        # Names the standards that do cover the material, when the catalogue
        # holds any. "Review this requirement" — what the fallback would have
        # said — is the least useful sentence available at the exact moment the
        # system knows the most.
        Verdict.WRONG_SCOPE: (
            (
                f"The tender specifies {scope_mismatch.required_material} "
                f"{scope_mismatch.attribute} but cites a standard covering "
                f"{scope_mismatch.covered_material} {scope_mismatch.attribute}. "
                + (
                    "Replace the citation with "
                    + ", ".join(scope_mismatch.alternatives)
                    + " if that matches the intended product, or correct the "
                    "material in the specification."
                    if scope_mismatch.alternatives else
                    "Identify the standard covering this material on "
                    "standardsbis.gov.in, or correct the material in the "
                    "specification."
                )
            )
            if scope_mismatch else
            "The cited standard appears to cover a different application than "
            "the requirement describes. Verify on standardsbis.gov.in."
        ),
        Verdict.MISSING_REQUIREMENT: (
            "Add the applicable IS standard to the technical specification. "
            + ("This is mandatory due to a QCO notification." if qco_notified else "")
        ),
        Verdict.AMBIGUOUS: (
            "Specify the year of the IS edition to avoid disputes during bid evaluation."
        ),
        Verdict.REQUIRES_HUMAN_VERIFICATION: (
            "Flag for senior procurement officer review before finalizing the tender."
        ),
        Verdict.POTENTIALLY_OVER_RESTRICTIVE: (
            "Review whether this requirement narrows competition unreasonably. "
            "Consider accepting equivalent international standards."
        ),
        Verdict.UNABLE_TO_DETERMINE: (
            "Verify this requirement manually. "
            "Check the BIS portal (standardsbis.gov.in) for current status."
        ),
    }
    action = actions.get(verdict, "Review this requirement.")

    # An unmet dependency is actionable regardless of the verdict — a "justified"
    # citation whose prerequisites are missing still leaves the spec incomplete.
    unmet = sorted({
        n for entry in (cross_references or []) for n in entry["unmet"]
    })
    if unmet:
        action += (
            f" Also add the referenced standard(s) {', '.join(unmet)} to the "
            "technical specification, or state explicitly why they do not apply."
        )
    return action


def _build_currentness_context(compliance_results: list[ComplianceResult]) -> dict | None:
    """Build the 'currentness' dict for a finding from compliance results."""
    if not compliance_results:
        return None

    best = min(compliance_results, key=lambda cr: _verdict_severity(cr.suggested_verdict))
    vc = best.version_check
    sc = best.status_check

    return {
        "cited_year": vc.cited_year,
        "current_year": vc.current_year,
        "is_current": vc.is_current,
        "year_omitted": vc.is_year_omitted,
        "gap_years": vc.gap_years,
        "status": sc.status.value,
        "superseded_by": sc.superseded_by,
        "transition_deadline": sc.transition_deadline.isoformat() if sc.transition_deadline else None,
        "within_transition": sc.within_transition,
        "qco_notified": best.qco_check.qco_notified,
        "qco_ministry": best.qco_check.issuing_ministry,
    }
