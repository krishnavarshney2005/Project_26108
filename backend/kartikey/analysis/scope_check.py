"""
kartikey/analysis/scope_check.py

Deterministic detection of a citation that names the wrong standard for the
product actually specified.

The problem this solves
-----------------------
A tender that asks for "1.1 kV grade XLPE insulated armoured power cables ...
conforming to IS 1554 : Part 1" has cited a real, active, BIS-published standard
— and the wrong one. IS 1554 Part 1 covers *PVC* insulated cables. Every check
this codebase had before this module would pass that citation: the standard
exists, it is not withdrawn, it is not superseded, its QCO is recorded. The
year-and-status checks cannot see the defect because the defect is not about
years or status. It is about what the standard covers.

Three things a report must not confuse, and which this module keeps apart:

  retrieved   the retrieval stage found it similar to the document
  cited       the tender names it
  applicable  it actually governs the requirement

A citation can be all three, or cited without being applicable. That last case
is what this module detects, and it is reported as `Verdict.WRONG_SCOPE` — "the
IS exists but covers a different application" — rather than being forced into
`applicable_standards`.

Why this is not an LLM call
---------------------------
Because it does not need to be. BIS states the material in the *title*: "PVC
Insulated (Heavy Duty) Electric Cables", "Cross Linked Polyethylene (XLPE)
Insulated Thermoplastic Sheathed Cables". The catalogue is therefore its own
dictionary of which materials exist and which standards cover them, and the
comparison is a set difference. No model is asked to judge it, no vocabulary is
typed in by hand, and no synthetic data is involved — remove IS 7098 from the
catalogue and this module stops claiming XLPE is a known insulation material,
which is the correct behaviour rather than a bug.

What it deliberately does NOT do
--------------------------------
  - It does not check voltage bands, core counts, sizes or dimensions. Those
    need unit-aware range comparison against scope prose that most catalogue
    records do not carry.
  - It only reads material qualifiers written the way BIS writes them, i.e. the
    qualifier *preceding* the attribute ("XLPE insulated", "PVC insulation").
    "Insulated with XLPE" is not matched. Missing a mismatch costs a finding;
    inventing one tells a procurement officer to change a citation that was
    correct, so the bias is deliberate.
  - It never concludes that a citation is *right*. A standard whose material
    matches has only passed this one check.
"""

from __future__ import annotations

import re
import weakref
from dataclasses import dataclass, field

from shared.models import Requirement, Standard, StandardStatus
from shared.utils import get_logger

logger = get_logger(__name__)


# ===========================================================================
# Output type
# ===========================================================================

@dataclass
class ScopeCheck:
    """
    Result of comparing the material a requirement specifies against the
    material the cited standard covers.

    `checked` is the field to read first. False means the comparison could not
    be made — the requirement named no material, or the standard's title states
    none — and in that case `mismatch` being False says nothing at all about
    whether the citation is appropriate.
    """
    checked: bool
    mismatch: bool
    attribute: str | None = None
    required_material: str | None = None
    required_as_written: str | None = None
    covered_material: str | None = None
    alternatives: list[str] = field(default_factory=list)
    note: str = ""


_NOT_CHECKED = ScopeCheck(
    checked=False,
    mismatch=False,
    note="No material qualifier was found to compare; scope was not assessed.",
)


# ===========================================================================
# Title grammar
# ===========================================================================

# The attributes a material qualifies. Adjective form as BIS writes it in
# titles, plus the noun forms a tender is likely to use in prose.
_ATTRIBUTES: dict[str, tuple[str, ...]] = {
    "insulated": ("insulated", "insulation"),
    "sheathed": ("sheathed", "sheathing", "sheath"),
    "coated": ("coated", "coating"),
    "covered": ("covered",),
    "clad": ("clad", "cladding"),
    "lined": ("lined", "lining"),
    "plated": ("plated", "plating"),
    "galvanised": ("galvanised", "galvanized"),
    "bonded": ("bonded",),
}

_ATTRIBUTE_FORMS: dict[str, str] = {
    form: attribute
    for attribute, forms in _ATTRIBUTES.items()
    for form in forms
}

_ATTRIBUTE_RE = re.compile(
    r"\b(" + "|".join(sorted(_ATTRIBUTE_FORMS, key=len, reverse=True)) + r")\b",
    re.IGNORECASE,
)

# Words that cannot be part of a material name. Without this the title
# "Methods of tests for Covered ... wires" mines "Methods of tests for" as a
# material, and "Reels for Covered Round Electrical Winding Wires" mines
# "Reels for".
_FUNCTION_WORDS = frozenset({
    "a", "an", "and", "are", "as", "at", "be", "by", "for", "from", "in",
    "including", "is", "its", "of", "on", "or", "other", "per", "shall", "than",
    "the", "to", "up", "used", "with", "grade", "type", "types", "specification",
    "specifications", "methods", "method", "test", "tests", "requirements",
    "general", "part", "section", "sec",
})

# Aliases too generic to identify a material on their own.
_ALIAS_STOPWORDS = frozenset({
    "electric", "electrical", "cable", "cables", "wire", "wires", "round",
    "flexible", "heavy", "duty", "power", "single", "double", "multi", "core",
})

# A word inside a title or requirement. Parentheses are kept so an acronym
# written "(XLPE)" survives tokenization and can be split out as an alias.
_WORD_RE = re.compile(r"\(?[A-Za-z][A-Za-z0-9\-]*\)?")

# Punctuation that ends a material phrase. A qualifier never spans one.
#
# Parentheses are deliberately absent. BIS writes the acronym inside the name —
# "Cross Linked Polyethylene (XLPE) Insulated" — so treating ")" as a break
# leaves nothing between it and the attribute, and the single most important
# material in this catalogue goes unmined.
_PHRASE_BREAK_RE = re.compile(r"[,.;:!?\[\]/–—-]")

# How far back from the attribute word to look, and how many words a material
# name may run to.
_LOOKBACK_CHARS = 80
_MAX_MATERIAL_WORDS = 4
_MIN_ALIAS_CHARS = 3


def _aliases_for(phrase: str) -> set[str]:
    """
    Matchable forms of a material name.

    "Cross Linked Polyethylene (XLPE)" yields both the full name and the
    acronym, because a tender may use either and they mean the same material.
    """
    aliases: set[str] = set()

    acronyms = re.findall(r"\(([A-Za-z][A-Za-z0-9\-]{1,11})\)", phrase)
    bare = re.sub(r"\([^)]*\)", " ", phrase)
    bare = " ".join(bare.split()).casefold()

    for candidate in [bare, *(a.casefold() for a in acronyms)]:
        if (
            len(candidate) >= _MIN_ALIAS_CHARS
            and candidate not in _ALIAS_STOPWORDS
            and not all(w in _ALIAS_STOPWORDS for w in candidate.split())
        ):
            aliases.add(candidate)

    return aliases


def _material_phrase_before(text: str, stop: int) -> str | None:
    """
    Read the material name immediately preceding `stop` in `text`.

    Walks back word by word from the attribute, stopping at punctuation or at
    the first word that cannot be part of a material name, then returns what is
    left. Returns None when nothing usable precedes the attribute.
    """
    window = text[max(0, stop - _LOOKBACK_CHARS):stop]

    # Only the run since the last phrase break belongs to this attribute.
    breaks = list(_PHRASE_BREAK_RE.finditer(window))
    if breaks:
        window = window[breaks[-1].end():]

    words = _WORD_RE.findall(window)
    if not words:
        return None

    kept: list[str] = []
    for word in reversed(words[-_MAX_MATERIAL_WORDS:]):
        token = word.strip("()").casefold()
        if token in _FUNCTION_WORDS:
            break
        # A material name cannot contain another attribute. "Cross Linked
        # Polyethylene (XLPE) Insulated Thermoplastic Sheathed" states two
        # separate facts, and without this the sheath material reads as
        # "Polyethylene (XLPE) Insulated Thermoplastic".
        if token in _ATTRIBUTE_FORMS:
            break
        kept.append(word)

    if not kept:
        return None
    return " ".join(reversed(kept))


def _normalize_material(phrase: str) -> str:
    """
    Identity of a material, independent of spacing and case.

    The catalogue spells the same material both "Partial Discharge Free
    Electrical" and "Partial Discharge free Electrical". Treated as two
    materials they collide on every alias, and the alias is then dropped as
    ambiguous — losing the material entirely over a capital letter.
    """
    return " ".join(phrase.split()).casefold()


# ===========================================================================
# Vocabulary mined from the catalogue
# ===========================================================================

@dataclass(frozen=True)
class _Vocabulary:
    """
    Which materials the catalogue knows about, and which standards cover them.

    Materials are identified by their normalized form (see
    `_normalize_material`); `display` holds the spelling BIS actually used, for
    anything a person will read.

    alias_to_material:  (attribute, alias)    -> material key
    coverage:           (attribute, material) -> designations covering it
    display:            material key          -> BIS's own spelling
    """
    alias_to_material: dict[tuple[str, str], str]
    coverage: dict[tuple[str, str], list[str]]
    display: dict[str, str]

    def material_for(self, attribute: str, alias: str) -> str | None:
        return self.alias_to_material.get((attribute, alias))

    def spelling_of(self, material: str) -> str:
        return self.display.get(material, material)

    def aliases_for(self, attribute: str) -> list[str]:
        """Longest first, so "cross linked polyethylene" wins over a substring."""
        return sorted(
            (alias for attr, alias in self.alias_to_material if attr == attribute),
            key=len,
            reverse=True,
        )


# Keyed on the StandardsStore instance so a rebuilt registry gets a rebuilt
# vocabulary, and a discarded store does not keep one alive.
_VOCAB_CACHE: "weakref.WeakKeyDictionary[object, _Vocabulary]" = (
    weakref.WeakKeyDictionary()
)


def _build_vocabulary(standards: list[Standard]) -> _Vocabulary:
    """Mine every material qualifier BIS states in a title in the catalogue."""
    alias_to_material: dict[tuple[str, str], str] = {}
    ambiguous: set[tuple[str, str]] = set()
    coverage: dict[tuple[str, str], list[str]] = {}
    display: dict[str, str] = {}

    for std in standards:
        for attribute, phrase in _materials_in(std.title or ""):
            material = _normalize_material(phrase)
            display.setdefault(material, phrase)

            # Aliases are mined from every record, including withdrawn ones — a
            # withdrawn standard still tells us the material exists and is worth
            # recognising in a tender. Coverage is not: a withdrawn standard must
            # never be offered to an officer as the standard to cite instead.
            if std.status != StandardStatus.WITHDRAWN:
                key = (attribute, material)
                coverage.setdefault(key, [])
                if std.designation not in coverage[key]:
                    coverage[key].append(std.designation)

            for alias in _aliases_for(phrase):
                alias_key = (attribute, alias)
                existing = alias_to_material.get(alias_key)
                if existing is not None and existing != material:
                    # Two materials answer to the same word. Trusting either one
                    # would be a guess, so the alias is dropped.
                    ambiguous.add(alias_key)
                    continue
                alias_to_material[alias_key] = material

    for alias_key in ambiguous:
        alias_to_material.pop(alias_key, None)

    return _Vocabulary(
        alias_to_material=alias_to_material,
        coverage=coverage,
        display=display,
    )


def _materials_in(text: str) -> list[tuple[str, str]]:
    """
    Every `(attribute, material)` pair stated in `text`, in order.

    Used on titles to build the vocabulary and on a cited standard's title to
    read what it covers. Not used on requirement prose — see
    `_required_materials`, which matches known aliases instead of trusting
    whatever words happen to precede the attribute.
    """
    found: list[tuple[str, str]] = []
    for match in _ATTRIBUTE_RE.finditer(text):
        attribute = _ATTRIBUTE_FORMS[match.group(1).casefold()]
        phrase = _material_phrase_before(text, match.start())
        if not phrase:
            continue
        if not _aliases_for(phrase):
            continue
        pair = (attribute, phrase)
        if pair not in found:
            found.append(pair)
    return found


def _vocabulary() -> _Vocabulary | None:
    """
    The mined vocabulary for the live catalogue, or None if no catalogue is
    loaded — in which case no scope claim can be made and none is.
    """
    # Imported lazily: this module is part of the analysis layer and must not
    # depend on orchestration at import time.
    from kartikey.orchestration.knowledge_registry import get_registry

    try:
        store = get_registry().standards_store
    except Exception:
        return None

    cached = _VOCAB_CACHE.get(store)
    if cached is not None:
        return cached

    try:
        standards = store.list_all()
    except Exception:
        return None
    if not standards:
        return None

    vocabulary = _build_vocabulary(standards)
    try:
        _VOCAB_CACHE[store] = vocabulary
    except TypeError:
        # Store implementation does not support weak references; recompute.
        pass

    logger.debug(
        "scope_check: mined %d material aliases across %d attribute/material "
        "pairs from %d standards.",
        len(vocabulary.alias_to_material), len(vocabulary.coverage), len(standards),
    )
    return vocabulary


# ===========================================================================
# Requirement side
# ===========================================================================

def _required_materials(
    text: str, vocabulary: _Vocabulary,
) -> list[tuple[str, str, str]]:
    """
    `(attribute, canonical material, alias as written)` for each material the
    requirement specifies.

    Only aliases already known to the catalogue are matched. An unrecognised
    word before "insulated" is not evidence of anything — it may be a typo, a
    trade name, or a material BIS has no standard for — so it is ignored rather
    than reported as a mismatch.
    """
    results: list[tuple[str, str, str]] = []

    for match in _ATTRIBUTE_RE.finditer(text):
        attribute = _ATTRIBUTE_FORMS[match.group(1).casefold()]
        window = text[max(0, match.start() - _LOOKBACK_CHARS):match.start()]
        breaks = list(_PHRASE_BREAK_RE.finditer(window))
        if breaks:
            window = window[breaks[-1].end():]
        haystack = " ".join(window.split()).casefold()
        if not haystack:
            continue

        for alias in vocabulary.aliases_for(attribute):
            if re.search(rf"(?<![a-z0-9]){re.escape(alias)}(?![a-z0-9])", haystack):
                material = vocabulary.material_for(attribute, alias)
                if material and (attribute, material, alias) not in results:
                    results.append((attribute, material, alias))
                break

    return results


def _standard_mentions(standard: Standard, aliases: set[str]) -> bool:
    """
    True if the standard's own record mentions the material anywhere.

    Deliberately generous, and checked before any mismatch is reported: a
    standard whose scope prose covers XLPE must not be called wrong for XLPE
    just because its title happens to lead with PVC.
    """
    haystack = " ".join(
        part for part in (
            standard.title,
            standard.scope,
            " ".join(standard.keywords or []),
            " ".join(standard.product_categories or []),
        ) if part
    ).casefold()

    return any(
        re.search(rf"(?<![a-z0-9]){re.escape(alias)}(?![a-z0-9])", haystack)
        for alias in aliases
    )


# ===========================================================================
# Public API
# ===========================================================================

def check_scope(requirement: Requirement, standard: Standard) -> ScopeCheck:
    """
    Compare the material the requirement specifies against the material the
    cited standard covers.

    Returns a `ScopeCheck` whose `mismatch` is True only when all of the
    following hold, each of which is a fact read out of the catalogue:

      1. The requirement names a material the catalogue knows, for an attribute
         (insulation, sheathing, ...) the catalogue distinguishes on.
      2. The cited standard's title states a *different* material for that same
         attribute — so both sides made a claim about the same slot.
      3. That material appears nowhere in the cited standard's title, scope,
         keywords or categories.

    Anything less returns `checked=False`, which reports that scope was not
    assessed rather than implying it passed. In particular `mismatch=False` with
    `checked=True` means one attribute was compared and agreed — never that the
    citation as a whole is correct.
    """
    text = " ".join(
        part for part in (requirement.text, requirement.normalized_text) if part
    )
    if not text or not _ATTRIBUTE_RE.search(text):
        return _NOT_CHECKED

    vocabulary = _vocabulary()
    if vocabulary is None:
        return ScopeCheck(
            checked=False,
            mismatch=False,
            note=(
                "The standards catalogue was not loaded, so the materials the "
                "cited standard covers could not be read. Scope was not assessed."
            ),
        )

    required = _required_materials(text, vocabulary)
    if not required:
        return _NOT_CHECKED

    # What the standard's own title states, keyed by attribute. Both sides are
    # normalized so the comparison is about materials, not capitalisation, but
    # the standard's own spelling is what gets quoted back.
    covered_phrase = dict(_materials_in(standard.title or ""))
    covered = {
        attribute: _normalize_material(phrase)
        for attribute, phrase in covered_phrase.items()
    }

    compared: list[tuple[str, str]] = []

    for attribute, material, as_written in required:
        covered_material = covered.get(attribute)
        if covered_material is None:
            # The standard's title makes no claim about this attribute, so there
            # is nothing to contradict. Common and not a defect: "Luminaires —
            # Part 5" states no material at all.
            continue
        compared.append((attribute, material))
        if covered_material == material:
            continue
        if _standard_mentions(standard, _aliases_for(vocabulary.spelling_of(material))):
            continue

        alternatives = [
            designation
            for designation in vocabulary.coverage.get((attribute, material), [])
            if designation != standard.designation
        ]
        material_name = vocabulary.spelling_of(material)

        return ScopeCheck(
            checked=True,
            mismatch=True,
            attribute=attribute,
            required_material=material_name,
            required_as_written=as_written,
            covered_material=covered_phrase[attribute],
            alternatives=alternatives,
            note=(
                f"The requirement specifies {as_written.upper()} {attribute}, but "
                f"{standard.designation} covers {covered_phrase[attribute]} "
                f"{attribute} ({standard.title}). The cited standard does not "
                f"mention {as_written.upper()} anywhere in its title, scope or "
                "keywords."
                + (
                    f" In this catalogue {attribute} with {material_name} is "
                    "covered by "
                    + ", ".join(alternatives)
                    + " — verify which standard applies before issuing the tender."
                    if alternatives else
                    " No standard covering this material was found in the "
                    "catalogue — verify on standardsbis.gov.in."
                )
            ),
        )

    # Falling out of the loop is not the same as agreeing. If the standard's
    # title stated no material for any attribute the requirement named, nothing
    # was compared, and saying so is the only honest answer — this branch used
    # to report a match, so a tender specifying XLPE and citing a standard whose
    # title mentions no material at all came back reassuring the officer that
    # the materials agreed.
    if not compared:
        return ScopeCheck(
            checked=False,
            mismatch=False,
            note=(
                f"The requirement specifies a material, but {standard.designation} "
                "does not state one in its title, so the two could not be "
                "compared. Scope was not assessed."
            ),
        )

    attribute, material = compared[0]
    return ScopeCheck(
        checked=True,
        mismatch=False,
        attribute=attribute,
        required_material=vocabulary.spelling_of(material),
        covered_material=covered_phrase.get(attribute),
        note=(
            f"The {attribute} material the requirement specifies "
            f"({vocabulary.spelling_of(material)}) matches what "
            f"{standard.designation} covers. This check does not assess voltage "
            "rating, size or any other parameter."
        ),
    )
