"""
ai-engine/src/gap_detector.py

Detects compliance gaps between a tender's requirements and the matched standard.

Key improvement: the old version checked whether *database fields were empty*.
This version checks whether *tender requirements are covered by the standard*.
That is a fundamentally different (and correct) thing to do.

Gap types:
  - PARAMETER_UNVERIFIABLE  : standard scope doesn't mention this parameter
  - CERTIFICATION_MISSING   : tender requires a cert the standard doesn't mention
  - OUTDATED_REF            : tender references an older edition
  - NO_TEST_METHOD          : standard has no test method for this parameter
  - SCOPE_UNCLEAR           : standard scope is null/empty, cannot verify coverage
"""

import logging
import re

logger = logging.getLogger(__name__)


def detect_gaps(standard_record: dict, query_understanding: dict | None = None) -> list[dict]:
    """
    Detect compliance gaps between the tender requirements and the standard.

    Parameters
    ----------
    standard_record : dict
        The top-matched standard record from the knowledge base.
    query_understanding : dict | None
        Parsed procurement requirements from query_understanding.parse_query().

    Returns
    -------
    list[dict] — structured gap objects, each with:
        gap_type        : str
        description     : str
        severity        : 'high' | 'medium' | 'low'
        recommendation  : str
    """
    gaps = []

    is_number = standard_record.get("is_number", "unknown")

    # `scope` has two shapes in the wild: the full KB stores a provenance dict
    # {value, source_type, verified}, while the older 50-record dev KB stores a
    # bare string (or null). Normalise both instead of assuming the dict, which
    # used to raise AttributeError on the string form and take out the whole
    # recommendation pipeline. A bare string carries no provenance, so it cannot
    # be treated as verified -- it falls through to SCOPE_UNCLEAR below.
    scope_raw = standard_record.get("scope")
    if isinstance(scope_raw, dict):
        scope_text = (scope_raw.get("value") or "").lower()
        scope_source = scope_raw.get("source_type", "unverified")
        is_verified = bool(scope_raw.get("verified", False))
    elif isinstance(scope_raw, str):
        scope_text = scope_raw.lower()
        scope_source = "unverified"
        is_verified = False
    else:
        scope_text = ""
        scope_source = "unverified"
        is_verified = False

    # 1. If scope is empty or synthetic, gap detection is unreliable
    if not scope_text or not is_verified:
        return [
            {
                "gap_type": "SCOPE_UNCLEAR",
                "description": f"Official verified scope for {is_number} is not available.",
                "severity": "medium",
                "recommendation": (
                    "Manually verify the standard's scope on bis.gov.in to confirm "
                    "it covers all technical requirements."
                )
            }
        ]

    search_text = (standard_record.get("search_text") or "").lower()
    combined_text = scope_text + " " + search_text
    test_methods = standard_record.get("test_methods") or []
    norm_refs = standard_record.get("normative_references") or []
    cert_data = standard_record.get("certification") or {}

    # -------------------------------------------------------------------
    # 2. No test methods — means compliance testing can't be specified
    # -------------------------------------------------------------------
    if not test_methods:
        gaps.append({
            "gap_type": "NO_TEST_METHOD",
            "description": f"No test methods are recorded for {is_number} in the knowledge base.",
            "severity": "low",
            "recommendation": (
                "Specify the applicable test clauses from the standard in the tender document "
                "to ensure vendors can demonstrate compliance."
            ),
        })

    # -------------------------------------------------------------------
    # 3. Check technical requirements against scope
    # -------------------------------------------------------------------
    if query_understanding:
        tech_reqs = query_understanding.get("technical_requirements") or []

        # Parameter name aliases for matching against scope text
        PARAM_ALIASES = {
            "power": ["watt", "power", "w ", "120w", "90w"],
            "voltage": ["volt", "voltage", "v ac", "vac"],
            "ip_rating": ["ip", "ingress protection", "ip6", "ip5"],
            "cct": ["color temperature", "colour temperature", "cct", "kelvin", "5700", "6500"],
            "efficacy": ["lm/w", "lumen", "efficacy", "luminous"],
            "thd": ["harmonic", "thd", "distortion"],
            "power_factor": ["power factor", "pf "],
            "surge_kv": ["surge", "spd", "kv"],
        }

        for req in tech_reqs:
            param = req.get("parameter", "")
            value = req.get("value", "")
            unit = req.get("unit", "")

            aliases = PARAM_ALIASES.get(param, [param.lower()])
            covered = any(alias in combined_text for alias in aliases)

            if not covered and scope_text.strip():
                gaps.append({
                    "gap_type": "PARAMETER_UNVERIFIABLE",
                    "description": (
                        f"The standard {is_number} scope does not explicitly mention "
                        f"'{param}' ({value} {unit}). Coverage cannot be automatically confirmed."
                    ),
                    "severity": "medium",
                    "recommendation": (
                        f"Verify that {is_number} includes requirements for {param} = {value} {unit}. "
                        "If not, a complementary standard may be required."
                    ),
                })

        # -------------------------------------------------------------------
        # 4. Certification requirements not in standard metadata
        # -------------------------------------------------------------------
        cert_reqs = query_understanding.get("certification_requirements") or []
        cert_keywords = [
            (cert_data.get("scheme") or ""),
            ("BIS" if cert_data.get("mandatory") else ""),
            (cert_data.get("qco") or ""),
        ]
        cert_text = " ".join(cert_keywords).lower()

        for cert_req in cert_reqs:
            if cert_req.lower() not in cert_text and cert_req.lower() not in combined_text:
                gaps.append({
                    "gap_type": "CERTIFICATION_MISSING",
                    "description": (
                        f"Tender requires '{cert_req}' certification, but this is not confirmed "
                        f"in the metadata for {is_number}."
                    ),
                    "severity": "high",
                    "recommendation": (
                        f"Verify BIS certification scheme for {is_number} on bis.gov.in "
                        f"to confirm whether '{cert_req}' is mandatory."
                    ),
                })

        # -------------------------------------------------------------------
        # 5. Explicit IS references in tender — cross-check they are present
        # -------------------------------------------------------------------
        explicit_refs = query_understanding.get("explicit_standard_refs") or []
        for ref in explicit_refs:
            ref_norm = ref.strip().lower().replace(" ", "")
            std_norm = is_number.lower().replace(" ", "").replace(":", "")
            if ref_norm.replace(":", "") not in std_norm and std_norm not in ref_norm.replace(":", ""):
                # The tender cites a standard that isn't the top match
                gaps.append({
                    "gap_type": "ADDITIONAL_STANDARD_CITED",
                    "description": (
                        f"Tender explicitly references '{ref}' which is different from the "
                        f"top-matched standard {is_number}."
                    ),
                    "severity": "high",
                    "recommendation": (
                        f"Ensure '{ref}' is also retrieved and reviewed — "
                        "it may be a mandatory companion standard."
                    ),
                })

    return gaps
