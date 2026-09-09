"""
kartikey/analysis/profile_extractor.py

Deterministic extraction of the procurement profile shown on the "Understanding
Procurement Requirements" screen: what is being bought, for what, under what
conditions, and which clauses in the document state technical, performance,
testing and regulatory requirements.

Why this exists rather than an LLM prompt
-----------------------------------------
That screen used to be produced by a single Gemini call. Three things followed
from that, and all three were visible in a demo:

  1. It was core logic behind an external quota. On a 429 the client retries with
     a growing sleep across several candidate models, so the request did not fail
     — it hung, and the loading screen hung with it.

  2. When the call did fail, the endpoint returned two invented requirements
     ("Equipment must be IP66 rated for outdoor use", "Must comply with BIS
     safety standards") and the product name "Unknown Entity". Those sentences
     were not in the user's document. A procurement officer reading them has no
     way to tell which lines came from their tender and which the system made up,
     which is worse than an error message.

  3. It put an LLM in front of the pipeline whose whole design is that the LLM is
     one degradable stage among many. The analysis itself already degrades to a
     deterministic path; the screen that introduces it did not.

So the profile is derived from the document text, by rules, offline. Every field
either quotes the document or says the document does not state it. Gemini is
still used — see `extract.py` — but only to *improve* the prose of `product`,
`application` and `environment` after this has run, under a hard timeout, and it
can never add or replace a requirement.

What this deliberately does not do
----------------------------------
It does not classify against the BIS catalogue, decide whether a cited standard
is right, or score anything. Those are the pipeline's job and it does them with
the retrieval and compliance machinery. This is an extraction step: it reports
what the document says.

It also does not guess a product name when the document has no procurement
phrasing to read one from. `product` is the heading of the whole screen, and a
wrong one reframes every requirement under it.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from kartikey.document_processing.extractor import iter_clauses, scan_is_references

# Shown wherever the document genuinely does not state something. One spelling,
# so the UI can style it and a reader learns to recognise it.
NOT_STATED = "Not stated in the document"


# ===========================================================================
# Output type
# ===========================================================================

@dataclass
class ProfileField:
    """One extracted line, quoted from the document."""
    id: str
    label: str
    value: str
    status: str          # "detected" — this layer never asserts more than that
    source_clause: str   # where in the document it was found

    def as_dict(self) -> dict:
        return {
            "id": self.id,
            "label": self.label,
            "value": self.value,
            "status": self.status,
            "sourceClause": self.source_clause,
        }


@dataclass
class ProcurementProfile:
    product: str
    category: str
    application: str
    environment: str
    technical_parameters: list[ProfileField] = field(default_factory=list)
    performance_requirements: list[ProfileField] = field(default_factory=list)
    testing_requirements: list[ProfileField] = field(default_factory=list)
    regulatory_mentions: list[ProfileField] = field(default_factory=list)

    def as_dict(self) -> dict:
        return {
            "product": self.product,
            "category": self.category,
            "application": self.application,
            "environment": self.environment,
            "technicalParameters": [f.as_dict() for f in self.technical_parameters],
            "performanceRequirements": [f.as_dict() for f in self.performance_requirements],
            "testingRequirements": [f.as_dict() for f in self.testing_requirements],
            "regulatoryMentions": [f.as_dict() for f in self.regulatory_mentions],
        }

    @property
    def total_fields(self) -> int:
        return (
            len(self.technical_parameters)
            + len(self.performance_requirements)
            + len(self.testing_requirements)
            + len(self.regulatory_mentions)
        )


# ===========================================================================
# Product
# ===========================================================================

# The phrasings Indian tender documents actually use to name their subject.
# Anchored at a word boundary and required to be followed by "of"/"for" so that
# prose like "the supplier shall" does not match.
_PRODUCT_LEAD = re.compile(
    r"\b("
    r"supply,?\s+(?:installation|erection)[^.]{0,60}?\s+of"
    r"|design,?\s+manufacture[^.]{0,60}?\s+of"
    r"|manufacture\s+and\s+supply\s+of"
    r"|supply\s+and\s+installation\s+of"
    r"|procurement\s+of"
    r"|purchase\s+of"
    r"|supply\s+of"
    r"|tender\s+for(?:\s+the\s+supply\s+of)?"
    r"|nit\s+for"
    r"|name\s+of\s+work\s*[:\-]"
    r"|subject\s*[:\-]"
    r")\s*",
    re.IGNORECASE,
)

# Where a product name stops. "for" is the usual one — "LED luminaires *for*
# municipal roads" splits the product from its application, which is exactly the
# distinction the two fields are supposed to draw.
_PRODUCT_TAIL = re.compile(
    r"\s+(?:for|to\s+be\s+|as\s+per|conforming|in\s+accordance|at\s+the|under\s+)\b",
    re.IGNORECASE,
)

_MAX_PRODUCT_CHARS = 90


def _extract_product(clauses: list[tuple[int, str]]) -> str:
    """
    Read the subject of the procurement out of the document's own phrasing.

    Earlier clauses win: a tender names what it is buying in its title or first
    line, and a later "supply of spare fuses" is a detail, not the subject.
    """
    for _, clause in clauses:
        match = _PRODUCT_LEAD.search(clause)
        if not match:
            continue
        rest = clause[match.end():].strip(" :—-")
        if not rest:
            continue
        tail = _PRODUCT_TAIL.search(rest)
        if tail and tail.start() >= 8:
            rest = rest[: tail.start()]
        rest = rest.strip(" ,.;:")
        if len(rest) < 4:
            continue
        if len(rest) > _MAX_PRODUCT_CHARS:
            # Cut on a word boundary rather than mid-word; a truncated product
            # name reads as a typo and undermines everything under it.
            cut = rest.rfind(" ", 0, _MAX_PRODUCT_CHARS)
            rest = rest[: cut if cut > 20 else _MAX_PRODUCT_CHARS].rstrip(" ,.;:")
        return rest
    return NOT_STATED


# ===========================================================================
# Category
# ===========================================================================

# A coarse classification of the *document*, not a BIS claim. Ordered: the first
# category with a hit wins, so the more specific families are listed first.
#
# This is deliberately shallow. A deeper taxonomy would start to look like an
# authoritative mapping to BIS division councils, which this is not — the
# catalogue supplies that during retrieval, from the standards it actually
# matched.
_CATEGORY_RULES: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("Outdoor Lighting", ("street light", "luminaire", "lamp post", "flood light",
                          "led driver", "lm/w", "street lighting")),
    ("Electrical Cables & Conductors", ("cable", "conductor", "xlpe", "sheathed",
                                        "armoured", "sqmm", "insulated wire")),
    ("Electrical Equipment", ("switchgear", "transformer", "circuit breaker",
                              "panel board", "distribution board", "motor",
                              "earthing", "busbar")),
    ("Construction Materials", ("cement", "aggregate", "reinforcement bar",
                                "structural steel", "concrete", "brick", "tmt")),
    ("Pipes & Fittings", ("pipe", "fitting", "valve", "flange", "gasket")),
    ("Medical Devices", ("syringe", "surgical", "medical device", "sterile",
                         "patient", "diagnostic")),
    ("IT Equipment", ("laptop", "desktop", "server", "router", "switch port",
                      "workstation", "printer")),
    ("Personal Protective Equipment", ("helmet", "safety shoe", "glove",
                                       "respirator", "protective clothing")),
    ("Furniture", ("furniture", "chair", "desk", "cupboard", "table top")),
    ("Vehicles", ("vehicle", "bus chassis", "ambulance", "tyre", "truck")),
)


def _extract_category(text: str, fallback: str) -> str:
    lowered = text.lower()
    for category, terms in _CATEGORY_RULES:
        if any(term in lowered for term in terms):
            return category
    return fallback or "General procurement"


# ===========================================================================
# Application
# ===========================================================================

_APPLICATION_LEAD = re.compile(
    r"\bfor\s+(?:the\s+|use\s+in\s+|installation\s+(?:in|at)\s+)?"
    r"((?:[A-Za-z0-9][\w\-/&]*\s+){1,9}?"
    r"(?:project|scheme|works?|road|roads|highway|street|streets|building|buildings"
    r"|hospital|school|campus|plant|substation|feeder|township|colony|corridor"
    r"|premises|site|department|division|network|system|lighting)\b)",
    re.IGNORECASE,
)

_MAX_APPLICATION_CHARS = 90


def _extract_application(clauses: list[tuple[int, str]]) -> str:
    for _, clause in clauses:
        match = _APPLICATION_LEAD.search(clause)
        if not match:
            continue
        phrase = " ".join(match.group(1).split()).strip(" ,.;:")
        if len(phrase) < 5:
            continue
        return phrase[:_MAX_APPLICATION_CHARS].rstrip(" ,.;:")
    return NOT_STATED


# ===========================================================================
# Environment
# ===========================================================================

# Each rule contributes only what it literally matched in the text. Nothing here
# infers a condition from another — "outdoor" does not imply a temperature range,
# and a demo that showed one would be inventing an operating condition.
#
# The pattern's group 1 is what gets shown, so for IP/IK it spans the whole
# designation: "IP66" is the name of the class, and "ingress protection 66" is
# not something a procurement officer would recognise.
_ENVIRONMENT_RULES: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("", re.compile(r"\b(IP\s?[0-6][0-9XK])\b", re.IGNORECASE)),
    ("", re.compile(r"\b(IK\s?(?:0[1-9]|10))\b", re.IGNORECASE)),
    ("", re.compile(
        r"(-?\d{1,3}\s?(?:°|deg(?:rees)?\s?)?C\s*(?:to|–|—|-)\s*\+?\d{1,3}\s?"
        r"(?:°|deg(?:rees)?\s?)?C)", re.IGNORECASE)),
    ("ambient temperature", re.compile(
        r"ambient\s+temperature[^.,;]{0,40}?(\d{1,3}\s?(?:°|deg)?\s?C)",
        re.IGNORECASE)),
    ("relative humidity", re.compile(
        r"(?:relative\s+)?humidity[^.,;]{0,30}?(\d{1,3}\s?%)", re.IGNORECASE)),
    ("altitude", re.compile(r"altitude[^.,;]{0,30}?(\d{2,5}\s?m(?:etres?)?)",
                            re.IGNORECASE)),
)

# Bare siting words. Matched whole so "outdoors" and "outdoor" both count while
# "indoor-style" prose elsewhere does not produce a duplicate.
_SITING_TERMS = (
    "outdoor", "indoor", "underground", "overhead", "coastal", "marine",
    "corrosive", "hazardous", "dusty", "submerged", "buried",
)


def _extract_environment(text: str) -> str:
    parts: list[str] = []
    seen: set[str] = set()

    for label, pattern in _ENVIRONMENT_RULES:
        match = pattern.search(text)
        if not match:
            continue
        value = " ".join(match.group(1).split())
        key = f"{label}:{value.lower()}"
        if key in seen:
            continue
        seen.add(key)
        parts.append(f"{label} {value}" if label else value)

    lowered = text.lower()
    siting = [term for term in _SITING_TERMS if re.search(rf"\b{term}s?\b", lowered)]
    if siting:
        parts.insert(0, ", ".join(siting))

    return "; ".join(parts) if parts else NOT_STATED


# ===========================================================================
# Requirement clauses
# ===========================================================================

# A clause earns a bucket by what it states. Order is priority: a clause citing
# a standard *and* giving a figure is a regulatory mention first, because that is
# the clause a compliance reviewer needs to find.
_TESTING_TERMS = (
    "test certificate", "type test", "routine test", "acceptance test",
    "nabl", "accredited laborator", "test report", "inspection",
    "sample shall", "testing shall", "test method", "shall be tested",
    "third party", "factory acceptance",
)

_CERTIFICATION_TERMS = (
    "bis certification", "bis registration", "isi mark", "isi marking",
    "cm/l", "crs scheme", "r-number", "hallmark", "licence number",
    "license number", "qco", "quality control order", "certificate of conformity",
)

_PERFORMANCE_TERMS = (
    "efficacy", "efficiency", "lumen", "lm/w", "power factor", "life",
    "burning hours", "thd", "surge", "output", "throughput", "tensile",
    "yield strength", "load", "flow rate", "accuracy", "warranty",
    "derating", "temperature rise", "insulation resistance",
)

# A figure with a unit. This is what separates a specification from prose: a
# tender clause that constrains a supplier almost always carries one.
_MEASURED_VALUE = re.compile(
    r"\d+(?:\.\d+)?\s?"
    r"(?:kv|v\b|kw|w\b|va\b|kva|a\b|ma\b|hz|mm|cm|m\b|km|sqmm|sq\.?\s?mm|mm2"
    r"|kg|g\b|ton|tonne|%|lm/w|lm\b|lux|k\b|°c|deg\s?c|nm|bar|mpa|n/mm2"
    r"|years?|months?|hours?|hrs?|core|way|watt|amp)",
    re.IGNORECASE,
)

# Class designations that constrain a supplier just as tightly as a figure but
# carry no unit. Without these, "Ingress protection shall be IP66 and impact
# protection IK08" states nothing as far as `_classify` is concerned, and the one
# clause a lighting tender is most likely to be judged on drops off the screen.
_CLASS_RATING = re.compile(
    r"\b(?:IP\s?[0-6][0-9XK]|IK\s?(?:0[1-9]|10)|class\s+[IVX]+\b"
    r"|grade\s+[A-Z0-9]{1,3}\b|type\s+[A-Z]{1,2}\d?\b)",
    re.IGNORECASE,
)


def _states_a_figure(clause: str) -> re.Match[str] | None:
    """A measured quantity or a class designation — either constrains a bid."""
    return _MEASURED_VALUE.search(clause) or _CLASS_RATING.search(clause)

# Clause text shorter than this is a heading or a fragment, not a requirement.
_MIN_CLAUSE_CHARS = 25
# Per-bucket cap. The screen is a review surface, not a dump of the document;
# beyond this the officer stops reading and the real findings get lost.
_MAX_PER_BUCKET = 12


def _location_for(offset: int, clause: str, text: str) -> str:
    """
    Describe where a clause came from, using the document's own numbering.

    Falls back to a character offset rather than inventing a section number —
    "Section 3.4" on a document with no section 3.4 is a fabricated citation, and
    the audit trail is the product.
    """
    numbered = re.match(r"^((?:Clause|Section|Item|Annex)\s+)?(\d{1,3}(?:\.\d{1,3})+)", clause)
    if numbered:
        return f"Clause {numbered.group(2)}"
    leading = re.match(r"^(\d{1,3})[.)]\s", clause)
    if leading:
        return f"Item {leading.group(1)}"
    line = text.count("\n", 0, offset) + 1
    return f"Line {line}"


def _classify(clause: str, has_is_reference: bool) -> str | None:
    """Return the bucket this clause belongs in, or None if it states nothing."""
    lowered = clause.lower()

    if has_is_reference or any(t in lowered for t in _CERTIFICATION_TERMS):
        return "regulatory"
    if any(t in lowered for t in _TESTING_TERMS):
        return "testing"
    if any(t in lowered for t in _PERFORMANCE_TERMS) and _states_a_figure(clause):
        return "performance"
    if _states_a_figure(clause):
        return "technical"
    return None


def _label_for(bucket: str, clause: str) -> str:
    """A short human label for the row, taken from the clause where possible."""
    lowered = clause.lower()
    if bucket == "regulatory":
        refs = scan_is_references(clause)
        if refs:
            return refs[0]["matched_text"]
        for term in _CERTIFICATION_TERMS:
            if term in lowered:
                return term.upper() if len(term) <= 5 else term.title()
        return "Regulatory requirement"
    if bucket == "testing":
        for term in _TESTING_TERMS:
            if term in lowered:
                return term.title()
        return "Testing requirement"
    if bucket == "performance":
        for term in _PERFORMANCE_TERMS:
            if term in lowered:
                return term.title()
        return "Performance requirement"
    measured = _states_a_figure(clause)
    return measured.group(0).strip() if measured else "Technical parameter"


# ===========================================================================
# Public API
# ===========================================================================

def extract_profile(text: str, fallback_category: str = "") -> ProcurementProfile:
    """
    Build the procurement profile from document text, deterministically.

    Parameters
    ----------
    text:
        Extracted document text, or pasted specification text.
    fallback_category:
        The category the caller already knows (the user picked it in the UI).
        Used only when the text gives no signal — it is the user's own input, not
        a guess this module made.

    Returns
    -------
    ProcurementProfile
        Populated from `text` alone. No network calls, no model, no invented
        values: fields the document does not state read `NOT_STATED`, and every
        requirement row quotes a clause that is in `text`.
    """
    if not text or not text.strip():
        return ProcurementProfile(
            product=NOT_STATED, category=fallback_category or "General procurement",
            application=NOT_STATED, environment=NOT_STATED,
        )

    clauses = iter_clauses(text)

    # Offsets of every IS citation, so a clause can be tested for one without
    # re-scanning per clause.
    ref_offsets = [ref["char_offset"] for ref in scan_is_references(text)]

    buckets: dict[str, list[ProfileField]] = {
        "technical": [], "performance": [], "testing": [], "regulatory": [],
    }
    seen_values: set[str] = set()
    counter = 0

    for offset, clause in clauses:
        if len(clause) < _MIN_CLAUSE_CHARS:
            continue
        clause_end = offset + len(clause)
        has_ref = any(offset <= ref < clause_end for ref in ref_offsets)

        bucket = _classify(clause, has_ref)
        if bucket is None or len(buckets[bucket]) >= _MAX_PER_BUCKET:
            continue

        key = clause.lower()
        if key in seen_values:
            continue
        seen_values.add(key)

        counter += 1
        buckets[bucket].append(ProfileField(
            id=f"req-{counter}",
            label=_label_for(bucket, clause),
            value=clause,
            status="detected",
            source_clause=_location_for(offset, clause, text),
        ))

    return ProcurementProfile(
        product=_extract_product(clauses),
        category=_extract_category(text, fallback_category),
        application=_extract_application(clauses),
        environment=_extract_environment(text),
        technical_parameters=buckets["technical"],
        performance_requirements=buckets["performance"],
        testing_requirements=buckets["testing"],
        regulatory_mentions=buckets["regulatory"],
    )


# Fields Gemini is allowed to improve, and only when this module found nothing.
# Requirement rows are absent by design: they quote the document, and a model
# rewriting a quote breaks the one guarantee the screen makes.
LLM_REFINABLE_FIELDS = ("product", "application", "environment")


def merge_llm_context(
    profile: ProcurementProfile, context: dict | None,
) -> tuple[ProcurementProfile, list[str]]:
    """
    Let the LLM fill only the prose fields this module could not read.

    Returns the profile and the list of field names the LLM actually supplied, so
    the response can declare its own provenance instead of presenting model
    output and document quotes as the same kind of fact.

    Deliberately one-directional: a field the document stated is never
    overwritten. The document is the evidence; the model is a convenience for the
    cases where the document is phrased in a way the rules above cannot read.
    """
    if not isinstance(context, dict):
        return profile, []

    refined: list[str] = []
    for name in LLM_REFINABLE_FIELDS:
        if getattr(profile, name) != NOT_STATED:
            continue
        value = context.get(name)
        if not isinstance(value, str):
            continue
        value = " ".join(value.split()).strip(" ,.;:")
        # Models answer "unknown" in a dozen ways; none of them is information.
        if len(value) < 4 or value.lower() in {
            "unknown", "unknown entity", "n/a", "na", "none", "not specified",
            "not stated", "not mentioned", "not applicable",
        }:
            continue
        setattr(profile, name, value)
        refined.append(name)

    return profile, refined
