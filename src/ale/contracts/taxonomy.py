"""Room-type taxonomy and deterministic label normalisation (unitless).

The packaged ``taxonomy.yaml`` defines the room-type keys. ``Taxonomy.normalize_label``
maps a raw drawing label to a key by exact or prefix match on canonical forms (see
``canon``); there is no fuzzy matching.
"""

from __future__ import annotations

import functools
import re
import unicodedata
from pathlib import Path
from typing import Annotated, Final, Literal

import yaml
from pydantic import (
    AfterValidator,
    BaseModel,
    ConfigDict,
    PrivateAttr,
    StrictBool,
    StrictStr,
    model_validator,
)

from ale.contracts.enums import MacroZone, TypeCategory

__all__ = [
    "UNKNOWN",
    "LabelMatch",
    "RoomTypeDef",
    "RoomTypeKey",
    "Taxonomy",
    "canon",
    "canon_tokens",
    "load_taxonomy",
]

UNKNOWN: Final = "unknown"
TAXONOMY_PATH: Final = Path(__file__).with_name("taxonomy.yaml")

_CONFIG = ConfigDict(extra="forbid", frozen=True)
_KEY_RE = re.compile(r"^[a-z][a-z0-9_]*$")
_SEMVER_RE = re.compile(
    r"^(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)"
    r"(?:-[0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*)?(?:\+[0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*)?$"
)
_NON_ALNUM_RE = re.compile(r"[^A-Z0-9]")
_DIGITS_RE = re.compile(r"^\d+$")
_AREA_TOKEN_RE = re.compile(r"^\d+M2$")
_ROOM_NUMBER_RE = re.compile(r"^(?:\d+[A-Z]?|[A-Z]\d+)$")


def _remove_area_expressions(tokens: list[str]) -> list[str]:
    out: list[str] = []
    i = 0
    n = len(tokens)
    while i < n:
        tok = tokens[i]
        if _AREA_TOKEN_RE.match(tok):
            i += 1
            continue
        if _DIGITS_RE.match(tok):
            if i + 1 < n and tokens[i + 1] == "M2":
                i += 2
                continue
            if i + 2 < n and _DIGITS_RE.match(tokens[i + 1]) and tokens[i + 2] == "M2":
                i += 3
                continue
        out.append(tok)
        i += 1
    return out


def _merge_single_letters(tokens: list[str]) -> list[str]:
    out: list[str] = []
    run: list[str] = []
    for tok in [*tokens, ""]:  # "" is a sentinel that flushes the last run
        if len(tok) == 1:
            run.append(tok)
            continue
        if len(run) >= 2:
            out.append("".join(run))
        else:
            out.extend(run)
        run = []
        if tok:
            out.append(tok)
    return out


def canon_tokens(s: str) -> tuple[str, ...]:
    """Canonical token list of a label or synonym (see ``canon``)."""
    text = unicodedata.normalize("NFKC", s)
    text = unicodedata.normalize("NFD", text)
    text = "".join(c for c in text if not unicodedata.combining(c)).upper()
    tokens = _NON_ALNUM_RE.sub(" ", text).split()
    tokens = _remove_area_expressions(tokens)
    while tokens and _ROOM_NUMBER_RE.match(tokens[0]):
        tokens.pop(0)
    while tokens and _ROOM_NUMBER_RE.match(tokens[-1]):
        tokens.pop()
    return tuple(_merge_single_letters(tokens))


def canon(s: str) -> str:
    """Canonical form of a label or synonym.

    NFKC, strip accents (NFD + drop combining marks), upper-case; non ``A-Z0-9`` → space;
    tokenise; drop area expressions (``12 40 M2``, ``12M2``); drop leading/trailing room
    numbers (``12``, ``3A``, ``B12``); merge runs of ≥ 2 single-letter tokens; join with
    single spaces.
    """
    return " ".join(canon_tokens(s))


class RoomTypeDef(BaseModel):
    """One room type of the taxonomy."""

    model_config = _CONFIG

    key: StrictStr
    label_fr: StrictStr
    label_en: StrictStr
    category: TypeCategory
    default_macro_zone: MacroZone | None
    service_core: StrictBool
    synonyms: tuple[StrictStr, ...]


class LabelMatch(BaseModel):
    """Result of ``Taxonomy.normalize_label``."""

    model_config = _CONFIG

    key: StrictStr
    rule: Literal["exact", "prefix", "none"]
    matched_synonym: StrictStr | None
    canonical_input: StrictStr


class Taxonomy(BaseModel):
    """The room-type taxonomy (validated at load time)."""

    model_config = _CONFIG

    version: StrictStr
    types: tuple[RoomTypeDef, ...]

    # canonical synonym -> (type key, synonym as written); first occurrence in file order wins
    _exact: dict[str, tuple[str, str]] = PrivateAttr(default_factory=dict)
    # (canonical tokens, canonical string, type key, synonym as written), file order
    _synonyms: tuple[tuple[tuple[str, ...], str, str, str], ...] = PrivateAttr(default=())
    _by_key: dict[str, RoomTypeDef] = PrivateAttr(default_factory=dict)

    @model_validator(mode="after")
    def _integrity(self) -> Taxonomy:
        problems: list[str] = []
        if not _SEMVER_RE.match(self.version):
            problems.append(f"version {self.version!r} is not semver")
        seen: set[str] = set()
        owner: dict[str, str] = {}
        for t in self.types:
            if not _KEY_RE.match(t.key):
                problems.append(f"bad key {t.key!r} (must match ^[a-z][a-z0-9_]*$)")
            if t.key in seen:
                problems.append(f"duplicate key {t.key!r}")
            seen.add(t.key)
            if t.category is not TypeCategory.SPECIAL and not t.synonyms:
                problems.append(f"type {t.key!r} has no synonyms")
            for syn in t.synonyms:
                c = canon(syn)
                if not c:
                    problems.append(f"synonym {syn!r} of {t.key!r} has an empty canonical form")
                    continue
                other = owner.setdefault(c, t.key)
                if other != t.key:
                    problems.append(
                        f"canonical synonym {c!r} ({syn!r}) shared by types {other!r} and {t.key!r}"
                    )
        unknown = [t for t in self.types if t.key == UNKNOWN]
        if not unknown:
            problems.append(f"missing type {UNKNOWN!r}")
        else:
            u = unknown[0]
            if u.category is not TypeCategory.SPECIAL:
                problems.append(f"type {UNKNOWN!r} must have category SPECIAL")
            if u.synonyms:
                problems.append(f"type {UNKNOWN!r} must have no synonyms")
        if problems:
            raise ValueError("invalid taxonomy: " + "; ".join(problems))
        return self

    def model_post_init(self, context: object, /) -> None:
        """Build the lookup indexes (private, derived from the frozen fields)."""
        exact: dict[str, tuple[str, str]] = {}
        synonyms: list[tuple[tuple[str, ...], str, str, str]] = []
        for t in self.types:
            for syn in t.synonyms:
                toks = canon_tokens(syn)
                c = " ".join(toks)
                exact.setdefault(c, (t.key, syn))
                synonyms.append((toks, c, t.key, syn))
        self._exact = exact
        self._synonyms = tuple(synonyms)
        self._by_key = {t.key: t for t in self.types}

    def get(self, key: str) -> RoomTypeDef:
        """Return the type definition for ``key`` (``KeyError`` if absent)."""
        return self._by_key[key]

    def keys(self) -> tuple[str, ...]:
        """All type keys, in file order."""
        return tuple(t.key for t in self.types)

    def normalize_label(self, raw: str) -> LabelMatch:
        """Map a raw drawing label to a type key (exact, then longest proper-prefix match)."""
        toks = canon_tokens(raw)
        c = " ".join(toks)
        if not toks:
            return LabelMatch(key=UNKNOWN, rule="none", matched_synonym=None, canonical_input=c)
        hit = self._exact.get(c)
        if hit is not None:
            return LabelMatch(key=hit[0], rule="exact", matched_synonym=hit[1], canonical_input=c)
        best: tuple[tuple[str, ...], str, str, str] | None = None
        for entry in self._synonyms:
            stoks = entry[0]
            is_prefix = len(stoks) < len(toks) and toks[: len(stoks)] == stoks
            if is_prefix and (
                best is None or (len(stoks), len(entry[1])) > (len(best[0]), len(best[1]))
            ):
                best = entry
        if best is not None:
            return LabelMatch(
                key=best[2], rule="prefix", matched_synonym=best[3], canonical_input=c
            )
        return LabelMatch(key=UNKNOWN, rule="none", matched_synonym=None, canonical_input=c)


def _parse_taxonomy(path: Path) -> Taxonomy:
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    return Taxonomy.model_validate(data)


@functools.cache
def _default_taxonomy() -> Taxonomy:
    return _parse_taxonomy(TAXONOMY_PATH)


def load_taxonomy(path: Path | None = None) -> Taxonomy:
    """Load a taxonomy YAML file; the packaged default (``path=None``) is cached."""
    if path is None:
        return _default_taxonomy()
    return _parse_taxonomy(Path(path))


def _check_known_type(v: str) -> str:
    if v not in load_taxonomy()._by_key:
        raise ValueError(f"unknown room type key {v!r}")
    return v


RoomTypeKey = Annotated[StrictStr, AfterValidator(_check_known_type)]
"""A room-type key that exists in the packaged taxonomy."""
