"""Normalize live BIS metadata into the repository's existing shared models."""
from __future__ import annotations

import re
from datetime import date, datetime, timezone
from typing import Any

from shared.models import Amendment, DocumentType, Evidence, EvidenceSourceType, Standard, StandardStatus

PORTAL_URL = "https://standards.bis.gov.in/"

_IS_RE = re.compile(
    r"^\s*(IS\s*\d+)\s*(?:\((Part\s*\d+)(?:\s*/\s*(Sec\s*\d+))?\))?\s*(?::\s*(\d{4}))?\s*$",
    re.IGNORECASE,
)


def normalize_designation(value: str) -> str:
    value = re.sub(r"\s+", " ", value.strip())
    value = re.sub(r"\s*/\s*", "/", value)
    value = re.sub(r"\(\s*Part\s*", "(Part ", value, flags=re.I)
    value = re.sub(r"\(\s*Sec\s*", "(Sec ", value, flags=re.I)
    value = re.sub(r"\s*\)", ")", value)
    value = re.sub(r"\s*:\s*", ":", value)
    return value


def parse_designation(value: str) -> tuple[str, str | None, str | None, int | None]:
    normalized = normalize_designation(value)
    match = _IS_RE.match(normalized)
    if not match:
        raise ValueError(f"Unsupported BIS designation: {value!r}")
    number = re.sub(r"\s+", " ", match.group(1)).upper()
    part = match.group(2)
    section = match.group(3)
    year = int(match.group(4)) if match.group(4) else None
    return number, part, section, year


def _year(value: Any) -> int | None:
    if value is None or value == "":
        return None
    if isinstance(value, int):
        return value
    match = re.search(r"(?:19|20)\d{2}", str(value))
    return int(match.group(0)) if match else None


def _date(value: Any) -> date | None:
    if value is None or value == "":
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    text = str(value).strip()
    for fmt in ("%Y-%m-%d", "%Y/%m/%d", "%d-%m-%Y", "%d/%m/%Y"):
        try:
            return datetime.strptime(text[:10], fmt).date()
        except ValueError:
            continue
    return None


def _document_type(value: Any) -> DocumentType:
    text = str(value or "").strip().casefold()
    mapping = {
        "product specification": DocumentType.PRODUCT_SPECIFICATION,
        "code of practice": DocumentType.CODE_OF_PRACTICE,
        "method of test": DocumentType.METHOD_OF_TEST,
        "terminology": DocumentType.TERMINOLOGY,
        "guide": DocumentType.GUIDE,
    }
    return mapping.get(text, DocumentType.OTHER)


def _explicit_status(detail: dict[str, Any]) -> StandardStatus:
    """Use only explicit textual status signals; never guess from numeric BIS codes."""
    if int(detail.get("withdrawStatus") or 0) == 1:
        return StandardStatus.WITHDRAWN

    explicit = str(
        detail.get("status")
        or detail.get("standardStatus")
        or detail.get("statusName")
        or ""
    ).strip().casefold()
    if "withdraw" in explicit or "cancel" in explicit:
        return StandardStatus.WITHDRAWN
    if "supersed" in explicit or "replac" in explicit:
        return StandardStatus.SUPERSEDED
    if "active" in explicit or "current" in explicit or "valid" in explicit:
        return StandardStatus.ACTIVE

    if detail.get("superseded_byis"):
        return StandardStatus.SUPERSEDED

    # Numeric isStatus has not been mapped because its enum semantics are not
    # established. UNKNOWN is safer than presenting an inferred lifecycle state.
    return StandardStatus.UNKNOWN


def normalize_amendments(items: list[dict[str, Any]], source_url: str) -> list[Amendment]:
    result: list[Amendment] = []
    for item in items:
        number = item.get("noOfAmendment") or item.get("amendmentNumber") or item.get("number")
        try:
            number = int(number)
        except (TypeError, ValueError):
            continue

        year = _year(item.get("amendmentYear") or item.get("year") or item.get("date"))
        effective = _date(
            item.get("effectiveDate")
            or item.get("effective_date")
            or item.get("amendmentDate")
            or item.get("date")
        )
        description = item.get("amendmentLabel") or item.get("description") or item.get("title")
        result.append(
            Amendment(
                amendment_number=number,
                year=year,
                description=description,
                gazette_so_number=item.get("gazetteSoNumber") or item.get("gazette_so_number"),
                effective_date=effective,
                source_url=source_url,
            )
        )

    unique: dict[tuple[int, int | None, str | None], Amendment] = {}
    for item in result:
        unique[(item.amendment_number, item.year, item.description)] = item
    return sorted(unique.values(), key=lambda x: (x.amendment_number, x.year or 0))


def normalize_standard(
    detail: dict[str, Any],
    amendments: list[dict[str, Any]] | None = None,
    *,
    source_url: str = PORTAL_URL,
) -> tuple[Standard, list[Evidence]]:
    designation = normalize_designation(str(detail.get("standardNumber") or ""))
    is_number, part, section, year = parse_designation(designation)
    retrieved_at = datetime.now(timezone.utc)
    parsed_amendments = normalize_amendments(amendments or [], source_url)

    std = Standard(
        is_number=is_number,
        part=part,
        section=section,
        year=year,
        amendments=parsed_amendments,
        title=str(detail.get("standardName") or detail.get("shortTitle") or designation).strip(),
        scope=None,
        document_type=_document_type(detail.get("typeOfStandardId") or detail.get("standardType")),
        ics_code=detail.get("icsCode") or detail.get("ics_code"),
        division_council=detail.get("groupName") or detail.get("divisionCouncil"),
        technical_committee=detail.get("committeeName") or detail.get("technicalCommittee"),
        status=_explicit_status(detail),
        reaffirmation_year=_year(detail.get("reAffirmationYear") or detail.get("reaffirmationYear")),
        superseded_by=detail.get("superseded_byis") or detail.get("supersededBy") or None,
        withdrawal_date=_date(detail.get("withdrawOn") or detail.get("withdrawalDate")),
        source_url=source_url,
        retrieved_at=retrieved_at,
    )

    evidence: list[Evidence] = [
        Evidence(
            source_type=EvidenceSourceType.BIS_STANDARD,
            source_name=f"BIS Standards Portal — {designation}",
            authority="BIS",
            url=source_url,
            section="Standard metadata",
            excerpt=(
                f"{designation}; title: {std.title}; published: {detail.get('publishedOn')}; "
                f"status: {std.status.value}; reaffirmation: {detail.get('reAffirmationYear') or None}; "
                f"superseded_by: {std.superseded_by or None}."
            ),
            publication_date=_date(detail.get("publishedOn")),
            retrieval_date=retrieved_at,
            confidence=1.0,
        )
    ]

    for amendment in parsed_amendments:
        evidence.append(
            Evidence(
                source_type=EvidenceSourceType.BIS_AMENDMENT,
                source_name=f"BIS Amendment {amendment.amendment_number} — {designation}",
                authority="BIS",
                url=amendment.source_url or source_url,
                section="Amendment metadata",
                excerpt=amendment.description or f"Amendment {amendment.amendment_number}",
                publication_date=amendment.effective_date,
                amendment_number=amendment.amendment_number,
                retrieval_date=retrieved_at,
                confidence=1.0,
            )
        )
    return std, evidence

