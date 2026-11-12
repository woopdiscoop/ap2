"""Variant generation: prepare → seed → anneal → export, N variants (RD 3.4 §4).

Ticket Q.3 (budget split): per variant the seeder gets
``min(SEED_TIME_BUDGET_S, SEED_SHARE * optimizer.time_budget_s)`` and the annealer the rest of
``optimizer.time_budget_s`` (through a copy of the config), so a variant takes about
``time_budget_s`` in all.
"""

from __future__ import annotations

from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict

from ale.contracts.config import AleConfig
from ale.contracts.serialization import canonical_json
from ale.export import export_run
from ale.guards import bounded_range
from ale.optimize.anneal import anneal
from ale.program import load_rulebook, prepare_input
from ale.program.models import InputError
from ale.topology import seed_plan

__all__ = ["SUMMARY_NAME", "GenerateResult", "VariantResult", "generate", "render_summary"]

SUMMARY_NAME = "summary.md"
SEED_TIME_BUDGET_S = 20.0
"""Upper bound of the time given to :func:`seed_plan` per variant."""
SEED_SHARE = 0.25
"""Share of ``optimizer.time_budget_s`` the seeder may use at most (Q.3)."""
_VARIANTS_TIME_S = 1e9
"""The variant loop is bounded by ``variants``; each variant bounds its own time."""


class VariantResult(BaseModel):
    """One variant: status, metrics of the final layout and where it was written."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    index: int
    seed: int
    status: Literal["ok", "failed"]
    out_dir: Path | None = None
    failures: tuple[str, ...] = ()
    initial_cost: float | None = None
    final_cost: float | None = None
    initial_hard: int | None = None
    final_hard: int | None = None
    violations: int | None = None
    circulation_pct: float | None = None
    iterations: int = 0
    stopped_by: str | None = None
    elapsed_s: float = 0.0
    duplicate_of: int | None = None


class GenerateResult(BaseModel):
    """All variants of a :func:`generate` run and the summary file."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    out: Path
    summary: Path
    variants: tuple[VariantResult, ...]

    @property
    def succeeded(self) -> int:
        """Number of variants with status ``"ok"``."""
        return sum(1 for v in self.variants if v.status == "ok")


def _fmt(value: float | None, spec: str) -> str:
    return "—" if value is None else format(value, spec)


def render_summary(out: Path, seed: int, variants: tuple[VariantResult, ...]) -> str:
    """The French ``summary.md`` of a run."""
    ok = sum(1 for v in variants if v.status == "ok")
    lines = [
        f"# Synthèse de génération — {out.name}",
        "",
        f"- Graine de base : {seed}",
        f"- Variantes : {len(variants)} (réussies : {ok}, échouées : {len(variants) - ok})",
        "",
        "| Variante | Statut | Coût final | Violations | Circulation (%) | Durée (s) | Remarque |",
        "|---|---|---|---|---|---|---|",
    ]
    for v in variants:
        status = "réussie" if v.status == "ok" else "échec"
        if v.status == "failed":
            note = "; ".join(v.failures)
        elif v.duplicate_of is not None:
            note = f"doublon de la variante {v.duplicate_of:02d}"
        else:
            note = ""
        lines.append(
            f"| {v.index:02d} | {status} | {_fmt(v.final_cost, '.3f')} | "
            f"{'—' if v.violations is None else v.violations} | "
            f"{_fmt(v.circulation_pct, '.1f')} | {v.elapsed_s:.1f} | {note.replace('|', '/')} |"
        )
    return "\n".join(lines) + "\n"


def generate(
    program: Path,
    site: Path,
    rulebook: Path,
    out: Path,
    *,
    seed: int,
    variants: int,
    config: AleConfig,
) -> GenerateResult:
    """Generate ``variants`` layouts into ``out/variant_XX/`` and write ``out/summary.md``.

    Raises ``ValueError`` for ``variants < 1``, :class:`InputError` (nothing written) when
    the inputs are invalid, and
    ``FileExistsError`` when a variant folder already holds run files.
    """
    if variants < 1:
        raise ValueError(f"variants must be >= 1, got {variants}")
    prepared = prepare_input(program, site, rulebook, config)
    rb, issues = load_rulebook(rulebook)
    if rb is None:  # pragma: no cover - prepare_input already validated the rulebook
        raise InputError(issues)
    out = Path(out)
    results: list[VariantResult] = []
    finals: dict[str, int] = {}
    total_s = config.optimizer.time_budget_s
    seed_budget = min(SEED_TIME_BUDGET_S, SEED_SHARE * total_s)
    anneal_config = config.model_copy(
        update={
            "optimizer": config.optimizer.model_copy(
                update={"time_budget_s": total_s - seed_budget}
            )
        }
    )
    footprint_m2 = prepared.feasibility.footprint_m2
    for k in bounded_range(
        variants, _VARIANTS_TIME_S, label="generate-variants", on_exhaust="stop"
    ):
        index, seed_k = k + 1, seed + k
        seeded = seed_plan(prepared, rb, config, seed=seed_k, time_budget_s=seed_budget)
        if seeded.realization.layout is None:
            results.append(
                VariantResult(
                    index=index,
                    seed=seed_k,
                    status="failed",
                    failures=tuple(f"{f.code}: {f.detail}" for f in seeded.realization.failures),
                    elapsed_s=seeded.elapsed_s,
                )
            )
            continue
        res = anneal(prepared, rb, anneal_config, seeded.plan, seed=seed_k)
        target = out / f"variant_{index:02d}"
        export_run(
            res.layout,
            prepared,
            target,
            rulebook_version=prepared.rulebook_version,
            run_id=f"{out.name}-v{index}",
            config=config,
            rulebook=rb,
        )
        key = canonical_json(res.plan).decode("utf-8")
        metrics = res.layout.metrics
        results.append(
            VariantResult(
                index=index,
                seed=seed_k,
                status="ok",
                out_dir=target,
                initial_cost=res.initial_cost,
                final_cost=res.final_cost,
                initial_hard=res.initial_hard,
                final_hard=res.final_hard,
                violations=len(metrics.violations),
                circulation_pct=(
                    100.0 * metrics.circulation_area_m2 / footprint_m2 if footprint_m2 else None
                ),
                iterations=res.iterations,
                stopped_by=res.stopped_by,
                elapsed_s=seeded.elapsed_s + res.elapsed_s,
                duplicate_of=finals.get(key),
            )
        )
        finals.setdefault(key, index)
    out.mkdir(parents=True, exist_ok=True)
    summary = out / SUMMARY_NAME
    done = tuple(results)
    summary.write_text(render_summary(out, seed, done), encoding="utf-8", newline="\n")
    return GenerateResult(out=out, summary=summary, variants=done)
