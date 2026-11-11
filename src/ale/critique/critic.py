"""Visual critique of a variant with Claude (advisory; Ticket R.6).

:func:`run_critique` reads ``layout.json`` and ``report.md`` of a variant folder, renders
the layout (:mod:`ale.critique.render`), and makes one Messages API call: the PNG, then a
fixed French prompt with a compact table of the rooms. The answer is constrained with
structured outputs to :data:`RESPONSE_SCHEMA`. It writes ``critique.md`` (French) and
``critique.json`` into the variant folder and nothing else: the layout, the report and
the costs are never touched.

The client follows the pattern of :mod:`ale.labels.providers.anthropic_provider`: lazy
``anthropic`` import, key read from the environment variable named in
``[vlm] api_key_env`` (never stored or logged), no sampling parameter, adaptive thinking,
low effort and the server-side refusal fallback. Raw answers are cached by
(layout hash, prompt version, model id) so a second run makes no call.
"""

from __future__ import annotations

import base64
import contextlib
import hashlib
import json
import os
import re
import tempfile
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Annotated, Any, Final, Literal

from pydantic import BaseModel, ConfigDict, Field, StrictInt, StrictStr, ValidationError

from ale.contracts.config import AleConfig
from ale.contracts.enums import MacroZone
from ale.contracts.models import Layout
from ale.critique.render import RenderError, render_layout
from ale.export.report import JSON_NAME, REPORT_NAME, SVG_NAME, ZONE_FR, fr_num, touches_facade
from ale.labels.cache import VlmCache
from ale.labels.providers.anthropic_provider import DEFAULT_MODEL_ID, FALLBACK_BETA

__all__ = [
    "CRITIQUE_JSON_NAME",
    "CRITIQUE_MD_NAME",
    "KINDS",
    "KIND_FR",
    "MAX_TOKENS",
    "PROMPT_FR",
    "PROMPT_VERSION",
    "RESPONSE_SCHEMA",
    "Critique",
    "CritiqueError",
    "CritiqueResult",
    "CritiqueUnavailableError",
    "Defect",
    "ReportRoom",
    "build_request",
    "cache_key",
    "parse_report_rooms",
    "render_markdown",
    "room_table",
    "run_critique",
]

CRITIQUE_MD_NAME: Final = "critique.md"
CRITIQUE_JSON_NAME: Final = "critique.json"
#: Version of :data:`PROMPT_FR` and of the table layout (part of the cache key).
PROMPT_VERSION: Final = "critique-v1"
#: Output cap of one critique (non-streaming request).
MAX_TOKENS: Final = 16000

KINDS: Final = ("circulation", "lumiere", "proportion", "adjacence", "acces", "residuel", "autre")
KIND_FR: Final[dict[str, str]] = {
    "circulation": "Circulation",
    "lumiere": "Lumière naturelle",
    "proportion": "Proportions",
    "adjacence": "Adjacences",
    "acces": "Accès",
    "residuel": "Espace résiduel",
    "autre": "Autre",
}
_GENERAL: Final = "général"

PROMPT_FR: Final = (
    "Tu es architecte et tu relis un plan d'étage généré automatiquement (image ci-dessus).\n"
    "Les pièces sont colorées par zone (jaune : public, bleu : administratif, gris moyen : "
    "services), les circulations sont en gris clair, les espaces résiduels en rose pâle. "
    "Chaque pièce porte son identifiant et la flèche indique le nord.\n"
    "Relève les défauts qu'un architecte verrait au premier regard : circulations "
    "inefficaces ou en impasse, pièces sans lumière naturelle, proportions inutilisables, "
    "adjacences maladroites, accès difficiles, espaces résiduels.\n"
    "Pour chaque défaut, donne : room_ids (identifiants exacts des pièces concernées, tels "
    "qu'ils figurent dans le tableau ; liste vide si le défaut est général), kind "
    "(circulation, lumiere, proportion, adjacence, acces, residuel ou autre), severity "
    "(1 = mineur, 2 = gênant, 3 = majeur), observation (ce que tu vois) et suggestion "
    "(correction concrète). Termine par summary : une synthèse en deux ou trois phrases.\n"
    "Réponds en français. Ne signale que des défauts réels et visibles ; s'il n'y en a "
    "aucun, renvoie une liste vide.\n\n"
    "Tableau des pièces (surfaces en m², dimensions en m) :\n"
)

#: JSON schema of the model's answer (structured outputs).
RESPONSE_SCHEMA: Final[dict[str, object]] = {
    "type": "object",
    "properties": {
        "defects": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "room_ids": {"type": "array", "items": {"type": "string"}},
                    "kind": {"type": "string", "enum": list(KINDS)},
                    "severity": {"type": "integer", "enum": [1, 2, 3]},
                    "observation": {"type": "string"},
                    "suggestion": {"type": "string"},
                },
                "required": ["room_ids", "kind", "severity", "observation", "suggestion"],
                "additionalProperties": False,
            },
        },
        "summary": {"type": "string"},
    },
    "required": ["defects", "summary"],
    "additionalProperties": False,
}

_OK_STOPS: Final = frozenset({"end_turn", "stop_sequence"})
_CONFIG: Final = ConfigDict(frozen=True, extra="forbid")
Kind = Literal["circulation", "lumiere", "proportion", "adjacence", "acces", "residuel", "autre"]


class CritiqueError(RuntimeError):
    """The critique failed (bad variant folder, API error, refusal, invalid answer)."""


class CritiqueUnavailableError(CritiqueError):
    """No usable provider: ``[vlm]`` is not configured or the API key is missing."""


class Defect(BaseModel):
    """One defect seen by the model (``room_ids`` empty = general remark)."""

    model_config = _CONFIG

    room_ids: tuple[StrictStr, ...]
    kind: Kind
    severity: Annotated[StrictInt, Field(ge=1, le=3)]
    observation: StrictStr
    suggestion: StrictStr


class _Answer(BaseModel):
    model_config = _CONFIG

    defects: tuple[Defect, ...]
    summary: StrictStr


class Critique(BaseModel):
    """Content of ``critique.json``."""

    model_config = _CONFIG

    schema_version: Literal["ale.critique/1"] = "ale.critique/1"
    layout_sha256: StrictStr
    model_id: StrictStr
    prompt_version: StrictStr
    summary: StrictStr
    defects: tuple[Defect, ...]
    #: Number of room ids named by the model that do not exist in the layout (dropped).
    unknown_room_ids: Annotated[StrictInt, Field(ge=0)]
    warnings: tuple[StrictStr, ...]


@dataclass(frozen=True)
class CritiqueResult:
    """Outcome of :func:`run_critique` (``calls`` = API calls made: 0 on a cache hit)."""

    critique: Critique
    critique_md: Path
    critique_json: Path
    calls: int


@dataclass(frozen=True)
class ReportRoom:
    """Name, type and zone of a room as printed in ``report.md``."""

    name: str
    type_label: str
    zone_label: str

    @property
    def zone(self) -> MacroZone | None:
        """The macro-zone named by ``zone_label`` (``None`` when unknown)."""
        for zone, label in ZONE_FR.items():
            if label == self.zone_label:
                return zone
        return None


# --------------------------------------------------------------------------- inputs

_CELL_SPLIT = re.compile(r"(?<!\\)\|")
_NORTH_RE = re.compile(r'data-north-angle-deg="(-?\d+(?:\.\d+)?)"')


def parse_report_rooms(report_md: str) -> dict[str, ReportRoom]:
    """Rows of the « Surfaces » table of ``report.md``, keyed by instance id."""
    rooms: dict[str, ReportRoom] = {}
    in_table = False
    for line in report_md.splitlines():
        if not line.startswith("|"):
            in_table = False
            continue
        cells = [c.strip().replace("\\|", "|") for c in _CELL_SPLIT.split(line)[1:-1]]
        if cells[:4] == ["ID", "Nom", "Type", "Zone"]:
            in_table = True
        elif in_table and len(cells) >= 4 and not cells[0].startswith("---"):
            rooms[cells[0]] = ReportRoom(name=cells[1], type_label=cells[2], zone_label=cells[3])
    return rooms


def room_table(layout: Layout, report_rooms: dict[str, ReportRoom]) -> str:
    """The compact text table sent with the image (one line per room, then circulation)."""
    codes: dict[str, set[str]] = {}
    for v in layout.metrics.violations:
        for iid in v.instance_ids:
            codes.setdefault(iid, set()).add(v.code)
    mm = layout.grid.module_mm
    lines = ["id | nom | type | zone | surface | dimensions | façade | violations"]
    for kind, seq in (("room", layout.rooms), ("circ", layout.circulation)):
        for p in seq:
            info = report_rooms.get(p.instance_id)
            if kind == "circ":
                name, type_label, zone = "circulation", "circulation", "—"
            elif info is None:
                name, type_label, zone = p.instance_id, "—", "—"
            else:
                name, type_label, zone = info.name, info.type_label, info.zone_label
            long_m = max(p.rect.w, p.rect.h) * mm / 1000
            short_m = min(p.rect.w, p.rect.h) * mm / 1000
            cells = [
                p.instance_id,
                name,
                type_label,
                zone,
                fr_num(p.area_m2(layout.grid)),
                f"{fr_num(long_m)} x {fr_num(short_m)}",
                "oui" if touches_facade(p.rect, layout.footprint) else "non",
                ", ".join(sorted(codes.get(p.instance_id, ()))) or "aucune",
            ]
            lines.append(" | ".join(c.replace("|", "/").replace("\n", " ") for c in cells))
    return "\n".join(lines) + "\n"


def cache_key(*, layout_sha256: str, prompt_version: str, model_id: str) -> str:
    """Hex sha256 cache key of one critique call."""
    payload = json.dumps(
        [layout_sha256, prompt_version, model_id], ensure_ascii=True, separators=(",", ":")
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


# --------------------------------------------------------------------------- request


def build_request(png: bytes, table: str, *, model_id: str, timeout_s: float) -> dict[str, Any]:
    """Keyword arguments of the ``client.beta.messages.create`` call."""
    data = base64.standard_b64encode(png).decode("ascii")
    return {
        "model": model_id,
        "max_tokens": MAX_TOKENS,
        "messages": [
            {
                "role": "user",
                "content": [
                    {
                        "type": "image",
                        "source": {"type": "base64", "media_type": "image/png", "data": data},
                    },
                    {"type": "text", "text": PROMPT_FR + table},
                ],
            }
        ],
        "thinking": {"type": "adaptive"},
        "output_config": {
            "effort": "low",
            "format": {"type": "json_schema", "schema": RESPONSE_SCHEMA},
        },
        "betas": [FALLBACK_BETA],
        "fallbacks": "default",
        "timeout": timeout_s,
    }


def _check_provider(config: AleConfig) -> None:
    """Raise :class:`CritiqueUnavailableError` unless ``[vlm]`` names a usable provider."""
    vlm = config.vlm
    how = (
        'Dans ale.toml du workspace, section [vlm] : provider = "anthropic" et '
        f'api_key_env = "{vlm.api_key_env}" (nom de la variable d\'environnement qui '
        "contient la clé d'API Anthropic), puis relancez avec --workspace."
    )
    if vlm.provider == "":
        raise CritiqueUnavailableError(f"aucun fournisseur VLM n'est configuré. {how}")
    if vlm.provider != "anthropic":
        raise CritiqueUnavailableError(
            f"fournisseur VLM « {vlm.provider} » non pris en charge pour la critique. {how}"
        )
    if not os.environ.get(vlm.api_key_env, "").strip():
        raise CritiqueUnavailableError(
            f"clé d'API absente : la variable d'environnement {vlm.api_key_env} est vide "
            f"ou non définie. {how}"
        )


def _make_client(config: AleConfig) -> Any:
    """The SDK client (key from the environment; never stored on our side)."""
    try:
        import anthropic
    except ImportError as exc:  # pragma: no cover - the extra is installed in CI
        raise CritiqueUnavailableError(
            "le paquet « anthropic » n'est pas installé (pip install 'ale[vlm]')."
        ) from exc
    return anthropic.Anthropic(
        api_key=os.environ.get(config.vlm.api_key_env, ""),
        timeout=config.vlm.timeout_s,
        max_retries=2,
    )


def _call(client: Any, request: dict[str, Any]) -> str:
    """One API call; the answer text. Raises :class:`CritiqueError` on any failure."""
    import anthropic

    try:
        message = client.beta.messages.create(**request)
    except anthropic.APIStatusError as exc:
        raise CritiqueError(
            f"erreur de l'API Anthropic ({exc.status_code}) : {exc.message}"
        ) from exc
    except anthropic.APITimeoutError as exc:
        raise CritiqueError("la requête à l'API Anthropic a expiré (délai dépassé).") from exc
    except anthropic.APIError as exc:
        raise CritiqueError(f"erreur de l'API Anthropic : {exc.message}") from exc
    stop = getattr(message, "stop_reason", None)
    if stop == "refusal":
        details = getattr(message, "stop_details", None)
        category = getattr(details, "category", None) if details is not None else None
        suffix = f" (catégorie : {category})" if category else ""
        raise CritiqueError(f"Claude a refusé la demande{suffix} ; aucune critique produite.")
    if stop == "max_tokens":
        raise CritiqueError(f"réponse de Claude tronquée (max_tokens={MAX_TOKENS}).")
    if stop not in _OK_STOPS:
        raise CritiqueError(f"fin de réponse inattendue (stop_reason={stop!r}).")
    blocks = list(getattr(message, "content", None) or [])
    # Only the text after the last fallback switch point is the final model's answer.
    start = 0
    for i, block in enumerate(blocks):
        if getattr(block, "type", None) == "fallback":
            start = i + 1
    text = "".join(
        str(getattr(b, "text", "")) for b in blocks[start:] if getattr(b, "type", None) == "text"
    )
    if not text.strip():
        raise CritiqueError("Claude n'a renvoyé aucun texte.")
    return text


def _parse_answer(raw: str) -> _Answer:
    try:
        return _Answer.model_validate_json(raw)
    except ValidationError as exc:
        raise CritiqueError(
            f"réponse de Claude invalide ({exc.error_count()} erreur(s) de schéma)."
        ) from exc


# --------------------------------------------------------------------------- outputs


def _filter_ids(answer: _Answer, known: Sequence[str]) -> tuple[tuple[Defect, ...], int]:
    """Drop unknown (and repeated) room ids; returns the defects and the unknown count."""
    known_set = set(known)
    dropped = 0
    out: list[Defect] = []
    for d in answer.defects:
        kept: list[str] = []
        for iid in d.room_ids:
            if iid not in known_set:
                dropped += 1
            elif iid not in kept:
                kept.append(iid)
        out.append(d.model_copy(update={"room_ids": tuple(kept)}))
    return tuple(out), dropped


def render_markdown(critique: Critique, names: dict[str, str], *, title: str) -> str:
    """French text of ``critique.md`` (one ``###`` section per defect)."""
    lines = [
        f"# Critique visuelle — {title}",
        "",
        "> Avis consultatif produit par un modèle de vision "
        f"(`{critique.model_id}`, prompt `{critique.prompt_version}`). "
        "Il ne modifie ni le plan, ni le rapport, ni les coûts.",
        "",
        "## Synthèse",
        "",
        critique.summary.strip() or "—",
        "",
        f"## Défauts ({len(critique.defects)})",
        "",
    ]
    if not critique.defects:
        lines += ["Aucun défaut relevé.", ""]
    for n, d in enumerate(critique.defects, start=1):
        if d.room_ids:
            rooms = ", ".join(
                f"`{iid}` ({names[iid]})" if names.get(iid, iid) != iid else f"`{iid}`"
                for iid in d.room_ids
            )
        else:
            rooms = _GENERAL
        lines += [
            f"### {n}. {KIND_FR[d.kind]} — gravité {d.severity} sur 3",
            "",
            f"- Pièces : {rooms}",
            f"- Observation : {' '.join(d.observation.split())}",
            f"- Suggestion : {' '.join(d.suggestion.split())}",
            "",
        ]
    if critique.warnings:
        lines += ["## Avertissements", "", *(f"- {w}" for w in critique.warnings), ""]
    return "\n".join(lines).rstrip("\n") + "\n"


def _write_atomic(path: Path, text: str) -> None:
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=".tmp-critique-", suffix=path.suffix)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as fh:
            fh.write(text)
        Path(tmp).replace(path)
    except BaseException:  # pragma: no cover - disk failure
        with contextlib.suppress(OSError):
            Path(tmp).unlink()
        raise


# --------------------------------------------------------------------------- entry point


def run_critique(
    variant_dir: Path,
    config: AleConfig,
    *,
    cache_dir: Path | None = None,
    client: Any = None,
) -> CritiqueResult:
    """Critique the variant in ``variant_dir`` and write its two files there.

    ``cache_dir`` (``<workspace>/cache/critique``) enables the answer cache. ``client``
    replaces the SDK client (tests). Raises :class:`CritiqueUnavailableError` when no
    provider / key is configured and :class:`CritiqueError` on any other failure; in both
    cases nothing is written.
    """
    _check_provider(config)
    variant = Path(variant_dir)
    try:
        layout_bytes = (variant / JSON_NAME).read_bytes()
        report_md = (variant / REPORT_NAME).read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        raise CritiqueError(
            f"variante illisible : {JSON_NAME} et {REPORT_NAME} sont requis dans {variant} "
            f"({type(exc).__name__})."
        ) from exc
    try:
        layout = Layout.model_validate_json(layout_bytes)
    except ValidationError as exc:
        raise CritiqueError(
            f"{JSON_NAME} n'est pas un plan valide ({exc.error_count()} erreur(s))."
        ) from exc

    model_id = config.vlm.model_id or DEFAULT_MODEL_ID
    layout_sha = hashlib.sha256(layout_bytes).hexdigest()
    key = cache_key(layout_sha256=layout_sha, prompt_version=PROMPT_VERSION, model_id=model_id)
    cache = VlmCache(cache_dir) if cache_dir is not None else None

    answer: _Answer | None = None
    calls = 0
    warnings: list[str] = []
    cached = cache.get(key) if cache is not None else None
    if cached is not None:
        with contextlib.suppress(CritiqueError):
            answer = _parse_answer(cached)
    if answer is None:
        report_rooms = parse_report_rooms(report_md)
        try:
            image = render_layout(
                layout,
                {iid: r.zone for iid, r in report_rooms.items()},
                north_angle_deg=_north_angle(variant),
            )
        except RenderError as exc:  # pragma: no cover - Pillow is installed in CI
            raise CritiqueError(str(exc)) from exc
        request = build_request(
            image.png,
            room_table(layout, report_rooms),
            model_id=model_id,
            timeout_s=config.vlm.timeout_s,
        )
        raw = _call(client if client is not None else _make_client(config), request)
        calls = 1
        answer = _parse_answer(raw)
        if cache is not None:
            cache.put(key, raw)  # a cache write failure only costs a later call

    known = [p.instance_id for p in (*layout.rooms, *layout.circulation)]
    defects, dropped = _filter_ids(answer, known)
    if dropped:
        warnings.append(f"{dropped} identifiant(s) de pièce inconnu(s) ignoré(s) dans la réponse.")
    critique = Critique(
        layout_sha256=layout_sha,
        model_id=model_id,
        prompt_version=PROMPT_VERSION,
        summary=answer.summary,
        defects=defects,
        unknown_room_ids=dropped,
        warnings=tuple(warnings),
    )
    names = {iid: r.name for iid, r in parse_report_rooms(report_md).items()}
    md_path, json_path = variant / CRITIQUE_MD_NAME, variant / CRITIQUE_JSON_NAME
    payload = json.dumps(critique.model_dump(mode="json"), ensure_ascii=False, indent=2) + "\n"
    _write_atomic(json_path, payload)
    _write_atomic(md_path, render_markdown(critique, names, title=variant.resolve().name))
    return CritiqueResult(
        critique=critique, critique_md=md_path, critique_json=json_path, calls=calls
    )


def _north_angle(variant: Path) -> float:
    """North angle recorded in ``preview.svg`` (0 when the file or attribute is absent)."""
    try:
        match = _NORTH_RE.search((variant / SVG_NAME).read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError):
        return 0.0
    return float(match.group(1)) if match else 0.0
