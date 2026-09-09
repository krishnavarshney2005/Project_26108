"""
shared/models/__init__.py

Canonical Pydantic domain models for the SIH 26108 procurement intelligence system.

These models are the single source of truth for data shapes shared across:
  - kartikey/ (API, analysis, orchestration)
  - kshiraj/  (database, ingestion, retrieval)

Key design decisions based on actual BIS/CPPP domain research:
  - IS numbers have a strict format (IS XXXX (Part N/Sec M):YYYY Amd.N)
  - Standard status has 5 real states from BIS, NOT generic "active/inactive"
  - BIS certification types are distinct: ISI (CM/L number) vs CRS (R-number) vs Hallmarking (HUID)
  - QCOs are issued by specific ministries and link standards to mandatory certification
  - Evidence is a first-class object: every finding must trace to a source
  - Tenders can be updated via Corrigenda that override original IS references

Do not modify these without coordinating with both Kartikey and Kshiraj.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime, timezone
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field, computed_field


# ===========================================================================
# Helpers
# ===========================================================================

def _new_id() -> str:
    return str(uuid.uuid4())

def _utcnow() -> datetime:
    return datetime.now(tz=timezone.utc)


# ===========================================================================
# Enums — all values are grounded in real BIS/CPPP domain data
# ===========================================================================

class StandardStatus(str, Enum):
    """
    Real status values used by BIS.
    Source: BIS "Know Your Standard" portal field observations.
    """
    ACTIVE = "active"
    # Standard is currently being updated by technical committee.
    # Still usable but a new version is forthcoming.
    UNDER_REVISION = "under_revision"
    # Reviewed and confirmed valid, no changes needed.
    # Remains Active; the reaffirmation year is recorded separately.
    REAFFIRMED = "reaffirmed"
    # Replaced by a newer IS version. Old version retired.
    # The superseded_by field points to the current standard.
    SUPERSEDED = "superseded"
    # No longer valid. No replacement standard exists.
    # Any BIS license under this IS is automatically cancelled.
    WITHDRAWN = "withdrawn"
    # Status could not be determined from available sources.
    UNKNOWN = "unknown"


class CertificationScheme(str, Enum):
    """
    BIS certification schemes — each has a different identifier type and process.
    ISI  → CM/L number (factory audit required, per manufacturer)
    CRS  → R-number   (self-declaration, per manufacturer per model, electronics only)
    HALLMARKING → HUID (per jewellery piece, precious metals only)
    """
    ISI_MARK = "isi_mark"               # CM/L number; physical products, industrial/consumer
    CRS = "crs"                         # R-number; electronics/IT (MeitY-notified)
    HALLMARKING = "hallmarking"         # HUID; gold/silver jewellery only
    OTHER = "other"


class DataAvailability(str, Enum):
    """
    Whether a field's value is actually known, and how well.

    This is a first-class value rather than a null because the two situations a
    null conflates need different responses from a procurement officer:
    "BIS does not publish this" is a fact about the standard, while "we have a
    value but nobody checked it" is a caveat on our own data. A frontend that
    only sees `null` cannot tell them apart, and renders both as a blank cell.

    NOT_AVAILABLE is used where the source catalogue genuinely carries nothing.
    It is never used to hide a value we could have imported.
    """
    VERIFIED = "verified"            # present, and provenance confirmed at source
    UNVERIFIED = "unverified"        # present, but provenance not confirmed
    NOT_AVAILABLE = "not_available"  # the source catalogue carries no value


class DocumentType(str, Enum):
    """BIS document types as classified on the BIS portal."""
    PRODUCT_SPECIFICATION = "product_specification"
    CODE_OF_PRACTICE = "code_of_practice"
    METHOD_OF_TEST = "method_of_test"
    TERMINOLOGY = "terminology"
    GUIDE = "guide"
    OTHER = "other"


class RequirementCategory(str, Enum):
    """Category of a tender requirement, assigned during extraction."""
    TECHNICAL_SPECIFICATION = "technical_specification"
    CERTIFICATION = "certification"
    PERFORMANCE = "performance"
    TESTING = "testing"
    SAFETY = "safety"
    MATERIAL = "material"
    INSTALLATION = "installation"
    ELIGIBILITY = "eligibility"
    OTHER = "other"


class AnalysisStatus(str, Enum):
    """Lifecycle states of an analysis job."""
    QUEUED = "queued"
    EXTRACTING = "extracting"       # extracting text + requirements from document
    RETRIEVING = "retrieving"       # searching knowledge base for relevant standards
    ANALYZING = "analyzing"         # AI/ML reasoning over requirements + standards
    ENRICHING = "enriching"         # version checks, cross-refs, QCO lookups, compliance
    COMPLETED = "completed"
    PARTIALLY_COMPLETED = "partially_completed"  # some requirements failed
    FAILED = "failed"


class InputType(str, Enum):
    DOCUMENT = "document"   # uploaded PDF/DOCX
    TEXT = "text"           # free-text procurement description


class Verdict(str, Enum):
    """
    Possible findings from the analysis engine.
    These are conceptual categories validated against the SIH problem statement.
    """
    JUSTIFIED = "justified"
    POTENTIALLY_UNNECESSARY = "potentially_unnecessary"
    OUTDATED_REFERENCE = "outdated_reference"         # tender cites old IS year
    INCORRECT_STANDARD = "incorrect_standard"         # wrong IS for this product
    WRONG_SCOPE = "wrong_scope"                       # IS exists but covers different application
    AMBIGUOUS = "ambiguous"                           # requirement is unclear
    MISSING_REQUIREMENT = "missing_requirement"       # applicable IS not referenced in tender
    CONFLICTING = "conflicting"                       # two requirements contradict each other
    POTENTIALLY_OVER_RESTRICTIVE = "potentially_over_restrictive"
    UNSUPPORTED = "unsupported"                       # requirement has no known IS basis
    UNABLE_TO_DETERMINE = "unable_to_determine"
    REQUIRES_HUMAN_VERIFICATION = "requires_human_verification"


class EvidenceSourceType(str, Enum):
    """Authority level of an evidence source."""
    BIS_STANDARD = "bis_standard"
    BIS_AMENDMENT = "bis_amendment"
    BIS_GAZETTE_NOTIFICATION = "bis_gazette_notification"
    QCO_NOTIFICATION = "qco_notification"
    CPPP_TENDER = "cppp_tender"
    GEM_CATALOG = "gem_catalog"
    BIS_WIDE_CIRCULATION_DRAFT = "bis_wide_circulation_draft"
    REGULATORY_NOTIFICATION = "regulatory_notification"
    OTHER_GOVERNMENT = "other_government"
    SECONDARY = "secondary"


# ===========================================================================
# Core domain models
# ===========================================================================

# ---------------------------------------------------------------------------
# Amendment — a specific change applied to a standard
# ---------------------------------------------------------------------------

class Amendment(BaseModel):
    """
    A numbered amendment to an IS standard.
    Multiple amendments can apply to one IS. They are cumulative.

    Example: IS 2062:2011 Amd.4 means the 4th amendment has been applied.
    """
    amendment_number: int               # 1, 2, 3, 4 ...
    year: int | None = None             # year the amendment was issued
    description: str | None = None     # brief description of what changed
    gazette_so_number: str | None = None  # e.g. "S.O. 219(E)"
    effective_date: date | None = None
    source_url: str | None = None


# ---------------------------------------------------------------------------
# Standard — a BIS Indian Standard
# ---------------------------------------------------------------------------

class Standard(BaseModel):
    """
    A BIS Indian Standard (IS).

    The is_number + part + section + year together form the canonical designation.
    Example: IS 1180 (Part 1):2014 Amd.2

    Notes:
    - reaffirmation_year: if set, standard was reviewed and confirmed valid in that year.
      Status remains ACTIVE but reaffirmation_year is updated.
    - superseded_by: if status == SUPERSEDED, this points to the replacement standard number.
    - transition_deadline: the date after which the superseded version becomes invalid.
      During this window, both old and new versions can be valid concurrently.
    - qco_notified: True if a Quality Control Order has been issued requiring BIS certification
      for this product. A tender procuring this product MUST mandate CM/L or R-number.
    - required_certification_scheme: which BIS scheme (ISI/CRS/Hallmarking) applies if QCO-notified.
    """
    id: str = Field(default_factory=_new_id)

    # ------------------------------------------------------------------
    # Designation fields (form the canonical IS identifier)
    # ------------------------------------------------------------------
    is_number: str                          # e.g. "IS 269", "IS 1180", "IS 10322"
    part: str | None = None                 # e.g. "Part 1", "Part 5"
    section: str | None = None             # e.g. "Sec 3", "Sec 5"
    year: int | None = None                 # year of publication/revision, e.g. 2015
    amendments: list[Amendment] = []        # list of applied amendments

    @computed_field
    def designation(self) -> str:
        """
        Return the canonical IS designation string.
        e.g. "IS 10322 (Part 5/Sec 3):2012"
             "IS 269:2015 Amd.2"
        """
        d = self.is_number
        if self.part and self.section:
            d += f" ({self.part}/{self.section})"
        elif self.part:
            d += f" ({self.part})"
        if self.year:
            d += f":{self.year}"
        if self.amendments:
            d += f" Amd.{self.amendments[-1].amendment_number}"
        return d

    # ------------------------------------------------------------------
    # Descriptive metadata
    # ------------------------------------------------------------------
    title: str
    scope: str | None = None               # text describing coverage and exclusions
    # Standards a procurement officer cannot ignore once this one is cited.
    # normative_references are binding (the citing standard's requirements are
    # only meaningful if these are also met); related_standards are informative.
    # Both hold designation strings as the catalogue records them
    # ("IS 10322 : Part 1"), not resolved Standard objects — the enrichment layer
    # resolves them against the store when it needs the object.
    normative_references: list[str] = []
    related_standards: list[str] = []
    document_type: DocumentType = DocumentType.OTHER
    ics_code: str | None = None            # ICS taxonomy code e.g. "91.100.10"
    division_council: str | None = None    # BIS Division Council (sector)
    technical_committee: str | None = None # committee responsible

    # Catalogue-supplied descriptors. Useful to a procurement officer in their own
    # right ("which tests does this standard actually prescribe?") and to the
    # frontend's standards map, which groups by product category.
    keywords: list[str] = []
    product_categories: list[str] = []     # e.g. ["Lighting & LED"]
    test_methods: list[str] = []           # e.g. ["IPX9 ingress protection"]

    # ------------------------------------------------------------------
    # Status and lifecycle
    # ------------------------------------------------------------------
    status: StandardStatus = StandardStatus.UNKNOWN
    reaffirmation_year: int | None = None  # set if status == REAFFIRMED
    superseded_by: str | None = None       # IS number of replacement (if SUPERSEDED)
    supersedes: str | None = None           # edition this one replaced, as catalogued
    transition_deadline: date | None = None  # when superseded version becomes invalid
    withdrawal_date: date | None = None    # set if status == WITHDRAWN

    # The newest edition the catalogue knows of. Usually equals `year`; it differs
    # when the record we hold is not the latest, which is exactly the case
    # VersionChecker exists to catch. Kept separate from `year` so "the edition
    # this record describes" and "the newest edition that exists" never merge.
    latest_known_edition: str | None = None
    latest_known_year: int | None = None

    # ------------------------------------------------------------------
    # QCO and certification
    # ------------------------------------------------------------------
    qco_notified: bool = False
    qco_gazette_so_number: str | None = None    # e.g. "S.O. 219(E)"
    qco_issuing_ministry: str | None = None     # e.g. "DPIIT", "MeitY"
    qco_effective_date: date | None = None
    required_certification_scheme: CertificationScheme | None = None

    # ------------------------------------------------------------------
    # Source / provenance
    # ------------------------------------------------------------------
    source_url: str | None = None          # canonical BIS page URL
    retrieved_at: datetime | None = None

    # Where this record came from, verbatim from the reconciled catalogue:
    #   {"organization": "BIS", "source_type": "bis.gov.in",
    #    "verified": true, "url": null, "record_source": "curated_additions"}
    # The report's provenance column reads this. A record whose provenance is
    # unverified is still usable — it just cannot be presented as authoritative.
    provenance: dict[str, Any] | None = None

    # Per-field availability, keyed by field name, values from DataAvailability:
    #   {"scope": "verified", "certification": "not_available",
    #    "normative_references": "verified", "currentness": "unverified"}
    #
    # Populated by the catalogue loader. Everything downstream — the API, the PDF,
    # the frontend badges — reads this instead of inferring meaning from an empty
    # value, so "BIS publishes no scope for this standard" and "we failed to load
    # a scope" stop looking identical.
    field_availability: dict[str, str] = {}

    # ------------------------------------------------------------------
    # For retrieval (populated by kshiraj/knowledge)
    # ------------------------------------------------------------------
    relevance_score: float | None = None   # set by retrieval service, not stored
    semantic_score: float | None = None   # set by retrieval service, for ML reasoning

    text_excerpt: str | None = None        # relevant excerpt for evidence

    # ------------------------------------------------------------------
    # Dynamic hallucinated/extracted fields for demo
    # ------------------------------------------------------------------
    demo_operating_voltage: str | None = None
    demo_ip_rating: str | None = None
    demo_surge_protection: str | None = None
    demo_thermal_dissipation: str | None = None
    demo_test_methods: str | None = None


# ---------------------------------------------------------------------------
# Evidence — a traceable piece of authoritative source information
# ---------------------------------------------------------------------------

class Evidence(BaseModel):
    """
    A single piece of traceable evidence supporting a finding.

    Evidence is a first-class concept in this system.
    Every important finding must link to at least one evidence record.
    The source_type indicates the authority level of the evidence.

    Fields are modelled on real BIS/CPPP source structures:
    - gazette_so_number: for QCO/amendment gazette notifications
    - amendment_number: for IS amendment evidence
    - page/section: for standard document evidence
    - tender_id: for CPPP tender evidence
    """
    id: str = Field(default_factory=_new_id)

    source_type: EvidenceSourceType
    source_name: str                        # human-readable source name
    authority: str | None = None            # issuing body: "BIS", "DPIIT", "MeitY", etc.
    category: str = "clause"                # "metadata" or "clause"

    # Location within the source
    url: str | None = None
    page: int | None = None
    section: str | None = None             # e.g. "Foreword", "Clause 3.1", "Annex A"
    document_section: str | None = None    # broader section in the document

    # The actual evidence text
    excerpt: str | None = None

    # Gazette-specific (QCO, amendment notifications)
    gazette_so_number: str | None = None   # e.g. "S.O. 219(E)"
    publication_date: date | None = None

    # Amendment-specific
    amendment_number: int | None = None

    # Tender-specific (CPPP/eProcure)
    tender_id: str | None = None           # e.g. "2026_DEPT_123456_1"
    corrigendum_number: int | None = None  # set if this evidence comes from a corrigendum

    # Retrieval metadata
    retrieval_date: datetime = Field(default_factory=_utcnow)
    retrieval_score: float | None = None   # semantic similarity score (0.0–1.0)
    confidence: float | None = None        # overall confidence in this evidence (0.0–1.0)


# ---------------------------------------------------------------------------
# Requirement — a single technical/certification requirement from a tender
# ---------------------------------------------------------------------------

class Requirement(BaseModel):
    """
    A single requirement extracted from a tender document.

    is_reference: the IS number as cited in the tender (may be outdated/wrong)
    cited_year: the year cited in the tender (may differ from current)
    location: where in the tender this was found (e.g. "Section 3, Clause 4.2")
    """
    id: str = Field(default_factory=_new_id)
    analysis_id: str

    text: str                               # raw requirement text as extracted
    normalized_text: str | None = None      # cleaned/normalized version
    category: RequirementCategory = RequirementCategory.OTHER

    # IS reference as cited in the tender
    is_reference: str | None = None         # e.g. "IS 10322"
    cited_year: int | None = None           # e.g. 2012 (the year cited in the tender)
    cited_designation: str | None = None    # full string as it appeared: "IS 10322:2012"

    # Source location in the tender document
    location: str | None = None             # e.g. "Section 5 - Technical Specifications, Clause 4.2"
    page: int | None = None

    # Extraction metadata
    extracted_at: datetime = Field(default_factory=_utcnow)
    extraction_confidence: float | None = None   # how confident the extractor was (0.0–1.0)

    # If this requirement came from a corrigendum (override of original tender)
    from_corrigendum: bool = False
    corrigendum_number: int | None = None


# ---------------------------------------------------------------------------
# Finding — the result of analysing one requirement
# ---------------------------------------------------------------------------

class Finding(BaseModel):
    """
    The result of analysing a single procurement requirement against standards and evidence.

    Every important field must be traceable to evidence.
    The AI/ML component returns finding_id, requirement_id, verdict, reason, and
    references to standard IDs and evidence IDs.

    The backend's analysis layer (kartikey/analysis/) assembles the actual
    Standard and Evidence objects from the database — the LLM does not generate them.

    currentness: describes the version situation detected
    dimensions: the per-axis assessment behind the single headline verdict
    cross_references: standards this one depends on, and which are uncited
    applicable_standards: the standards the system determined are relevant
    evidence: the evidence backing this finding
    """
    id: str = Field(default_factory=_new_id)
    requirement_id: str
    analysis_id: str

    verdict: Verdict
    reason: str                             # human-readable explanation
    recommended_action: str | None = None   # what the officer should do

    # What standards are actually applicable (may differ from what tender cited)
    applicable_standards: list[Standard] = []

    # Standards the tender cites that were assessed and found NOT to govern this
    # requirement — the "cited but not applicable" case.
    #
    # Three things a report must not conflate: a standard retrieval found
    # similar, a standard the tender names, and a standard that actually governs
    # the requirement. A tender specifying XLPE insulation while citing IS 1554
    # (PVC) has named a real, active, correctly-numbered standard that does not
    # cover its product. Leaving it in `applicable_standards` tells the officer
    # the citation is fine; dropping it entirely loses the citation they need to
    # fix. It belongs here, with `dimensions["scope"]` saying why.
    #
    # Everything the enrichment layer produced about it — status, currentness,
    # QCO, evidence, cross-references — is still reported, because the officer
    # needs all of it precisely because the tender cites it.
    cited_standards: list[Standard] = []

    # Version/currentness details (populated by enrichment layer)
    currentness: dict[str, Any] | None = None
    # e.g. {
    #   "cited": "IS 10322:2012",
    #   "current": "IS 10322 (Part 5/Sec 3):2022",
    #   "status": "superseded",
    #   "transition_deadline": "2024-01-01"
    # }

    # Per-dimension assessment, populated by the enrichment layer.
    #
    # `verdict` above is a single headline value because that is what the API
    # contract and the frontend badge switch on. But "the tender cites a 2012
    # edition" and "this clause narrows the vendor pool" are independent
    # judgements, and the severe one used to silently replace the other. This
    # field keeps each axis intact so the headline is explained rather than
    # substituted:
    #   {
    #     "applicability":  {"verdict": "potentially_over_restrictive", "confidence": 0.72,
    #                        "source": "ai"},
    #     "currentness":    {"label": "OUTDATED", "verdict": "outdated_reference",
    #                        "gap_years": 10, "source": "version_checker"},
    #     "certification":  {"qco_notified": true, "scheme": "isi_mark"},
    #     "headline":       {"verdict": "outdated_reference", "resolution": "compliance_override"}
    #   }
    dimensions: dict[str, Any] | None = None

    # Standards the cited standard itself depends on, and which of those the
    # tender never mentions. A tender that cites IS 16107 but not the IS 10322
    # it normatively references is incomplete even though every citation in it
    # is individually valid. One entry per applicable standard that has
    # references; see kshiraj/enrichment/crossref_extractor.py.
    cross_references: list[dict[str, Any]] = []

    # Evidence backing this finding
    evidence: list[Evidence] = []

    # Per-section availability, one entry per optional block the report renders.
    #
    # An empty `cross_references` is ambiguous on its own: it means either "this
    # standard publishes no normative references" or "the enrichment step never
    # ran". The frontend cannot tell those apart, so it either renders a blank
    # panel that looks broken or invents reassuring text. This field removes the
    # ambiguity by stating which it is, per section:
    #
    #   verified        real data is present in this section
    #   not_available   the source genuinely does not publish it
    #   not_assessed    the check could not run (a stage was unavailable)
    #   not_identified  the check ran and found nothing to report
    #
    # Populated by kartikey/analysis/findings.py. Never a substitute for data:
    # a section marked not_available stays empty, it is only labelled.
    data_availability: dict[str, str] = {}

    # Confidence and verification
    confidence: float                       # 0.0–1.0
    requires_human_verification: bool = False
    verification_reason: str | None = None  # why human verification is needed


# ---------------------------------------------------------------------------
# Analysis — the top-level job for one tender/description
# ---------------------------------------------------------------------------

class Analysis(BaseModel):
    """
    Represents one complete analysis job for a procurement input.

    A single analysis may contain many requirements and many findings.
    Status transitions: queued → extracting → retrieving → analyzing → enriching → completed
    """
    id: str = Field(default_factory=_new_id)
    input_type: InputType

    # Input
    raw_text: str | None = None             # set if input_type == TEXT
    document_id: str | None = None          # set if input_type == DOCUMENT
    document_filename: str | None = None

    # Tender metadata (extracted or user-provided)
    tender_id: str | None = None            # CPPP tender ID if known
    tender_title: str | None = None

    # Lifecycle
    status: AnalysisStatus = AnalysisStatus.QUEUED
    created_at: datetime = Field(default_factory=_utcnow)
    updated_at: datetime = Field(default_factory=_utcnow)
    error_message: str | None = None

    # Results
    requirements: list[Requirement] = []
    findings: list[Finding] = []

    # Summary (generated after analysis is complete)
    summary: str | None = None
    total_requirements: int = 0
    issues_found: int = 0

    # Extra metadata (for internal use)
    metadata: dict[str, Any] = Field(default_factory=dict)


# ---------------------------------------------------------------------------
# Simulation — what-if analysis (P2 feature, schema defined early for planning)
# ---------------------------------------------------------------------------

class SimulationScenario(BaseModel):
    """
    Represents a 'what-if' simulation:
    What happens if a specific requirement is removed or modified?

    This is a P2 feature — defined here so the data model is consistent
    when implementation begins. Do not implement before core pipeline works.
    """
    id: str = Field(default_factory=_new_id)
    analysis_id: str
    requirement_id: str

    # What change is being simulated
    change_type: str   # "remove" | "relax" | "modify"
    modified_text: str | None = None  # new requirement text if change_type == "modify"

    # Results
    status: str = "pending"           # pending | completed | failed
    affected_findings: list[Finding] = []
    impact_summary: str | None = None
    mandatory_violations: list[str] = []  # QCO/mandatory requirements that would be violated
    created_at: datetime = Field(default_factory=_utcnow)
