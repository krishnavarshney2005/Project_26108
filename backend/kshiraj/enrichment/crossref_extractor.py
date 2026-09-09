"""
kshiraj/enrichment/crossref_extractor.py

Deterministic extraction of cross-referenced Indian Standards from standard text or scope.

For a Standard input, all four reference-bearing fields are scanned: `scope`,
`text_excerpt`, `normative_references`, and `related_standards`. The last two
are the catalogue's own structured dependency lists and are the reason this is
worth running at all — a tender that cites IS 16107 but never mentions the
IS 10322 it normatively references is incomplete even though every citation in
it is individually valid.

Callers decide what an extracted reference *means*: this module reports what the
text says and nothing more. In particular it does not drop self-references
(IS 10322 Part 5 Sec 3 → IS 10322 Part 1 both normalise to "IS 10322"), because
whether that matters depends on the caller's question.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import List, Union

from shared.models import Standard

_IS_REF_RE = re.compile(
    r"IS\s+"                # "IS " prefix (case-insensitive)
    r"(\d+)"                # IS number digits
    r"(?:\s*\(([^)]+)\))?"  # optional (Part N/Sec M)
    r"(?:\s*:\s*(\d{4}))?"  # optional :YYYY year
    r"(?:\s+Amd\.?\s*(\d+))?",  # optional Amd.N
    re.IGNORECASE,
)


@dataclass(frozen=True)
class CrossRefResult:
    """
    Result of extracting IS cross-references from text or a Standard model.

    Attributes:
        source_is_number: The canonical IS number of the source standard (e.g. "IS 10322"),
                          or empty string if extracted from a raw string.
        referenced_is_numbers: Deduplicated list of base IS numbers (e.g. ["IS 2062", "IS 1608"])
                               in order of first appearance.
        raw_matches: Exact full matched reference strings (e.g. ["IS 10322 (Part 5/Sec 3):2012 Amd.2"]).
    """

    source_is_number: str
    referenced_is_numbers: List[str] = field(default_factory=list)
    raw_matches: List[str] = field(default_factory=list)


class CrossRefExtractor:
    """
    Extracts Indian Standard references from standard text or Standard objects.
    """

    def extract(self, text_or_standard: Union[str, Standard]) -> CrossRefResult:
        """
        Extract cross-references from either a raw text string or a Standard instance.

        Neither requirement nor standard is modified.
        """
        source_is_number = ""
        text_parts: List[str] = []

        if isinstance(text_or_standard, Standard):
            source_is_number = text_or_standard.is_number.strip()
            if text_or_standard.scope:
                text_parts.append(text_or_standard.scope)
            if text_or_standard.text_excerpt:
                text_parts.append(text_or_standard.text_excerpt)
            # The catalogue also records references as structured lists rather
            # than prose ("IS 10322 : Part 1"). They are the authoritative
            # dependencies — scope text only mentions them in passing, if at all
            # — so scan them too. Same regex: the entries are designation
            # strings, which is exactly what it matches.
            text_parts.extend(text_or_standard.normative_references)
            text_parts.extend(text_or_standard.related_standards)
            combined_text = "\n".join(text_parts)
        elif isinstance(text_or_standard, str):
            combined_text = text_or_standard
        else:
            return CrossRefResult(
                source_is_number="",
                referenced_is_numbers=[],
                raw_matches=[],
            )

        if not combined_text or not combined_text.strip():
            return CrossRefResult(
                source_is_number=source_is_number,
                referenced_is_numbers=[],
                raw_matches=[],
            )

        raw_matches: List[str] = []
        referenced_is_numbers: List[str] = []
        seen_is_numbers: set[str] = set()

        for match in _IS_REF_RE.finditer(combined_text):
            raw_match = match.group(0).strip()
            raw_matches.append(raw_match)

            is_digit = match.group(1)
            norm_is_num = f"IS {is_digit}"

            if norm_is_num not in seen_is_numbers:
                seen_is_numbers.add(norm_is_num)
                referenced_is_numbers.append(norm_is_num)

        return CrossRefResult(
            source_is_number=source_is_number,
            referenced_is_numbers=referenced_is_numbers,
            raw_matches=raw_matches,
        )
