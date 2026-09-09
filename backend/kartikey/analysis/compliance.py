"""
kartikey/analysis/compliance.py

Deterministic compliance rules applied to each requirement + its matched standard.

This module does NOT call the LLM. It applies pure logic rules based on
structured data from the knowledge base. The results are facts, not opinions.

What this module checks:
  1. Version currency   — is the year cited in the tender current?
  2. Standard status    — is the standard active, superseded, or withdrawn?
  3. QCO mandatory flag — does a QCO make BIS certification mandatory?
  4. Transition period  — if superseded, is it still within the allowed window?
  5. Year omitted       — tender cited the IS number without a year (risky)
  6. Scope/material     — does the standard cover the material specified?

Check 1 is not implemented here. It is delegated to
`kshiraj/enrichment/version_checker.py`, which every candidate standard now
passes through — see `_check_version`. Check 6 is delegated to
`scope_check.py`, which reads the material out of BIS's own titles.

Why deterministic checks matter:
  The LLM analysis step is probabilistic — it reasons over text.
  But "IS 10322:2012 is superseded by IS 10322 (Part 5/Sec 3):2022" is a
  database fact. We never let the LLM decide facts that we can check directly.
  These checks run *after* the LLM returns findings and override them where
  we have authoritative data.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, timezone

from shared.models import (
    CertificationScheme,
    Evidence,
    EvidenceSourceType,
    Requirement,
    Standard,
    StandardStatus,
    Verdict,
)
from shared.utils import get_logger, utcnow

from kartikey.analysis.scope_check import ScopeCheck, check_scope
from kshiraj.enrichment.version_checker import VersionChecker, VersionCheckResult

logger = get_logger(__name__)

# The single authority on currentness. This module used to decide it inline,
# which meant two implementations that disagreed in exactly the cases that
# matter: the inline version called a citation current when the standard's own
# year was unknown, and called a citation *newer* than the catalogue current
# too (`cited >= current`). Both are unprovable claims, and the second let a
# tender citing a nonexistent future edition come back "justified".
_version_checker = VersionChecker()


# ===========================================================================
# Output types
# ===========================================================================

@dataclass
class VersionCheck:
    """
    Result of comparing the year cited in the tender vs the current standard year.

    Mirrors `VersionCheckResult` field-for-field, adding only a procurement-facing
    `note`. It exists so `ComplianceResult` stays one flat shape; the decision
    itself comes from VersionChecker.
    """
    cited_year: int | None
    current_year: int | None
    is_current: bool
    is_year_omitted: bool
    gap_years: int | None
    note: str


@dataclass
class StatusCheck:
    """Result of checking the standard's current BIS status."""
    status: StandardStatus
    is_usable: bool
    superseded_by: str | None
    transition_deadline: date | None
    within_transition: bool
    note: str


@dataclass
class QCOCheck:
    """Result of checking whether a QCO makes BIS certification mandatory."""
    qco_notified: bool
    certification_scheme: CertificationScheme | None
    issuing_ministry: str | None
    effective_date: date | None
    gazette_so_number: str | None
    note: str


@dataclass
class ComplianceResult:
    """
    Full compliance assessment for one (requirement, standard) pair.
    All fields are deterministic — no LLM involved.
    """
    requirement_id: str
    standard_id: str
    standard_designation: str

    version_check: VersionCheck
    status_check: StatusCheck
    qco_check: QCOCheck
    scope_check: ScopeCheck

    suggested_verdict: Verdict
    confidence: float
    evidence: list[Evidence] = field(default_factory=list)


# ===========================================================================
# Public API
# ===========================================================================

def run_compliance_checks(
    requirement: Requirement,
    standard: Standard,
) -> ComplianceResult:
    """
    Run all deterministic compliance checks for a (requirement, standard) pair.

    Parameters
    ----------
    requirement:
        The extracted requirement from the tender (contains cited IS number + year).
    standard:
        The matched Standard from the knowledge base (authoritative status, year, QCO, etc.)

    Returns
    -------
    ComplianceResult
        Full structured result with a suggested verdict and evidence chain.
    """
    today = datetime.now(tz=timezone.utc).date()

    version_check = _check_version(requirement, standard)
    status_check = _check_status(standard, today)
    qco_check = _check_qco(standard)
    scope_check = check_scope(requirement, standard)

    suggested_verdict, confidence = _determine_verdict(
        version_check, status_check, qco_check, scope_check, requirement, standard,
    )

    evidence = _build_evidence(standard, version_check, status_check, qco_check)

    result = ComplianceResult(
        requirement_id=requirement.id,
        standard_id=standard.id,
        standard_designation=standard.designation,
        version_check=version_check,
        status_check=status_check,
        qco_check=qco_check,
        scope_check=scope_check,
        suggested_verdict=suggested_verdict,
        confidence=confidence,
        evidence=evidence,
    )

    logger.debug(
        "ComplianceCheck: req=%s standard=%s verdict=%s confidence=%.2f",
        requirement.id[:8], standard.designation,
        suggested_verdict.value, confidence,
    )
    return result


def check_missing_requirement(
    standard: Standard,
) -> tuple[Verdict, str]:
    """
    Check if a standard that's NOT cited in the tender should have been.
    Used when retrieval finds a strongly applicable QCO-notified standard
    that the tender completely omitted.
    """
    if standard.qco_notified and standard.status == StandardStatus.ACTIVE:
        return (
            Verdict.MISSING_REQUIREMENT,
            f"{standard.designation} is mandated by a QCO issued by "
            f"{standard.qco_issuing_ministry or 'an issuing ministry'}. "
            "BIS certification must be required in the tender.",
        )
    if standard.status == StandardStatus.ACTIVE:
        return (
            Verdict.POTENTIALLY_UNNECESSARY,
            f"{standard.designation} appears applicable but is not cited in the tender.",
        )
    return (
        Verdict.UNABLE_TO_DETERMINE,
        f"{standard.designation} may be applicable (status: {standard.status.value}).",
    )


# ===========================================================================
# Internal check functions
# ===========================================================================

def _check_version(requirement: Requirement, standard: Standard) -> VersionCheck:
    """
    Compare the cited edition year against the standard's own year.

    The comparison itself is delegated to `VersionChecker`; this function only
    turns its result into procurement-facing prose. Keeping the decision in one
    place is the point — the numbers a report shows and the numbers a verdict is
    derived from must not be able to drift apart.
    """
    result = _version_checker.check(requirement, standard)
    return VersionCheck(
        cited_year=result.cited_year,
        current_year=result.current_year,
        is_current=result.is_current,
        is_year_omitted=result.is_year_omitted,
        gap_years=result.gap_years,
        note=_version_note(result, standard),
    )


def _version_note(result: VersionCheckResult, standard: Standard) -> str:
    """
    Explain a VersionCheckResult in terms a procurement officer can act on.

    VersionChecker's own note states the arithmetic. This adds what it means for
    the tender: whether the gap is small enough to survive a transition period,
    and what BIS convention says about an omitted year.
    """
    if result.is_year_omitted:
        return (
            f"Tender cites '{standard.is_number}' without a year. "
            "Per BIS convention this implies 'latest edition including amendments', "
            "but makes compliance verification harder and can cause bid disputes."
        )

    if result.current_year is None:
        return (
            f"Year {result.cited_year} cited, but the current edition year for "
            f"{standard.is_number} is not in the knowledge base. Currentness "
            "cannot be established — verify on standardsbis.gov.in."
        )

    gap = result.gap_years or 0

    if gap == 0:
        return f"Year {result.cited_year} matches current edition ({standard.designation}). ✓"

    if gap < 0:
        # Cited edition is newer than anything the knowledge base knows about.
        # Either the catalogue is stale or the tender cites an edition that does
        # not exist; both need a human, and neither is "current".
        return (
            f"Year {result.cited_year} is {abs(gap)} year(s) *newer* than the "
            f"latest known edition ({standard.designation}). Either the "
            "knowledge base is stale or the tender cites an edition that does "
            "not exist. Not treated as current."
        )

    if gap <= 3:
        return (
            f"Year {result.cited_year} is {gap} year(s) behind current edition "
            f"({standard.designation}). Minor gap — check if still within transition period."
        )

    return (
        f"Year {result.cited_year} is {gap} year(s) behind current edition "
        f"({standard.designation}). Significant outdated reference — tender should be updated."
    )


def _check_status(standard: Standard, today: date) -> StatusCheck:
    if standard.status == StandardStatus.WITHDRAWN:
        return StatusCheck(
            status=standard.status, is_usable=False,
            superseded_by=None, transition_deadline=None, within_transition=False,
            note=(
                f"{standard.designation} has been WITHDRAWN by BIS. "
                "All existing licenses under this standard are automatically cancelled. "
                "This standard CANNOT be used for certification or procurement."
            ),
        )

    if standard.status == StandardStatus.SUPERSEDED:
        replacement = standard.superseded_by or "a newer version"
        within_transition = False
        transition_note = ""
        if standard.transition_deadline:
            within_transition = today <= standard.transition_deadline
            if within_transition:
                days_left = (standard.transition_deadline - today).days
                transition_note = (
                    f" Within transition period ({days_left} days remaining "
                    f"until {standard.transition_deadline.isoformat()})."
                )
            else:
                transition_note = (
                    f" Transition period ended {standard.transition_deadline.isoformat()}. "
                    "Superseded version is no longer valid."
                )
        return StatusCheck(
            status=standard.status,
            is_usable=within_transition,
            superseded_by=replacement,
            transition_deadline=standard.transition_deadline,
            within_transition=within_transition,
            note=f"{standard.designation} is SUPERSEDED by {replacement}.{transition_note}",
        )

    if standard.status == StandardStatus.UNDER_REVISION:
        return StatusCheck(
            status=standard.status, is_usable=True,
            superseded_by=None, transition_deadline=None, within_transition=False,
            note=(
                f"{standard.designation} is UNDER REVISION. Still valid, "
                "but a new edition is forthcoming. Monitor before tender finalization."
            ),
        )

    if standard.status == StandardStatus.REAFFIRMED:
        yr = f" (reaffirmed {standard.reaffirmation_year})" if standard.reaffirmation_year else ""
        return StatusCheck(
            status=standard.status, is_usable=True,
            superseded_by=None, transition_deadline=None, within_transition=False,
            note=f"{standard.designation} is ACTIVE{yr}. BIS reviewed and confirmed valid.",
        )

    # ACTIVE or UNKNOWN
    return StatusCheck(
        status=standard.status, is_usable=True,
        superseded_by=None, transition_deadline=None, within_transition=False,
        note=f"{standard.designation} is {standard.status.value.upper()}.",
    )


def _check_qco(standard: Standard) -> QCOCheck:
    if not standard.qco_notified:
        return QCOCheck(
            qco_notified=False, certification_scheme=None,
            issuing_ministry=None, effective_date=None, gazette_so_number=None,
            note="No Quality Control Order issued for this standard.",
        )

    scheme = standard.required_certification_scheme
    scheme_name = {
        CertificationScheme.ISI_MARK: "BIS ISI mark (CM/L license number required in bid)",
        CertificationScheme.CRS: "BIS CRS registration (R-number required in bid)",
        CertificationScheme.HALLMARKING: "BIS Hallmarking (HUID required)",
    }.get(scheme, "BIS certification (scheme unspecified)")

    return QCOCheck(
        qco_notified=True,
        certification_scheme=scheme,
        issuing_ministry=standard.qco_issuing_ministry,
        effective_date=standard.qco_effective_date,
        gazette_so_number=standard.qco_gazette_so_number,
        note=(
            f"QCO MANDATORY: Issued by {standard.qco_issuing_ministry or 'issuing ministry'} "
            f"(Gazette {standard.qco_gazette_so_number or 'ref not in DB'}). "
            f"Requires {scheme_name}. "
            "Tender MUST mandate this certification — suppliers without it are ineligible."
        ),
    )


def _determine_verdict(
    version_check: VersionCheck,
    status_check: StatusCheck,
    qco_check: QCOCheck,
    scope_check: ScopeCheck,
    requirement: Requirement,
    standard: Standard,
) -> tuple[Verdict, float]:
    """
    Priority-ordered verdict decision from deterministic checks.
    Higher-priority checks override lower-priority ones.
    """
    # 1. Withdrawn — hardest fact, highest priority
    if not status_check.is_usable and standard.status == StandardStatus.WITHDRAWN:
        return Verdict.INCORRECT_STANDARD, 0.95

    # 1b. The standard covers a different material than the one specified.
    #
    # Above every currentness rule deliberately. All of those answer "is this the
    # right *edition*", and answering that first means telling an officer to
    # update the year of a standard that does not apply to their product — advice
    # that is worse than silence, because it reads as having been checked.
    # Withdrawal still outranks it: a withdrawn standard cannot be used at all,
    # whatever it covers.
    #
    # WRONG_SCOPE rather than INCORRECT_STANDARD: the standard is real, live and
    # correctly numbered. What is wrong is the pairing, and WRONG_SCOPE is the
    # verdict this codebase already defines for "IS exists but covers a different
    # application" — it also files on the applicability axis rather than
    # currentness, which is where a material mismatch belongs.
    #
    # Confidence 0.80, not higher: the comparison is a fact read out of BIS's own
    # title, but a title is a summary. A standard can carry an annex the title
    # never mentions, so this asks for verification rather than asserting error.
    if scope_check.mismatch:
        return Verdict.WRONG_SCOPE, 0.80

    # 2. Superseded + transition ended
    if (
        standard.status == StandardStatus.SUPERSEDED
        and status_check.transition_deadline
        and not status_check.within_transition
    ):
        return Verdict.OUTDATED_REFERENCE, 0.95

    # 3. Superseded (in transition or no deadline info)
    if standard.status == StandardStatus.SUPERSEDED:
        confidence = 0.75 if status_check.within_transition else 0.85
        return Verdict.OUTDATED_REFERENCE, confidence

    # 4. Year significantly behind (>5 years)
    if version_check.gap_years is not None and version_check.gap_years > 5:
        return Verdict.OUTDATED_REFERENCE, 0.80

    # 5. Year moderately behind (1-5 years)
    if version_check.gap_years is not None and version_check.gap_years > 0:
        return Verdict.OUTDATED_REFERENCE, 0.70

    # 5b. Tender cites an edition newer than any we know of. Not outdated — the
    # opposite — but not verifiable either: either our catalogue is behind or the
    # tender cites an edition that was never published. A bid evaluated against
    # a nonexistent edition is indefensible, so this must reach a human.
    if version_check.gap_years is not None and version_check.gap_years < 0:
        return Verdict.REQUIRES_HUMAN_VERIFICATION, 0.55

    # 5c. A year was cited but we have no year to compare it against, so
    # currentness is simply unknown. Reporting "justified" here would be
    # asserting something we never checked.
    if not version_check.is_year_omitted and version_check.current_year is None:
        return Verdict.UNABLE_TO_DETERMINE, 0.45

    # 6. Under revision — flag for human review
    if standard.status == StandardStatus.UNDER_REVISION:
        return Verdict.REQUIRES_HUMAN_VERIFICATION, 0.65

    # 7. Year omitted
    if version_check.is_year_omitted:
        return Verdict.AMBIGUOUS, 0.60

    # 8. Status unknown
    if standard.status == StandardStatus.UNKNOWN:
        return Verdict.UNABLE_TO_DETERMINE, 0.50

    # 9. Everything checks out
    return Verdict.JUSTIFIED, 0.85


def _build_evidence(
    standard: Standard,
    version_check: VersionCheck,
    status_check: StatusCheck,
    qco_check: QCOCheck,
) -> list[Evidence]:
    """Build Evidence objects from the compliance check results."""
    now = utcnow()
    evidence: list[Evidence] = []

    # The standard itself
    evidence.append(Evidence(
        source_type=EvidenceSourceType.BIS_STANDARD,
        source_name=f"BIS Standard {standard.designation}",
        authority="BIS",
        url=standard.source_url,
        category="metadata",
        retrieval_date=standard.retrieved_at or now,
    ))

    # Each amendment
    for amd in standard.amendments:
        evidence.append(Evidence(
            source_type=EvidenceSourceType.BIS_AMENDMENT,
            source_name=f"{standard.designation} Amendment {amd.amendment_number}",
            authority="BIS",
            url=amd.source_url,
            category="metadata",
            gazette_so_number=amd.gazette_so_number,
            publication_date=amd.effective_date,
            amendment_number=amd.amendment_number,
            retrieval_date=now,
        ))

    # QCO gazette
    if qco_check.qco_notified and qco_check.gazette_so_number:
        evidence.append(Evidence(
            source_type=EvidenceSourceType.QCO_NOTIFICATION,
            source_name=f"QCO Gazette {qco_check.gazette_so_number}",
            authority=qco_check.issuing_ministry or "Government of India",
            url=None,
            category="metadata",
            gazette_so_number=qco_check.gazette_so_number,
            publication_date=qco_check.effective_date,
            retrieval_date=now,
        ))

    return evidence
