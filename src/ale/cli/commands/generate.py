"""``ale generate`` (Ticket 3.4): prepare → seed → anneal → export, N variants.

``ale.optimize`` (and through it openpyxl / ezdxf) is imported lazily so that the CLI
starts without the extras.
"""

from __future__ import annotations

from pathlib import Path
from typing import Annotated

import typer

from ale.cli.commands._common import (
    EXIT_OK,
    EXIT_RUNTIME,
    WorkspaceOption,
    open_workspace_or_exit,
)
from ale.config import AleConfig


def _require_suffix(value: Path, suffixes: tuple[str, ...]) -> Path:
    if value.suffix.lower() not in suffixes:
        raise typer.BadParameter(f"expected a {' or '.join(suffixes)} file, got {value.name!r}")
    return value


def _program_suffix(value: Path) -> Path:
    return _require_suffix(value, (".xlsx",))


def _site_suffix(value: Path) -> Path:
    return _require_suffix(value, (".yaml", ".yml"))


def generate(
    ctx: typer.Context,
    program: Annotated[
        Path,
        typer.Option(
            "--program",
            exists=True,
            dir_okay=False,
            callback=_program_suffix,
            help="Space program (.xlsx, must exist).",
        ),
    ],
    site: Annotated[
        Path,
        typer.Option(
            "--site",
            exists=True,
            dir_okay=False,
            callback=_site_suffix,
            help="Site description (.yaml/.yml, must exist).",
        ),
    ],
    rulebook: Annotated[
        Path, typer.Option("--rulebook", exists=True, help="Rulebook (must exist).")
    ],
    out: Annotated[Path, typer.Option("--out", help="Output folder.")],
    seed: Annotated[
        int | None,
        typer.Option("--seed", min=0, help="Random seed (default: [determinism].seed)."),
    ] = None,
    variants: Annotated[
        int, typer.Option("--variants", min=1, help="Number of variants (>= 1).")
    ] = 1,
    workspace: WorkspaceOption = None,
) -> None:
    """Generate layout variants for a program on a site."""
    config = open_workspace_or_exit(ctx, workspace).config if workspace is not None else AleConfig()
    from ale.cli.commands.program import _issue_line
    from ale.optimize import generate as run_generate
    from ale.program.models import InputError

    base_seed = config.determinism.seed if seed is None else seed
    try:
        result = run_generate(
            program, site, rulebook, out, seed=base_seed, variants=variants, config=config
        )
    except InputError as exc:
        errors = [i for i in exc.issues if i.severity == "error"]
        lines = [f"Erreurs ({len(errors)}) :", *(_issue_line(i) for i in errors)]
        lines.append("ÉCHEC : corrigez les erreurs ci-dessus.")
        typer.echo("\n".join(lines), err=True)
        raise typer.Exit(EXIT_RUNTIME) from exc
    except FileExistsError as exc:
        typer.echo(f"ÉCHEC : {exc}", err=True)
        raise typer.Exit(EXIT_RUNTIME) from exc
    for v in result.variants:
        if v.status == "ok":
            typer.echo(
                f"variante {v.index:02d} : coût {v.final_cost:.3f}, "
                f"violations {v.violations}, {v.out_dir}"
            )
        else:
            typer.echo(f"variante {v.index:02d} : échec ({'; '.join(v.failures)})")
    typer.echo(f"synthèse : {result.summary}")
    raise typer.Exit(EXIT_OK if result.succeeded else EXIT_RUNTIME)
