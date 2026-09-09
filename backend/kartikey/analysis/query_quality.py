"""
kartikey/analysis/query_quality.py

Deterministic input-quality gate, run before anything expensive.

Why this exists
---------------
A user typing `fhbjfbdjvfdjhbdf` used to trigger the full pipeline: an LLM
extraction call, a hybrid retrieval sweep over 1028 standards, an ML
applicability scoring pass, and a Gemini final pass — several seconds and real
API spend to conclude nothing. Worse, the extractor is obliging: given noise it
sometimes returns a requirement anyway, and the report then presents a confident
analysis of a string that means nothing.

So the gate is cheap and it runs first. No model, no network, no retrieval — a
few regexes and character statistics over the input text.

Why not a length check
----------------------
Because the shortest inputs are the most legitimate. `IS 10322` is eight
characters and is the single most precise query this system can receive; `cable`
is five. Meanwhile `dhdjfhfjfjfjfjsjsjshshsjsjs` is twenty-seven characters of
nothing. Length carries no information here — the character *composition* does.

The decision rule
-----------------
The gate looks for affirmative evidence in both directions and rejects only when
one side is empty and the other is not:

    reject  <=>  no positive signal at all  AND  at least one gibberish token

Positive signals (any one is enough):

    designation   an IS / IEC / ISO / EN / ASTM number      -> "IS 10322"
    product code  letters and digits in one token           -> "N95", "VG30"
    vocabulary    a known procurement or technical term     -> "luminaire", "tender"
    specification a value with a unit or a standard code    -> "230V", "IP66", "2.5 sqmm"
    word-shaped   a token whose letters look like a word    -> "borewell"

That last one is deliberate and it is what keeps the gate honest. A valid query
about something whose vocabulary we do not carry must still get through — the
instruction is not to reject a query merely because we cannot match it to a
standard. So an unrecognised but well-formed word is treated as evidence of
meaning, and only *malformed* tokens count against the input.

Gibberish is decided per token, from four independent shape tests, and only for
tokens of six letters or more. That floor exists to protect the acronyms this
domain runs on: PVC, XLPE, THD, MCB, CRS, QCO, GeM and IS itself are all short
and several are all-consonant, so any vowel-based test would condemn them.

    no vowels             "fhbjfbdjvfdjhbdf"    0 vowels in 16 letters
    consonant run >= 5    "asdfghjkl"           9 consonants in a row
    <= 2 distinct letters "dhdjfhfjfjfjfj..."   5 distinct letters in 27
    keyboard run >= 5     "qwertyuiop"          ten adjacent keys

The keyboard test is what catches home-row mashing, which the vowel test misses
(`qwertyuiop` is 40% vowels). No English word runs five keys adjacent.

One aggregate rule supplements the per-token logic: input where four fifths of
the testable tokens are gibberish is rejected even if a real word appears among
them, because a stray recognisable token inside a wall of noise is a coincidence,
not a requirement. It does not apply when a designation is present — a tender
citing IS 10322 is analysable no matter how badly the surrounding text was OCRed.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from shared.utils import AnalysisError, get_logger

logger = get_logger(__name__)


# The message the API returns for rejected input. Fixed text: it tells the user
# what to do instead, which "invalid input" does not.
REJECTION_MESSAGE = (
    "Unable to identify a meaningful procurement requirement. "
    "Please enter a product, specification, or tender requirement."
)


class UnanalysableInputError(AnalysisError):
    """
    Raised by the pipeline when gated input reaches it (the document path).

    A subclass rather than a bare AnalysisError because the pipeline's generic
    handler writes ``f"[{code}] {message}"`` into error_message, and this one
    message has to reach the user exactly as written — a "[NOT_A_PROCUREMENT_
    REQUIREMENT]" prefix on a sentence addressed to a procurement officer is
    noise. The pipeline catches this first and copies the message through.
    """

    def __init__(self, signals: dict[str, object] | None = None) -> None:
        super().__init__(REJECTION_MESSAGE, code="NOT_A_PROCUREMENT_REQUIREMENT")
        self.signals = signals or {}


# ===========================================================================
# Positive signal 1 — standard designations
# ===========================================================================

# Deliberately looser than the extractor's pattern. This asks only "is the user
# naming a standard?", so it accepts forms the extractor would not fully parse
# ("IS10322", "IS:10322-2012") rather than rejecting the query over a space.
_DESIGNATION_RE = re.compile(
    r"""\b(
        IS | IS/IEC | IS/ISO | IEC | ISO | EN | BS | ASTM | ANSI | DIN | JIS | AWWA
    )\s*[:/-]?\s*\d{2,6}\b""",
    re.IGNORECASE | re.VERBOSE,
)


# ===========================================================================
# Positive signal 2 — vocabulary
# ===========================================================================

# Terms that establish the input is about procurement, standards, or engineering.
# Not a dictionary and not trying to be: it only has to be broad enough that
# ordinary tender prose lands at least one hit, with the word-shape signal below
# covering everything it misses.
_VOCABULARY: frozenset[str] = frozenset(
    """
    tender bid bidder bidding procurement purchase purchaser buyer supply supplier
    vendor contractor contract quotation rfp rfq eoi nit boq schedule rate
    specification specifications spec specs requirement requirements clause
    compliance compliant conform conforming conformity conformance deviation
    eligibility qualifying criteria technical commercial scope delivery warranty
    guarantee inspection acceptance testing test tests certificate certification
    certified accreditation nabl empanelled empanelment gem cppp eprocurement
    quantity unit rate price cost estimate emd security performance

    standard standards bis isi crs qco gazette notification amendment edition
    revision revised withdrawn superseded reaffirmed latest current version
    normative reference referenced annex annexure appendix

    luminaire luminaires lamp lamps lighting light led street road pole mast
    driver ballast lumen lumens luminous photometric colour color temperature
    cri flux efficacy glare illuminance photobiological ingress ip ipx surge
    protection thermal dissipation heatsink

    cable cables cabling conductor conductors core cores armoured unarmoured
    insulated insulation sheath sheathed pvc xlpe copper aluminium aluminum
    voltage volt volts current ampere amperes amp kilovolt kv lv ht
    earthing earth grounding busbar switchgear panel mcb mccb rcbo rccb elcb
    breaker contactor relay fuse isolator transformer motor motors pump pumps
    generator alternator inverter ups battery batteries solar photovoltaic pv
    frequency hertz hz phase power factor harmonic thd efficiency ie1 ie2 ie3 ie4

    pipe pipes pipeline fitting fittings valve valves flange gasket pumpset
    steel iron cement concrete reinforcement rebar tmt aggregate sand brick
    bitumen asphalt paint coating galvanised galvanized zinc plating
    tank vessel boiler compressor chiller hvac duct ducting fan blower
    plywood timber furniture fabric textile garment yarn

    dimension dimensions tolerance grade class classification type designation
    material construction mechanical electrical thermal chemical physical
    strength tensile impact bending hardness density thickness diameter length
    width height weight mass load rating capacity range accuracy calibration
    safety hazard risk fire flame retardant durability lifetime maintenance
    energy consumption label labelling marking mark packing packaging transport

    municipal corporation department ministry authority board council smart city
    railway highway airport hospital school water sewerage sanitation waste
    """.split()
)


# ===========================================================================
# Positive signal 3 — specification values
# ===========================================================================

# A number carrying a unit, or an engineering code. "230V", "IP66", "2.5sqmm",
# "50Hz", "1.5mm2", "IE3", "6kV". Strong evidence of a real technical query even
# with no surrounding words.
_SPEC_RE = re.compile(
    r"""(
        \bIP\s?\d{2}\b                                  # ingress protection
      | \bIPX\s?\d\b
      | \bIE\s?[1-4]\b                                  # motor efficiency class
      | \bCM/L\b                                        # BIS licence reference
      | \d+(?:\.\d+)?\s*
        (?: mm2? | sq\.?\s?mm | cm | m | km
          | v | kv | mv | a | ma | ka | w | kw | mw | va | kva
          | hz | khz | k | lm | lux | lx | cd | nm
          | kg | g | t | mpa | pa | bar | psi | rpm | hp
          | deg | °c | c | % )\b
    )""",
    re.IGNORECASE | re.VERBOSE,
)


# ===========================================================================
# Token shape
# ===========================================================================

_VOWELS = frozenset("aeiouy")

# Minimum letters before the shape tests apply. Six protects every acronym this
# domain uses (PVC, XLPE, THD, RCCB, DPIIT) from the vowel-based tests.
_SHAPE_MIN_LETTERS = 6

# Shortest token that can serve as weak positive evidence. Below three letters
# there is nothing to judge: "of", "mm", "kV" say nothing either way.
_WORDLIKE_MIN_LETTERS = 3

_MAX_CONSONANT_RUN = 4          # "strengths" reaches 4; nothing real exceeds it
_MIN_DISTINCT_LETTERS = 3       # "abababab" has 2
_MAX_KEYBOARD_RUN = 4           # adjacency steps; "qwerty" has 5

# QWERTY neighbours, used only to detect a finger dragged along a row.
_KEYBOARD_ROWS = ("qwertyuiop", "asdfghjkl", "zxcvbnm")
_KEYBOARD_NEIGHBOURS: dict[str, set[str]] = {}
for _row in _KEYBOARD_ROWS:
    for _i, _ch in enumerate(_row):
        _KEYBOARD_NEIGHBOURS.setdefault(_ch, set())
        if _i:
            _KEYBOARD_NEIGHBOURS[_ch].add(_row[_i - 1])
        if _i + 1 < len(_row):
            _KEYBOARD_NEIGHBOURS[_ch].add(_row[_i + 1])


def _max_run(letters: str, predicate) -> int:
    best = run = 0
    for ch in letters:
        run = run + 1 if predicate(ch) else 0
        best = max(best, run)
    return best


def _max_keyboard_run(letters: str) -> int:
    """Longest chain of consecutive characters adjacent on a QWERTY row."""
    best = run = 0
    for previous, current in zip(letters, letters[1:]):
        run = run + 1 if current in _KEYBOARD_NEIGHBOURS.get(previous, ()) else 0
        best = max(best, run)
    return best


def _gibberish_reasons(letters: str) -> list[str]:
    """Which shape tests a token's letters fail. Empty means the token looks real."""
    reasons: list[str] = []

    if not any(ch in _VOWELS for ch in letters):
        reasons.append("no_vowels")
    if _max_run(letters, lambda ch: ch not in _VOWELS) > _MAX_CONSONANT_RUN:
        reasons.append("consonant_run")
    if len(set(letters)) < _MIN_DISTINCT_LETTERS:
        reasons.append("few_distinct_letters")
    if _max_keyboard_run(letters) > _MAX_KEYBOARD_RUN:
        reasons.append("keyboard_run")

    return reasons


def _is_short_wordlike(token: str, letters: str) -> bool:
    """
    Whether a 3-to-5-letter token is weak evidence of meaning.

    Tokens this short cannot face the vowel tests — half this domain's vocabulary
    is all-consonant acronyms — but they still carry information, and treating
    them as neutral rejected "N95 mask", which is an ordinary procurement query.

    Two shapes count:

        contains a vowel        "mask", "pipe", "tile", "wire", "tank"
        written as an acronym   "PVC", "THD", "MCB", "XLPE", "GeM"

    A short all-consonant token in lower case is neither, so "kjh gfd saq" earns
    nothing and stays rejectable — which is the case this distinction exists for.
    """
    if any(ch in _VOWELS for ch in letters):
        return True
    return token.isupper()


# ===========================================================================
# Result
# ===========================================================================

@dataclass
class QueryQuality:
    """
    The gate's verdict, with the evidence that produced it.

    `signals` and `rejected_tokens` exist so that a disputed decision can be
    explained without re-running anything — the API surfaces them, which is the
    difference between "your input was rejected" and a user who can see why.
    """
    is_meaningful: bool
    message: str | None = None
    signals: dict[str, object] = field(default_factory=dict)
    rejected_tokens: list[str] = field(default_factory=list)


# ===========================================================================
# The gate
# ===========================================================================

# Tokens are letters/digits with internal punctuation the sources use in
# designations and specs, so "IS 10322", "2.5mm2" and "IP-66" stay whole.
_TOKEN_RE = re.compile(r"[A-Za-z0-9]+(?:[./\-'][A-Za-z0-9]+)*")

# A product or grade code: letters and digits in one token. "N95", "VG30",
# "DN300", "M20", "Fe500", "T8", "R410a", "ACSR-Panther". Procurement text is
# full of these and they are frequently the entire query, so a bare one has to
# pass — while a bare "12345" still says nothing and does not.
_CODE_RE = re.compile(r"\b(?=[A-Za-z0-9]*[A-Za-z])(?=[A-Za-z0-9]*\d)[A-Za-z0-9]{2,}\b")

# Letters outside the ASCII range — Devanagari, Tamil, Bengali and the rest.
# Indian tender documents are routinely bilingual and the shape tests above are
# Latin-only, so without this a requirement written in Hindi is invisible to
# every signal and gets rejected as empty. Text in an Indic script is also
# affirmative evidence on its own: it takes a deliberate input method to produce,
# which is not how keyboard mashing happens.
_NON_LATIN_RE = re.compile(r"[^\W\dA-Za-z_]", re.UNICODE)

# Above this share of gibberish, a stray real word is coincidence, not meaning.
_GIBBERISH_DOMINANCE = 0.8
_DOMINANCE_MIN_TOKENS = 3

# Enough non-Latin letters to be a phrase rather than a stray symbol.
_MIN_NON_LATIN_LETTERS = 3

# Only the opening of a long document is examined. A tender's first few thousand
# characters always carry its subject; scanning a 200-page PDF to reach the same
# answer would make a gate that exists to be cheap expensive.
_MAX_SCAN_CHARS = 4000


def assess_query(text: str | None) -> QueryQuality:
    """
    Decide whether *text* states something analysable.

    Deterministic and side-effect free: no model call, no network, no retrieval.
    Same input always yields the same verdict.
    """
    if text is None or not text.strip():
        return QueryQuality(
            is_meaningful=False,
            message=REJECTION_MESSAGE,
            signals={"reason": "empty"},
        )

    sample = text.strip()[:_MAX_SCAN_CHARS]

    has_designation = bool(_DESIGNATION_RE.search(sample))
    has_spec = bool(_SPEC_RE.search(sample))
    has_code = bool(_CODE_RE.search(sample))
    non_latin_letters = len(_NON_LATIN_RE.findall(sample))

    tokens = _TOKEN_RE.findall(sample)
    vocabulary_hits: list[str] = []
    word_shaped: list[str] = []
    gibberish: list[str] = []
    short_wordlike: list[str] = []
    malformed_short: list[str] = []
    testable = 0

    for token in tokens:
        letters = "".join(ch for ch in token if ch.isalpha()).casefold()

        if letters and letters in _VOCABULARY:
            vocabulary_hits.append(letters)
            continue

        if len(letters) < _WORDLIKE_MIN_LETTERS:
            # A unit, an initial, a bare number. Neutral either way.
            continue

        if len(letters) < _SHAPE_MIN_LETTERS:
            # Too short for the shape tests, which need enough letters to make a
            # vowel ratio meaningful. Weighed against each other below rather
            # than trusted outright: one "mask" is a real query, but one "saq"
            # among three consonant clusters is mashing.
            if _is_short_wordlike(token, letters):
                short_wordlike.append(token)
            else:
                malformed_short.append(token)
            continue

        testable += 1
        if _gibberish_reasons(letters):
            gibberish.append(token)
        else:
            word_shaped.append(token)

    signals: dict[str, object] = {
        "designation": has_designation,
        "specification": has_spec,
        "product_code": has_code,
        "vocabulary_hits": len(vocabulary_hits),
        "word_shaped_tokens": len(word_shaped),
        "short_wordlike_tokens": len(short_wordlike),
        "gibberish_tokens": len(gibberish),
        "malformed_short_tokens": len(malformed_short),
        "non_latin_letters": non_latin_letters,
        "tokens_examined": len(tokens),
        "sample_terms": sorted(set(vocabulary_hits))[:8],
    }

    positive = (
        has_designation
        or has_spec
        or has_code
        or bool(vocabulary_hits)
        or bool(word_shaped)
        or non_latin_letters >= _MIN_NON_LATIN_LETTERS
        # Short tokens are the weakest evidence there is, so they only carry the
        # input when they outnumber the malformed ones beside them.
        or len(short_wordlike) > len(malformed_short)
    )

    # Affirmative gibberish is required to reject. Absence of recognition is not
    # enough — that would reject valid queries about products we have no
    # vocabulary for, which is exactly what this gate must not do.
    malformed = gibberish + malformed_short
    if not positive and malformed:
        return QueryQuality(
            is_meaningful=False,
            message=REJECTION_MESSAGE,
            signals={**signals, "reason": "no_meaningful_content"},
            rejected_tokens=malformed[:10],
        )

    # Nothing positive and nothing negative: a bare number, or punctuation. There
    # is no requirement in it to analyse.
    if not positive:
        return QueryQuality(
            is_meaningful=False,
            message=REJECTION_MESSAGE,
            signals={**signals, "reason": "no_analysable_content"},
        )

    if (
        not has_designation
        and testable >= _DOMINANCE_MIN_TOKENS
        and len(gibberish) / testable >= _GIBBERISH_DOMINANCE
    ):
        return QueryQuality(
            is_meaningful=False,
            message=REJECTION_MESSAGE,
            signals={**signals, "reason": "dominated_by_gibberish"},
            rejected_tokens=gibberish[:10],
        )

    return QueryQuality(is_meaningful=True, signals=signals)
