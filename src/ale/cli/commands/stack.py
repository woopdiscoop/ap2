"""``ale stack``: stack a programme on the floors of a building (Ticket M.1).

Exit codes: 0 = stacking produced without hard miss; 1 = input error (nothing written) or a
hard miss (over-capacity floor, skeleton miss, floor without diagram): the outputs are still
written and the misses listed in ``stacking.md``; 2 = usage error (also Ticket M.3: an invalid
``bay_m``, ``grid_m`` or ``typical_floor`` in the rules, with a French message).

Ticket M.2, ``--plans [--rulebook R] [--budget S]``: after the stacking every floor gets an exact
plan (``floor_NN/plan/``, ``plans.md``). Exit 1 also when a floor cannot be generated, a plan
does not pass ``check_layout`` or the vertical check (core and wet stack identical on every
floor) fails; the other floors are still produced. ``--rulebook`` is required with ``--plans``.
"""

from __future__ import annotations

from pathlib import Path
from typing import Annotated

import typer

from ale.cli.commands._common import EXIT_OK, EXIT_RUNTIME, EXIT_USAGE

__all__ = ["stack"]


def stack(
    program: Annotated[Path, typer.Option("--program", exists=True, dir_okay=False)],
    building: Annotated[Path, typer.Option("--building", exists=True, dir_okay=False)],
    out: Annotated[Path, typer.Option("--out", help="Dossier de sortie.")],
    rules: Annotated[
        Path | None, typer.Option("--rules", exists=True, dir_okay=False, help="Règles YAML.")
    ] = None,
    seed: Annotated[int, typer.Option("--seed", help="Graine des diagrammes.")] = 0,
    plans: Annotated[
        bool, typer.Option("--plans", help="Plans exacts par niveau autour du squelette (M.2).")
    ] = False,
    rulebook: Annotated[
        Path | None,
        typer.Option("--rulebook", exists=True, dir_okay=False, help="Rulebook (avec --plans)."),
    ] = None,
    budget: Annotated[
        float, typer.Option("--budget", min=1.0, help="Secondes par niveau (avec --plans).")
    ] = 20.0,
) -> None:
    """Stack the programme on the floors, fix the vertical skeleton, lay out each floor."""
    from ale.cli.commands.program import _issue_line
    from ale.program import read_program
    from ale.stack import StackInputError, load_building, load_rules, run_stack, write_outputs
    from ale.stack.rules import RhythmInputError

    if plans and rulebook is None:
        raise typer.BadParameter("--plans demande --rulebook.", param_hint="--rulebook")
    prog, report = read_program(program)
    errors = [i for i in report.issues if i.severity == "error"]
    if prog is None or errors:
        lines = [f"Erreurs ({len(errors)}) :", *(_issue_line(i) for i in errors)]
        typer.echo("\n".join([*lines, "ÉCHEC : corrigez les erreurs ci-dessus."]), err=True)
        raise typer.Exit(EXIT_RUNTIME)
    try:
        bld = load_building(building)
        rl = load_rules(rules)
    except RhythmInputError as exc:
        typer.echo("\n".join([*exc.lines, "ÉCHEC : trame ou module de travée invalide."]), err=True)
        raise typer.Exit(EXIT_USAGE) from exc
    except StackInputError as exc:
        typer.echo("\n".join([*exc.lines, "ÉCHEC : corrigez les erreurs ci-dessus."]), err=True)
        raise typer.Exit(EXIT_RUNTIME) from exc
    try:
        result = run_stack(prog, bld, rl, seed=seed, strict_solids=plans)
    except RhythmInputError as exc:
        typer.echo("\n".join([*exc.lines, "ÉCHEC : trame ou module de travée invalide."]), err=True)
        raise typer.Exit(EXIT_USAGE) from exc
    except StackInputError as exc:
        typer.echo("\n".join([*exc.lines, "ÉCHEC : entrée inutilisable."]), err=True)
        raise typer.Exit(EXIT_RUNTIME) from exc
    write_outputs(result, out)
    typer.echo(
        f"{bld.n_floors} niveaux, empilabilité {result.stackability:.1%}, "
        f"manques durs {len(result.misses)}"
    )
    typer.echo(f"rapport : {out / 'stacking.md'}")
    misses = list(result.misses)
    if plans:
        assert rulebook is not None
        from ale.stack.plans import run_plans

        pr, used = run_plans(result, rulebook, out, budget_s=budget, seed=seed)
        done = sum(1 for p in pr.floors if p.passes)
        typer.echo(f"plans : {done}/{len(pr.floors)} niveaux, rapport : {out / 'plans.md'}")
        misses += list(pr.misses)
        if used is not result:  # the stacking was redone with a strict wet stack
            misses = [*used.misses, *pr.misses]
    if misses:
        for m in misses:
            typer.echo(f"MANQUE DUR : {m}", err=True)
        raise typer.Exit(EXIT_RUNTIME)
    raise typer.Exit(EXIT_OK)
